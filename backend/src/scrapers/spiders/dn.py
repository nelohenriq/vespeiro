"""
Custom spider for DN — Diário de Notícias (dn.pt).

DN's homepage is JS-heavy (no article links in raw HTML), but it has
comprehensive daily sitemaps and SSR article pages accessible via httpx.

Strategy
--------
1. Fetch the sitemap index (``/sitemap.xml``) to find daily sitemap URLs.
2. Fetch the latest daily sitemap (``sitemap-daily-YYYY-MM-DD.xml``) to get
   article URLs and lastmod timestamps.
3. Fetch each article page **concurrently** (semaphore-limited) and extract:
   - **Title**: ``<meta property="og:title">`` or ``<title>`` or ``<h1>``
   - **Author**: ``<meta name="author" content="...">``
   - **Published date**: ``<time dateTime="...">``
   - **Body text**: trafilatura
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re

import httpx
import trafilatura

from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.extractors import parse_date

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_SITEMAP_INDEX_URL = "https://www.dn.pt/sitemap.xml"

_MAX_ARTICLES = 30


def _extract_metadata(html_text: str) -> dict:
    """Extract article metadata from HTML.

    Extracts title, author, and published_at from HTML meta tags,
    ``<title>``, ``<h1>``, and ``<time>`` elements.

    Returns a dict with keys: title, author, published_at (datetime or None).
    """
    title = ""
    author = None
    published_at = None

    # Title: prefer og:title, fall back to <title>, then <h1>
    m = re.search(
        r'<meta\s+property=[\'"]og:title[\'"]\s+content=[\'"]([^\'"]+)[\'"]',
        html_text,
    )
    if m:
        title = html_mod.unescape(m.group(1).strip())
    if not title:
        m = re.search(r'<title>([^<]+)</title>', html_text)
        if m:
            title = html_mod.unescape(m.group(1).strip())
    if not title:
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html_text)
        if m:
            title = html_mod.unescape(m.group(1).strip())

    # Author from <meta name="author" content="...">
    m = re.search(
        r'<meta\s+name=[\'"]author[\'"]\s+content=[\'"]([^\'"]+)[\'"]',
        html_text,
    )
    if not m:
        m = re.search(
            r'<meta\s+content=[\'"]([^\'"]+)[\'"]\s+name=[\'"]author[\'"]',
            html_text,
        )
    if m:
        author = html_mod.unescape(m.group(1).strip()) or None

    # Published date from <time dateTime="..."> (DN uses space-separated format)
    # Case-insensitive on attribute name for future-proof HTML5 compatibility
    m = re.search(r'<time[^>]+[dD]ate[Tt]ime=[\'"]([^\'"]+)[\'"]', html_text)
    if m:
        date_str = m.group(1).strip()
        published_at = parse_date(date_str)
    if not published_at:
        # Fallback: <meta property="article:published_time" content="...">
        m = re.search(
            r'<meta\s+property=[\'"]article:published_time[\'"]\s+content=[\'"]([^\'"]+)[\'"]',
            html_text,
        )
        if not m:
            m = re.search(
                r'<meta\s+content=[\'"]([^\'"]+)[\'"]\s+property=[\'"]article:published_time[\'"]',
                html_text,
            )
        if m:
            published_at = parse_date(m.group(1).strip())

    return {
        "title": title,
        "author": author,
        "published_at": published_at,
    }


async def _fetch_article(
    client: httpx.AsyncClient,
    url: str,
    source_id: str,
    semaphore: asyncio.Semaphore,
) -> ScrapedArticle | None:
    """Fetch a single DN article page and extract metadata + content.

    Args:
        semaphore: Concurrency limiter (passed in so each spider instance
            owns its own semaphore, avoiding cross-instance contention).
    """
    async with semaphore:
        try:
            response = await client.get(url, timeout=15.0)
            if response.status_code != 200:
                return None
            html_text = response.text
        except httpx.RequestError:
            return None

    # Extract metadata from HTML
    meta = _extract_metadata(html_text)

    # DN uses complex dynamically-generated CSS class names that trafilatura's
    # precision mode misidentifies as boilerplate. Using favor_recall (default)
    # correctly identifies the article body.
    content_text = trafilatura.extract(
        html_text,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=False,
    )
    if content_text:
        content_text = content_text.strip()[:5000]
        if len(content_text) < 100:
            content_text = None

    return ScrapedArticle(
        url=url,
        title=meta.get("title") or "",
        content_text=content_text,
        summary=None,
        author=meta.get("author"),
        published_at=meta.get("published_at"),
        language="pt",
        source_id=source_id,
    )


class DNSpider(BaseSpider):
    """Scrape DN (dn.pt) via sitemap-based article discovery.

    1. Fetches sitemap index to find the latest daily sitemap.
    2. Extracts article URLs from the daily sitemap.
    3. Fetches each article page concurrently and extracts content.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
        )
        self._fetch_semaphore = asyncio.Semaphore(5)

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        """Fetch articles via DN's daily sitemap."""
        try:
            # 1. Fetch sitemap index to find daily sitemaps
            logger.info("DN: fetching sitemap index %s", _SITEMAP_INDEX_URL)
            response = await self.http_client.get(_SITEMAP_INDEX_URL)
            response.raise_for_status()
            sitemap_html = response.text

            # Find all daily sitemap URLs
            daily_urls = re.findall(
                r'<loc>(https?://[^<]*daily[^<]*)</loc>',
                sitemap_html,
            )
            if not daily_urls:
                logger.warning("DN: no daily sitemaps found")
                return []

            # Use the latest daily sitemap
            latest_sitemap = sorted(daily_urls)[-1]
            logger.info("DN: fetching latest sitemap %s", latest_sitemap)

            # 2. Fetch article URLs from daily sitemap
            sd_response = await self.http_client.get(latest_sitemap)
            sd_response.raise_for_status()
            sitemap_text = sd_response.text

            article_urls = re.findall(
                r'<loc>(https?://[^<]+)</loc>',
                sitemap_text,
            )
            logger.info("DN: %d article URLs in latest sitemap", len(article_urls))

            if not article_urls:
                return []

            # 3. Fetch article pages concurrently
            urls_to_fetch = article_urls[:_MAX_ARTICLES]
            tasks = [
                _fetch_article(self.http_client, art_url, source_id, self._fetch_semaphore)
                for art_url in urls_to_fetch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            articles: list[ScrapedArticle] = []
            for result in results:
                if isinstance(result, ScrapedArticle):
                    articles.append(result)
                elif isinstance(result, Exception):
                    logger.debug("DN article fetch failed: %s", result)

            articles_with_content = sum(1 for a in articles if a.content_text)
            logger.info(
                "DN: %d articles (%d with content, %d with author, %d with date)",
                len(articles),
                articles_with_content,
                sum(1 for a in articles if a.author),
                sum(1 for a in articles if a.published_at),
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "DN sitemap fetch failed: HTTP %d", exc.response.status_code
            )
            return []
        except httpx.RequestError as exc:
            logger.error("DN sitemap fetch failed: %s", exc)
            return []
        finally:
            await self.http_client.aclose()

        return articles
