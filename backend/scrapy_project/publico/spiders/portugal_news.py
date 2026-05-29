"""
Generic Scrapy spider for Portuguese news media websites.

Usage
-----
    scrapy crawl portugal_news \\
        -a site_url=https://eco.sapo.pt \\
        -a link_selector=article a \\
        -a source_name=ECO

Strategy
--------
1. Visit the configured homepage URL and extract article links using the
   provided CSS selector (``link_selector``).  If no selector is given, fall
   back to looking for ``<a>`` elements whose ``href`` contains a date-like
   segment (``/2026/``, ``/2025/``, etc.).
2. Follow each article URL and extract structured data from JSON-LD
   (``<script type="application/ld+json">``) — the most reliable source for
   headline, date, and author across modern news sites.
3. Fall back to HTML selectors (``h1`` for title, ``div.content p`` for body
   text) if JSON-LD is absent.
"""

from __future__ import annotations

import json
import logging
import re

import scrapy
from scrapy.http import Response

from publico.items import PublicoArticleItem

logger = logging.getLogger(__name__)

# ── Date-aware link filter ────────────────────────────────────────────────────

_RE_DATE_IN_PATH = re.compile(r"/20\d{2}/\d{2}/\d{2}/")  # /2026/05/28/...
_RE_DATE_SHORT = re.compile(r"/20\d{2}\d{2}\d{2}")  # /20260528/...
_RE_DATE_YEAR = re.compile(r"/20\d{2}/\d{1,2}/")  # /2026/5/...


def _is_navigation_link(href: str) -> bool:
    """Check if a URL is obviously not an article (nav, social, etc.)."""
    bad_patterns = ("#", "javascript:", "mailto:", "tel:", "/tag/", "/autor/",
                    "/categoria/", "/search", "/pesquisa", "/login", "/register",
                    "/assinatur", "/newsletter")
    return any(p in href for p in bad_patterns)


def _looks_like_article_url(href: str) -> bool:
    """Heuristic: does this URL look like a news article?

    Used only as fallback when no ``link_selector`` is provided.
    Looks for date-like segments in the path.
    """
    if _is_navigation_link(href):
        return False
    return bool(
        _RE_DATE_IN_PATH.search(href)
        or _RE_DATE_SHORT.search(href)
        or _RE_DATE_YEAR.search(href)
    )


# ── Spider ────────────────────────────────────────────────────────────────────


