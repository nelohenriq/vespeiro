#!/usr/bin/env python3
"""Seed all sources from sources.yaml into the database.

This ensures the dashboard shows the full source count even for sources
that haven't been scraped yet. Individual scrapes will add articles later.

Usage:
    python seed_sources.py              # Default DB
    python seed_sources.py --db sqlite+aiosqlite:///custom.db
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def seed() -> None:
    from src.config import load_sources
    from src.config.settings import settings
    from src.db.session import create_engine_and_session, Base
    from src.db.models import Source
    from sqlalchemy import select

    config = load_sources()
    print(f"📋 {len(config.sources)} sources defined in sources.yaml\n")

    # Ensure DB and tables exist
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        path_part = (
            db_url.replace("sqlite+aiosqlite:///", "")
            .replace("sqlite:///", "")
        )
        Path(path_part).parent.mkdir(parents=True, exist_ok=True)

    engine, session_factory = create_engine_and_session(db_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # Get existing source IDs
        result = await session.execute(select(Source.id))
        existing_ids: set[str] = {row[0] for row in result.all()}

        added = 0
        skipped = 0

        for src in config.sources:
            if src.id in existing_ids:
                skipped += 1
                continue

            session.add(Source(
                id=src.id,
                name=src.name,
                category=src.category.value,
                language=src.language,
                is_active=True,
            ))
            added += 1
            print(f"   ✅ {src.id:30} → {src.name}")

        await session.commit()

    await engine.dispose()

    print(f"\n📊 {added} sources added, {skipped} already existed")
    print(f"   Total: {added + skipped}/{len(config.sources)} sources in DB")


if __name__ == "__main__":
    asyncio.run(seed())
