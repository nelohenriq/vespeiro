"""Tests for GovernmentSpider.

Mocks the httpx.AsyncClient via httpx.MockTransport so no external
requests are made. Two source types: ``portugal_gov`` and ``presidencia``.
"""

from __future__ import annotations

import pytest
import httpx
import pytest_asyncio

from src.scrapers.base import ScrapedArticle
from src.scrapers.spiders.government import GovernmentSpider


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <link>https://news.google.com</link>
    <description>Google News RSS</description>
    <item>
      <title>Governo anuncia novo pacote de investimentos na saúde</title>
      <link>https://news.google.com/articles/CBMi123</link>
      <guid>tag:google.com,2026:news:CBMi123</guid>
      <pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate>
      <source url="https://www.portugal.gov.pt">Governo de Portugal</source>
    </item>
    <item>
      <title>Conselho de Ministros aprova Orçamento do Estado para 2027</title>
      <link>https://news.google.com/articles/CBMi456</link>
      <guid>tag:google.com,2026:news:CBMi456</guid>
      <pubDate>Tue, 26 May 2026 14:30:00 GMT</pubDate>
      <source url="https://www.portugal.gov.pt">Governo de Portugal</source>
    </item>
    <item>
      <title>Portugal defende resposta europeia para a crise energética</title>
      <link>https://news.google.com/articles/CBMi789</link>
      <guid>tag:google.com,2026:news:CBMi789</guid>
      <pubDate>Mon, 25 May 2026 09:15:00 GMT</pubDate>
      <source url="https://www.portugal.gov.pt">Governo de Portugal</source>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_PRESIDENCIA = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <link>https://news.google.com</link>
    <description>Google News RSS</description>
    <item>
      <title>Presidente da República promulga diploma do Governo</title>
      <link>https://news.google.com/articles/CBMi999</link>
      <guid>tag:google.com,2026:news:CBMi999</guid>
      <pubDate>Wed, 27 May 2026 09:54:51 GMT</pubDate>
      <source url="https://www.presidencia.pt">Presidência da República</source>
    </item>
    <item>
      <title>Presidente da República recebe Primeiro-Ministro em audiência</title>
      <link>https://news.google.com/articles/CBMi888</link>
      <guid>tag:google.com,2026:news:CBMi888</guid>
      <pubDate>Tue, 26 May 2026 11:51:25 GMT</pubDate>
      <source url="https://www.presidencia.pt">Presidência da República</source>
    </item>
  </channel>
</rss>
"""

EMPTY_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Empty</title>
    <link>https://news.google.com</link>
    <description>No articles</description>
  </channel>
</rss>"""


def _gov_handler(request: httpx.Request) -> httpx.Response:
    """Return different RSS content depending on the requested URL."""
    url = str(request.url)
    if "presidencia.pt" in url:
        return httpx.Response(200, text=SAMPLE_RSS_PRESIDENCIA)
    if "portugal.gov.pt" in url:
        return httpx.Response(200, text=SAMPLE_RSS)
    return httpx.Response(404, text="Not Found")


@pytest_asyncio.fixture
async def mock_client() -> httpx.AsyncClient:
    """Provide an httpx.AsyncClient with a mock transport for government sources.

    Note: the spider's ``fetch()`` closes the client in its ``finally`` block,
    so we do NOT use ``async with`` here — we let the spider own the lifecycle.
    """
    return httpx.AsyncClient(transport=httpx.MockTransport(_gov_handler))


@pytest_asyncio.fixture
async def gov_spider(mock_client: httpx.AsyncClient) -> GovernmentSpider:
    """Create a GovernmentSpider whose HTTP client is replaced with the mock."""
    spider = GovernmentSpider()
    await spider.http_client.aclose()
    spider.http_client = mock_client
    return spider


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_portugal_gov_returns_articles(gov_spider: GovernmentSpider) -> None:
    """Should return articles from portugal.gov.pt RSS feed."""
    articles = await gov_spider.fetch("portugal_gov")

    assert len(articles) == 3

    a0 = articles[0]
    assert a0.source_id == "portugal_gov"
    assert a0.title == "Governo anuncia novo pacote de investimentos na saúde"
    assert a0.url == "https://news.google.com/articles/CBMi123"
    assert a0.author == "Governo de Portugal"
    assert a0.language == "pt"
    assert a0.published_at is not None
    assert a0.published_at.year == 2026
    assert a0.published_at.month == 5
    assert a0.published_at.day == 26


@pytest.mark.asyncio
async def test_fetch_presidencia_returns_articles(gov_spider: GovernmentSpider) -> None:
    """Should return articles from presidencia.pt RSS feed."""
    articles = await gov_spider.fetch("presidencia")

    assert len(articles) == 2

    a0 = articles[0]
    assert a0.source_id == "presidencia"
    assert a0.title == "Presidente da República promulga diploma do Governo"
    assert a0.author == "Presidência da República Portuguesa"
    assert a0.language == "pt"


@pytest.mark.asyncio
async def test_fetch_unknown_source_returns_empty(gov_spider: GovernmentSpider) -> None:
    """Should return empty list for an unknown source_id (no RSS URL found)."""
    articles = await gov_spider.fetch("unknown_source")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_empty_rss() -> None:
    """Should handle empty RSS feed gracefully."""
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=EMPTY_RSS)

    spider = GovernmentSpider()
    await spider.http_client.aclose()
    spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    articles = await spider.fetch("portugal_gov")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_http_error() -> None:
    """Should handle HTTP errors gracefully (return empty list, not raise)."""
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Server Error")

    spider = GovernmentSpider()
    await spider.http_client.aclose()
    spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    articles = await spider.fetch("portugal_gov")
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_respects_max_30() -> None:
    """Should cap at 30 articles (same as other spiders)."""
    items = ""
    for i in range(50):
        items += f"""
    <item>
      <title>Comunicado {i}</title>
      <link>https://news.google.com/articles/CBMi{i}</link>
      <guid>tag:google.com,2026:news:CBMi{i}</guid>
      <pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate>
    </item>
"""
    rss_50 = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <link>https://news.google.com</link>
    <description>Test</description>
    {items}
  </channel>
</rss>"""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=rss_50)

    spider = GovernmentSpider()
    await spider.http_client.aclose()
    spider.http_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    articles = await spider.fetch("portugal_gov")
    assert len(articles) == 30


@pytest.mark.asyncio
async def test_each_article_has_required_fields(gov_spider: GovernmentSpider) -> None:
    """Every returned article should have source_id, title, and external_id."""
    articles = await gov_spider.fetch("portugal_gov")

    for a in articles:
        assert isinstance(a, ScrapedArticle)
        assert a.source_id == "portugal_gov"
        assert a.title, "Article must have a title"
        assert a.external_id, "Article must have an external_id"
        assert a.collected_at.tzinfo is not None  # UTC by default
