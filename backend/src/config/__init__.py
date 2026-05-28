from enum import Enum
from pydantic import BaseModel
import yaml
from pathlib import Path


class SourceType(str, Enum):
    RSS = "rss"
    GOOGLE_NEWS_RSS = "google_news_rss"
    GOOGLE_CUSTOM_SEARCH = "google_custom_search"
    SCRAPE = "scrape"
    API = "api"
    SITEMAP = "sitemap"


class SourceCategory(str, Enum):
    AGENCY = "agency"
    PUBLIC_BROADCASTER = "public_broadcaster"
    MAINSTREAM = "mainstream"
    INTERNATIONAL = "international"
    GOVERNMENT = "government"
    PARLIAMENT = "parliament"
    OFFICIAL_GAZETTE = "official_gazette"
    REGULATOR = "regulator"


class ExtractionStrategy(str, Enum):
    TRAFILATURA = "trafilatura"
    NEWSPAPER4K = "newspaper4k"


class SourceConfig(BaseModel):
    id: str
    name: str
    type: SourceType
    url: str
    language: str
    category: SourceCategory
    schedule_interval_minutes: int = 30
    extraction_strategy: ExtractionStrategy = ExtractionStrategy.TRAFILATURA


class SourcesConfig(BaseModel):
    sources: list[SourceConfig]


def load_sources() -> SourcesConfig:
    """Load all source definitions from sources.yaml."""
    config_path = Path(__file__).parent / "sources.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return SourcesConfig.model_validate(data)
