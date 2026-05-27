from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScrapedArticle:
    """Standardised article output from all spiders."""
    external_id: str | None = None
    url: str = ""
    title: str = ""
    content_text: str | None = None
    summary: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    language: str | None = None
    source_id: str = ""


class BaseSpider(ABC):
    """Every spider must implement fetch()."""

    @abstractmethod
    async def fetch(self, source_id: str, url: str) -> list[ScrapedArticle]:
        ...
