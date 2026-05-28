"""
DRE (Diário da República Eletrónico) spider — appointment discovery via Google
Custom Search API, PDF download from files.dre.pt, and text extraction with
pdfplumber.

Approach
--------
The DRE website is built on OutSystems and renders 100% client-side with no
public REST API.  Individual publication PDFs are directly accessible at::

    files.dre.pt/{series}s/{year}/{month}/{id}.pdf

Google Custom Search API (free tier: 100 queries/day) is used to discover
relevant PDF URLs by searching for media-related appointments (Lusa, RTP, ERC,
etc.).  Each discovered PDF is downloaded and its text extracted.

Relevant organs & typical search queries
-----------------------------------------
- Lusa: ``site:files.dre.pt Lusa nomeação``
- RTP:  ``site:files.dre.pt RTP nomeação``
- ERC:  ``site:files.dre.pt ERC``
- General: ``site:files.dre.pt "comunicação social" nomeação``

Volume estimate: ~20-40 relevant appointments/year.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import httpx
import pdfplumber
from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.extractors import parse_date
from src.config.settings import settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}

# ── Search queries ────────────────────────────────────────────────────────────
# Each query targets PDFs published on files.dre.pt (the public PDF repository
# that requires no authentication).  Keywords focus on media-related
# appointments published in Série II (administrative acts).

DRE_SEARCH_QUERIES: list[str] = [
    'site:files.dre.pt Lusa nomeação OR designação',
    'site:files.dre.pt RTP nomeação OR designação "conselho de administração"',
    'site:files.dre.pt ERC nomeação OR designação',
    'site:files.dre.pt "comunicação social" nomeação OR designação',
    'site:files.dre.pt ANACOM nomeação OR designação',
    'site:files.dre.pt "serviço público" rádio OR televisão nomeação',
]


def _extract_pdf_url(link: str) -> str | None:
    """Extract a clean ``files.dre.pt`` PDF URL from a Google result link.

    Google Custom Search returns the real URL directly (unlike Google News RSS
    which wraps everything in redirects), so mostly this is a pass-through.
    We just normalise the scheme and return ``None`` if it's not a DRE PDF.
    """
    if not link:
        return None
    if "files.dre.pt" not in link.lower():
        return None
    # Ensure https
    if link.startswith("http://"):
        link = "https://" + link[7:]
    return link


def _extract_publication_date(pagemap: dict | None) -> datetime | None:
    """Try to extract a publication date from Google result metadata.

    Falls back to ``None`` — the DRE publication date can often only be
    determined after downloading the PDF and parsing its header.
    """
    # Google's ``metatags`` sometimes include ``publication_date``
    if pagemap and isinstance(pagemap, dict):
        mt = pagemap.get("metatags", [{}])
        if mt and isinstance(mt, list):
            for tag in mt:
                for key in ("publication_date", "date", "dc.date"):
                    val = tag.get(key)
                    if val:
                        parsed = parse_date(val)
                        if parsed:
                            return parsed
    # No usable date found
    return None


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
    """Discover DRE appointment PDFs via Google Custom Search API.

    Requires ``GOOGLE_API_KEY`` and ``GOOGLE_CUSTOM_SEARCH_CX`` to be set in
    the environment (or ``.env`` file).  If either is missing the spider
    returns an empty list and logs a warning.

    The ``url`` parameter from ``sources.yaml`` is ignored; search queries
    are defined internally in ``DRE_SEARCH_QUERIES``.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        if not settings.google_api_key or not settings.google_custom_search_cx:
            logger.warning(
                "DRE spider: GOOGLE_API_KEY or GOOGLE_CUSTOM_SEARCH_CX not set — "
                "skipping DRE search"
            )
            return []

        articles: list[ScrapedArticle] = []
        seen_urls: set[str] = set()

        try:
            for query in DRE_SEARCH_QUERIES:
                try:
                    results = await self._search(query)
                    for link, title, snippet, pagemap in results:
                        pdf_url = _extract_pdf_url(link)
                        if pdf_url is None or pdf_url in seen_urls:
                            continue
                        seen_urls.add(pdf_url)

                        # Download and extract PDF
                        pdf_content = await self._download_pdf(pdf_url)
                        content_text: str | None = None
                        if pdf_content:
                            content_text = _extract_text_from_pdf(pdf_content)

                        pub_date = _extract_publication_date(pagemap)

                        articles.append(ScrapedArticle(
                            external_id=pdf_url,
                            url=pdf_url,
                            title=title or _describe_pdf_url(pdf_url),
                            content_text=content_text,
                            summary=snippet[:500] if snippet else None,
                            author=None,
                            published_at=pub_date,
                            language="pt",
                            source_id=source_id,
                        ))
                        logger.info("DRE: found %s — %s", pdf_url, title[:80] if title else "")
                except Exception as exc:
                    logger.warning("DRE search query failed (%s): %s", query[:60], exc)
                    continue
        finally:
            await self.http_client.aclose()

        return articles

    async def _search(self, query: str) -> list[tuple[str, str, str, dict | None]]:
        """Call the Google Custom Search API and return result tuples.

        Each tuple is ``(link, title, snippet, pagemap)``.

        Reference: https://developers.google.com/custom-search/v1
        """
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": settings.google_api_key,
            "cx": settings.google_custom_search_cx,
            "q": query,
            "lr": "lang_pt",  # Portuguese results
            "num": 10,  # Max per page (free tier)
        }

        response = await self.http_client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results: list[tuple[str, str, str, dict | None]] = []
        for item in data.get("items", []):
            results.append((
                item.get("link", ""),
                item.get("title", ""),
                item.get("snippet", ""),
                item.get("pagemap"),
            ))
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

