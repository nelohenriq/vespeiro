#!/usr/bin/env python3
"""Generate daily stats.json for the Vespeiro dashboard.

Reads divergence reports from ``reports/divergence/*.json`` (produced by
``run_analysis.py``) and optionally queries the project database for
source/article metrics. Produces a single ``stats.json`` consumed by the
React frontend dashboard.

Usage:
    # No-database mode (divergence reports only)
    python run_stats.py

    # Custom output path
    python run_stats.py --output /tmp/stats.json

    # Custom reports directory
    python run_stats.py --reports-dir custom/reports/dir

    # With database (requires SQLite/Supabase configured)
    python run_stats.py --db
"""

import argparse
import sys
from pathlib import Path

# ── Entrypoint ──────────────────────────────────────────────────────────────


async def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Lazy-load StatsGenerator (avoids slow imports at module level)
    from src.stats.generator import StatsGenerator

    # ── Optional DB session ─────────────────────────────────────────────────
    db_session = None
    if args.db:
        print("🔌 Connecting to database…")
        try:
            from src.db.session import create_engine_and_session
            from src.config.settings import settings

            _, session_factory = create_engine_and_session(settings.database_url)
            db_session = session_factory()
        except Exception as exc:
            print(f"⚠️  Failed to connect to database: {exc}")
            print("   Stats will be generated without DB-backed metrics.")
            db_session = None

    # Resolve reports directory (absolute path relative to project root)
    if args.reports_dir:
        reports_path = Path(args.reports_dir)
    else:
        # Default: reports/divergence/ relative to project root
        # run_stats.py lives in backend/, so go up one level
        reports_path = Path(__file__).resolve().parent.parent / "reports" / "divergence"

    # ── Generator ──────────────────────────────────────────────────────────
    generator = StatsGenerator(
        db_session=db_session,
        reports_dir=reports_path,
    )

    print("📊 Collecting metrics…")
    payload = await generator.collect()

    # ── Serialize ──────────────────────────────────────────────────────────
    json_str = payload.model_dump_json(indent=2)

    # ── Output path ─────────────────────────────────────────────────────────
    if args.output:
        output_path = Path(args.output)
    else:
        # Default: frontend/public/stats.json relative to project root
        # run_stats.py lives in backend/, so go up one level
        output_path = Path(__file__).resolve().parent.parent / "frontend" / "public" / "stats.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_str, encoding="utf-8")

    # ── Summary ─────────────────────────────────────────────────────────────
    file_size_kb = len(json_str) / 1024
    print(f"✅ stats.json written to {output_path}")
    print(f"   Size: {file_size_kb:.1f} KB")
    print(f"   Generated at: {payload.generated_at.isoformat()}")
    print(f"   Sources: {payload.sources.total} total, {payload.sources.active} active")
    print(f"   Articles: {payload.sources.articles_total} total, {payload.sources.articles_today} today")
    if payload.divergence.global_avg is not None:
        print(f"   Divergence (global avg): {payload.divergence.global_avg:.1%}")
    else:
        print("   Divergence (global avg): N/A (no reports found)")
    print(f"   Divergence outlets: {len(payload.divergence.per_outlet)}")
    print(f"   Timeline days: {len(payload.timelines.dates_7d)}")

    # ── Cleanup ─────────────────────────────────────────────────────────────
    if db_session is not None:
        await db_session.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate daily stats.json for the Vespeiro dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path for stats.json (default: frontend/public/stats.json)",
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Path to divergence report JSON files (default: reports/divergence/)",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help="Enable database-backed metrics (source counts, article counts, system health)",
    )

    return parser


if __name__ == "__main__":
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
