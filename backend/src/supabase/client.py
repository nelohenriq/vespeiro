"""Supabase client — lazy-initialised singleton for production writes.

Requires ``SUPABASE_URL`` and ``SUPABASE_SERVICE_KEY`` to be set in the
environment (typically via GitHub Actions secrets).  Falls back to a
``None`` client if either is missing, allowing local development without
Supabase credentials.
"""

import logging
from typing import Any

from src.config.settings import settings

logger = logging.getLogger(__name__)

_supabase: Any = None  # supabase.Client | None


def get_supabase() -> Any:
    """Return the Supabase client singleton, or ``None`` if not configured.

    The client is created once and cached.  Requires both ``supabase_url``
    and ``supabase_service_key`` to be set in :class:`Settings`.
    """
    global _supabase

    if _supabase is not None:
        return _supabase

    if not settings.supabase_url or not settings.supabase_service_key:
        logger.warning(
            "Supabase credentials not configured — set SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY in your .env or environment."
        )
        _supabase = False  # sentinel — don't retry
        return None

    try:
        from supabase import create_client  # type: ignore[import-untyped]

        _supabase = create_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )
        logger.info("Supabase client initialised")
    except Exception as exc:
        logger.error("Failed to initialise Supabase client: %s", exc)
        _supabase = False
        return None

    return _supabase
