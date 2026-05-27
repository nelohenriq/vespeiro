import hashlib
from datetime import datetime


def compute_hash(text: str) -> str:
    """SHA-256 hash for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string into datetime, or None if unparseable."""
    if not date_str:
        return None
    try:
        from dateutil import parser
        return parser.parse(date_str)
    except ImportError:
        # fallback: try common RSS formats
        from datetime import timezone
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
    except Exception:
        return None
