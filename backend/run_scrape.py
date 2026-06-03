#!/usr/bin/env python3
"""Entrypoint for GitHub Actions scraping workflow.

Called by ``.github/workflows/scrape.yml``.

Usage:
    python run_scrape.py <source_id>

Example:
    python run_scrape.py lusa
    python run_scrape.py all          # scrape every configured source
"""

import asyncio
import sys

from src.config import load_sources
from src.scrapers.loader import get_spider
from src.pipeline.embedder import EmbeddingService
from src.pipeline.embedder import article_text as _article_text
from src.supabase.client import get_supabase


async def run_scrape(source_id: str) -> None:
    config = load_sources()
    matching = [s for s in config.sources if s.id == source_id]

    if not matching:
        print(f"❌ Source '{source_id}' not found in config")
        return

    source_cfg = matching[0]
    print(f"🔍 Scraping {source_cfg.name} ({source_cfg.id})…")

    spider = get_spider(source_cfg)
    articles = await spider.fetch(source_cfg.id, source_cfg.url)
    print(f"   Found {len(articles)} articles")

    embedder = EmbeddingService()
    supabase = get_supabase()

    if supabase is None:
        print("   ⚠️  Supabase not configured — printing articles instead")
        for art in articles[:3]:
            print(f"   - {art.title} ({art.url})")
        return

    new_count = 0
    new_articles = []
    new_embeddings = []
    for art in articles:
        # Check duplicate by URL
        existing = (
            supabase.table("articles")
            .select("id")
            .eq("url", art.url)
            .execute()
        )
        if existing.data:
            continue

        new_articles.append(art)
        new_count += 1

    # Batch-embed all new articles (much faster than one-by-one with API)
    embeddings: list[list[float]] = []
    if new_articles:
        try:
            import time
            t0 = time.time()
            texts = [_article_text(a) for a in new_articles]
            texts = [t for t in texts if t.strip()]
            embeddings = embedder.embed_batch(texts)
            embedder._persist_cache()
            elapsed = time.time() - t0
            print(f"   🧠 {len(texts)} articles embedded in {elapsed:.1f}s ({embedder._provider})")
        except Exception as exc:
            print(f"   ⚠️  Embedding failed (non-fatal): {exc}")
            embeddings = [[0.0] * embedder.dimension] * len(new_articles)

    for art, embedding in zip(new_articles, embeddings):
        supabase.table("articles").insert({
            "url": art.url,
            "title": art.title,
            "content_text": art.content_text,
            "summary": art.summary,
            "author": art.author,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "language": art.language or source_cfg.language,
            "source_id": source_cfg.id,
            "embedding": embedding,
        }).execute()

    print(f"   ✅ Inserted {new_count} new articles")


async def run_all() -> None:
    config = load_sources()
    for src in config.sources:
        try:
            await run_scrape(src.id)
        except Exception as exc:
            print(f"   ❌ Failed to scrape {src.id}: {exc}")


if __name__ == "__main__":
    source_id = sys.argv[1] if len(sys.argv) > 1 else "lusa"

    if source_id == "all":
        asyncio.run(run_all())
    else:
        asyncio.run(run_scrape(source_id))
