"""Shared utilities for Scrapy-based spiders.

Provides ``_parse_date`` and ``_SCRAPY_PROJECT_DIR`` so that
all Scrapy-adapter spiders can import from a single location
instead of depending on ``src.scrapers.spiders.publico``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


# Path to the Scrapy project directory (containing scrapy.cfg)
_SCRAPY_PROJECT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "scrapy_project"
)


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an ISO 8601 date string, returning None on failure."""
    if not date_str:
        return None
    try:
        from dateutil import parser

        return parser.parse(date_str)
    except Exception:
        return None
