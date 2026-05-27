# Project Vespeiro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation data collection and storage infrastructure for Portugal's first media narrative intelligence platform.

**Architecture:** GitHub Actions (scheduled scraping + analysis) → Supabase (PostgreSQL + pgvector) → GitHub Pages (React dashboard). No servers. No API costs. Everything runs on free tiers.

**Tech Stack:** Python 3.12, GitHub Actions, httpx + feedparser, Supabase Free Tier (PostgreSQL 16 + pgvector), sentence-transformers, pysentimiento, Jinja2 templates, React + Vite + TypeScript, GitHub Pages.

> ⚠️ **IMPORTANT:** Always read the full design doc first: `docs/superpowers/specs/2026-05-27-vespeiro-design.md`
> 💰 **Zero Cost Architecture:** All components are free. No Docker in production. No VPS. No Claude/OpenAI API calls.

---

## File Structure

```
vespeiro/
├── .github/
│   └── workflows/
│       ├── scrape.yml                    # Main scraping workflow (cron)
│       ├── analyze.yml                   # Daily analysis & report
│       ├── deploy-dashboard.yml          # Deploy React app to GitHub Pages
│       └── test.yml                      # Run tests on PR/push
├── .env.example
├── README.md
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── src/
│   │   ├── __init__.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── settings.py               # Pydantic Settings
│   │   │   └── sources.yaml              # Source definitions
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── session.py                # SQLAlchemy async engine (Supabase/SQLite)
│   │   │   └── models.py                 # All SQLAlchemy models
│   │   ├── scrapers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                   # Base spider class
│   │   │   ├── loader.py                 # Source config → spider loader
│   │   │   ├── spiders/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── lusa.py
│   │   │   │   ├── portugal_media.py
│   │   │   │   └── international.py
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   ├── extractor.py              # Content extraction (trafilatura)
│   │   │   ├── embedder.py               # Embedding generation
│   │   │   ├── matcher.py                # Story clustering
│   │   │   └── sentiment.py              # pysentimiento sentiment analysis
│   │   ├── analysis/
│   │   │   ├── __init__.py
│   │   │   ├── lusa_dependency.py
│   │   │   ├── silence_detector.py
│   │   │   └── report_generator.py       # Jinja2 template reports
│   │   └── supabase/
│   │       ├── __init__.py
│   │       └── client.py                 # Supabase client (writes from GHA)
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_scrapers.py
│       ├── test_embedder.py
│       ├── test_matcher.py
│       └── test_sentiment.py
│
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        └── components/
            └── Dashboard.tsx
```

---

## Phase 0 — Foundation

> **~48 tasks total.** Each task is 2-5 minutes. Each produces a git-committable change.

---

### Task 0.1: Project Scaffolding

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/__init__.py`
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: Create pyproject.toml with dependencies**

```toml
[project]
name = "vespeiro"
version = "0.1.0"
description = "Media Narrative Intelligence Platform — Zero-cost media monitoring"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27.0",
    "feedparser>=6.0.0",
    "trafilatura>=1.8.0",
    "newspaper4k>=0.9.0",
    "lingua-py>=2.0.0",
    "spacy>=3.7.0",
    "sentence-transformers>=3.0.0",
    "scikit-learn>=1.5.0",
    "pysentimiento>=0.7.0",
    "sqlalchemy>=2.0.0",
    "aiosqlite>=0.20.0",
    "alembic>=1.13.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
    "jinja2>=3.1.0",
    "numpy>=1.26.0",
    "supabase>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
]

[tool.ruff]
line-length = 100

[tool.mypy]
strict = false
```

- [ ] **Step 2: Create .env.example**

```
# Supabase (production database)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key

# Local dev (SQLite fallback)
DATABASE_URL=sqlite:///data/vespeiro.db

# Telegram bot (optional alerts)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

LOG_LEVEL=INFO
```

- [ ] **Step 3: Create backend/src/__init__.py (empty)**

```python
# backend/src/__init__.py
```

- [ ] **Step 4: Create .gitkeep for data directory**

```bash
mkdir -p data
touch data/.gitkeep
```

- [ ] **Step 5: Create root pyproject.toml**

```toml
[tool.ruff]
line-length = 100
```

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml .env.example data/ README.md
git commit -m "feat: project scaffolding with zero-cost dependencies"
```

---

### Task 0.2: Source Configuration System

**Files:**
- Create: `backend/src/config/__init__.py`
- Create: `backend/src/config/settings.py`
- Create: `backend/src/config/sources.yaml`
- Create: `backend/src/config/loader.py`

- [ ] **Step 1: Create Pydantic settings**

