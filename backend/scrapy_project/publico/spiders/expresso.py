"""
Scrapy spider for Expresso (expresso.pt).

Status
------
Expresso uses **DataDome** bot protection, which blocks ALL automated HTTP
requests (including Scrapy, httpx, curl, and headless Playwright).  Direct
article pages and the homepage return HTTP 403.

What works
----------
- **Sitemap** (``sitemap/news.xml``) — accessible, provides article URLs,
  ``<news:title>``, and ``<news:publication_date>``.
- **Google News RSS** — provides article titles, dates, and real
  ``expresso.pt`` URLs extracted from the ``<description>`` HTML (falls back
  to Google News redirect URLs when extraction fails).

Strategy
--------
1. Parse ``sitemap/news.xml`` for article URLs + titles + publication dates.
2. After the sitemap is processed, fetch Google News RSS for supplementary
   article discovery (without filling the quota before the sitemap).
3. Return metadata-rich items even when full text is unavailable.

The article text will be empty for Expresso items, but titles, URLs, and
publication dates are always available from the sitemap.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import scrapy
from scrapy.http import Response

from publico.items import PublicoArticleItem


logger = logging.getLogger(__name__)

_SITEMAP_URL = "https://expresso.pt/sitemap/news.xml"
_GNEWS_RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=site:expresso.pt&hl=pt-PT&ceid=PT:pt"
)

# Full namespace URIs for XPath queries (avoids namespace-dict ambiguity)
_NS_SITEMAP = "http://www.sitemaps.org/schemas/sitemap/0.9"
_NS_NEWS = "http://www.google.com/schemas/sitemap-news/0.9"


class ExpressoSpider(scrapy.Spider):
    """Scrape Expresso via sitemap + Google News RSS.

    Parameters (set via ``-a`` on the command line):
        max_articles  — Max articles to collect (default 60)
    """

    name = "expresso"

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "USER_AGENT": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def _remaining(self) -> int:
        """How many more articles we can collect before hitting max_articles."""
        return max(0, self.max_articles - len(self._seen_urls))

    start_urls = [
        _SITEMAP_URL,  # Sitemap first — RSS is triggered after sitemap is done
    ]

    def __init__(
        self,
        max_articles: str = "60",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.max_articles = max(0, int(max_articles))
        self._seen_urls: set[str] = set()

    def parse(self, response: Response):
        """Parse the sitemap, then optionally fetch Google News RSS."""
        yield from self._parse_sitemap(response)

        # After sitemap is fully processed, fetch Google News RSS for
        # supplementary articles (up to max_articles total).
        if self._remaining() > 0:
            yield scrapy.Request(
                _GNEWS_RSS_URL,
                callback=self._parse_google_news_rss,
                dont_filter=True,
            )

    # ── Parse sitemap ────────────────────────────────────────────────────────

    def _parse_sitemap(self, response: Response) -> list:
        """Parse the Google News sitemap — returns a list of item dicts."""
        items: list = []

        if response.status != 200:
            logger.error("Expresso sitemap returned HTTP %d", response.status)
            return items

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            logger.error("Expresso sitemap parse error: %s", exc)
            return items

        url_elems = root.findall(f"{{{_NS_SITEMAP}}}url")
        logger.info("Expresso sitemap: %d url elements", len(url_elems))

        for url_elem in url_elems:
            if self._remaining() == 0:
                break

            loc = url_elem.findtext(f"{{{_NS_SITEMAP}}}loc", default="").strip()
            if not loc or loc in self._seen_urls:
                continue

            # Extract news metadata
            news = url_elem.find(f"{{{_NS_NEWS}}}news")
            title = ""
            pub_date = ""
            if news is not None:
                title = (news.findtext(f"{{{_NS_NEWS}}}title", default="") or "").strip()
                pub_date = (news.findtext(f"{{{_NS_NEWS}}}publication_date", default="") or "").strip()

            if not title:
                continue

            self._seen_urls.add(loc)
            items.append(PublicoArticleItem(
                url=loc,
                title=title,
                content_text=None,
                summary=None,
                author=None,
                published_at=pub_date,
            ))

        logger.info(
            "Expresso sitemap done: %d / %d articles",
            len(self._seen_urls),
            self.max_articles,
        )
        return items

    # ── Parse Google News RSS ────────────────────────────────────────────────

    def _parse_google_news_rss(self, response: Response):
        """Parse Google News RSS for additional Expresso article metadata.

        Google News RSS provides Google redirect URLs (``link``), but the
        ``<description>`` HTML often contains the real ``expresso.pt`` URL.
        We extract real URLs from descriptions when possible for better
        deduplication against sitemap items and better frontend links.

        This method runs AFTER the sitemap has been fully processed, so it
        only contributes supplementary items up to the remaining quota.
        """
        if response.status != 200:
            logger.error("Expresso GNews RSS returned HTTP %d", response.status)
            return

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            logger.error("Expresso GNews RSS parse error: %s", exc)
            return

        url_pattern = re.compile(r'href="(https?://expresso\.pt[^"]+)"')

        for item in root.iter("item"):
            if self._remaining() == 0:
                break

            gnews_link = item.findtext("link", default="").strip()
            title = (item.findtext("title", default="") or "").strip()
            pub_date = (item.findtext("pubDate", default="") or "").strip()

            if not title or not gnews_link:
                continue

            # Try to extract real expresso.pt URL from description HTML
            description = (item.findtext("description", default="") or "").strip()
            m = url_pattern.search(description)
            real_url = m.group(1) if m else None

            # Use real URL if found, fall back to Google News redirect
            link = real_url or gnews_link

            if link in self._seen_urls:
                continue

            self._seen_urls.add(link)

            yield PublicoArticleItem(
                url=link,
                title=title,
                content_text=None,
                summary=None,
                author=None,
                published_at=pub_date,
            )

        logger.info(
            "Expresso GNews RSS done: %d / %d articles",
            len(self._seen_urls),
            self.max_articles,
        )
