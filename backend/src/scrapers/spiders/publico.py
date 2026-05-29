"""
Publico spider — adapter that runs the Scrapy spider via subprocess and
converts the Scrapy output to the project's ``ScrapedArticle`` format.

Why subprocess?
---------------
Scrapy's ``CrawlerProcess`` manages the Twisted reactor, which conflicts with
asyncio when running inside the project's async ``fetch()`` method.  Running
Scrapy as a subprocess avoids Twisted/asyncio conflicts and keeps the Scrapy
project fully independent (usable via ``scrapy crawl publico``).

The subprocess overhead (~1 s startup) is negligible for a crawl that takes
30–60 seconds.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.scrapers.base import BaseSpider, ScrapedArticle

logger = logging.getLogger(__name__)

# Path to the Scrapy project directory (containing scrapy.cfg)
_SCRAPY_PROJECT_DIR = Path(__file__).parent.parent.parent.parent / "scrapy_project"


class PublicoSpider(BaseSpider):
    """Run the Scrapy Público spider and return results as ScrapedArticle list.

    The spider visits the Público homepage, extracts article links, follows
    each link, and extracts full text + metadata from each article page.

    Requires Scrapy and its dependencies to be installed.  The Scrapy project
    lives under ``backend/scrapy_project/``.
    """

    async def fetch(self, source_id: str, url: str = "") -> list[ScrapedArticle]:
        """Execute the Scrapy spider via subprocess and parse JSON Lines output."""
        if not _SCRAPY_PROJECT_DIR.exists():
            logger.error("Scrapy project dir not found: %s", _SCRAPY_PROJECT_DIR)
            return []

        items_raw = await self._run_scrapy_crawl()
        if not items_raw:
            logger.warning("PublicoSpider: no items returned from Scrapy crawl")
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
                published_at=self._parse_date(item.get("published_at")),
                language="pt",
                source_id=source_id,
            ))

        logger.info(
            "PublicoSpider: %d articles from %d items",
            len(articles),
            len(items_raw),
        )
        return articles

    async def _run_scrapy_crawl(self) -> list[dict[str, Any]]:
        """Run ``scrapy crawl publico`` in a subprocess and parse JSON Lines output.

        Uses a temporary file for the JSON Lines feed — each line is a separate
        JSON object, avoiding the multiple-array issue with Scrapy's JSON exporter.
        """
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
                "publico",
                "-o",
                tmp_path,
                "-s",
                "FEED_FORMAT=jsonlines",
                "-s",
                "LOG_ENABLED=False",
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
                    "Scrapy crawl failed (exit %d): %s",
                    result.returncode,
                    stderr_text,
                )
                return []

            # Parse JSON Lines: one JSON object per line
            with open(tmp_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            if not lines:
                logger.debug("Scrapy crawl produced no output (empty file)")
                return []

            items: list[dict[str, Any]] = []
            for i, line in enumerate(lines):
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        items.append(item)
                except json.JSONDecodeError as exc:
                    logger.debug("Skipping malformed JSON line %d: %s", i, exc)
                    continue

            logger.info("Scrapy crawl complete: %d items", len(items))
            return items

        except subprocess.TimeoutExpired:
            logger.warning("Scrapy crawl timed out after 120 s")
            return []
        except Exception as exc:
            logger.error("Scrapy crawl failed unexpectedly: %s", exc)
            return []
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        """Parse an ISO 8601 date string, returning None on failure."""
        if not date_str:
            return None
        try:
            from dateutil import parser
            return parser.parse(date_str)
        except Exception:
            return None
