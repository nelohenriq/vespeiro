"""
Government communication spider — press releases from portugal.gov.pt and presidencia.pt.

Both government sites use JS-rendered listing pages without public RSS feeds.
We use Google News RSS with site: queries to capture their press releases.

Consistent with the Google News RSS pattern used by most Portuguese media outlets
in the project (publico, observador, expresso, etc.).
"""
import feedparser
import httpx
from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.extractors import parse_date


_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}

# Government sources and their Google News RSS search queries
GOVERNMENT_QUERIES: dict[str, str] = {
    "portugal_gov": (
        "https://news.google.com/rss/search?"
        "q=site:portugal.gov.pt&hl=pt-PT&ceid=PT:pt"
    ),
    "presidencia": (
        "https://news.google.com/rss/search?"
        "q=site:presidencia.pt&hl=pt-PT&ceid=PT:pt"
    ),
}

# Human-readable author tags per source
SOURCE_AUTHORS: dict[str, str] = {
    "portugal_gov": "Governo de Portugal",
    "presidencia": "Presidência da República Portuguesa",
}


class GovernmentSpider(BaseSpider):
    """Fetch Portuguese government press releases via Google News RSS.

    Supports two sources:
    - ``portugal_gov`` — portugal.gov.pt (Conselho de Ministros, ministérios)
    - ``presidencia`` — presidencia.pt (Presidente da República)

    The ``url`` parameter passed to :meth:`fetch` is ignored; the Google News
    RSS URL is looked up by ``source_id`` from ``GOVERNMENT_QUERIES``.
    """

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        rss_url = GOVERNMENT_QUERIES.get(source_id)
        if rss_url is None:
            return []

        author = SOURCE_AUTHORS.get(source_id)
        articles: list[ScrapedArticle] = []
        try:
            response = await self.http_client.get(rss_url)
            response.raise_for_status()
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:30]:
                external_id = entry.get("id") or entry.get("link", "")
                articles.append(ScrapedArticle(
                    external_id=external_id,
                    url=entry.get("link", ""),
                    title=entry.get("title", ""),
                    summary=str(entry.get("summary", ""))[:500] or None,
                    author=author,
                    published_at=parse_date(entry.get("published", "")),
                    language="pt",
                    source_id=source_id,
                ))
        except Exception:
            # HTTP errors, timeouts, malformed RSS — return what we have (likely [])
            pass
        finally:
            await self.http_client.aclose()

        return articles
