"""
Lusa spider — Google News RSS.

Lusa does not offer a public RSS feed (B2B paid service).
We use Google News RSS with site:lusa.pt query instead.

After fetching RSS entries, each article's URL is followed and full text is
extracted via trafilatura so the Lusa dependency analyzer has enough signal.
"""
import feedparser
import httpx
from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.extractors import parse_date, enrich_articles_with_full_text, extract_article_url


_HEADERS = {
    "User-Agent": "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
}


class LusaSpider(BaseSpider):
    """Fetch Lusa articles via Google News RSS."""

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=_HEADERS
        )

    async def fetch(self, source_id: str, url: str) -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:50]:
                article_url, _original_url = extract_article_url(entry)
                articles.append(ScrapedArticle(
                    external_id=entry.get("id"),
                    url=article_url,
                    title=entry.get("title", ""),
                    summary=str(entry.get("summary", ""))[:500] or None,
                    author="Lusa",
                    published_at=parse_date(entry.get("published", "")),
                    language="pt",
                    source_id=source_id,
                ))

            # Fetch full article text for Lusa dependency analysis
            if articles:
                await enrich_articles_with_full_text(articles, self.http_client)
        finally:
            await self.http_client.aclose()

        return articles