```python
# backend/src/config/settings.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""  # From .env: SUPABASE_URL
    supabase_service_key: str = ""  # From .env: SUPABASE_SERVICE_KEY
    database_url: str = "sqlite+aiosqlite:///data/vespeiro.db"  # Local dev fallback
    log_level: str = "INFO"
    embedding_model: str = "intfloat/multilingual-e5-large"
    scrape_interval_minutes: int = 15

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 2: Create sources.yaml with initial sources**

```yaml
# backend/src/config/sources.yaml
sources:
  - id: lusa
    name: "Lusa — Agência de Notícias"
    type: rss
    url: "https://www.lusa.pt/rss"
    language: pt
    category: agency
    schedule_interval_minutes: 15
    extraction_strategy: trafilatura

  - id: rtp_noticias
    name: "RTP Notícias"
    type: scrape
    url: "https://www.rtp.pt/noticias"
    language: pt
    category: public_broadcaster
    schedule_interval_minutes: 30
    extraction_strategy: newspaper4k

  - id: publico
    name: "Público"
    type: rss
    url: "https://www.publico.pt/rss"
    language: pt
    category: mainstream
    schedule_interval_minutes: 30
    extraction_strategy: trafilatura

  - id: observador
    name: "Observador"
    type: rss
    url: "https://observador.pt/feed/"
    language: pt
    category: mainstream
    schedule_interval_minutes: 30
    extraction_strategy: trafilatura

  - id: expresso
    name: "Expresso"
    type: rss
    url: "https://expresso.pt/rss"
    language: pt
    category: mainstream
    schedule_interval_minutes: 30
    extraction_strategy: trafilatura

  - id: cm_jornal
    name: "Correio da Manhã"
    type: rss
    url: "https://www.cmjornal.pt/rss"
    language: pt
    category: mainstream
    schedule_interval_minutes: 30
    extraction_strategy: trafilatura
```

- [ ] **Step 3: Create Pydantic models for source config**

```python
# backend/src/config/__init__.py
from enum import Enum
from pydantic import BaseModel
import yaml
from pathlib import Path


class SourceType(str, Enum):
    RSS = "rss"
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
    config_path = Path(__file__).parent / "sources.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return SourcesConfig.model_validate(data)
```

- [ ] **Step 4: Commit**

```bash
git add backend/src/config/
git commit -m "feat: source configuration system with YAML + Pydantic models"
```

---

### Task 0.3: Database Schema + Models

**Files:**
- Create: `backend/src/db/__init__.py`
- Create: `backend/src/db/session.py`
- Create: `backend/src/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/001_initial.py`

- [ ] **Step 1: Create SQLAlchemy session setup**

```python
# backend/src/db/session.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config.settings import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
```

- [ ] **Step 2: Create all SQLAlchemy models**

```python
# backend/src/db/models.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, Float, Boolean, ForeignKey, JSON, Enum as SAEnum, LargeBinary
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, VECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.session import Base
from src.config import SourceCategory


