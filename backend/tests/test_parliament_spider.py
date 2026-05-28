"""Tests for ParliamentSpider.

Mocks httpx transport to simulate the export endpoint responses.
No external network calls are made.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from src.scrapers.spiders.parliament import (
    ParliamentSpider,
    build_export_url,
    extract_text_from_pdf,
    _is_media_relevant,
    _format_title,
    guess_published_date,
    _DISCOVERY_RANGES,
)
from src.scrapers.base import ScrapedArticle


# ── Tiny valid PDF for testing ────────────────────────────────────────────────

TINY_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 112 >>\nstream\nBT /F1 12 Tf\n"
    b"100 700 Td (Debate sobre a ERC e a comunicacao social) Tj\n"
    b"100 680 Td (RTP e Lusa foram mencionadas) Tj\n"
    b"ET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000266 00000 n \n0000000374 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n443\n%%EOF"
)

TINY_PDF_IRRELEVANT = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 62 >>\nstream\nBT /F1 12 Tf\n"
    b"100 700 Td (Debate sobre o orcamento do Estado para 2026) Tj\n"
    b"ET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000266 00000 n \n0000000374 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n443\n%%EOF"
)


# ── Mock transport handler ────────────────────────────────────────────────────

def _make_handler(
    available_docs: list[tuple[str, str, str, int]],
    pdf_content: bytes = TINY_PDF,
) -> Callable[..., httpx.Response]:
    """Create an httpx mock transport handler.

    ``available_docs`` is a list of ``(serie, legis, sessao, numero)`` that
    should return HTTP 200/PDF.  Everything else returns 404.
    """
    available_urls = {
        build_export_url(serie, legis, sessao, num)
        for serie, legis, sessao, num in available_docs
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) in available_urls:
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=pdf_content,
            )
        return httpx.Response(404, text="Not Found")

    return _handler


async def _make_spider(
    available_docs: list[tuple[str, str, str, int]],
    pdf_content: bytes = TINY_PDF,
) -> ParliamentSpider:
    """Create a ParliamentSpider with a mocked HTTP client."""
    handler = _make_handler(available_docs, pdf_content)
    spider = ParliamentSpider()
    await spider.http_client.aclose()
    spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return spider


# ── Unit tests for helper functions ───────────────────────────────────────────


class TestBuildExportUrl:
    def test_basic_url(self) -> None:
        url = build_export_url("01", "16", "01", 1)
        assert "debates.parlamento.pt/pagina/export" in url
        assert "exportType=pdf" in url
        assert "legis=16" in url
        assert "sessao=01" in url
        assert "numero=001" in url

    def test_number_formatting(self) -> None:
        url = build_export_url("01", "15", "02", 42)
        assert "numero=042" in url

    def test_all_params_present(self) -> None:
        url = build_export_url("01", "14", "03", 123)
        assert "exportControl=documentoCompleto" in url
        assert "periodo=r3" in url
        assert "publicacao=dar" in url
        assert "serie=01" in url


class TestExtractTextFromPdf:
    def test_valid_pdf_returns_text(self) -> None:
        text = extract_text_from_pdf(TINY_PDF)
        assert text is not None
        assert "ERC" in text
        assert "comunicacao social" in text

    def test_invalid_pdf_returns_none(self) -> None:
        text = extract_text_from_pdf(b"not a pdf")
        assert text is None

    def test_empty_bytes_returns_none(self) -> None:
        text = extract_text_from_pdf(b"")
        assert text is None


class TestIsMediaRelevant:
    def test_erc_mention(self) -> None:
        assert _is_media_relevant("O relatório da ERC sobre comunicação social")

    def test_rtp_mention(self) -> None:
        assert _is_media_relevant("A RTP deve continuar a ser serviço público")

    def test_lusa_mention(self) -> None:
        assert _is_media_relevant("A Lusa é a agência de notícias nacional")

    def test_liberdade_imprensa(self) -> None:
        assert _is_media_relevant("A liberdade de imprensa é fundamental")

    def test_irrelevant_text(self) -> None:
        assert not _is_media_relevant("O orçamento para a saúde foi aprovado")

    def test_anacom_mention(self) -> None:
        assert _is_media_relevant("ANACOM regula as comunicações em Portugal")

    def test_jornalistas_keyword(self) -> None:
        assert _is_media_relevant("Os jornalistas portugueses enfrentam desafios")

    def test_case_insensitive(self) -> None:
        assert _is_media_relevant("a erc analisou o mercado")
        assert _is_media_relevant("Comunicação Social é tema importante")


class TestFormatTitle:
    def test_xvi_legislatura(self) -> None:
        title = _format_title("01", "16", "01", 1)
        assert "XVI Legislatura" in title
        assert "N.º 001" in title
        assert "Sessão 1" in title

    def test_xv_legislatura(self) -> None:
        title = _format_title("01", "15", "02", 42)
        assert "XV Legislatura" in title
        assert "N.º 042" in title
        assert "Sessão 2" in title


class TestGuessPublishedDate:
    def test_legis_16_sessao_01(self) -> None:
        dt = guess_published_date("16", "01", 1)
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 3

    def test_legis_15_sessao_02(self) -> None:
        dt = guess_published_date("15", "02", 42)
        assert dt is not None
        assert dt.year == 2022
        assert dt.month == 10

    def test_legis_14_sessao_03(self) -> None:
        dt = guess_published_date("14", "03", 100)
        assert dt is not None
        assert dt.year == 2020
        assert dt.month == 3

    def test_unknown_legis(self) -> None:
        dt = guess_published_date("99", "01", 1)
        assert dt is None


# ── DRESpider fetch tests ─────────────────────────────────────────────────────


class TestParliamentSpider:
    @pytest.mark.asyncio
    async def test_fetch_discovers_and_filters_media_relevant(self) -> None:
        """Should discover available docs and return media-relevant ones."""
        available = [
            ("01", "16", "01", 1),
            ("01", "16", "01", 2),
            ("01", "16", "01", 3),
        ]
        spider = await _make_spider(available, TINY_PDF)
        articles = await spider.fetch("parlamento_debates")

        # All 3 PDFs contain "ERC" and "comunicacao social" → should all be kept
        assert len(articles) == 3

        for a in articles:
            assert a.source_id == "parlamento_debates"
            assert a.url.startswith("http://debates.parlamento.pt")
            assert "DAR I Série" in a.title
            assert a.language == "pt"
            assert a.author == "Assembleia da República"
            assert a.content_text is not None
            assert "ERC" in a.content_text

    @pytest.mark.asyncio
    async def test_fetch_filters_irrelevant_documents(self) -> None:
        """Should skip documents that don't mention media keywords."""
        available = [("01", "16", "01", 1)]
        spider = await _make_spider(available, TINY_PDF_IRRELEVANT)  # Only talks about budget
        articles = await spider.fetch("parlamento_debates")

        assert len(articles) == 0  # Not media-relevant

    @pytest.mark.asyncio
    async def test_fetch_no_available_documents(self) -> None:
        """Should return empty when no documents are available."""

        def _handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        spider = ParliamentSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("parlamento_debates")
        assert articles == []

    @pytest.mark.asyncio
    async def test_fetch_http_error_on_download(self) -> None:
        """Should skip documents that fail to download."""

        def _handler(request: httpx.Request) -> httpx.Response:
            # HEAD succeeds (discovery), but GET fails
            if request.method == "HEAD":
                return httpx.Response(200, headers={"content-type": "application/pdf"})
            return httpx.Response(500, text="Error")

        spider = ParliamentSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("parlamento_debates")
        assert articles == []  # Document found but download failed → skip

    @pytest.mark.asyncio
    async def test_fetch_non_pdf_response_skipped(self) -> None:
        """Should skip documents where the export returns non-PDF content."""

        def _handler(request: httpx.Request) -> httpx.Response:
            if "numero=001" in str(request.url):
                # HEAD says 200 PDF
                if request.method == "HEAD":
                    return httpx.Response(200, headers={"content-type": "application/pdf"})
                # GET returns HTML instead of PDF
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Oops</html>")
            return httpx.Response(404, text="Not Found")

        spider = ParliamentSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("parlamento_debates")
        assert articles == []

    @pytest.mark.asyncio
    async def test_each_article_has_required_fields(self) -> None:
        """Every returned article should have core fields populated."""
        available = [("01", "16", "01", 1)]
        spider = await _make_spider(available, TINY_PDF)

        articles = await spider.fetch("parlamento_debates")

        assert len(articles) == 1
        a = articles[0]
        assert isinstance(a, ScrapedArticle)
        assert a.source_id == "parlamento_debates"
        assert a.title
        assert a.url
        assert a.content_text
        assert a.author == "Assembleia da República"
        assert a.language == "pt"
        assert a.collected_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        """Should not create duplicate articles for the same URL."""
        # Two discovery ranges that overlap
        available = [("01", "16", "01", 1), ("01", "16", "01", 1)]
        spider = await _make_spider(available, TINY_PDF)

        # Manually patch _DISCOVERY_RANGES to cause overlap
        with patch(
            "src.scrapers.spiders.parliament._DISCOVERY_RANGES",
            [("16", "01", 1), ("16", "01", 1)],  # Same range twice
        ):
            articles = await spider.fetch("parlamento_debates")

        assert len(articles) == 1  # No duplicates

    @pytest.mark.asyncio
    async def test_discovery_ranges_have_valid_data(self) -> None:
        """Ensure _DISCOVERY_RANGES contains valid entries for testing."""
        for legis, sessao, max_num in _DISCOVERY_RANGES:
            assert len(legis) == 2
            assert len(sessao) == 2
            assert 1 <= max_num <= 300

    @pytest.mark.asyncio
    async def test_summary_truncated_from_content(self) -> None:
        """Summary should be the first ~500 chars of the extracted text."""
        available = [("01", "16", "01", 1)]
        spider = await _make_spider(available, TINY_PDF)

        articles = await spider.fetch("parlamento_debates")

        assert len(articles) == 1
        a = articles[0]
        assert a.summary is not None
        # The full text is short (112 bytes in the PDF stream), so summary should match
        assert "ERC" in a.summary
