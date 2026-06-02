"""
Expresso spider adapter — runs the Scrapy ``expresso`` spider via subprocess.

Why subprocess?
---------------
Same reasoning as ``PublicoSpider`` and ``PortugalNewsScrapySpider``: Scrapy's
Twisted reactor conflicts with asyncio.

DataDome limitation
-------------------
Expresso is protected by **DataDome**, which blocks all automated HTTP access
(including Scrapy's HTTP client, httpx, curl, and headless Playwright).

**What works:**
- Sitemap (``sitemap/news.xml``) — accessible, provides article URLs, titles,
  and publication dates via the Google News sitemap schema.
- Google News RSS — provides article titles, dates, and Google News redirect URLs.

**What doesn't work:**
- Homepage — blocked (403)
- Individual article pages — blocked (403)
- Headless Playwright — blocked (DataDome detects headless browsers)

**Content quality:**
- Articles from this spider will have **titles, URLs, and publication dates**
  but will **not** have full article text.
- The ``content_text`` field will be ``None`` for Expresso articles.
- The pipeline's deduplication (by URL) handles this gracefully.
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

# How many articles to collect from sitemap + RSS
_MAX_ARTICLES = 60


class ExpressoSpider(BaseSpider):
    """Run the Scrapy ``expresso`` spider via subprocess.

    The spider scrapes Expresso using:
    1. Sitemap (``sitemap/news.xml``) — primary source (URLs, titles, dates)
    2. Google News RSS — secondary source (for additional coverage)

    Full article text is **not available** due to DataDome protection.
    """

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        """Execute the Scrapy spider for Expresso and return articles."""
        if not _SCRAPY_PROJECT_DIR.exists():
            logger.error("Scrapy project dir not found: %s", _SCRAPY_PROJECT_DIR)
            return []

        items_raw = await self._run_scrapy_crawl()
        if not items_raw:
            logger.warning("ExpressoSpider: no items returned from Scrapy crawl")
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
                content_text=item.get("content_text"),  # Will be None for Expresso
                summary=item.get("summary"),
                author=item.get("author"),
                published_at=_parse_date(item.get("published_at")),
                language="pt",
                source_id=source_id,
            ))

        logger.info(
            "ExpressoSpider: %d articles from %d items",
            len(articles),
            len(items_raw),
        )
        return articles

    async def _run_scrapy_crawl(self) -> list[dict[str, Any]]:
        """Run ``scrapy crawl expresso`` in a subprocess."""
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
                "expresso",
                "-o",
                tmp_path,
                "-s",
                "FEED_FORMAT=jsonlines",
                "-s",
                "LOG_ENABLED=False",
                "-a",
                f"max_articles={_MAX_ARTICLES}",
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
                    "Scrapy crawl expresso failed (exit %d): %s",
                    result.returncode,
                    stderr_text,
                )
                return []

            with open(tmp_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            if not lines:
                logger.debug("Scrapy crawl expresso produced no output")
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

            logger.info("Scrapy crawl expresso: %d items", len(items))
            return items

        except subprocess.TimeoutExpired:
            logger.warning("Scrapy crawl expresso timed out")
            return []
        except Exception as exc:
            logger.error("Scrapy crawl expresso failed: %s", exc)
            return []
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
