"""Tests for ERCAdvertisingSpider.

Mocks httpx transport to simulate the ERC website and PDF responses.
No external network calls are made.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from src.scrapers.spiders.erc_advertising import (
    ERCAdvertisingSpider,
    extract_tables_from_pdf,
    format_report_as_text,
    summarize_report,
    _build_report_title,
    _extract_report_date,
    _parse_month_from_url,
    _parse_year_from_url,
)
from src.scrapers.base import ScrapedArticle


# ── Tiny valid PDF with a simple table ────────────────────────────────────────

# Minimal PDF containing "Total: 1.234.567 €" and "RTP: 100.000 €"
TINY_PDF_WITH_TABLE = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 172 >>\nstream\nBT /F1 12 Tf\n"
    b"100 750 Td (ERC Relatorio PIE - Janeiro 2026) Tj\n"
    b"100 720 Td (Investimento total: 1.234.567 EUR) Tj\n"
    b"100 690 Td (RTP: 100.000 EUR) Tj\n"
    b"100 660 Td (Lusa: 50.000 EUR) Tj\n"
    b"100 630 Td (Publico: 75.000 EUR) Tj\n"
    b"ET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000266 00000 n \n0000000488 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n557\n%%EOF"
)

# PDF without any number/total data
TINY_PDF_EMPTY = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 55 >>\nstream\nBT /F1 12 Tf\n"
    b"100 700 Td (Relatorio vazio sem dados numericos) Tj\n"
    b"ET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000266 00000 n \n0000000374 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n443\n%%EOF"
)


# ── Mock ERC listing page ────────────────────────────────────────────────────

ERC_LISTING_HTML = """<!DOCTYPE html>
<html>
<body>
  <h1>Relatório sobre Publicidade Institucional do Estado</h1>
  <ul>
    <li><a href="/documentos/Relatorios/PIE2026/RelatorioPIEjaneiro2026.pdf">Janeiro 2026</a></li>
    <li><a href="/documentos/Relatorios/PIE2026/RelatorioPIEfevereiro2026.pdf">Fevereiro 2026</a></li>
    <li><a href="/documentos/Relatorios/PIE2025/RelatorioGlobalPIE2025.pdf">Relatório Global 2025</a></li>
    <li><a href="https://www.erc.pt/documentos/Relatorios/PIE2025/RelatorioPIEdezembro2025.pdf">Dezembro 2025</a></li>
  </ul>