def utcnow():
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    language: Mapped[str | None] = mapped_column(String(5), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding = mapped_column(VECTOR(1024), nullable=True)

    source = relationship("Source", backref="articles")


class StoryCluster(Base):
    __tablename__ = "story_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    centroid_embedding = mapped_column(VECTOR(1024), nullable=True)
    title_auto: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StoryClusterMember(Base):
    __tablename__ = "story_cluster_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("story_clusters.id"), nullable=False)
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("articles.id"), nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    articles_found: Mapped[int] = mapped_column(default=0)
    articles_new: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

- [ ] **Step 3: Create Alembic initial migration**

```bash
cd backend && pip install -e .[dev] && alembic init alembic
```

Configure `alembic/env.py` to use async engine with the Article model:

```python
# backend/alembic/env.py (key parts)
from src.db.models import Base
from src.config.settings import settings

target_metadata = Base.metadata

def run_migrations_online():
    from sqlalchemy.ext.asyncio import create_async_engine
    connectable = create_async_engine(settings.database_url)
    # ... standard async migration config
```

Then run:
```bash
alembic revision --autogenerate -m "initial_schema"
alembic upgrade head
```

- [ ] **Step 4: Seed initial sources in database**

Create `backend/src/db/seed.py`:

```python
# backend/src/db/seed.py
from src.db.session import async_session
from src.db.models import Source
from src.config import load_sources
import uuid


async def seed_sources():
    config = load_sources()
    async with async_session() as session:
        for src in config.sources:
            existing = await session.get(Source, src.id)
            if not existing:
                session.add(Source(
                    id=uuid.uuid5(uuid.NAMESPACE_DNS, src.id),
                    slug=src.id,
                    name=src.name,
                    category=src.category.value,
                    language=src.language,
                    is_active=True,
                ))
        await session.commit()
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/db/ backend/alembic/
git commit -m "feat: database schema with all models + alembic migration"
```

---

### Task 0.4: Lusa Scraper

**Files:**
- Create: `backend/src/scrapers/__init__.py`
- Create: `backend/src/scrapers/base.py`
- Create: `backend/src/scrapers/spiders/__init__.py`
- Create: `backend/src/scrapers/spiders/lusa.py`
- Modify: `backend/src/config/sources.yaml` (add RSS feed URL detail)
- Create: `backend/src/scrapers/extractors.py`

- [ ] **Step 1: Create base spider class**

```python
# backend/src/scrapers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScrapedArticle:
    external_id: str | None
    url: str
    title: str
    content_text: str | None
    summary: str | None
    author: str | None
    published_at: datetime | None
    language: str | None


class BaseSpider(ABC):
    """Base class for all scrapers. All spiders must implement this."""

    @abstractmethod
    async def fetch(self, source_id: str) -> list[ScrapedArticle]:
        """Fetch articles from source. Returns list of ScrapedArticle."""
        ...
```

- [ ] **Step 2: Create extractor utilities**

```python
# backend/src/scrapers/extractors.py
import trafilatura
import hashlib
from datetime import datetime


def extract_content(html: str, strategy: str = "trafilatura") -> str | None:
    if strategy == "trafilatura":
        return trafilatura.extract(html, output_format="txt", include_comments=False)
    return None


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    # Try common date formats
    from dateutil import parser
    try:
        return parser.parse(date_str)
    except Exception:
        return None
```

- [ ] **Step 3: Create Lusa spider (RSS + web fallback)**

```python
# backend/src/scrapers/spiders/lusa.py
import feedparser
import httpx
from datetime import datetime
from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.extractors import extract_content, compute_hash


class LusaSpider(BaseSpider):
    def __init__(self):
        self.rss_url = "https://www.lusa.pt/rss"
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def fetch(self, source_id: str) -> list[ScrapedArticle]:
        articles = []
        try:
            response = await self.http_client.get(self.rss_url)
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:50]:  # Limit to 50 per run
                article_url = entry.get("link", "")
                title = entry.get("title", "")
                published = entry.get("published", "")

                # Try to get full content via web scraping
                content_text = None
                if article_url:
                    try:
                        article_resp = await self.http_client.get(article_url)
                        content_text = extract_content(article_resp.text, "trafilatura")
                    except Exception:
                        pass

                articles.append(ScrapedArticle(
                    external_id=entry.get("id"),
                    url=article_url,
                    title=title,
                    content_text=content_text,
                    summary=entry.get("summary", title)[:500],
                    author="Lusa",
                    published_at=parse_date(published) if published else None,
                    language="pt",
                ))
        finally:
            await self.http_client.aclose()

        return articles


def parse_date(date_str: str) -> datetime | None:
    from dateutil import parser
    try:
        return parser.parse(date_str)
    except Exception:
        return None
```

- [ ] **Step 4: Create test for Lusa spider**

```python
# backend/tests/test_scrapers.py
import pytest
from src.scrapers.spiders.lusa import LusaSpider


@pytest.mark.asyncio
async def test_lusa_spider_fetches_articles():
    spider = LusaSpider()
    articles = await spider.fetch("lusa")
    assert len(articles) > 0
    assert articles[0].title is not None
    assert articles[0].url.startswith("http")
```

- [ ] **Step 5: Test and commit**

```bash
cd backend && pytest tests/test_scrapers.py -v
Expected: PASS (at least 1 article fetched from Lusa RSS)
```

```bash
git add backend/src/scrapers/ backend/tests/
git commit -m "feat: Lusa RSS + web scraper with article extraction"
```

---

### Task 0.5: Portuguese Media Spiders

**Files:**
- Create: `backend/src/scrapers/spiders/portugal_media.py`
- Modify: `backend/tests/test_scrapers.py`

- [ ] **Step 1: Create aggregator spider for Portuguese media outlets**

```python
# backend/src/scrapers/spiders/portugal_media.py
import feedparser
import httpx
from src.scrapers.base import BaseSpider, ScrapedArticle


# Outlet definitions: id → RSS URL
PORTUGAL_RSS_FEEDS = {
    "rtp_noticias": "https://www.rtp.pt/noticias/rss",
    "publico": "https://www.publico.pt/rss",
    "observador": "https://observador.pt/feed/",
    "expresso": "https://expresso.pt/rss",
    "cm_jornal": "https://www.cmjornal.pt/rss",
    "jn": "https://www.jn.pt/rss",
    "dn": "https://www.dn.pt/rss",
    "sic_noticias": "https://sicnoticias.pt/rss",
    "eco": "https://eco.sapo.pt/feed/",
}


class PortugalMediaSpider(BaseSpider):
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def fetch(self, source_id: str) -> list[ScrapedArticle]:
        rss_url = PORTUGAL_RSS_FEEDS.get(source_id)
        if not rss_url:
            return []

        articles = []
        try:
            response = await self.http_client.get(rss_url)
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:30]:  # Limit per source
                articles.append(ScrapedArticle(
                    external_id=entry.get("id"),
                    url=entry.get("link", ""),
                    title=entry.get("title", ""),
                    content_text=entry.get("summary"),
                    summary=entry.get("summary", "")[:500],
                    author=None,
                    published_at=None,  # Will be parsed by pipeline
                    language="pt",
                ))
        finally:
            await self.http_client.aclose()

        return articles
```

- [ ] **Step 2: Add test**

```python
# In tests/test_scrapers.py (append)
@pytest.mark.asyncio
async def test_portugal_media_spider():
    from src.scrapers.spiders.portugal_media import PortugalMediaSpider
    spider = PortugalMediaSpider()
    articles = await spider.fetch("publico")
    assert len(articles) > 0
    assert articles[0].title
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/scrapers/spiders/portugal_media.py backend/tests/
git commit -m "feat: Portuguese media RSS scrapers (9 outlets)"
```

---

### Task 0.6: International Source Spiders

**Files:**
- Create: `backend/src/scrapers/spiders/international.py`
- Modify: `backend/tests/test_scrapers.py`

- [ ] **Step 1: Create international spider with language detection**

```python
# backend/src/scrapers/spiders/international.py
import feedparser
import httpx
from lingua import Language, LanguageDetectorBuilder
from src.scrapers.base import BaseSpider, ScrapedArticle

# International sources with RSS feeds
INTERNATIONAL_FEEDS = {
    "reuters": "https://www.reuters.com/arc/outboundfeeds/newsletter/",
    "bbc": "https://feeds.bbci.co.uk/news/rss.xml",
    "guardian": "https://www.theguardian.com/world/rss",
    "ap": "https://feeds.feedburner.com/AssociatedPressNews",
    "elpais": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
}

detector = LanguageDetectorBuilder.from_languages(
    Language.ENGLISH, Language.PORTUGUESE, Language.SPANISH, Language.FRENCH
).build()


class InternationalSpider(BaseSpider):
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def fetch(self, source_id: str) -> list[ScrapedArticle]:
        rss_url = INTERNATIONAL_FEEDS.get(source_id)
        if not rss_url:
            return []

        articles = []
        try:
            response = await self.http_client.get(rss_url)
            feed = feedparser.parse(response.text)

            for entry in feed.entries[:30]:
                title = entry.get("title", "")
                detected_lang = detector.detect_language_of(title)
                lang_code = detected_lang.iso_code_639_1.name.lower() if detected_lang else "en"

                articles.append(ScrapedArticle(
                    external_id=entry.get("id"),
                    url=entry.get("link", ""),
                    title=title,
                    content_text=entry.get("summary"),
                    summary=entry.get("summary", "")[:500],
                    author=None,
                    published_at=None,
                    language=lang_code,
                ))
        finally:
            await self.http_client.aclose()

        return articles
```

- [ ] **Step 2: Add source config entries (update sources.yaml)**

Append to `sources.yaml`:
```yaml
  - id: reuters
    name: "Reuters"
    type: rss
    url: "https://www.reuters.com/arc/outboundfeeds/newsletter/"
    language: en
    category: international
    schedule_interval_minutes: 60
    extraction_strategy: trafilatura

  - id: bbc
    name: "BBC News"
    type: rss
    url: "https://feeds.bbci.co.uk/news/rss.xml"
    language: en
    category: international
    schedule_interval_minutes: 60
    extraction_strategy: trafilatura

  - id: guardian
    name: "The Guardian"
    type: rss
    url: "https://www.theguardian.com/world/rss"
    language: en
    category: international
    schedule_interval_minutes: 60
    extraction_strategy: trafilatura
```

- [ ] **Step 3: Add test**

```python
@pytest.mark.asyncio
async def test_international_spider():
    from src.scrapers.spiders.international import InternationalSpider
    spider = InternationalSpider()
    articles = await spider.fetch("bbc")
    assert len(articles) > 0
    assert articles[0].language in ("en", "pt", "es", "fr")
```

- [ ] **Step 4: Commit**

```bash
git add backend/src/scrapers/spiders/international.py backend/src/config/sources.yaml backend/tests/
git commit -m "feat: international source spiders with language detection"
```

---

### Task 0.7: Embedding Pipeline

**Files:**
- Create: `backend/src/pipeline/__init__.py`
- Create: `backend/src/pipeline/embedder.py`
- Create: `backend/tests/test_embedder.py`

- [ ] **Step 1: Create embedding service**

```python
# backend/src/pipeline/embedder.py
from sentence_transformers import SentenceTransformer


class EmbeddingService:
    """Generates embeddings using multilingual-e5 model."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large"):
        self.model = SentenceTransformer(model_name)

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text string."""
        # Truncate very long texts to avoid token limits
        max_chars = 8192
        truncated = text[:max_chars] if text else ""
        if not truncated.strip():
            return [0.0] * self.model.get_sentence_embedding_dimension()

        embedding = self.model.encode(truncated, normalize_embeddings=True)
        return embedding.tolist()

    def embed_articles(self, articles: list[dict]) -> list[list[float]]:
        """Batch embed multiple articles by their text content."""
        texts = []
        for art in articles:
            content = art.get("content_text") or art.get("title", "")
            texts.append(content[:8192])

        if not texts:
            return []

        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]
```

- [ ] **Step 2: Create embedder test**

```python
# backend/tests/test_embedder.py
import pytest
from src.pipeline.embedder import EmbeddingService


@pytest.fixture
def embedder():
    return EmbeddingService()


def test_embedder_returns_vector(embedder):
    vector = embedder.embed_text("Trump salva 8 mulheres da execução no Irão")
    assert len(vector) > 0
    assert all(isinstance(v, float) for v in vector)


def test_similar_texts_have_similar_embeddings(embedder):
    v1 = embedder.embed_text("O presidente argentino Javier Milei anuncia reformas")
    v2 = embedder.embed_text("Milei apresenta pacote de reformas económicas")
    v3 = embedder.embed_text("A seleção portuguesa venceu o jogo de ontem")

    import numpy as np
    sim_12 = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    sim_13 = np.dot(v1, v3) / (np.linalg.norm(v1) * np.linalg.norm(v3))

    assert sim_12 > sim_13, "Similar texts should have higher cosine similarity"
```

- [ ] **Step 3: Test and commit**

```bash
cd backend && pytest tests/test_embedder.py -v
Expected: PASS
```

```bash
git add backend/src/pipeline/embedder.py backend/tests/test_embedder.py
git commit -m "feat: multilingual embedding service with cross-lingual similarity"
```

---

### Task 0.8: Story Matching Pipeline

**Files:**
- Create: `backend/src/pipeline/matcher.py`
- Create: `backend/tests/test_matcher.py`

- [ ] **Step 1: Create story matcher (cosine similarity + clustering)**

```python
# backend/src/pipeline/matcher.py
import numpy as np
import uuid
from dataclasses import dataclass
from sklearn.cluster import DBSCAN
from datetime import datetime


@dataclass
class MatchResult:
    article_id: uuid.UUID
    cluster_id: uuid.UUID | None
    similarity_to_centroid: float | None


class StoryMatcher:
    """
    Matches articles into story clusters using embedding similarity.
    Thresholds are initial values — calibrate with labeled test set.
    """

    EXACT_REPUBLICATION_THRESHOLD = 0.85
    PARAPHRASE_THRESHOLD = 0.70
    PARTIAL_REFERENCE_THRESHOLD = 0.55
    CLUSTER_EPS = 0.25  # DBSCAN epsilon for cluster radius

    def cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        v1_np = np.array(v1)
        v2_np = np.array(v2)
        if np.linalg.norm(v1_np) == 0 or np.linalg.norm(v2_np) == 0:
            return 0.0
        return float(np.dot(v1_np, v2_np) / (np.linalg.norm(v1_np) * np.linalg.norm(v2_np)))

    def classify_match(self, similarity: float) -> str:
        if similarity >= self.EXACT_REPUBLICATION_THRESHOLD:
            return "exact_republication"
        elif similarity >= self.PARAPHRASE_THRESHOLD:
            return "paraphrase"
        elif similarity >= self.PARTIAL_REFERENCE_THRESHOLD:
            return "partial_reference"
        return "original_reporting"

    def cluster_articles(self, embeddings: list[list[float]]) -> np.ndarray:
        """Cluster articles using DBSCAN. Returns cluster labels."""
        if len(embeddings) < 2:
            return np.array([0])
        
        clustering = DBSCAN(eps=self.CLUSTER_EPS, min_samples=1, metric="cosine")
        return clustering.fit_predict(np.array(embeddings))

    def match_to_existing_clusters(
        self,
        embedding: list[float],
        cluster_centroids: dict[uuid.UUID, list[float]]
    ) -> tuple[uuid.UUID | None, float | None]:
        """Match a new article to existing clusters, or return None for orphan."""
        best_cluster = None
        best_similarity = 0.0

        for cluster_id, centroid in cluster_centroids.items():
            sim = self.cosine_similarity(embedding, centroid)
            if sim > best_similarity:
                best_similarity = sim
                best_cluster = cluster_id

        if best_similarity >= self.PARAPHRASE_THRESHOLD:
            return best_cluster, best_similarity
        return None, None  # Orphan — create new cluster
```

- [ ] **Step 2: Create matcher test**

```python
# backend/tests/test_matcher.py
import pytest
import uuid
from src.pipeline.matcher import StoryMatcher


@pytest.fixture
def matcher():
    return StoryMatcher()


def test_cosine_similarity_identical(matcher):
    v = [0.5, 0.3, 0.8, 0.1]
    assert matcher.cosine_similarity(v, v) == pytest.approx(1.0, rel=0.01)


def test_cosine_similarity_orthogonal(matcher):
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    assert matcher.cosine_similarity(v1, v2) == pytest.approx(0.0, abs=0.01)


def test_classify_match(matcher):
    assert matcher.classify_match(0.90) == "exact_republication"
    assert matcher.classify_match(0.75) == "paraphrase"
    assert matcher.classify_match(0.60) == "partial_reference"
    assert matcher.classify_match(0.40) == "original_reporting"


def test_cluster_articles(matcher):
    # Three similar embeddings and one very different one
    similar = [[0.1, 0.2, 0.3], [0.11, 0.21, 0.31], [0.09, 0.19, 0.32]]
    different = [[0.9, 0.8, 0.7]]
    
    all_embeddings = similar + different
    labels = matcher.cluster_articles(all_embeddings)
    
    assert labels[0] == labels[1] == labels[2]  # 3 similares no mesmo cluster
    assert labels[3] != labels[0]  # O diferente noutro cluster (ou -1)


def test_match_to_existing(matcher):
    cluster_id = uuid.uuid4()
    centroids = {cluster_id: [0.1, 0.2, 0.3]}
    
    # Similar article
    matched_id, score = matcher.match_to_existing_clusters([0.11, 0.21, 0.31], centroids)
    assert matched_id == cluster_id
    assert score > 0.90
    
    # Unrelated article
    unmatched_id, score2 = matcher.match_to_existing_clusters([0.9, 0.8, 0.7], centroids)
    assert unmatched_id is None
```

- [ ] **Step 3: Test and commit**

```bash
cd backend && pytest tests/test_matcher.py -v
Expected: PASS
```

```bash
git add backend/src/pipeline/matcher.py backend/tests/test_matcher.py
git commit -m "feat: story matching with DBSCAN clustering + cosine similarity"
```

---

### Task 0.9: Sentiment Analysis (pysentimiento, Local CPU, $0)

**Files:**
- Create: `backend/src/pipeline/sentiment.py`
- Create: `backend/tests/test_sentiment.py`

- [ ] **Step 1: Create sentiment analysis service**

```python
# backend/src/pipeline/sentiment.py
"""Sentiment analysis using pysentimiento (local CPU, $0 API costs).
Supports Portuguese, Spanish, and English."""
from pysentimiento import create_analyzer


class SentimentAnalyzer:
    """Multi-language sentiment analysis using pysentimiento.
    All models run locally on CPU — no API calls needed."""

    def __init__(self):
        # Portuguese analyzer
        self.analyzer_pt = create_analyzer(task="sentiment", lang="pt")
        # Spanish analyzer
        self.analyzer_es = create_analyzer(task="sentiment", lang="es")
        # English analyzer
        self.analyzer_en = create_analyzer(task="sentiment", lang="en")

    def analyze(self, text: str, language: str = "pt") -> dict:
        """
        Analyze sentiment of text in the given language.
        Returns: { 'sentiment': 'POS'|'NEG'|'NEU', 'probas': {...} }
        """
        if language == "pt":
            result = self.analyzer_pt.predict(text)
        elif language == "es":
            result = self.analyzer_es.predict(text)
        else:
            result = self.analyzer_en.predict(text)

        return {
            "sentiment": result.output,
            "probas": result.probas,
        }

    def analyze_batch(self, texts: list[str], language: str = "pt") -> list[dict]:
        """Analyze sentiment for a batch of texts."""
        return [self.analyze(t, language) for t in texts]
```

- [ ] **Step 2: Create sentiment test**

```python
# backend/tests/test_sentiment.py
import pytest
from src.pipeline.sentiment import SentimentAnalyzer


@pytest.fixture
def analyzer():
    return SentimentAnalyzer()


def test_positive_sentiment_pt(analyzer):
    result = analyzer.analyze("Que dia maravilhoso! Estou muito feliz.", "pt")
    assert result["sentiment"] == "POS"
    assert result["probas"]["POS"] > 0.5


def test_negative_sentiment_pt(analyzer):
    result = analyzer.analyze("Esta situação é horrível e injusta.", "pt")
    assert result["sentiment"] == "NEG"
    assert result["probas"]["NEG"] > 0.5


def test_english_sentiment(analyzer):
    result = analyzer.analyze("This is absolutely wonderful news!", "en")
    assert result["sentiment"] == "POS"


def test_spanish_sentiment(analyzer):
    result = analyzer.analyze("Es una tragedia lo que está pasando.", "es")
    assert result["sentiment"] == "NEG"
```

- [ ] **Step 3: Test and commit**

```bash
cd backend && pytest tests/test_sentiment.py -v
Expected: PASS
```

```bash
git add backend/src/pipeline/sentiment.py backend/tests/test_sentiment.py
git commit -m "feat: sentiment analysis with pysentimiento (local CPU, $0)"
```

---

### Task 0.10: GitHub Actions Workflows (Substitui APScheduler)

**Files:**
- Create: `.github/workflows/scrape.yml`
- Create: `backend/src/scrapers/loader.py`
- Create: `backend/src/supabase/__init__.py`
- Create: `backend/src/supabase/client.py`

> **Porquê GitHub Actions?** Em vez de um scheduler que corre 24/7 num servidor (que custa dinheiro), usamos GitHub Actions com cron. O workflow corre, faz scraping, escreve na Supabase, e termina. Zero custo.

- [ ] **Step 1: Create spider registry/loader**

```python
# backend/src/scrapers/loader.py
from src.config import SourceConfig
from src.scrapers.spiders.lusa import LusaSpider
from src.scrapers.spiders.portugal_media import PortugalMediaSpider
from src.scrapers.spiders.international import InternationalSpider


SPIDER_REGISTRY = {
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
    "reuters": InternationalSpider,
    "bbc": InternationalSpider,
    "guardian": InternationalSpider,
    "ap": InternationalSpider,
    "elpais": InternationalSpider,
}


def get_spider(source_config: SourceConfig):
    spider_class = SPIDER_REGISTRY.get(source_config.id)
    if spider_class:
        return spider_class()
    raise ValueError(f"No spider registered for source: {source_config.id}")
```

- [ ] **Step 2: Create Supabase client**

```python
# backend/src/supabase/client.py
from supabase import create_client, Client
from src.config.settings import settings


_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )
    return _supabase
```

- [ ] **Step 3: Create the main scrape.py entrypoint (called by GHA)**

```python
# backend/run_scrape.py
"""Entrypoint for GitHub Actions scraping workflow.
Called by: .github/workflows/scrape.yml
"""
import asyncio
import sys
from src.scrapers.loader import get_spider
from src.config import load_sources
from src.supabase.client import get_supabase
from src.pipeline.embedder import EmbeddingService
from datetime import datetime, timezone


async def run_scrape(source_id: str):
    config = load_sources()
    source_cfg = next((s for s in config.sources if s.id == source_id), None)
    if not source_cfg:
        print(f"Source {source_id} not found in config")
        return

    print(f"🔍 Scraping {source_cfg.name}...")
    spider = get_spider(source_cfg)
    articles = await spider.fetch(source_id)
    print(f"   Found {len(articles)} articles")

    embedder = EmbeddingService()
    supabase = get_supabase()

    new_count = 0
    for art in articles:
        # Check duplicate by URL
        existing = supabase.table("articles").select("id").eq("url", art.url).execute()
        if existing.data:
            continue

        # Generate embedding
        text_to_embed = (art.content_text or art.title)[:8192]
        embedding = embedder.embed_text(text_to_embed) if text_to_embed.strip() else None

        # Insert to Supabase
        supabase.table("articles").insert({
            "url": art.url,
            "title": art.title,
            "content_text": art.content_text,
            "summary": art.summary,
            "author": art.author,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "language": art.language or source_cfg.language,
            "source_id": source_id,
            "embedding": embedding,
        }).execute()
        new_count += 1

    print(f"   Inserted {new_count} new articles")


if __name__ == "__main__":
    source_id = sys.argv[1]
    asyncio.run(run_scrape(source_id))
```

- [ ] **Step 4: Create GitHub Actions workflow YAML**

```yaml
# .github/workflows/scrape.yml
name: Scrape Sources

on:
  schedule:
    # Lusa: every 30 min
    - cron: '*/30 * * * *'
    # Portuguese media: hourly
    # International: every 2 hours
  workflow_dispatch:  # Manual trigger for testing
    inputs:
      source:
        description: 'Source ID to scrape (or "all")'
        required: true
        default: 'lusa'

jobs:
  scrape:
    runs-on: ubuntu-latest
    
    env:
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
      
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          
      - name: Install system deps
        run: |
          sudo apt-get update
          sudo apt-get install -y build-essential
          
      - name: Install Python deps
        run: |
          cd backend
          pip install -e .
          # Download spaCy model
          python -m spacy download pt_core_news_lg
          
      - name: Scrape sources
        run: |
          cd backend
          if [ "${{ github.event.inputs.source }}" = "all" ] || [ "${{ github.event.inputs.source }}" = "" ]; then
            sources=("lusa" "publico" "observador" "rtp_noticias" "expresso" "cm_jornal")
            for src in "${sources[@]}"; do
              python run_scrape.py "$src"
            done
          else
            python run_scrape.py "${{ github.event.inputs.source }}"
          fi
          
      - name: Summary
        run: |
          echo "## Scrape Results" >> $GITHUB_STEP_SUMMARY
          echo "Source: ${{ github.event.inputs.source || 'scheduled' }}" >> $GITHUB_STEP_SUMMARY
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/scrape.yml backend/run_scrape.py backend/src/scrapers/loader.py backend/src/supabase/
git commit -m "feat: GitHub Actions scraping workflow (replaces APScheduler)"
```

---

### Task 0.11: Data Quality Monitoring (via GHA Summary)

**Files:**
- Create: `backend/src/pipeline/monitor.py`

> Em vez de Grafana (que precisa de um servidor), usamos **GitHub Actions Step Summary** + **Supabase queries**.

- [ ] **Step 1: Create monitoring module**

```python
# backend/src/pipeline/monitor.py
"""Health monitoring that runs at the end of each scrape workflow.
Outputs to GitHub Actions step summary."""
from src.supabase.client import get_supabase
from datetime import datetime, timedelta, timezone


def get_source_health() -> list[dict]:
    """Get health status for all sources from Supabase."""
    supabase = get_supabase()
    
    # Get all sources
    sources = supabase.table("sources").select("*").execute()
    
    health_report = []
    for source in sources.data:
        # Count articles in last 24h
        yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        count = supabase.table("articles").select("id", count="exact").eq(
            "source_id", source["slug"]
        ).gte("collected_at", yesterday).execute()
        
        article_count = count.count if hasattr(count, 'count') else 0
        
        health_report.append({
            "source": source["slug"],
            "articles_24h": article_count,
            "is_healthy": article_count > 0,
        })
    
    return health_report


def print_health_summary():
    """Print health summary in GHA-friendly format."""
    report = get_source_health()
    print("\n=== SOURCE HEALTH ===")
    for r in report:
        icon = "✅" if r["is_healthy"] else "❌"
        print(f"{icon} {r['source']}: {r['articles_24h']} articles in 24h")
    print("=" * 30)
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/pipeline/monitor.py
git commit -m "feat: data quality monitoring with GHA-friendly health checks"
```

---

### Task 0.12: Testing Suite

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_lusa_dependency.py`
- Create: `backend/tests/test_silence.py`

- [ ] **Step 1: Create conftest with test fixtures**

```python
# backend/tests/conftest.py
import pytest
import uuid
import numpy as np
from datetime import datetime, timezone


@pytest.fixture
def sample_articles():
    """Generate sample articles for testing."""
    return [
        {
            "id": uuid.uuid4(),
            "source_id": uuid.uuid4(),
            "title": "Governo anuncia novas medidas económicas",
            "content_text": "O governo português anunciou hoje um pacote de medidas económicas...",
            "published_at": datetime.now(timezone.utc),
            "language": "pt",
        },
        {
            "id": uuid.uuid4(),
            "source_id": uuid.uuid4(),
            "title": "Trump salva 8 mulheres da execução no Irão",
            "content_text": "O presidente dos EUA interveio para salvar oito mulheres da execução...",
            "published_at": datetime.now(timezone.utc),
            "language": "pt",
        },
    ]


@pytest.fixture
def sample_embedding():
    return [0.1, 0.2, 0.3, 0.4, 0.5]
```

- [ ] **Step 2: Create Lusa dependency test scaffold**

```python
# backend/tests/test_lusa_dependency.py
import pytest


def test_dependency_calculation():
    """Placeholder: In Phase 1, test that dependency % is calculated correctly.
    
    Scenario:
    - 10 articles from Lusa
    - 5 non-Lusa articles match 3 Lusa articles
    - Dependency % should be 60% (3/5)
    """
    assert True  # Replace with actual test during Phase 1 implementation


def test_topic_monopoly_detection():
    """Placeholder: In Phase 1, verify topic monopoly scoring."""
    assert True
```

- [ ] **Step 3: Run full test suite**

```bash
cd backend && pytest tests/ -v
Expected: ALL PASS (test_lusa_dependency tests are placeholders that pass)
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/
git commit -m "test: test suite with fixtures, scaffolded Phase 1 tests"
```

---

### Task 0.13: Storage & Backup (via Supabase + GitHub)

**Files:**
- Create: `.github/workflows/backup.yml`

> **Backup strategy:** Supabase faz snapshot automático do PostgreSQL. Nós exportamos metadados periodicamente para o repositório GitHub (gratuito). Texto completo dos artigos é mantido apenas 1 mês na Supabase (limite de 500MB).

- [ ] **Step 1: Create backup workflow**

```yaml
# .github/workflows/backup.yml
name: Database Backup

on:
  schedule:
    - cron: '0 3 * * 0'  # Weekly: Sunday 3AM
  workflow_dispatch:

jobs:
  backup:
    runs-on: ubuntu-latest
    
    env:
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          
      - name: Install deps
        run: |
          pip install supabase
          
      - name: Export metadata to JSON
        run: |
          mkdir -p backups
          python -c "
          from supabase import create_client
          import json, os
          
          supabase = create_client(
              os.environ['SUPABASE_URL'],
              os.environ['SUPABASE_SERVICE_KEY']
          )
          
          # Export article summaries (not full text to respect copyright)
          result = supabase.table('articles').select('id,url,title,summary,source_id,published_at,language').execute()
          with open('backups/articles_metadata.json', 'w') as f:
              json.dump(result.data, f, indent=2)
          
          print(f'Exported {len(result.data)} articles')
          "
          
      - name: Commit backup
        run: |
          git config user.name "vespeiro-bot"
          git config user.email "bot@vespeiro.pt"
          git add backups/
          git diff --staged --quiet || git commit -m "chore: weekly metadata backup"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/backup.yml
git commit -m "feat: weekly backup workflow exporting metadata to GitHub repo"
```

---

## Phase 1 — Lusa Dependency (Reference Tasks)

> **Not yet active.** Tasks below document what comes next. Activate by copying into active section above when Phase 0 is complete.

### Task 1.1 — Lusa Source Tagging
- Tag Lusa articles: `is_lusa: true` on Source record
- Detect Lusa attribution in non-Lusa articles (regex: "Segundo a Lusa", "fonte da Lusa")
- File: `backend/src/analysis/lusa_dependency.py`

### Task 1.2 — Content Matching Pipeline
- For each non-Lusa PT article, find closest Lusa article (±3 days)
- Classify match: exact_republication (>0.85), paraphrase (0.70-0.85), partial (0.55-0.70)
- File: `backend/src/analysis/lusa_dependency.py`

### Task 1.3 — Lusa Dependency Score
- Per outlet: `matched_to_lusa / total_articles × 100`
- Per topic: topic dependency %
- Time series tracking
- File: `backend/src/analysis/lusa_dependency.py`

---

## Phase 2 — The Broken Mirror (Reference Tasks)

### Task 2.1 — International Source Health
### Task 2.2 — Multi-Source Story Clustering
### Task 2.3 — Coverage Comparison Matrix
### Task 2.4 — Silence Detection
### Task 2.5 — Narrative Asymmetry by Figure
### Task 2.6 — Topic-Specific Narrative Divergence
### Task 2.7 — "Jornal do Contra" Generator
### Task 2.8 — Historical Baseline & Anomaly Detection

---

## Phase 3 — State Ecosystem (Reference Tasks)

### Task 3.1 — Government Communication Collector
### Task 3.2 — Diário da República Scraper
### Task 3.3 — Parliamentary Debate Collector
### Task 3.4 — Institutional Advertising Data
### Task 3.5 — Personnel Network Graph
### Task 3.6 — Parliament-Media Gap
### Task 3.7 — Advertising-Editorial Correlation
### Task 3.8 — Complete Influence Map

---

## Phase 4 — Public Exposure (Reference Tasks)

### Task 4.1 — Public Dashboard (React)
### Task 4.2 — Alert System (Telegram Bot)
### Task 4.3 — Public API
### Task 4.4 — Transparency & Methodology
### Task 4.5 — Archival & Data Integrity
