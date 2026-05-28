"""
Parliamentary Debate Collector — DAR (Diário da Assembleia da República) I Série.

Downloads plenary debate transcripts from the Portuguese Assembly of the Republic
via the confirmed-working export endpoint at debates.parlamento.pt.

Approach
--------
Single-phase GET: iterates across known (legislature, session, number) ranges,
does concurrent GETs, checks content-type, extracts PDF text with pdfplumber,
and filters for media-relevant documents.  No separate HEAD discovery step
because the Parliament server rejects GET after many HEAD requests on the same
connection.

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

import asyncio
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


def extract_text_from_pdf(content: bytes, max_pages: int | None = None) -> str | None:
    """Extract text from a PDF byte stream using pdfplumber.

    If ``max_pages`` is set, only the first N pages are extracted.
    Returns ``None`` if extraction fails.
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = pdf.pages[:max_pages] if max_pages else pdf.pages
            text_parts: list[str] = []
            for page in pages:
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


_CONCURRENT_REQUESTS = 20
_RELEVANCE_SCAN_PAGES = 5  # Only scan first N pages for media relevance (perf)


# ── Spider ────────────────────────────────────────────────────────────────────


class ParliamentSpider(BaseSpider):
    """Download DAR I Série debate transcripts and filter for media relevance.

    Uses a single-phase GET approach: concurrently GETs all candidate URLs,
    checks content-type for PDFs, extracts text, and filters for media-relevant
    documents.  No separate HEAD discovery step is used because the Parliament
    export server rejects GET requests after many HEAD requests on the same
    connection.

    The ``url`` parameter passed to :meth:`fetch` is ignored; discovery ranges
    are built from ``_DISCOVERY_RANGES``.
    """

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(_CONCURRENT_REQUESTS)

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        # Build all candidate URLs
        candidates: list[tuple[str, str, str, int]] = []
        for legis, sessao, max_num in _DISCOVERY_RANGES:
            for num in range(1, max_num + 1):
                candidates.append(("01", legis, sessao, num))

        logger.info(
            "Parliament spider: probing %d candidate URLs (%d concurrent)…",
            len(candidates), _CONCURRENT_REQUESTS,
        )

        # Single-phase: GET every candidate URL concurrently.
        # Non-existent docs return 404 quickly; real PDFs get downloaded.
        http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_HEADERS,
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        try:
            tasks = [
                self._fetch_one(http_client, serie, legis, sessao, numero, source_id)
                for serie, legis, sessao, numero in candidates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            articles: list[ScrapedArticle] = []
            not_found = 0
            errors = 0
            skipped = 0
            for result in results:
                if isinstance(result, Exception):
                    errors += 1
                elif result is None:
                    not_found += 1
                elif result == "skip":
                    skipped += 1
                else:
                    articles.append(result)

            logger.info(
                "Parliament spider: %d media-relevant, %d non-relevant, "
                "%d not found, %d errors",
                len(articles), skipped, not_found, errors,
            )
        finally:
            await http_client.aclose()

        return articles

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        serie: str,
        legis: str,
        sessao: str,
        numero: int,
        source_id: str,
    ) -> ScrapedArticle | str | None:
        """GET a single candidate URL; return article, "skip", or None."""
        url = build_export_url(serie, legis, sessao, numero)

        async with self._semaphore:
            try:
                resp = await client.get(url)
            except Exception as exc:
                logger.debug("GET failed for %s: %s", url, exc)
                return None

        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type.lower():
            logger.debug("Non-PDF response at %s: %s", url, content_type)
            return None

        # Extract text from first N pages for relevance check (fast path)
        scan_text = extract_text_from_pdf(resp.content, max_pages=_RELEVANCE_SCAN_PAGES)
        if not scan_text:
            return None

        # Filter: only keep media-relevant documents
        if not _is_media_relevant(scan_text):
            return "skip"

        # Media-relevant! Extract full text for storage
        full_text = extract_text_from_pdf(resp.content)
        if not full_text:
            return None

        # Build title and date
        title = _format_title(serie, legis, sessao, numero)
        pub_date = guess_published_date(legis, sessao, numero)

        # Extract a snippet for the summary
        snippet = full_text[:500].strip().replace("\n", " ").strip()
        if len(snippet) > 500:
            snippet = snippet[:497] + "..."

        return ScrapedArticle(
            external_id=url,
            url=url,
            title=title,
            content_text=full_text,
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
