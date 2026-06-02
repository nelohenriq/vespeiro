"""Spider registry: maps source IDs to spider classes."""

from src.config import SourceConfig
from src.scrapers.base import BaseSpider
from src.scrapers.spiders.lusa import LusaSpider
from src.scrapers.spiders.portugal_media import PortugalMediaSpider
from src.scrapers.spiders.publico import PublicoSpider
from src.scrapers.spiders.portugal_news_scrapy import PortugalNewsScrapySpider
from src.scrapers.spiders.expresso_scrapy import ExpressoSpider as ExpressoScrapySpider
from src.scrapers.spiders.international import InternationalSpider
from src.scrapers.spiders.government import GovernmentSpider
from src.scrapers.spiders.dre import DRESpider
from src.scrapers.spiders.parliament import ParliamentSpider
from src.scrapers.spiders.erc_advertising import ERCAdvertisingSpider
from src.scrapers.spiders.tsf import TSFSpider
from src.scrapers.spiders.dn import DNSpider
from src.scrapers.spiders.jn import JNSpider


SPIDER_REGISTRY: dict[str, type[BaseSpider]] = {
    "lusa": LusaSpider,
    "rtp_noticias": PortugalMediaSpider,
    "publico": PublicoSpider,
    "observador": PortugalNewsScrapySpider,
    "expresso": ExpressoScrapySpider,  # Uses sitemap + Google News RSS (DataDome blocks direct access)
    "cm_jornal": PortugalNewsScrapySpider,
    "jn": JNSpider,  # News sitemap + httpx article fetching (Scrapy blocked, homepage JS-heavy)
    "dn": DNSpider,  # Sitemap-based httpx spider (homepage is JS-heavy, article pages are SSR)
    "sic_noticias": PortugalMediaSpider,  # Blocks automated access (HTTP 403)
    "eco": PortugalNewsScrapySpider,
    "cnn_portugal": PortugalNewsScrapySpider,  # SSR homepage — Scrapy works
    "tsf": TSFSpider,  # httpx-based homepage scraping (Scrapy blocked)
    "renascenca": PortugalMediaSpider,  # Already has RSS
    "sapo_24": PortugalNewsScrapySpider,
    "nam": PortugalNewsScrapySpider,
    "tvi_noticias": PortugalMediaSpider,  # Google News RSS (no public RSS)
    "jornal_negocios": PortugalMediaSpider,  # Google News RSS (no public RSS)
    # International sources
    "reuters": InternationalSpider,
    "bbc": InternationalSpider,
    "guardian": InternationalSpider,
    "ap": InternationalSpider,
    "elpais": InternationalSpider,
    "afp": InternationalSpider,
    "lemonde": InternationalSpider,
    "dw": InternationalSpider,
    "france24": InternationalSpider,
    # Government sources
    "portugal_gov": GovernmentSpider,
    "presidencia": GovernmentSpider,
    # Diário da República (Exa + Tavily — appointment discovery)
    "dre_appointments": DRESpider,
    "dre_general_appointments": DRESpider,
    # Parliamentary debates
    "parlamento_debates": ParliamentSpider,
    # ERC Institutional Advertising Reports
    "erc_advertising": ERCAdvertisingSpider,
}


def get_spider(source_config: SourceConfig) -> BaseSpider:
    """Get the appropriate spider instance for a source config."""
    spider_class = SPIDER_REGISTRY.get(source_config.id)
    if spider_class is None:
        raise ValueError(f"No spider registered for source: {source_config.id} (type={source_config.type})")
    return spider_class()
