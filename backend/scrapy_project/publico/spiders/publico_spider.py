"""
Scrapy spider for Público (publico.pt).

Strategy
--------
1. Start on the homepage and extract article links from ``<h2 class="article__title">``.
2. Follow each article URL and extract structured data from JSON-LD
   (``<script type="application/ld+json">``) — the most stable source for
   headline, date, and author.
3. Fall back to HTML selectors if JSON-LD is absent or malformed.

Rate limiting is configured in ``publico.settings`` (3 s delay, auto-throttle).
"""

from __future__ import annotations

import json
import logging

import scrapy
from scrapy.http import Response

from publico.items import PublicoArticleItem

logger = logging.getLogger(__name__)


class PublicoMediaSpider(scrapy.Spider):
    """Scrape Público article listings and full-text pages."""

    name = "publico"
    start_urls = ["https://www.publico.pt/"]

    def __init__(self, max_articles: int = 30, *args, **kwargs):
        """Limit the number of articles to scrape per run."""
        super().__init__(*args, **kwargs)
        self.max_articles = max_articles
        self._articles_queued = 0

    # ── Homepage: collect article links ──────────────────────────────────────

    def parse(self, response: Response) -> scrapy.Request:
        """Extract article links from the homepage and queue them."""
        for a_tag in response.css("h2.article__title a"):
            if self._articles_queued >= self.max_articles:
                break
            href = a_tag.css("::attr(href)").get()
            if not href:
                continue
            # Article URLs always contain a date segment: /2026/MM/DD/...
            if "/202" not in href:
                continue
            url = response.urljoin(href)
            yield scrapy.Request(url, callback=self.parse_article)
            self._articles_queued += 1

        self.logger.info(
            "PublicoSpider: %d article links queued", self._articles_queued
        )

    # ── Article page: extract content ────────────────────────────────────────

    def parse_article(self, response: Response) -> PublicoArticleItem:
        """Extract article data — prefer JSON-LD, fall back to HTML selectors."""
        item = self._try_jsonld(response)
        if item is not None:
            return item
        return self._parse_html(response)

    # ── Extraction helpers ───────────────────────────────────────────────────

    def _try_jsonld(self, response: Response) -> PublicoArticleItem | None:
        """Attempt to extract article data from JSON-LD structured metadata.

        This is the preferred extraction path because JSON-LD is stable across
        site redesigns.  Returns ``None`` if no valid NewsArticle JSON-LD is
        found.
        """
        scripts = response.css(
            'script[type="application/ld+json"]::text'
        ).getall()

        for script in scripts:
            try:
                data = json.loads(script)
            except json.JSONDecodeError:
                continue

            # Handle both top-level and @graph structures
            candidates: list[dict] = []
            if isinstance(data, dict):
                candidates.append(data)
                if "@graph" in data and isinstance(data["@graph"], list):
                    candidates.extend(data["@graph"])
            elif isinstance(data, list):
                candidates = data

            for candidate in candidates:
                headline = (
                    candidate.get("headline")
                    or candidate.get("name")
                    or candidate.get("title")
                )
                if not headline:
                    continue
                # Found a valid article metadata block
                content_text = self._extract_content_text(response)
                return PublicoArticleItem(
                    url=response.url,
                    title=headline.strip(),
                    content_text=content_text,
                    summary=candidate.get("description"),
                    author=self._extract_author(candidate),
                    published_at=(
                        candidate.get("datePublished")
                        or candidate.get("dateModified")
                    ),
                )
        return None

    def _parse_html(self, response: Response) -> PublicoArticleItem:
        """Fallback: extract article data from HTML selectors."""
        title = response.css("h1::text").get("").strip()
        content_text = self._extract_content_text(response)

        return PublicoArticleItem(
            url=response.url,
            title=title,
            content_text=content_text,
            summary=None,
            author=None,
            published_at=response.css("time::attr(datetime)").get(),
        )

    # ── Shared helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_content_text(response: Response) -> str | None:
        """Extract clean article body text from the ``.content`` div.

        Concatenates all paragraph texts with double-newline separators.
        Returns ``None`` if no paragraphs are found.
        """
        paras = response.css("div.content p::text").getall()
        # Also try getting text from child elements
        if not paras:
            paras = response.css("div.content *::text").getall()

        if not paras:
            return None

        cleaned = [p.strip() for p in paras if p.strip()]
        if not cleaned:
            return None

        return "\n\n".join(cleaned)

    @staticmethod
    def _extract_author(data: dict) -> str | None:
        """Extract author name from JSON-LD, handling various formats."""
        author = data.get("author")
        if author is None:
            return None
        if isinstance(author, str) and author.strip():
            return author.strip()
        if isinstance(author, dict):
            name = author.get("name")
            if name and isinstance(name, str):
                return name.strip()
        if isinstance(author, list):
            for a in author:
                if isinstance(a, dict):
                    name = a.get("name")
                    if name and isinstance(name, str):
                        return name.strip()
                elif isinstance(a, str) and a.strip():
                    return a.strip()
        return None