class PortugalNewsSpider(scrapy.Spider):
    """Generic spider configurable for any Portuguese news website.

    Parameters (set via ``-a`` on the command line):
        site_url        — Homepage URL (required)
        link_selector   — CSS selector for article links on homepage
                          (optional; falls back to date-aware heuristic)
        source_name     — Human-readable name for logging (optional)
        max_articles    — Max articles to scrape (default 30)
    """

    name = "portugal_news"

    def __init__(
        self,
        site_url: str = "",
        link_selector: str = "",
        source_name: str = "",
        max_articles: str = "30",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.site_url = site_url
        self.link_selector = link_selector
        self.source_name = source_name or site_url
        self.max_articles = int(max_articles)
        self._articles_queued = 0

        # Use start_urls (proven pattern) instead of start_requests
        if site_url:
            self.start_urls = [site_url]

    # ── Homepage: collect article links ──────────────────────────────────────

    def parse(self, response: Response):
        """Extract article links from the homepage and queue them."""
        if self.link_selector:
            # Use explicit CSS selector — less strict URL filtering
            elements = response.css(self.link_selector)
            for el in elements:
                if self._articles_queued >= self.max_articles:
                    break
                href = el.css("::attr(href)").get()
                if href and not _is_navigation_link(href):
                    url = response.urljoin(href)
                    yield scrapy.Request(url, callback=self.parse_article)
                    self._articles_queued += 1

            # If selector found nothing, try finding links inside matched elements
            if self._articles_queued == 0:
                for el in elements:
                    if self._articles_queued >= self.max_articles:
                        break
                    # Look for links inside the matched element (e.g., article > div > a)
                    for a in el.css("a[href]"):
                        if self._articles_queued >= self.max_articles:
                            break
                        href = a.css("::attr(href)").get()
                        if href and not _is_navigation_link(href):
                            url = response.urljoin(href)
                            yield scrapy.Request(url, callback=self.parse_article)
                            self._articles_queued += 1
        else:
            # Fall back to finding any <a> with a date-like href
            for a in response.css("a[href]"):
                if self._articles_queued >= self.max_articles:
                    break
                href = a.css("::attr(href)").get()
                if href and _looks_like_article_url(href):
                    url = response.urljoin(href)
                    yield scrapy.Request(url, callback=self.parse_article)
                    self._articles_queued += 1

            # If still nothing, try <h2> + <h3> links
            if self._articles_queued == 0:
                for heading_sel in ("h2 a[href]", "h3 a[href]", "h4 a[href]"):
                    for a in response.css(heading_sel):
                        if self._articles_queued >= self.max_articles:
                            break
                        href = a.css("::attr(href)").get()
                        if href and not _is_navigation_link(href):
                            url = response.urljoin(href)
                            yield scrapy.Request(
                                url, callback=self.parse_article
                            )
                            self._articles_queued += 1
                    if self._articles_queued > 0:
                        break

        self.logger.info(
            "%s: %d article links queued from %s",
            self.source_name,
            self._articles_queued,
            self.site_url,
        )

    # ── Article page: extract content ────────────────────────────────────────

    def parse_article(self, response: Response) -> PublicoArticleItem:
        """Extract article data — prefer JSON-LD, fall back to HTML selectors."""
        item = self._try_jsonld(response)
        if item is not None:
            return item
        return self._parse_html(response)

    # ── Error handler ────────────────────────────────────────────────────────

    # ── Extraction helpers ───────────────────────────────────────────────────

    def _try_jsonld(self, response: Response) -> PublicoArticleItem | None:
        """Extract article data from JSON-LD structured metadata.

        Prefers ``NewsArticle`` or ``Article`` types; skips ``WebSite``,
        ``Organization``, and other non-article types that may have a
        generic ``name`` field (e.g. "Observador").
        """
        scripts = response.css(
            'script[type="application/ld+json"]::text'
        ).getall()

        all_candidates: list[tuple[dict, bool]] = []  # (candidate, is_article_type)

        for script in scripts:
            try:
                data = json.loads(script)
            except json.JSONDecodeError:
                continue

            candidates: list[dict] = []
            if isinstance(data, dict):
                candidates.append(data)
                if "@graph" in data and isinstance(data["@graph"], list):
                    candidates.extend(data["@graph"])
            elif isinstance(data, list):
                candidates = data

            for cand in candidates:
                atype = (cand.get("@type") or "").lower() if isinstance(cand.get("@type"), str) else ""
                is_article = "newsarticle" in atype or "article" in atype
                if is_article or cand.get("headline") or cand.get("name"):
                    all_candidates.append((cand, is_article))

        # Sort: article-type candidates first, then by having headline
        def _sort_key(item):
            cand, is_article = item
            return (
                0 if is_article else 1,          # article types first
                0 if cand.get("headline") else 1,  # with headline first
            )
        all_candidates.sort(key=_sort_key)

        for candidate, _ in all_candidates:
            headline = candidate.get("headline") or ""
            if not headline.strip():
                # For article types, trust the name field
                if "newsarticle" in (candidate.get("@type") or "").lower():
                    headline = candidate.get("name") or candidate.get("title") or ""
                else:
                    continue

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
        """Fallback: extract article data from generic HTML selectors."""
        title = response.css("h1::text").get("").strip()
        content_text = self._extract_content_text(response)

        return PublicoArticleItem(
            url=response.url,
            title=title or response.css("title::text").get("") or "",
            content_text=content_text,
            summary=None,
            author=response.css('meta[name="author"]::attr(content)').get(),
            published_at=(
                response.css('meta[property="article:published_time"]::attr(content)').get()
                or response.css("time::attr(datetime)").get()
            ),
        )

    @staticmethod
    def _extract_content_text(response: Response) -> str | None:
        """Extract article body text from common container selectors."""
        # Try common content containers
        for sel in (
            "div.content",
            "article",
            "div.article-body",
            "div.entry-content",
            "div.post-content",
            "div.text",
            "main",
        ):
            paras = response.css(f"{sel} p::text").getall()
            if paras:
                break

        # Fallback: get all paragraph text on the page
        if not paras:
            paras = response.css("p::text").getall()

        if not paras:
            return None

        cleaned = [p.strip() for p in paras if p.strip()]
        if not cleaned:
            return None

        return "\n\n".join(cleaned)

    @staticmethod
    def _extract_author(data: dict) -> str | None:
        """Extract author name from JSON-LD."""
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
