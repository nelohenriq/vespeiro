"""
Custom spider for TSF (tsf.pt).

TSF blocks Scrapy (HTTP 403 / connection refused due to TLS fingerprinting)
and has no public RSS feed.  The official RSS feed was discontinued.
Google News RSS was the previous fallback — this spider upgrades that by
scraping the SSR homepage directly via httpx, which gives us real TSF
article URLs, full text via trafilatura, and metadata from JSON-LD.

Strategy
--------
1. Download the SSR homepage (``https://www.tsf.pt``) via httpx with a
   browser User-Agent — accessible and contains ~250 article links.
2. Extract all links matching ``/artigo/`` with their link text (title).
3. Download each article page **concurrently** (semaphore-limited) and extract:
   - **JSON-LD** (preferred): headline, datePublished, author
   - **trafilatura**: clean article body text
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

# Matches <a href="https://www.tsf.pt/.../artigo/...">TITLE</a>
# Captures the URL and the link text (which is the article headline).
_ARTICLE_LINK_RE = re.compile(
    r'href="(https?://(?:www\.)?tsf\.pt[^\"]*/artigo/[^\"]*)"[^>]*>'
    r'((?:(?!</a>).)*)</a>',
    re.DOTALL,
)

# Strip inner HTML tags from link text
_STRIP_HTML_TAGS = re.compile(r'<[^>]+>')

_MAX_ARTICLES = 30
# Limit concurrent article page fetches
_FETCH_SEMAPHORE = asyncio.Semaphore(5)


def _extract_meta_metadata(html_text: str) -> dict:
    """Extract article metadata from HTML <meta> tags and <time> elements.

    TSF article pages don't use JSON-LD — they use standard HTML meta tags:
    - ``<meta property="article:published_time" content="...">``
    - ``<meta name="author" content="...">``

    Returns a dict with keys: author, published_at (datetime or None).
    """
    author = None
    published_at = None

    # Author from <meta name="author" content="...">
    m = re.search(r'<meta\s+name=["\']author["\']\s+content=["\']([^"\']+)["\']', html_text)
    if not m:
        m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']author["\']', html_text)
    if m:
        author = html_mod.unescape(m.group(1).strip()) or None

    # Published date from <meta name="article:published_time" content="..."> or <meta property="...">
    m = re.search(r'<meta\s+(?:name|property)=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']', html_text)
    if not m:
        m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+(?:name|property)=["\']article:published_time["\']', html_text)
    if m:
        published_at = parse_date(m.group(1).strip())
    if not published_at:
        # Fallback: <time datetime="...">
        m = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html_text)
        if m:
            published_at = parse_date(m.group(1).strip())

    return {
        "author": author,
        "published_at": published_at,
    }


async def _fetch_article(
    client: httpx.AsyncClient,
    url: str,
    link_title: str,
    source_id: str,
) -> ScrapedArticle | None:
    """Fetch a single TSF article page and extract metadata + content."""
    async with _FETCH_SEMAPHORE:
        try:
            response = await client.get(url, timeout=15.0)
            if response.status_code != 200:
                return None
            # Read response body inside the semaphore to avoid race conditions
            # on the shared httpx client connection pool.
            html_text = response.text
        except httpx.RequestError:
            return None

    # Extract metadata from HTML meta tags (TSF doesn't use JSON-LD)
    meta = _extract_meta_metadata(html_text)

    # Extract body text via trafilatura
    content_text = trafilatura.extract(
        html_text,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if content_text:
        content_text = content_text.strip()[:5000]
        if len(content_text) < 100:
            content_text = None

    title = link_title
    author = meta.get("author")
    published_at = meta.get("published_at")

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


class TSFSpider(BaseSpider):
    """Scrape TSF (tsf.pt) via httpx homepage scraping.

    Fetches the SSR homepage, extracts ``/artigo/`` links, fetches each
    article page concurrently, and extracts content via trafilatura plus
    metadata from JSON-LD.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA},
        )

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        """Fetch articles from the TSF homepage."""
        try:
            # 1. Download the homepage
            logger.info("TSF: fetching homepage https://www.tsf.pt")
            response = await self.http_client.get("https://www.tsf.pt")
            response.raise_for_status()
            html_text = response.text

            # 2. Extract /artigo/ links with titles from the link text
            raw_matches = _ARTICLE_LINK_RE.findall(html_text)
            seen_urls: set[str] = set()
            seen_titles: set[str] = set()
            matched: list[tuple[str, str]] = []
            for article_url, inner_html in raw_matches:
                if article_url in seen_urls:
                    continue
                seen_urls.add(article_url)
                # Strip inner HTML (e.g. <span>, <em>) to get clean title text
                title = _STRIP_HTML_TAGS.sub("", inner_html).strip()
                title = html_mod.unescape(title)
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                matched.append((article_url, title))

            logger.info(
                "TSF: %d /artigo/ links found (%d unique titles)",
                len(raw_matches),
                len(matched),
            )

            if not matched:
                logger.warning("TSF: no article links found on homepage")
                return []

            # 3. Fetch article pages concurrently
            tasks = [
                _fetch_article(self.http_client, url, title, source_id)
                for url, title in matched[:_MAX_ARTICLES]
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            articles: list[ScrapedArticle] = []
            for result in results:
                if isinstance(result, ScrapedArticle):
                    articles.append(result)
                elif isinstance(result, Exception):
                    logger.debug("TSF article fetch failed: %s", result)

            articles_with_content = sum(
                1 for a in articles if a.content_text
            )
            logger.info(
                "TSF: %d articles (%d with content, %d with author, %d with date)",
                len(articles),
                articles_with_content,
                sum(1 for a in articles if a.author),
                sum(1 for a in articles if a.published_at),
            )

        except httpx.HTTPStatusError as exc:
            logger.error("TSF homepage fetch failed: HTTP %d", exc.response.status_code)
            return []
        except httpx.RequestError as exc:
            logger.error("TSF homepage fetch failed: %s", exc)
            return []
        finally:
            await self.http_client.aclose()

        return articles
