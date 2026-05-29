"""Spider registry: maps source IDs to spider classes."""

from src.config import SourceConfig
from src.scrapers.base import BaseSpider
from src.scrapers.spiders.lusa import LusaSpider
from src.scrapers.spiders.portugal_media import PortugalMediaSpider
from src.scrapers.spiders.international import InternationalSpider
from src.scrapers.spiders.government import GovernmentSpider
from src.scrapers.spiders.dre import DRESpider
from src.scrapers.spiders.parliament import ParliamentSpider
from src.scrapers.spiders.erc_advertising import ERCAdvertisingSpider


SPIDER_REGISTRY: dict[str, type[BaseSpider]] = {
    "lusa": LusaSpider,
    "rtp_noticias": PortugalMediaSpider,
    "publico": PortugalMediaSpider,
    "observador": PortugalMediaSpider,
    "expresso": PortugalMediaSpider,
    "cm_jornal": PortugalMediaSpider,
    "jn": PortugalMediaSpider,
    "dn": PortugalMediaSpider,
    "sic_noticias": PortugalMediaSpider,
    "eco": PortugalMediaSpider,
    "cnn_portugal": PortugalMediaSpider,
    "tsf": PortugalMediaSpider,
    "renascenca": PortugalMediaSpider,
    "sapo_24": PortugalMediaSpider,
    "nam": PortugalMediaSpider,
    # International sources
    "reuters": InternationalSpider,
    "bbc": InternationalSpider,
    "guardian": InternationalSpider,
    "ap": InternationalSpider,
    "elpais": InternationalSpider,
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
