"""
International source spider — RSS from major global news outlets.

Uses lingua-py for light-weight language detection on article titles,
so we can filter or tag Portuguese-relevant international coverage.

All feeds are standard RSS parsed with feedparser.
"""

import feedparser
import httpx
from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.extractors import parse_date, enrich_articles_with_full_text, extract_article_url


_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}

# International sources with known-working RSS feeds
INTERNATIONAL_FEEDS: dict[str, str] = {
    "reuters": "https://news.google.com/rss/search?q=site:reuters.com&hl=en&ceid=US:en",
    "bbc": "https://feeds.bbci.co.uk/news/rss.xml",
    "guardian": "https://www.theguardian.com/world/rss",
    "ap": "https://feeds.feedburner.com/AssociatedPressNews",
    "elpais": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
}


def _build_detector():
    """Build a lingua-py language detector (called once at module level)."""
    try:
        from lingua import Language, LanguageDetectorBuilder

        return LanguageDetectorBuilder.from_languages(
            Language.ENGLISH,
            Language.PORTUGUESE,
            Language.SPANISH,
            Language.FRENCH,
            Language.GERMAN,
            Language.ITALIAN,
        ).build()
    except Exception:
        return None


_LANG_DETECTOR = _build_detector()


def _detect_language(title: str) -> str:
    """Detect language of a title string using lingua-py.

    Falls back to 'en' if detection fails or lingua is not installed.
    """
    if _LANG_DETECTOR is not None:
        try:
            detected = _LANG_DETECTOR.detect_language_of(title[:200])
            if detected is not None:
                return detected.iso_code_639_1.name.lower()
        except Exception:
            pass
    return "en"


class InternationalSpider(BaseSpider):
    """Fetch articles from international news outlets via RSS.

    The ``url`` parameter passed to :meth:`fetch` is ignored for this spider;
    instead, the feed URL is looked up from ``INTERNATIONAL_FEEDS`` by
    ``source_id``.  This keeps ``sources.yaml`` entries simple while allowing
    the spider to manage its own feed URLs.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        rss_url = INTERNATIONAL_FEEDS.get(source_id)
        if rss_url is None:
            return []

        articles: list[ScrapedArticle] = []
        try:
            response = await self.http_client.get(rss_url)
            response.raise_for_status()
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:30]:
                title = entry.get("title", "")
                article_url, _original_url = extract_article_url(entry)
                articles.append(ScrapedArticle(
                    external_id=entry.get("id"),
                    url=article_url,
                    title=title,
                    summary=str(entry.get("summary", ""))[:500] or None,
                    author=None,
                    published_at=parse_date(entry.get("published", "")),
                    language=_detect_language(title),
                    source_id=source_id,
                ))

            # Fetch full article text for Lusa dependency analysis
            if articles:
                await enrich_articles_with_full_text(articles, self.http_client)
        finally:
            await self.http_client.aclose()

        return articles
