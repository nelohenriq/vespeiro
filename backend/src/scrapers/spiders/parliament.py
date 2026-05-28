"""
Parliamentary Debate Collector — DAR (Diário da Assembleia da República) I Série.

Downloads plenary debate transcripts from the Portuguese Assembly of the Republic
via the confirmed-working export endpoint at debates.parlamento.pt.

Approach
--------
1. **Discovery** — Probe the export endpoint with HEAD requests across known
   (legislature, session, number) ranges to find available documents.
2. **Download** — For each available document, GET the PDF and extract text
   with pdfplumber.
3. **Media-relevance filtering** — Documents that mention media-related keywords
   (ERC, RTP, Lusa, comunicação social, regulação, etc.) are kept; others are
   skipped to keep volume manageable.

Export URL pattern (verified working)::

    http://debates.parlamento.pt/pagina/export
        ?exportType=pdf
        &exportControl=documentoCompleto
        &periodo=r3
        &publicacao=dar
        &serie=01        ← DAR I Série (plenary); 02=committees (currently broken)
        &legis={leg}     ← Legislature number (14, 15, 16, …)
        &sessao={sess}   ← Session (01–04)
        &numero={num:03d} ← Document number (001–300)

Reference code: ``bgmartins/scripts-parlamento`` on GitHub (dardownloader.py,
darpdfurls.py) confirms the same URL pattern.

Current coverage (probed)::

    XVI Legislatura (2024–26): sessão 01, números 001–100
    XV  Legislatura (2022–24): sessão 01 001–150, sessão 02 001–040
    XIV Legislatura (2019–22): sessão 01 001–070, sessão 02 001–090, sessão 03 001–030

Volume estimate: ~480 documents total, ~20–50 media-relevant per year.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import httpx
from src.scrapers.base import BaseSpider, ScrapedArticle

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}

# ── Discovery ranges ──────────────────────────────────────────────────────────
# (legislature, session, max_number)  —  probed and confirmed on 2026-05-27

_DISCOVERY_RANGES: list[tuple[str, str, int]] = [
    ("16", "01", 100),   # XVI Legislatura (2024–2026)
    ("15", "01", 150),   # XV  Legislatura (2022–2024) sessão 1
    ("15", "02",  40),   # XV  Legislatura (2022–2024) sessão 2
    ("14", "01",  70),   # XIV Legislatura (2019–2022) sessão 1
    ("14", "02",  90),   # XIV Legislatura (2019–2022) sessão 2
    ("14", "03",  30),   # XIV Legislatura (2019–2022) sessão 3
]

_LEGIS_TO_YEAR: dict[str, int] = {
    "16": 2024,
    "15": 2022,
    "14": 2019,
}

# ── Media-relevance keywords (case-insensitive) ───────────────────────────────
# A document is considered media-relevant if it contains at least one of these
# terms in its extracted text.

_MEDIA_KEYWORDS: list[str] = [
    # Regulators & regulatory bodies
    r"\bERC\b",
    r"Entidade Reguladora",
    r"ANACOM",
    r"regulação da comunicação",
    r"Conass",
    r"Conselho de Comunicação Social",
    # Media organisations
    r"\bRTP\b",
    r"Rádio e Televisão de Portugal",
    r"\bLusa\b",
    r"Agência de Notícias de Portugal",
    # Media sector topics
    r"comunicação social",
    r"serviço público de rádio",
    r"serviço público de televisão",
    r"concessão de televisão",
    r"concessão de rádio",
    r"liberdade de imprensa",
    r"liberdade de expressão",
    r"jornalistas?",
    # Advertising & propaganda
    r"publicidade institucional",
    r"publicidade do Estado",
    r"propaganda",
    # General media policy
    r"regulação dos media",
    r"regulação da comunicação social",
    r"meios de comunicação",
    # Parliamentary committee on media
    r"Comissão de Cultura, Comunicação",
    r"comunicação, juventude",
]

_MEDIA_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _MEDIA_KEYWORDS]


def _is_media_relevant(text: str) -> bool:
    """Return ``True`` if ``text`` contains at least one media-related keyword."""
    for pattern in _MEDIA_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ── Exported helpers (testable) ──────────────────────────────────────────────


def extract_text_from_pdf(content: bytes) -> str | None:
    """Extract text from a PDF byte stream using pdfplumber.

    Returns ``None`` if extraction fails.
    """
    import pdfplumber

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


def build_export_url(serie: str, legis: str, sessao: str, numero: int) -> str:
    """Build the export endpoint URL for a given DAR document.

    Example::
        >>> build_export_url("01", "16", "01", 1)
        'http://debates.parlamento.pt/pagina/export?exportType=pdf&exportControl=documentoCompleto&periodo=r3&publicacao=dar&serie=01&legis=16&sessao=01&numero=001'
    """
    return (
        f"http://debates.parlamento.pt/pagina/export"
        f"?exportType=pdf"
        f"&exportControl=documentoCompleto"
        f"&periodo=r3"
        f"&publicacao=dar"
        f"&serie={serie}"
        f"&legis={legis}"
        f"&sessao={sessao}"
        f"&numero={numero:03d}"
    )


def guess_published_date(legis: str, session: str, number: int) -> datetime | None:
    """Derive an approximate date from legislature metadata.

    The exact publication date requires parsing the PDF header, but this
    gives a reasonable estimate based on the session period.  We assign
    the first weekday of the month following the heuristic:
    - Session 01 → Q1 of the legislature start year
    - Session 02 → Q3
    - Session 03 → Q1 of the next year
    - Session 04 → Q3 of the next year

    For document numbers, later numbers = later in the session (roughly).
    We use a very rough mapping since DAR numbers reset each legislative
    session and are published irregularly.
    """
    base_year = _LEGIS_TO_YEAR.get(legis)
    if base_year is None:
        return None

    # Map session to approximate year/month
    session_map: dict[str, tuple[int, int]] = {
        "01": (base_year, 3),       # Spring
        "02": (base_year, 10),      # Autumn
        "03": (base_year + 1, 3),   # Spring of next year
        "04": (base_year + 1, 10),  # Autumn of next year
    }

    year_month = session_map.get(session)
    if year_month is None:
        return None

    year, month = year_month
    # Use 15th of the month as a middle estimate
    try:
        return datetime(year, month, 15, tzinfo=timezone.utc)
    except ValueError:
        return None


# ── Spider ────────────────────────────────────────────────────────────────────


class ParliamentSpider(BaseSpider):
    """Download DAR I Série debate transcripts and filter for media relevance.

    The spider is designed for periodic (e.g. weekly) runs.  It probes the
    export endpoint across known legislature/session/number ranges to discover
    available documents, downloads PDFs for those found, extracts text with
    pdfplumber, and retains only documents mentioning media-related keywords.

    The ``url`` parameter passed to :meth:`fetch` is ignored; discovery ranges
    are built from ``_DISCOVERY_RANGES``.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )
        # Cache of already-known URLs (safe for single fetch() call)
        self._seen_urls: set[str] = set()

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        self._seen_urls.clear()

        try:
            # Phase 1: Discover available documents
            available: list[tuple[str, str, str, int]] = []
            for legis, sessao, max_num in _DISCOVERY_RANGES:
                batch = await self._discover_range("01", legis, sessao, max_num)
                available.extend(batch)

            if not available:
                logger.info("Parliament spider: no documents found")
                return []

            logger.info("Parliament spider: %d documents available, downloading…", len(available))

            # Phase 2: Download, extract, filter
            for serie, legis, sessao, numero in available:
                try:
                    article = await self._download_and_process(
                        serie, legis, sessao, numero, source_id
                    )
                    if article is not None:
                        articles.append(article)
                except Exception as exc:
                    logger.debug("Skipping %s/%s/%s/%03d: %s", serie, legis, sessao, numero, exc)
                    continue

        finally:
            await self.http_client.aclose()

        return articles

    async def _discover_range(
        self, serie: str, legis: str, sessao: str, max_num: int
    ) -> list[tuple[str, str, str, int]]:
        """Probe the export endpoint with HEAD requests to find available documents.

        Returns a list of ``(serie, legis, sessao, numero)`` tuples.
        """
        found: list[tuple[str, str, str, int]] = []
        for num in range(1, max_num + 1):
            url = build_export_url(serie, legis, sessao, num)
            try:
                resp = await self.http_client.head(url)
                if resp.status_code == 200:
                    found.append((serie, legis, sessao, num))
            except Exception:
                continue
        return found

    async def _download_and_process(
        self, serie: str, legis: str, sessao: str, numero: int, source_id: str
    ) -> ScrapedArticle | None:
        """Download a DAR PDF, extract text, check relevance.

        Returns a ``ScrapedArticle`` if the document is media-relevant,
        otherwise ``None``.
        """
        url = build_export_url(serie, legis, sessao, numero)

        if url in self._seen_urls:
            return None
        self._seen_urls.add(url)

        # Download
        resp = await self.http_client.get(url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type.lower():
            logger.debug("Non-PDF response at %s: %s", url, content_type)
            return None

        # Extract
        content_text = extract_text_from_pdf(resp.content)
        if not content_text:
            return None

        # Filter: only keep media-relevant documents
        # (We also build the article for context even if not strictly relevant,
        # but skip it to keep volume manageable.)
        if not _is_media_relevant(content_text):
            return None

        # Build title from metadata
        title = _format_title(serie, legis, sessao, numero)
        pub_date = guess_published_date(legis, sessao, numero)

        # Extract a snippet of the first ~500 chars for the summary
        snippet = content_text[:500].strip()
        # Clean up — take the first meaningful paragraph
        snippet = snippet.replace("\n", " ").strip()
        if len(snippet) > 500:
            snippet = snippet[:497] + "..."

        return ScrapedArticle(
            external_id=url,
            url=url,
            title=title,
            content_text=content_text,
            summary=snippet,
            author="Assembleia da República",
            published_at=pub_date,
            language="pt",
            source_id=source_id,
        )


_LEGIS_ROMAN: dict[str, str] = {
    "16": "XVI",
    "15": "XV",
    "14": "XIV",
}

_MONTH_NAMES: dict[str, str] = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março",
    "04": "Abril", "05": "Maio", "06": "Junho",
    "07": "Julho", "08": "Agosto", "09": "Setembro",
    "10": "Outubro", "11": "Novembro", "12": "Dezembro",
}


def _format_title(serie: str, legis: str, sessao: str, numero: int) -> str:
    """Build a human-readable title for a DAR document.

    Example:
        ``DAR I Série — XVI Legislatura — Sessão 1 — N.º 001``
    """
    legis_rom = _LEGIS_ROMAN.get(legis, f"Legislatura {legis}")
    return (
        f"DAR I Série — {legis_rom} Legislatura — "
        f"Sessão {int(sessao)} — N.º {numero:03d}"
    )
