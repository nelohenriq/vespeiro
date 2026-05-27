#!/usr/bin/env python3
"""
Vespeiro — End-to-end pipeline runner.

Usage:
    python run_pipeline.py lusa          # Fetch Lusa articles
    python run_pipeline.py publico       # Fetch Público articles
    python run_pipeline.py all           # Fetch all active sources

Pipeline: load config → instantiate spider → fetch articles → store in SQLite → report
"""
import asyncio
import sys
from pathlib import Path
from sqlalchemy import select

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent))


async def fetch_and_store(source_id: str) -> int:
    """Fetch articles for one source and store them in SQLite. Returns count of new articles."""
    from src.config import load_sources
    from src.scrapers.loader import get_spider
    from src.db.session import create_engine_and_session, Base
    from src.db.models import Source, Article

    # 1. Load source config
    config = load_sources()
    source_cfg = next((s for s in config.sources if s.id == source_id), None)
    if not source_cfg:
        print(f"❌ Source '{source_id}' not found in sources.yaml")
        return 0

    print(f"\n{'='*60}")
    print(f"🔍 {source_cfg.name} ({source_cfg.type.value})")
    print(f"{'='*60}")

    # 2. Ensure data directory exists (SQLite won't create parent dirs)
    from src.config.settings import settings
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        # Extract path from sqlite+aiosqlite:///data/vespeiro.db → data/
        path_part = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        Path(path_part).parent.mkdir(parents=True, exist_ok=True)

    # 3. Create database tables
    engine, session_factory = create_engine_and_session(db_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 3. Ensure source exists in DB
    async with session_factory() as session:
        existing = await session.get(Source, source_id)
        if not existing:
            session.add(Source(
                id=source_id,
                name=source_cfg.name,
                category=source_cfg.category.value,
                language=source_cfg.language,
                is_active=True,
            ))
            await session.commit()
            print(f"   📝 Created source record in DB")

    # 4. Fetch articles
    spider = get_spider(source_cfg)
    articles = await spider.fetch(source_id, source_cfg.url)
    print(f"   📰 {len(articles)} articles fetched")

    if not articles:
        print("   ⚠️  No articles returned")
        await engine.dispose()
        return 0

    # 5. Store new articles (dedup by URL)
    new_count = 0
    async with session_factory() as session:
        for art in articles:
            if not art.url:
                continue

            # Check for duplicate by URL
            result = await session.execute(
                select(Article).where(Article.url == art.url)
            )
            if result.scalar_one_or_none():
                continue

            session.add(Article(
                source_id=source_id,
                external_id=art.external_id,
                url=art.url,
                title=art.title,
                content_text=art.content_text,
                summary=art.summary,
                author=art.author,
                published_at=art.published_at,
                language=art.language or source_cfg.language,
            ))
            new_count += 1

        await session.commit()
        total = len(articles)

    await engine.dispose()

    print(f"   ✅ {new_count} new articles stored (of {total} fetched)")
    return new_count


async def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python run_pipeline.py <source_id|all>")
        print("Sources: lusa, rtp_noticias, publico, observador, expresso, cm_jornal, jn, dn, sic_noticias, eco")
        sys.exit(1)

    target = args[0]

    if target == "all":
        from src.config import load_sources
        config = load_sources()
        total = 0
        errors = 0
        for src in config.sources:
            try:
                count = await fetch_and_store(src.id)
                total += count
            except Exception as exc:
                print(f"   ❌ Failed: {src.id} — {exc}")
                errors += 1
        print(f"\n{'='*60}")
        success = len(config.sources) - errors
        print(f"📊 {success}/{len(config.sources)} sources OK | {total} new articles stored")
        if errors:
            print(f"   {errors} sources failed")
        print(f"{'='*60}")
    else:
        await fetch_and_store(target)

    print("\n✅ Pipeline complete")


if __name__ == "__main__":
    asyncio.run(main())
