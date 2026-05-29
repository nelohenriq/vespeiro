"""
Generic Scrapy adapter for Portuguese news media websites.

Runs ``portugal_news`` spider (from ``backend/scrapy_project/``) via subprocess
with site-specific parameters (URL, CSS selector, etc.) and converts the
Scrapy JSON Lines output to the project's ``ScrapedArticle`` format.

Supports any source that has a JS-free, crawler-accessible homepage with
article links.  Sources that block automated requests (Expresso, SIC Notícias)
or require JavaScript (JN, DN) will need a separate approach (see notes below).

Supported sources
-----------------
- Observador (observador.pt)
- ECO (eco.sapo.pt)
- Correio da Manhã (cmjornal.pt)
- SAPO 24 (24noticias.sapo.pt)
- Notícias ao Minuto (noticiasaominuto.com)

Why subprocess?
---------------
Same reasoning as ``PublicoSpider``: Scrapy's Twisted reactor conflicts with
asyncio.  Running Scrapy as a subprocess is clean and keeps the Scrapy project
independently usable (``scrapy crawl portugal_news -a site_url=...``).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.scrapers.base import BaseSpider, ScrapedArticle
from src.scrapers.spiders.publico import _parse_date, _SCRAPY_PROJECT_DIR

logger = logging.getLogger(__name__)

# ── Site configurations ──────────────────────────────────────────────────────
#   Each entry maps a source_id to the parameters needed by the generic spider.
#   link_selector = CSS selector for article links on the homepage.
#     Empty string → spider uses date-aware heuristic.


class SiteConfig:
    """Configuration for a single news website."""

    def __init__(
        self,
        source_id: str,
        site_url: str,
        link_selector: str = "",
        max_articles: int = 30,
    ):
        self.source_id = source_id
        self.site_url = site_url
        self.link_selector = link_selector
        self.max_articles = max_articles


SITE_CONFIGS: dict[str, SiteConfig] = {
    "observador": SiteConfig(
        source_id="observador",
        site_url="https://observador.pt",
        link_selector="a[href*='/202']",  # Has JSON-LD but no <article> tags
    ),
    "eco": SiteConfig(
        source_id="eco",
        site_url="https://eco.sapo.pt",
        link_selector="article a",  # Well-structured, 16 <article> tags
    ),
    "cm_jornal": SiteConfig(
        source_id="cm_jornal",
        site_url="https://www.cmjornal.pt",
        link_selector="article a",  # 99 <article> tags, 2 JSON-LD
    ),
    "sapo_24": SiteConfig(
        source_id="sapo_24",
        site_url="https://24noticias.sapo.pt",
        link_selector="article a[href]",  # 114 <article> tags, links are inside
    ),
    "nam": SiteConfig(
        source_id="nam",
        site_url="https://www.noticiasaominuto.com",
        link_selector="a[href*='202']",  # Few <article> tags, date-based URLs
    ),
}


class PortugalNewsScrapySpider(BaseSpider):
    """Run the generic ``portugal_news`` Scrapy spider for a configured source.

    Usage:
        spider = PortugalNewsScrapySpider()
        articles = await spider.fetch('eco')
    """

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        """Execute the Scrapy spider for *source_id* and return articles."""
        config = SITE_CONFIGS.get(source_id)
        if config is None:
            logger.warning(
                "PortugalNewsScrapySpider: no config for source '%s'", source_id
            )
            return []

        if not _SCRAPY_PROJECT_DIR.exists():
            logger.error("Scrapy project dir not found: %s", _SCRAPY_PROJECT_DIR)
            return []

        items_raw = await self._run_scrapy_crawl(config)
        if not items_raw:
            logger.warning("PortugalNewsScrapySpider: no items for '%s'", source_id)
            return []

        articles = []
        seen_urls: set[str] = set()

        for item in items_raw:
            art_url = item.get("url", "")
            if not art_url or art_url in seen_urls:
                continue
            seen_urls.add(art_url)

            articles.append(ScrapedArticle(
                url=art_url,
                title=item.get("title", ""),
                content_text=item.get("content_text"),
                summary=item.get("summary"),
                author=item.get("author"),
                published_at=_parse_date(item.get("published_at")),
                language="pt",
                source_id=source_id,
            ))

        logger.info(
            "%s: %d articles from %d items",
            source_id,
            len(articles),
            len(items_raw),
        )
        return articles

    async def _run_scrapy_crawl(
        self, config: SiteConfig
    ) -> list[dict[str, Any]]:
        """Run ``scrapy crawl portugal_news`` with site-specific args."""
        import asyncio

        with tempfile.NamedTemporaryFile(
            suffix=".jl", mode="w+", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                sys.executable,
                "-m",
                "scrapy",
                "crawl",
                "portugal_news",
                "-o",
                tmp_path,
                "-s",
                "FEED_FORMAT=jsonlines",
                "-s",
                "LOG_ENABLED=False",
                "-a",
                f"site_url={config.site_url}",
                "-a",
                f"link_selector={config.link_selector}",
                "-a",
                f"source_name={config.source_id}",
                "-a",
                f"max_articles={config.max_articles}",
            ]

            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(_SCRAPY_PROJECT_DIR),
                capture_output=True,
                timeout=120,
            )

            if result.returncode != 0:
                stderr_text = result.stderr.decode("utf-8", errors="replace")[:500]
                logger.error(
                    "Scrapy crawl %s failed (exit %d): %s",
                    config.source_id,
                    result.returncode,
                    stderr_text,
                )
                return []

            with open(tmp_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            if not lines:
                return []

            items: list[dict[str, Any]] = []
            for i, line in enumerate(lines):
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        items.append(item)
                except json.JSONDecodeError as exc:
                    logger.debug(
                        "Skipping malformed JSON line %d: %s", i, exc
                    )
                    continue

            logger.info("Scrapy crawl %s: %d items", config.source_id, len(items))
            return items

        except subprocess.TimeoutExpired:
            logger.warning("Scrapy crawl %s timed out", config.source_id)
            return []
        except Exception as exc:
            logger.error("Scrapy crawl %s failed: %s", config.source_id, exc)
            return []
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
