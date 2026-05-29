"""Tests for DRESpider.

Mocks the Exa client to simulate search API responses and httpx transport
for PDF downloads.  No external network calls are made.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from src.scrapers.spiders.dre import (
    DRESpider,
    _extract_pdf_url,
    _extract_text_from_pdf,
    _describe_pdf_url,
)
from src.scrapers.base import ScrapedArticle
from src.config.settings import settings


# ── Test data ─────────────────────────────────────────────────────────────────

SEARCH_RESULT_LUSA = {
    "url": "https://files.dre.pt/2s/2026/05/12345.pdf",
    "title": "Despacho (extrato) n.º 5432/2026 — Nomeação de vogal do CA da Lusa",
    "text": "Procede à nomeação de um vogal do conselho de administração da Lusa — Agência de Notícias de Portugal, S.A.",
}

SEARCH_RESULT_RTP = {
    "url": "https://files.dre.pt/2s/2026/04/09876.pdf",
    "title": "Despacho n.º 4321/2026 — Designação de membro do CA da RTP",
    "text": "Designa um membro do conselho de administração da Rádio e Televisão de Portugal, S.A.",
}

SEARCH_RESULT_ERC = {
    "url": "https://files.dre.pt/1s/2026/03/00500.pdf",
    "title": "Resolução da AR n.º 123/2026 — Nomeação de membro do Conselho Regulador da ERC",
    "text": "Procede à nomeação de um membro do Conselho Regulador da ERC.",
}

SEARCH_RESULT_NON_DRE = {
    "url": "https://www.portugal.gov.pt/noticia.html",
    "title": "Comunicado do Governo",
    "text": "Anúncio do Governo sobre políticas de comunicação social.",
}

# Tiny valid PDF for testing extraction
TINY_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 57 >>\nstream\nBT /F1 12 Tf\n100 700 Td (Test content for DRE) Tj\nET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000266 00000 n \n0000000374 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n443\n%%EOF"
)

# ── Helper: build a fake Exa response ─────────────────────────────────────────


class _FakeExaResult:
    """Mimics an Exa search result item (has .url, .title, .text attrs)."""

    def __init__(self, data: dict) -> None:
        self.url = data.get("url", "")
        self.title = data.get("title", "")
        self.text = data.get("text", "")


class _FakeExaResponse:
    """Mimics an Exa search response (has .results list)."""

    def __init__(self, items: list[dict]) -> None:
        self.results = [_FakeExaResult(d) for d in items]


def _make_exa_response(items: list[dict]) -> _FakeExaResponse:
    return _FakeExaResponse(items)


# ── _extract_pdf_url tests ────────────────────────────────────────────────────


class TestExtractPdfUrl:
    def test_valid_dre_url(self) -> None:
        url = "https://files.dre.pt/2s/2026/05/12345.pdf"
        assert _extract_pdf_url(url) == url

    def test_http_to_https(self) -> None:
        url = "http://files.dre.pt/2s/2026/05/12345.pdf"
        assert _extract_pdf_url(url) == "https://files.dre.pt/2s/2026/05/12345.pdf"

    def test_non_dre_url_returns_none(self) -> None:
        assert _extract_pdf_url("https://example.com/doc.pdf") is None

    def test_gratuitos_url_returns_none(self) -> None:
        assert _extract_pdf_url("https://files.dre.pt/gratuitos/2s/2018/08/2S151A0000S00.pdf") is None

    def test_empty_link_returns_none(self) -> None:
        assert _extract_pdf_url("") is None


# ── _describe_pdf_url tests ───────────────────────────────────────────────────


class TestDescribePdfUrl:
    def test_serie_ii(self) -> None:
        result = _describe_pdf_url("https://files.dre.pt/2s/2026/05/12345.pdf")
        assert "Série II" in result
        assert "Maio" in result
        assert "2026" in result
        assert "12345" in result

    def test_serie_i(self) -> None:
        result = _describe_pdf_url("https://files.dre.pt/1s/2026/03/00100.pdf")
        assert "Série I" in result
        assert "Março" in result
        assert "00100" in result

    def test_short_url(self) -> None:
        result = _describe_pdf_url("https://files.dre.pt/2s")
        assert "Documento oficial" in result
        assert result == "DRE — Documento oficial"


# ── _extract_text_from_pdf tests ──────────────────────────────────────────────


class TestExtractTextFromPdf:
    def test_valid_pdf_returns_text(self) -> None:
        text = _extract_text_from_pdf(TINY_PDF)
        assert text is not None
        assert "Test content for DRE" in text

    def test_invalid_pdf_returns_none(self) -> None:
        text = _extract_text_from_pdf(b"not a pdf at all")
        assert text is None

    def test_empty_bytes_returns_none(self) -> None:
        text = _extract_text_from_pdf(b"")
        assert text is None


# ── DRESpider fetch tests ────────────────────────────────────────────────────


def _make_pdf_handler() -> object:
    """Create an httpx mock transport handler for PDF downloads."""

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "files.dre.pt" in url:
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=TINY_PDF,
            )
        return httpx.Response(404, text="Not Found")

    return _handler


async def _make_spider() -> DRESpider:
    """Create a DRESpider with a mocked HTTP client for PDFs."""
    spider = DRESpider()
    await spider.http_client.aclose()
    spider.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_make_pdf_handler())
    )
    return spider


class TestDRESpider:
    @pytest.mark.asyncio
    async def test_fetch_with_valid_query(self) -> None:
        """Should return articles from Exa results containing DRE PDFs."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response(
            [SEARCH_RESULT_LUSA, SEARCH_RESULT_RTP, SEARCH_RESULT_ERC]
        )

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        assert len(articles) == 3

        a0 = articles[0]
        assert a0.source_id == "dre_appointments"
        assert a0.url == "https://files.dre.pt/2s/2026/05/12345.pdf"
        assert "Lusa" in a0.title

        a1 = articles[1]
        assert a1.url == "https://files.dre.pt/2s/2026/04/09876.pdf"
        assert "RTP" in a1.title

        a2 = articles[2]
        assert a2.url == "https://files.dre.pt/1s/2026/03/00500.pdf"
        assert "ERC" in a2.title

    @pytest.mark.asyncio
    async def test_fetch_filters_non_dre_urls(self) -> None:
        """Should exclude search results that don't point to files.dre.pt."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response(
            [SEARCH_RESULT_LUSA, SEARCH_RESULT_NON_DRE]
        )

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        assert len(articles) == 1
        assert articles[0].url == "https://files.dre.pt/2s/2026/05/12345.pdf"

    @pytest.mark.asyncio
    async def test_fetch_deduplicates_urls(self) -> None:
        """Should not create duplicate articles for the same PDF URL."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response(
            [SEARCH_RESULT_LUSA, SEARCH_RESULT_LUSA]
        )

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_fetch_empty_search_results(self) -> None:
        """Should return empty list when Exa returns no results."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response([])

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        assert articles == []

    @pytest.mark.asyncio
    async def test_fetch_missing_api_key_returns_empty(self) -> None:
        """Should return empty list when no API keys are set."""
        spider = await _make_spider()
        with patch.object(settings, "exa_api_key", ""):
            with patch.object(settings, "tavily_api_key", ""):
                articles = await spider.fetch("dre_appointments")

        assert articles == []

    @pytest.mark.asyncio
    async def test_each_article_has_required_fields(self) -> None:
        """Every returned article should have core fields populated."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response(
            [SEARCH_RESULT_LUSA, SEARCH_RESULT_RTP]
        )

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        for a in articles:
            assert isinstance(a, ScrapedArticle)
            assert a.source_id == "dre_appointments"
            assert a.title
            assert a.url
            assert a.url.startswith("https://files.dre.pt/")
            assert a.language == "pt"
            assert a.collected_at.tzinfo is not None  # UTC

    @pytest.mark.asyncio
    async def test_content_text_extracted_from_pdf(self) -> None:
        """Should extract text content from downloaded PDFs."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response(
            [SEARCH_RESULT_LUSA]
        )

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        assert len(articles) == 1
        assert articles[0].content_text is not None
        assert "Test content for DRE" in articles[0].content_text

    @pytest.mark.asyncio
    async def test_fallback_to_tavily_when_exa_fails(self) -> None:
        """Should fall back to Tavily when Exa returns no results."""
        mock_exa = MagicMock()
        mock_exa.search.return_value = _make_exa_response([])  # Exa returns empty

        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {
            "results": [
                {
                    "url": "https://files.dre.pt/2s/2026/05/12345.pdf",
                    "title": "Nomeação Lusa via Tavily fallback",
                    "content": "Test fallback",
                }
            ]
        }

        spider = await _make_spider()
        spider._exa = mock_exa
        spider._tavily = mock_tavily
        with patch.object(settings, "exa_api_key", "fake-key"):
            with patch.object(settings, "tavily_api_key", "fake-key-tavily"):
                articles = await spider.fetch("dre_appointments")

        assert len(articles) >= 1
        assert "Tavily" in articles[0].title

    @pytest.mark.asyncio
    async def test_search_query_failure_continues(self) -> None:
        """Should continue processing remaining queries if one fails."""
        mock_exa = MagicMock()
        # First call raises error, second works
        mock_exa.search.side_effect = [
            Exception("API error"),
            _make_exa_response([SEARCH_RESULT_LUSA]),
        ]

        spider = await _make_spider()
        spider._exa = mock_exa
        with patch.object(settings, "exa_api_key", "fake-key"):
            articles = await spider.fetch("dre_appointments")

        assert len(articles) >= 1
