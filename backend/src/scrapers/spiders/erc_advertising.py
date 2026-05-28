"""
ERC Institutional Advertising spider — Relatório sobre Publicidade Institucional
do Estado (PIE).

Downloads monthly and annual reports published by the Portuguese media regulator
(ERC) detailing State spending on institutional advertising across media outlets.

Report URL pattern (confirmed working)
---------------------------------------
Monthly reports::

    https://www.erc.pt/documentos/Relatorios/PIE{YYYY}/RelatorioPIE{month}{year}.pdf

    Example: https://www.erc.pt/documentos/Relatorios/PIE2026/RelatorioPIEjaneiro2026.pdf

Annual reports::

    https://www.erc.pt/documentos/Relatorios/PIE{YYYY}/RelatorioGlobalPIE{YYYY}.pdf

    Example: https://www.erc.pt/documentos/Relatorios/PIE2025/RelatorioGlobalPIE2025.pdf

Coverage: 2015–present (monthly from 2016).

Data typically found in reports
--------------------------------
- Total spending by the State on institutional advertising
- Spending breakdown by ministry / government entity
- Spending breakdown by media group and outlet (TV, radio, print, digital)
- Distribution percentages across media types
- Compliance with legal requirements (e.g., 40%+ to local/regional media)

Extraction strategy
-------------------
1. Discover PDF URLs from the ERC listing page (preferred) or generate from
   the known URL pattern (fallback).
2. Download each PDF.
3. Extract tables with pdfplumber's ``extract_tables()`` method.
4. Also extract full text as context.
5. Format as ScrapedArticle with structured JSON in ``content_text``.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone

import httpx
from src.scrapers.base import BaseSpider, ScrapedArticle

_PT_MONTHS_LOWER: dict[str, str] = {
    "janeiro": "01", "fevereiro": "02", "marco": "03", "março": "03",
    "abril": "04", "maio": "05", "junho": "06",
    "julho": "07", "agosto": "08", "setembro": "09",
    "outubro": "10", "novembro": "11", "dezembro": "12",
}

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}

# ── PDF discovery ─────────────────────────────────────────────────────────────

ERC_REPORTS_PAGE = (
    "https://www.erc.pt/pt/estudos/publicidade--/"
    "relatorio-sobre-publicidade-institucional-do-estado-/"
)

# Fallback URL patterns for generating report URLs
_MONTH_URL_TEMPLATE = "https://www.erc.pt/documentos/Relatorios/PIE{year}/RelatorioPIE{month}{year}.pdf"
_ANNUAL_URL_TEMPLATE = "https://www.erc.pt/documentos/Relatorios/PIE{year}/RelatorioGlobalPIE{year}.pdf"

# Portugese month names (lowercase) as they appear in ERC URLs
_MONTH_NAMES: list[str] = [
    "janeiro", "fevereiro", "marco",
    "abril", "maio", "junho",
    "julho", "agosto", "setembro",
    "outubro", "novembro", "dezembro",
]

_YEARS = list(range(2016, 2027))  # 2016–2026 full years


def _parse_month_from_url(url: str) -> str | None:
    """Extract the month from a report PDF filename.

    Returns the 2-digit month string (\"01\", \"02\", …) or ``None``.
    """
    filename = url.rsplit("/", 1)[-1].lower()
    for pt_name, num in _PT_MONTHS_LOWER.items():
        if pt_name in filename:
            return num
    return None


def _parse_year_from_url(url: str) -> str | None:
    """Extract the 4-digit year from a report PDF filename or path."""
    m = re.search(r"(\d{4})", url)
    return m.group(1) if m else None


# ── PDF table extraction ──────────────────────────────────────────────────────


def extract_tables_from_pdf(content: bytes) -> list[dict]:
    """Extract tables and text from an ERC report PDF.

    Returns a list of dicts, each representing a page's extracted data:

    .. code-block:: python

        [
            {
                \"page\": 1,
                \"text\": \"...\",
                \"tables\": [
                    [[\"col1\", \"col2\"], [\"val1\", \"val2\"]],
                    ...
                ]
            },
            ...
        ]

    Returns an empty list on failure.
    """
    import pdfplumber

    pages_data: list[dict] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                entry: dict = {"page": page_num}

                # Extract full text
                page_text = page.extract_text()
                entry["text"] = page_text if page_text else ""

                # Extract tables
                raw_tables = page.extract_tables()
                cleaned_tables: list[list[list[str]]] = []
                for table in raw_tables:
                    cleaned: list[list[str]] = []
                    for row in table:
                        cleaned.append([(cell or "").strip() for cell in row])
                    if cleaned:
                        cleaned_tables.append(cleaned)
                entry["tables"] = cleaned_tables

                pages_data.append(entry)

        return pages_data
    except Exception as exc:
        logger.warning("ERC PDF table extraction failed: %s", exc)
        return []


def format_report_as_text(pages_data: list[dict], title: str, url: str) -> str:
    """Format the extracted PDF data into a structured text article.

    Includes both the full extracted text and any detected tables (formatted
    as markdown-like tables for readability).
    """
    lines: list[str] = [
        f"# {title}",
        f"Fonte: {url}",
        f"Extraído em: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    # Check if we have any table data at all
    has_tables = any(p["tables"] for p in pages_data)

    if has_tables:
        lines.append("## Tabelas Extraídas")
        lines.append("")

    for page in pages_data:
        # Include tables
        for table in page["tables"]:
            if not table:
                continue
            # Header row
            lines.append("| " + " | ".join(table[0]) + " |")
            # Separator
            lines.append("| " + " | ".join(["---"] * len(table[0])) + " |")
            # Data rows
            for row in table[1:]:
                # Pad row to match header length
                while len(row) < len(table[0]):
                    row.append("")
                lines.append("| " + " | ".join(row[:len(table[0])]) + " |")
            lines.append("")

        # Include full text if not already captured in tables
        if page["text"]:
            lines.append(page["text"])
            lines.append("")

    return "\n".join(lines)


def summarize_report(pages_data: list[dict]) -> str | None:
    """Generate a brief summary of key figures from the extracted data.

    Looks for total spending values and entity names in the first few
    pages of the report.
    """
    summary_lines: list[str] = []
    total_seen = False

    for page in pages_data[:5]:  # First 5 pages
        text = page.get("text", "")
        # Look for total spending patterns
        for pattern in [
            r"(?:total|investimento total|montante global)[^\n]*?([\d.,]+\s*[€E])",
            r"([\d.,]+)\s*(?:euros|€)",
        ]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches and not total_seen:
                summary_lines.append(f"Valor encontrado: {matches[0]}")
                total_seen = True

        # Check tables for totals
        for table in page.get("tables", []):
            for row in table:
                row_text = " ".join(row).lower()
                if "total" in row_text and any(c.isdigit() for c in row_text):
                    summary_lines.append(f"Linha de total: {' | '.join(row)}")

    if not summary_lines:
        return None
    return "; ".join(summary_lines[:3])  # Keep it concise


# ── Spider ────────────────────────────────────────────────────────────────────


class ERCAdvertisingSpider(BaseSpider):
    """Download ERC institutional advertising reports and extract structured data.

    Discovers report PDFs by:
    1. Scraping the ERC listing page for direct PDF links (preferred).
    2. Falling back to URL generation from the known pattern.

    Downloads each PDF, extracts tables with pdfplumber, and returns
    ``ScrapedArticle`` objects with structured table data in ``content_text``.

    The ``url`` parameter is used as the ERC reports listing page URL;
    if empty, the default page is used.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )
        self._seen_urls: set[str] = set()

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        self._seen_urls.clear()

        try:
            # Phase 1: Discover report PDF URLs
            listing_url = url or ERC_REPORTS_PAGE
            pdf_urls = await self._discover_pdfs(listing_url)

            if not pdf_urls:
                logger.info("ERC: no PDFs discovered via listing page, trying fallback")
                pdf_urls = self._generate_fallback_urls()

            if not pdf_urls:
                logger.warning("ERC: no report PDFs found at all")
                return []

            # Phase 2: Download and process
            for pdf_url in pdf_urls:
                if pdf_url in self._seen_urls:
                    continue
                self._seen_urls.add(pdf_url)

                try:
                    article = await self._process_report(pdf_url, source_id)
                    if article is not None:
                        articles.append(article)
                except Exception as exc:
                    logger.debug("ERC: failed to process %s: %s", pdf_url, exc)
                    continue

        finally:
            await self.http_client.aclose()

        return articles

    async def _discover_pdfs(self, listing_url: str) -> list[str]:
        """Scrape the ERC listing page for PDF links.

        Parses the page HTML for any ``.pdf`` URLs in the
        ``/documentos/Relatorios/`` path.
        """
        try:
            response = await self.http_client.get(listing_url)
            response.raise_for_status()
            html = response.text

            pdf_urls: list[str] = []
            for href in re.findall(r'href=[\"\']([^\"\']+\.pdf)[\"\']', html, re.IGNORECASE):
                if "Relatorio" in href:
                    full_url = href
                    if href.startswith("/"):
                        full_url = "https://www.erc.pt" + href
                    elif href.startswith("http://"):
                        full_url = "https://" + href[7:]
                    if full_url.startswith("https://www.erc.pt"):
                        pdf_urls.append(full_url)

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique: list[str] = []
            for u in pdf_urls:
                if u not in seen:
                    seen.add(u)
                    unique.append(u)

            return unique

        except Exception as exc:
            logger.warning("ERC: failed to scrape listing page (%s)", exc)
            return []

    def _generate_fallback_urls(self) -> list[str]:
        """Generate likely report URLs from known patterns.

        Covers monthly reports from the past 2 years + annual reports for
        all years in the known range.  This is a fallback for when the
        listing page cannot be scraped.
        """
        now = datetime.now(timezone.utc)
        current_year = now.year
        urls: list[str] = []

        # Monthly reports for current and previous year
        for year in [current_year, current_year - 1]:
            for month_name in _MONTH_NAMES:
                url = _MONTH_URL_TEMPLATE.format(year=year, month=month_name)
                urls.append(url)

        # Also try with "março" variant
        if current_year >= 2020 or current_year - 1 >= 2020:
            for year in [current_year, current_year - 1]:
                url = _MONTH_URL_TEMPLATE.format(year=year, month="março")
                urls.append(url)

        # Annual reports
        for year in _YEARS:
            url = _ANNUAL_URL_TEMPLATE.format(year=year)
            urls.append(url)

        return urls

    async def _process_report(self, pdf_url: str, source_id: str) -> ScrapedArticle | None:
        """Download a single ERC report PDF and extract structured data.

        Returns a ``ScrapedArticle`` or ``None`` on failure.
        """
        response = await self.http_client.get(pdf_url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type.lower():
            logger.debug("ERC: non-PDF at %s (%s)", pdf_url, content_type)
            return None

        # Extract tables and text
        pages_data = extract_tables_from_pdf(response.content)
        if not pages_data:
            logger.debug("ERC: no data extracted from %s", pdf_url)
            return None

        # Build title and date
        title = _build_report_title(pdf_url)
        pub_date = _extract_report_date(pdf_url)

        # Format content
        content_text = format_report_as_text(pages_data, title, pdf_url)
        summary = summarize_report(pages_data)

        return ScrapedArticle(
            external_id=pdf_url,
            url=pdf_url,
            title=title,
            content_text=content_text,
            summary=summary,
            author="Entidade Reguladora da Comunicação Social (ERC)",
            published_at=pub_date,
            language="pt",
            source_id=source_id,
        )


def _build_report_title(pdf_url: str) -> str:
    """Build a human-readable title from the PDF URL.

    Examples::

        ERC Relatório PIE — Janeiro 2026
        ERC Relatório PIE — Relatório Global 2025
    """
    filename = pdf_url.rsplit("/", 1)[-1].replace(".pdf", "")
    lower = filename.lower()

    if "global" in lower or "anual" in lower:
        year = _parse_year_from_url(pdf_url) or ""
        return f"ERC Relatório PIE — Relatório Global {year}".strip()

    month = _parse_month_from_url(pdf_url)
    year = _parse_year_from_url(pdf_url)
    month_name = ""
    if month:
        for name, num in _PT_MONTHS_LOWER.items():
            if num == month:
                # Capitalise first letter
                month_name = name.capitalize()
                break

    if month_name and year:
        return f"ERC Relatório PIE — {month_name} {year}"
    if year:
        return f"ERC Relatório PIE — {year}"

    return f"ERC Relatório PIE — {filename}"


def _extract_report_date(pdf_url: str) -> datetime | None:
    """Try to extract a publication date from the PDF URL."""
    year_str = _parse_year_from_url(pdf_url)
    month_str = _parse_month_from_url(pdf_url)

    if year_str:
        year = int(year_str)
        month = int(month_str) if month_str else 1
        # Use the 15th as an approximate date
        try:
            return datetime(year, month, 15, tzinfo=timezone.utc)
        except ValueError:
            return datetime(year, 1, 15, tzinfo=timezone.utc)

    return None
