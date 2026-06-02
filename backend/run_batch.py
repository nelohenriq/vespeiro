#!/usr/bin/env python3
"""Run the pipeline for a batch of sources, with per-source timeout."""
import asyncio
import sys
sys.path.insert(0, ".")

TIMEOUT_PER_SOURCE = 120  # seconds

# Sources that need more time (large PDFs, many candidates, etc.)
_TIMEOUT_OVERRIDES: dict[str, int] = {
    "parlamento_debates": 300,  # 100 PDFs + pdfplumber extraction
}


async def run_source(source_id: str) -> tuple[str, int, bool]:
    """Run one source and return (source_id, new_articles, success)."""
    from run_pipeline import fetch_and_store
    timeout = _TIMEOUT_OVERRIDES.get(source_id, TIMEOUT_PER_SOURCE)
    try:
        count = await asyncio.wait_for(
            fetch_and_store(source_id),
            timeout=timeout,
        )
        return source_id, count, True
    except asyncio.TimeoutError:
        print(f"   ⏰ {source_id} timed out after {timeout}s")
        return source_id, 0, False
    except Exception as exc:
        print(f"   ❌ {source_id} — {exc}")
        return source_id, 0, False


async def main():
    if len(sys.argv) < 2:
        print("Usage: python run_batch.py <source_id1,source_id2,...>")
        sys.exit(1)

    source_ids = [s.strip() for s in sys.argv[1].split(",") if s.strip()]
    print(f"Batch: {len(source_ids)} sources\n")

    total_new = 0
    success = 0
    failed = []
    for i, sid in enumerate(source_ids, 1):
        print(f"[{i}/{len(source_ids)}] {sid}...")
        _, count, ok = await run_source(sid)
        if ok:
            success += 1
            total_new += count
        else:
            failed.append(sid)

    print(f"\n{'='*50}")
    print(f"Done: {success}/{len(source_ids)} OK | {total_new} new articles")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
