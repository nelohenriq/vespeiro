from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import httpx
import trafilatura

if TYPE_CHECKING:
    from src.scrapers.base import ScrapedArticle

logger = logging.getLogger(__name__)

# Limit concurrent full-text fetches to avoid overwhelming target servers
_FETCH_SEMAPHORE = asyncio.Semaphore(5)


def compute_hash(text: str) -> str:
    """SHA-256 hash for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def fetch_article_text(
    url: str,
    client: httpx.AsyncClient,
    *,
    max_chars: int = 5000,
) -> str | None:
    """Fetch and extract clean article text from a URL using trafilatura.

    Follows the article link, downloads the HTML, and extracts the main
    content body (stripping navigation, ads, sidebars).  Returns ``None``
    if the URL is empty, the fetch fails, or no extractable content is found.

    Parameters
    ----------
    url:
        Article URL to fetch.
    client:
        Shared ``httpx.AsyncClient`` (reused across articles for connection
        pooling).
    max_chars:
        Maximum characters to keep from the extracted text (avoids storing
        enormous PDF transcripts, etc.).  Default 5000.
    """
    if not url:
        return None

    # Google News RSS redirect URLs always lead to a consent wall that blocks
    # automated fetches ("Before you continue to Google").  Skip the HTTP call
    # entirely — these sources rely on their RSS summary text instead.
    # Checked here as a last line of defense; the caller should also filter
    # these URLs in enrich_articles_with_full_text() to avoid task overhead.
    if "news.google.com" in url and "/rss/" in url:
        return None

    async with _FETCH_SEMAPHORE:
        try:
            response = await client.get(url, timeout=15.0)
            if response.status_code != 200:
                return None

            # trafilatura.extract handles boilerplate removal
            text = trafilatura.extract(
                response.text,
                url=url,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            if not text or len(text.strip()) < 100:
                return None

            # Reject consent wall / paywall / gate pages (check extracted text)
            consent_markers = (
                "Before you continue to Google",
                "before you continue to google",
            )
            if any(m.lower() in text.lower() for m in consent_markers):
                return None

            return text.strip()[:max_chars]

        except Exception:
            logger.debug("Failed to extract full text from %s", url, exc_info=True)
            return None


async def enrich_articles_with_full_text(
    articles: list[ScrapedArticle],
    client: httpx.AsyncClient,
) -> None:
    """Fetch full article text for every article missing ``content_text``.

    Processes all articles concurrently (limited by an internal semaphore to
    5 parallel fetches).  Each article's ``content_text`` field is set in-place.
    Failures are silent — articles keep their ``None`` content_text.
    """
    if not articles:
        return

    async def enrich_one(article: ScrapedArticle) -> None:
        if article.content_text:
            return
        url = article.url
        if not url:
            return
        # Google News RSS redirects always hit consent walls — skip early
        if "news.google.com" in url and "/rss/" in url:
            return
        article.content_text = await fetch_article_text(url, client)

    await asyncio.gather(*[enrich_one(a) for a in articles], return_exceptions=True)


def extract_article_url(entry: dict) -> tuple[str, str | None]:
    """Extract the best article URL from a feedparser RSS entry.

    For real RSS feeds, ``entry.link`` is the direct article URL.

    For Google News RSS entries, ``entry.link`` is a Google redirect
    (``news.google.com/rss/articles/...``) that resolves to the original
    article.  The ``<source>`` element only carries the domain homepage
    (e.g. ``www.lusa.pt``), not the specific article URL, so it is **not**
    used as the canonical URL.

    Note:
        Google's consent wall blocks automated fetches through the redirect,
        so full-text extraction via trafilatura will fail for Google News
        RSS sources.  These sources fall back to their RSS ``summary`` text.

    Returns
    -------
    (canonical_url, original_url_or_none)
        *canonical_url* is ``entry.link`` (direct URL or Google redirect).
        *original_url_or_none* is ``entry.source.url`` for Google News RSS
        entries (the source domain, for reference only), or ``None``.
    """
    link = (entry.get("link") or "").strip()

    # For Google News RSS, capture the source domain for reference
    source = entry.get("source")
    source_url: str | None = None
    if isinstance(source, dict):
        source_url = source.get("url") or source.get("href") or None

    # Always use entry.link as the canonical URL:
    # - Real RSS feeds: direct article URL
    # - Google News RSS: Google redirect (best we have — source.url is just the domain)
    return link, source_url


def parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string into datetime, or None if unparseable."""
    if not date_str:
        return None
    try:
        from dateutil import parser
        return parser.parse(date_str)
    except ImportError:
        # fallback: try common RSS formats
        from datetime import timezone
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
    except Exception:
        return None
