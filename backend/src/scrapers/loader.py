"""Spider registry: maps source IDs to spider classes."""

from src.config import SourceConfig
from src.scrapers.base import BaseSpider
from src.scrapers.spiders.lusa import LusaSpider
from src.scrapers.spiders.portugal_media import PortugalMediaSpider


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
}


def get_spider(source_config: SourceConfig) -> BaseSpider:
    """Get the appropriate spider instance for a source config."""
    spider_class = SPIDER_REGISTRY.get(source_config.id)
    if spider_class is None:
        raise ValueError(f"No spider registered for source: {source_config.id} (type={source_config.type})")
    return spider_class()
