"""
DRE (Diário da República Eletrónico) spider — appointment discovery via
Exa Search API (primary) / Tavily Search API (fallback), PDF download from
files.dre.pt, and text extraction with pdfplumber.

Approach
--------
The DRE website is built on OutSystems and renders 100% client-side with no
public REST API.  Individual publication PDFs are directly accessible at::

    files.dre.pt/{series}s/{year}/{month}/{id}.pdf

Exa Search API (free tier: 1,000 requests/month) is used as the primary search
back-end to discover relevant PDF URLs.  Tavily Search API (1,000 credits/month)
serves as a fallback if Exa is unavailable or exhausted.

Each discovered PDF is downloaded and its text extracted via pdfplumber.

Relevant organs & typical search queries
-----------------------------------------
- Lusa: nomeação + Lusa
- RTP:  nomeação + RTP
- ERC:  nomeação + ERC
- General: "comunicação social" nomeação

Volume estimate: ~20-40 relevant appointments/year.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import httpx
import pdfplumber
from exa_py import Exa
from tavily import TavilyClient
from src.config.settings import settings
from src.scrapers.base import BaseSpider, ScrapedArticle

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}

# ── Search queries ────────────────────────────────────────────────────────────
# Keywords for finding media-related appointments on files.dre.pt.
# For Exa: these are used as keyword queries with include_domains=["files.dre.pt"]
# For Tavily: "site:files.dre.pt" is prepended dynamically.

DRE_SEARCH_QUERIES: list[str] = [
    'Lusa nomeação',
    'RTP nomeação',
    'ERC nomeação',
    'ANACOM nomeação',
    '"comunicação social" nomeação',
    '"conselho de administração" comunicação',
]


def _extract_pdf_url(url: str) -> str | None:
    """Validate that a URL points to a ``files.dre.pt`` PDF.

    Returns the URL (normalised to https) or ``None`` if it's not a DRE PDF.

    ``gratuitos/`` URLs are rejected because they point to consolidated daily
    PDFs (hundreds of pages).  Only individual document PDFs are accepted
    (those matching ``files.dre.pt/{series}s/{year}/{month}/{id}.pdf``).
    """
    if not url:
        return None
    if "files.dre.pt" not in url.lower():
        return None
    # Skip consolidated daily PDFs (gratuitos/ path)
    if "/gratuitos/" in url.lower():
        return None
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url


def _extract_text_from_pdf(content: bytes) -> str | None:
    """Extract text from a PDF byte stream using pdfplumber.

    Returns ``None`` if extraction fails (corrupt PDF, empty, etc.).
    """
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text_parts: list[str] = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            full_text = "\n\n".join(text_parts)
            return full_text if full_text.strip() else None
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        return None


# ── Spider ────────────────────────────────────────────────────────────────────


class DRESpider(BaseSpider):
    """Discover DRE appointment PDFs via Exa Search API (primary) or Tavily (fallback).

    Requires ``EXA_API_KEY`` (and optionally ``TAVILY_API_KEY``) to be set in the
    environment (or ``.env`` file).

    Exa free tier: 1,000 requests/month — more than sufficient for 6 queries/week.
    Tavily fallback provides redundancy if the Exa quota is exhausted.

    The ``url`` parameter from ``sources.yaml`` is ignored; search queries
    are defined internally in ``DRE_SEARCH_QUERIES``.
    """

    def __init__(self) -> None:
        self._exa: Exa | None = None
        self._tavily: TavilyClient | None = None
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )

    @property
    def exa(self) -> Exa:
        if self._exa is None:
            self._exa = Exa(api_key=settings.exa_api_key)
        return self._exa

    @property
    def tavily(self) -> TavilyClient:
        if self._tavily is None:
            self._tavily = TavilyClient(api_key=settings.tavily_api_key)
        return self._tavily

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        has_exa = bool(settings.exa_api_key)
        has_tavily = bool(settings.tavily_api_key)

        if not has_exa and not has_tavily:
            logger.warning(
                "DRE spider: neither EXA_API_KEY nor TAVILY_API_KEY set — skipping DRE search"
            )
            return []

        articles: list[ScrapedArticle] = []
        seen_urls: set[str] = set()

        try:
            for query in DRE_SEARCH_QUERIES:
                results: list[tuple[str, str, str]] = []

                # Primary: Exa
                if has_exa:
                    try:
                        results = await self._search_exa(query)
                    except Exception as exc:
                        logger.debug("Exa search failed for %s: %s", query[:40], exc)

                # Fallback: Tavily (if Exa returned nothing)
                if not results and has_tavily:
                    try:
                        results = await self._search_tavily(query)
                    except Exception as exc:
                        logger.debug("Tavily search failed for %s: %s", query[:40], exc)

                if not results:
                    logger.debug("No results for query: %s", query[:40])
                    continue

                for link, title, snippet in results:
                    pdf_url = _extract_pdf_url(link)
                    if pdf_url is None or pdf_url in seen_urls:
                        continue
                    seen_urls.add(pdf_url)

                    # Download and extract PDF
                    pdf_content = await self._download_pdf(pdf_url)
                    content_text: str | None = None
                    if pdf_content:
                        content_text = _extract_text_from_pdf(pdf_content)

                    articles.append(ScrapedArticle(
                        external_id=pdf_url,
                        url=pdf_url,
                        title=title or _describe_pdf_url(pdf_url),
                        content_text=content_text,
                        summary=snippet[:500] if snippet else None,
                        author=None,
                        published_at=None,
                        language="pt",
                        source_id=source_id,
                    ))
                    logger.info("DRE: found %s — %s", pdf_url, title[:80] if title else "")
        finally:
            await self.http_client.aclose()

        return articles

    async def _search_exa(self, query: str) -> list[tuple[str, str, str]]:
        """Search via Exa API using neural (semantic) search with domain restriction.

        Returns list of ``(url, title, content)`` tuples.

        Neural search is used because Exa's keyword search struggles to match
        short Portuguese queries against PDF metadata.  ``files.dre.pt`` is
        included in the query text to help Exa's indexer disambiguate the domain.
        """
        import asyncio
        exa_query = f"files.dre.pt {query}"
        response = await asyncio.to_thread(
            self.exa.search,
            query=exa_query,
            include_domains=["files.dre.pt"],
            num_results=10,
            type="neural",
        )

        results: list[tuple[str, str, str]] = []
        for item in response.results:
            results.append((
                getattr(item, "url", ""),
                getattr(item, "title", ""),
                getattr(item, "text", ""),
            ))

        logger.debug("Exa returned %d results for query: %s", len(results), query[:40])
        return results

    async def _search_tavily(self, query: str) -> list[tuple[str, str, str]]:
        """Search via Tavily API (fallback).

        Prepends ``site:files.dre.pt`` to the query since Tavily
        supports the ``site:`` operator natively.

        Returns list of ``(url, title, content)`` tuples.
        """
        import asyncio
        tavily_query = f"site:files.dre.pt {query}"
        response = await asyncio.to_thread(
            self.tavily.search,
            query=tavily_query,
            search_depth="advanced",
        )

        results: list[tuple[str, str, str]] = []
        for item in response.get("results", []):
            results.append((
                item.get("url", ""),
                item.get("title", ""),
                item.get("content", ""),
            ))

        logger.debug("Tavily returned %d results for query: %s", len(results), query[:40])
        return results

    async def _download_pdf(self, pdf_url: str) -> bytes | None:
        """Download a PDF from ``files.dre.pt``.

        Returns ``None`` on failure (HTTP error, timeout, non-PDF content).
        """
        try:
            response = await self.http_client.get(pdf_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.lower():
                logger.debug("Non-PDF content at %s: %s", pdf_url, content_type)
                return None
            return response.content
        except Exception as exc:
            logger.debug("PDF download failed for %s: %s", pdf_url, exc)
            return None


_SERIE_MAP: dict[str, str] = {
    "1": "I",
    "2": "II",
    "3": "III",
}

_MONTH_NAMES: dict[str, str] = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março",
    "04": "Abril", "05": "Maio", "06": "Junho",
    "07": "Julho", "08": "Agosto", "09": "Setembro",
    "10": "Outubro", "11": "Novembro", "12": "Dezembro",
}


def _describe_pdf_url(pdf_url: str) -> str:
    """Derive a human-readable title from a ``files.dre.pt`` URL.

    Examples::

        files.dre.pt/2s/2026/05/12345.pdf → DRE Série II — Maio 2026 — Documento 12345
        files.dre.pt/1s/2026/03/00100.pdf → DRE Série I — Março 2026 — Documento 00100
    """
    path = pdf_url.replace("https://", "").replace("http://", "")
    parts = path.split("/")
    if len(parts) >= 5:
        series_raw = parts[1]  # e.g. "2s"
        year = parts[2]
        month = parts[3]
        doc_id = parts[4].replace(".pdf", "")
        serie_num = series_raw[0] if series_raw else ""
        serie_roman = _SERIE_MAP.get(serie_num, serie_num)
        month_name = _MONTH_NAMES.get(month, month)
        return f"DRE Série {serie_roman} — {month_name} {year} — Documento {doc_id}"
    return "DRE — Documento oficial"
