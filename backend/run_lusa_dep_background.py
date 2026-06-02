#!/usr/bin/env python3
"""Run LusaDependencyAnalyzer separately and save results for merging into stats.json.

This script runs the slow neural embedding model (10+ min on CPU) and writes
the results to a temp file. A separate merge script reads the temp file and
updates stats.json.

Usage:
    python run_lusa_dep_background.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def run() -> int:
    from src.db.session import create_engine_and_session, Base
    from src.config.settings import settings

    db_url = settings.database_url
    output = Path(__file__).parent / "data" / "lusa_dep_result.json"

    engine, session_factory = create_engine_and_session(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        from src.analysis.dependency import LusaDependencyAnalyzer

        t0 = datetime.now()
        print(f"[{t0.isoformat()}] Loading sentence transformer model...", flush=True)

        analyzer = LusaDependencyAnalyzer(db_session=session)
        result = await analyzer.analyze()

        t1 = datetime.now()
        elapsed = (t1 - t0).total_seconds()
        print(f"[{t1.isoformat()}] Analysis complete in {elapsed:.0f}s", flush=True)
        print(f"   global_pct: {result.global_pct}", flush=True)
        print(f"   outlets: {len(result.per_outlet)}", flush=True)
        print(f"   topics: {len(result.per_topic)}", flush=True)

        # Serialize
        payload = {
            "global_pct": result.global_pct,
            "per_outlet": {
                oid: {
                    "pct": od.pct,
                    "stories": od.stories,
                    "lusa_derived": od.lusa_derived,
                }
                for oid, od in result.per_outlet.items()
            },
            "per_topic": result.per_topic,
        }

        # Also get daily timeline
        print(f"[{datetime.now().isoformat()}] Computing daily timeline...", flush=True)
        daily = await analyzer.daily_timeline(days=7)
        payload["daily_timeline_7d"] = daily
        print(f"   timeline: {daily}", flush=True)

    await engine.dispose()

    # Write to temp file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Results saved to {output}", flush=True)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run())
    sys.exit(exit_code)