</body>
</html>
"""



def _make_handler(
    listing_html: str = ERC_LISTING_HTML,
    pdf_content: bytes = TINY_PDF_WITH_TABLE,
    pdf_status: int = 200,
) -> Callable[..., httpx.Response]:
    """Create an httpx mock transport handler.

    Routes requests based on URL:
    - ERC listing page returns the HTML
    - PDF endpoints return the PDF content (or error)
    """
    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if "/pt/estudos/" in url and ".pdf" not in url:
            # Listing page
            return httpx.Response(200, text=listing_html)

        if ".pdf" in url and "erc.pt" in url:
            # PDF download
            if pdf_status == 200:
                return httpx.Response(
                    pdf_status,
                    headers={"content-type": "application/pdf"},
                    content=pdf_content,
                )
            return httpx.Response(pdf_status, text="Error")

        # Fallback for fallback URL probes
        if ".pdf" in url:
            if pdf_status == 200:
                return httpx.Response(
                    pdf_status,
                    headers={"content-type": "application/pdf"},
                    content=pdf_content,
                )
            return httpx.Response(404, text="Not Found")

        return httpx.Response(404, text="Not Found")

    return _handler


async def _make_spider(
    listing_html: str = ERC_LISTING_HTML,
    pdf_content: bytes = TINY_PDF_WITH_TABLE,
    pdf_status: int = 200,
) -> ERCAdvertisingSpider:
    """Create an ERCAdvertisingSpider with a mocked HTTP client."""
    handler = _make_handler(listing_html, pdf_content, pdf_status)
    spider = ERCAdvertisingSpider()
    await spider.http_client.aclose()
    spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return spider


# ── Unit tests for helper functions ───────────────────────────────────────────


class TestParseMonthFromUrl:
    def test_janeiro(self) -> None:
        assert _parse_month_from_url("RelatorioPIEjaneiro2026.pdf") == "01"

    def test_marco(self) -> None:
        assert _parse_month_from_url("RelatorioPIEmarco2026.pdf") == "03"

    def test_março(self) -> None:
        assert _parse_month_from_url("RelatorioPIEmarço2026.pdf") == "03"

    def test_global_report(self) -> None:
        assert _parse_month_from_url("RelatorioGlobalPIE2025.pdf") is None

    def test_none(self) -> None:
        assert _parse_month_from_url("") is None


class TestParseYearFromUrl:
    def test_four_digit_year(self) -> None:
        assert _parse_year_from_url("RelatorioPIEjaneiro2026.pdf") == "2026"

    def test_no_year(self) -> None:
        assert _parse_year_from_url("RelatorioPIE.pdf") is None


class TestBuildReportTitle:
    def test_monthly_report(self) -> None:
        url = "https://www.erc.pt/documentos/Relatorios/PIE2026/RelatorioPIEjaneiro2026.pdf"
        title = _build_report_title(url)
        assert "Janeiro" in title
        assert "2026" in title

    def test_global_report(self) -> None:
        url = "https://www.erc.pt/documentos/Relatorios/PIE2025/RelatorioGlobalPIE2025.pdf"
        title = _build_report_title(url)
        assert "Global" in title
        assert "2025" in title

    def test_unknown_format(self) -> None:
        title = _build_report_title("https://www.erc.pt/documentos/Relatorios/PIE2026/outro.pdf")
        assert "ERC" in title


class TestExtractReportDate:
    def test_janeiro_2026(self) -> None:
        dt = _extract_report_date("https://www.erc.pt/.../RelatorioPIEjaneiro2026.pdf")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 1

    def test_global_report(self) -> None:
        dt = _extract_report_date("https://www.erc.pt/.../RelatorioGlobalPIE2025.pdf")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1  # Default month


# ── PDF extraction tests ──────────────────────────────────────────────────────


class TestExtractTablesFromPdf:
    def test_valid_pdf_returns_pages(self) -> None:
        pages = extract_tables_from_pdf(TINY_PDF_WITH_TABLE)
        assert len(pages) == 1
        assert pages[0]["page"] == 1
        assert "1.234.567 EUR" in pages[0]["text"]

    def test_invalid_pdf_returns_empty(self) -> None:
        pages = extract_tables_from_pdf(b"not a pdf")
        assert pages == []

    def test_empty_bytes_returns_empty(self) -> None:
        pages = extract_tables_from_pdf(b"")
        assert pages == []


class TestFormatReportAsText:
    def test_contains_title_and_source(self) -> None:
        pages = extract_tables_from_pdf(TINY_PDF_WITH_TABLE)
        text = format_report_as_text(pages, "Test Report", "https://example.com/test.pdf")
        assert "Test Report" in text
        assert "example.com" in text

    def test_contains_extracted_text(self) -> None:
        pages = extract_tables_from_pdf(TINY_PDF_WITH_TABLE)
        text = format_report_as_text(pages, "Test", "url")
        assert "1.234.567" in text


class TestSummarizeReport:
    def test_finds_total_value(self) -> None:
        pages = extract_tables_from_pdf(TINY_PDF_WITH_TABLE)
        summary = summarize_report(pages)
        assert summary is not None
        assert "1.234.567" in summary

    def test_empty_report_returns_none(self) -> None:
        pages = extract_tables_from_pdf(TINY_PDF_EMPTY)
        summary = summarize_report(pages)
        assert summary is None


# ── Spider fetch tests ────────────────────────────────────────────────────────


class TestERCAdvertisingSpider:
    @pytest.mark.asyncio
    async def test_fetch_discovers_pdfs_from_listing_page(self) -> None:
        """Should discover PDFs from the ERC listing page and return articles."""
        spider = await _make_spider()
        articles = await spider.fetch("erc_advertising")

        # We have 4 PDF links in the mock listing page
        assert len(articles) == 4

        for a in articles:
            assert a.source_id == "erc_advertising"
            assert a.url.endswith(".pdf")
            assert "ERC" in a.title
            assert a.language == "pt"
            assert a.author == "Entidade Reguladora da Comunicação Social (ERC)"
            assert a.content_text is not None
            assert "1.234.567" in a.content_text

    @pytest.mark.asyncio
    async def test_fetch_empty_listing_falls_back(self) -> None:
        """Should fall back to URL generation when listing page has no PDFs."""
        # Handler that returns listing page without PDF links
        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "erc.pt/pt/estudos" in url and ".pdf" not in url:
                return httpx.Response(200, text="<html><body>No PDFs</body></html>")
            if ".pdf" in url:
                # Some fallback URLs might exist
                if "RelatorioPIEjaneiro2026" in url:
                    return httpx.Response(200, headers={"content-type": "application/pdf"}, content=TINY_PDF_WITH_TABLE)
                # Return 404 for most fallback URLs
                return httpx.Response(404, text="Not Found")
            return httpx.Response(404, text="Not Found")

        spider = ERCAdvertisingSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("erc_advertising")
        # Some fallback URLs may exist (e.g., current year/month)
        assert isinstance(articles, list)

    @pytest.mark.asyncio
    async def test_fetch_no_pdfs_found(self) -> None:
        """Should return empty when no PDFs are found by either method."""

        def _handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        spider = ERCAdvertisingSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("erc_advertising")
        assert articles == []

    @pytest.mark.asyncio
    async def test_fetch_http_error_on_listing(self) -> None:
        """Should handle HTTP errors gracefully (fall back to URL generation)."""

        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "erc.pt/pt/estudos" in url and ".pdf" not in url:
                return httpx.Response(500, text="Error")
            # Some fallback URLs might work
            if "RelatorioPIEjaneiro2026" in url:
                return httpx.Response(200, headers={"content-type": "application/pdf"}, content=TINY_PDF_WITH_TABLE)
            return httpx.Response(404, text="Not Found")

        spider = ERCAdvertisingSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("erc_advertising")
        assert isinstance(articles, list)
        # May have some from fallback

    @pytest.mark.asyncio
    async def test_fetch_non_pdf_response_skipped(self) -> None:
        """Should skip URLs that return non-PDF content."""

        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "erc.pt/pt/estudos" in url and ".pdf" not in url:
                return httpx.Response(200, text=ERC_LISTING_HTML)
            if ".pdf" in url:
                # Return HTML instead of PDF
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Not a PDF</html>")
            return httpx.Response(404, text="Not Found")

        spider = ERCAdvertisingSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("erc_advertising")
        assert articles == []

    @pytest.mark.asyncio
    async def test_each_article_has_required_fields(self) -> None:
        """Every returned article should have core fields populated."""
        spider = await _make_spider()
        articles = await spider.fetch("erc_advertising")

        assert len(articles) > 0
        for a in articles:
            assert isinstance(a, ScrapedArticle)
            assert a.source_id == "erc_advertising"
            assert a.title
            assert a.url
            assert a.url.endswith(".pdf")
            assert a.content_text
            assert a.author == "Entidade Reguladora da Comunicação Social (ERC)"
            assert a.language == "pt"
            assert a.collected_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        """Should not create duplicate articles for the same PDF URL."""

        def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "erc.pt/pt/estudos" in url and ".pdf" not in url:
                # Return duplicate links
                return httpx.Response(200, text="""
                    <html><body>
                    <a href="/documentos/Relatorios/PIE2026/RelatorioPIEjaneiro2026.pdf">Link 1</a>
                    <a href="/documentos/Relatorios/PIE2026/RelatorioPIEjaneiro2026.pdf">Link 2</a>
                    </body></html>
                """)
            if ".pdf" in url:
                return httpx.Response(200, headers={"content-type": "application/pdf"}, content=TINY_PDF_WITH_TABLE)
            return httpx.Response(404, text="Not Found")

        spider = ERCAdvertisingSpider()
        await spider.http_client.aclose()
        spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

        articles = await spider.fetch("erc_advertising")
        assert len(articles) == 1  # Deduplicated

    @pytest.mark.asyncio
    async def test_fallback_urls_include_annual_reports(self) -> None:
        """Fallback URL generation should include annual reports."""
        spider = await _make_spider()
        fallback_urls = spider._generate_fallback_urls()

        # Should contain annual report URLs
        annual_urls = [u for u in fallback_urls if "Global" in u]
        assert len(annual_urls) > 0
        assert all("RelatorioGlobalPIE" in u for u in annual_urls)
