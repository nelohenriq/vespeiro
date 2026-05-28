"""Tests for spider modules — verify fetch() returns article lists.

These tests hit live RSS feeds.  They require network access and may be
slow if the feeds are unresponsive.  Marked with ``pytest.mark.asyncio``.
"""

import pytest
from src.scrapers.base import ScrapedArticle
from src.config import load_sources


# ── LusaSpider ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lusa_spider_fetches_articles():
    from src.scrapers.spiders.lusa import LusaSpider

    config = load_sources()
    lusa_cfg = next(s for s in config.sources if s.id == "lusa")

    spider = LusaSpider()
    articles = await spider.fetch("lusa", lusa_cfg.url)

    assert len(articles) > 0
    assert articles[0].title is not None
    assert articles[0].url.startswith("http")


# ── PortugalMediaSpider ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portugal_media_gnrss():
    """Test Google News RSS for Público."""
    from src.scrapers.spiders.portugal_media import PortugalMediaSpider

    config = load_sources()
    pub_cfg = next(s for s in config.sources if s.id == "publico")

    spider = PortugalMediaSpider()
    articles = await spider.fetch("publico", pub_cfg.url)

    assert len(articles) > 0
    assert articles[0].title
    assert articles[0].url.startswith("http")


@pytest.mark.asyncio
async def test_portugal_media_rss():
    """Test real RSS for RTP."""
    from src.scrapers.spiders.portugal_media import PortugalMediaSpider

    config = load_sources()
    rtp_cfg = next(s for s in config.sources if s.id == "rtp_noticias")

    spider = PortugalMediaSpider()
    articles = await spider.fetch("rtp_noticias", rtp_cfg.url)

    assert len(articles) > 0
    assert articles[0].title
    assert articles[0].url.startswith("http")


# ── InternationalSpider ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_international_spider_bbc():
    from src.scrapers.spiders.international import InternationalSpider

    spider = InternationalSpider()
    articles = await spider.fetch("bbc")

    assert len(articles) > 0
    assert articles[0].title
    assert articles[0].language in ("en", "pt", "es", "fr", "de", "it")


@pytest.mark.asyncio
async def test_international_spider_unknown_source():
    from src.scrapers.spiders.international import InternationalSpider

    spider = InternationalSpider()
    articles = await spider.fetch("nonexistent_source")
    assert articles == []


# ── Loader integration ──────────────────────────────────────────────────────


def test_get_spider_all_sources():
    """Every source in config has a registered spider."""
    from src.scrapers.loader import get_spider

    config = load_sources()
    for src in config.sources:
        spider = get_spider(src)
        assert spider is not None
        assert hasattr(spider, "fetch")
