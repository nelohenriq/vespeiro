"""
Custom spider for JN — Jornal de Notícias (jn.pt).

JN blocks Scrapy (HTTP 403 / TLS fingerprinting) and has no public RSS
feed.  The homepage is JS-heavy but contains SSR article links, and
article pages are fully accessible via httpx.

Strategy
--------
1. Fetch the Google News sitemap (``/feed/news/sitemap.xml``) which contains
   the ``news:news`` namespace with article URLs, titles, and publication
   dates — no need to parse HTML for these.
2. Fetch each article page **concurrently** (semaphore-limited) and extract:
   - **Author**: ``<meta name="author" content="...">``
   - **Body text**: trafilatura (``favor_recall`` mode — JN uses complex
     CSS class names like DN)
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

_NEWS_SITEMAP_URL = "https://www.jn.pt/feed/news/sitemap.xml"

_MAX_ARTICLES = 30


def _extract_sitemap_entries(xml_text: str) -> list[dict]:
    """Extract article entries from a ``news:news`` sitemap XML.

    Returns a list of dicts with keys: url, title, published_at.
    """
    entries: list[dict] = []
    # Find each <url> block and extract loc, news:title, news:publication_date
    url_blocks = re.findall(
        r'<url>(.*?)</url>',
        xml_text,
        re.DOTALL,
    )
    for block in url_blocks:
        url_match = re.search(r'<loc>(.*?)</loc>', block)
        title_match = re.search(r'<news:title>(.*?)</news:title>', block)
        date_match = re.search(
            r'<news:publication_date>(.*?)</news:publication_date>',
            block,
        )

        if not url_match:
            continue

        url = url_match.group(1).strip()
        title = html_mod.unescape(title_match.group(1).strip()) if title_match else ""

        published_at = None
        if date_match:
            published_at = parse_date(date_match.group(1).strip())

        entries.append({
            "url": url,
            "title": title,
            "published_at": published_at,
        })

    return entries


async def _fetch_article(
    client: httpx.AsyncClient,
    url: str,
    title: str,
    sitemap_date: "datetime | None",
    source_id: str,
    semaphore: asyncio.Semaphore,
) -> ScrapedArticle | None:
    """Fetch a single JN article page and extract author + content.

    Title and date are already known from the news sitemap — we only
    need author and body text from the article page.
    Falls back to ``<meta property="article:published_time">`` or
    ``<time dateTime>`` on the article page if the sitemap didn't
    provide a date.

    Args:
        semaphore: Concurrency limiter owned by the spider instance.
    """
    async with semaphore:
        try:
            response = await client.get(url, timeout=15.0)
            if response.status_code != 200:
                return None
            html_text = response.text
        except httpx.RequestError:
            return None

    # Extract author from <meta name="author" content="...">
    author = None
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

    # Date fallback: if sitemap didn't provide date, try article page HTML
    published_at = sitemap_date
    if published_at is None:
        m = re.search(
            r'<meta\s+(?:name|property)=[\'"]article:published_time[\'"]\s+content=[\'"]([^\'"]+)[\'"]',
            html_text,
        )
        if not m:
            m = re.search(
                r'<meta\s+content=[\'"]([^\'"]+)[\'"]\s+(?:name|property)=[\'"]article:published_time[\'"]',
                html_text,
            )
        if m:
            published_at = parse_date(m.group(1).strip())
        if published_at is None:
            # Fallback: <time dateTime="...">
            m = re.search(r'<time[^>]+dateTime=[\'"]([^\'"]+)[\'"]', html_text)
            if m:
                published_at = parse_date(m.group(1).strip())

    # Extract body text via trafilatura (favor_recall for complex CSS)
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
        title=title,
        content_text=content_text,
        summary=None,
        author=author,
        published_at=published_at,
        language="pt",
        source_id=source_id,
    )


class JNSpider(BaseSpider):
    """Scrape JN (jn.pt) via news sitemap + article page fetching.

    1. Fetches ``/feed/news/sitemap.xml`` for article URLs, titles, and dates.
    2. Fetches each article page concurrently for author + full content.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
        )
        self._fetch_semaphore = asyncio.Semaphore(5)

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        """Fetch articles via JN's Google News sitemap."""
        try:
            # 1. Fetch news sitemap
            logger.info("JN: fetching news sitemap %s", _NEWS_SITEMAP_URL)
            response = await self.http_client.get(_NEWS_SITEMAP_URL)
            response.raise_for_status()
            xml_text = response.text

            # 2. Extract entries from sitemap
            entries = _extract_sitemap_entries(xml_text)
            logger.info(
                "JN: %d entries in news sitemap (%d with title, %d with date)",
                len(entries),
                sum(1 for e in entries if e["title"]),
                sum(1 for e in entries if e["published_at"]),
            )

            if not entries:
                logger.warning("JN: no entries found in news sitemap")
                return []

            # 3. Fetch article pages concurrently for author + content
            urls_to_fetch = entries[:_MAX_ARTICLES]
            tasks = [
                _fetch_article(
                    self.http_client,
                    e["url"],
                    e["title"],
                    e["published_at"],
                    source_id,
                    self._fetch_semaphore,
                )
                for e in urls_to_fetch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            articles: list[ScrapedArticle] = []
            for result in results:
                if isinstance(result, ScrapedArticle):
                    articles.append(result)
                elif isinstance(result, Exception):
                    logger.debug("JN article fetch failed: %s", result)

            articles_with_content = sum(1 for a in articles if a.content_text)
            logger.info(
                "JN: %d articles (%d with content, %d with author, %d with date)",
                len(articles),
                articles_with_content,
                sum(1 for a in articles if a.author),
                sum(1 for a in articles if a.published_at),
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "JN sitemap fetch failed: HTTP %d", exc.response.status_code
            )
            return []
        except httpx.RequestError as exc:
            logger.error("JN sitemap fetch failed: %s", exc)
            return []
        finally:
            await self.http_client.aclose()

        return articles
