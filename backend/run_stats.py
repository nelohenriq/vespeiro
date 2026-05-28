#!/usr/bin/env python3
"""
Vespeiro — Daily stats generator.

Generates stats.json — the single source of truth for the Vespeiro frontend
dashboard. Runs queries against the local SQLite (or Supabase) database and
aggregates divergence reports to produce all platform metrics.

Usage:
    python run_stats.py                                # Default: writes to ../frontend/public/stats.json
    python run_stats.py --output path/to/stats.json    # Custom output path
    python run_stats.py --reports-dir reports/divergence  # Custom divergence reports directory
    python run_stats.py --db sqlite+aiosqlite:///custom.db  # Custom database URL
    python run_stats.py --no-db                        # Skip DB queries (divergence-only mode)

Pipeline: init DB → StatsGenerator.collect() → write stats.json → print summary
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent))


async def run(
    output_path: Path,
    db_url: str | None,
    reports_dir: str,
) -> int:
    """Generate stats.json and write it to *output_path*.

    Returns:
        0 on success, 1 on failure.
    """
    from src.stats.generator import StatsGenerator
    from src.stats.models import StatsPayload

    # ── DB session (optional) ───────────────────────────────────────────────
    db_session = None
    if db_url is not None:
        from src.db.session import create_engine_and_session, Base
        from sqlalchemy.ext.asyncio import AsyncSession

        # Ensure data directory exists for SQLite
        if db_url.startswith("sqlite"):
            path_part = (
                db_url.replace("sqlite+aiosqlite:///", "")
                .replace("sqlite:///", "")
            )
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)

        engine, session_factory = create_engine_and_session(db_url)

        # Ensure tables exist
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        db_session = session_factory()
        print(f"   🗄️  DB: {db_url}")
    else:
        print("   🗄️  DB: skipped (--no-db mode)")
        engine = None

    # ── Generate stats ──────────────────────────────────────────────────────
    print(f"   📊 Reports dir: {reports_dir}")
    print()

    generator = StatsGenerator(db_session=db_session, reports_dir=reports_dir)

    try:
        payload: StatsPayload = await generator.collect()
    except Exception as exc:
        print(f"❌ Stats generation failed: {exc}")
        return 1
    finally:
        if engine is not None:
            if db_session is not None:
                await db_session.close()
            await engine.dispose()

    # ── Write output ────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_str = payload.model_dump_json(indent=2, by_alias=True)
    output_path.write_text(json_str, encoding="utf-8")

    # ── Summary ─────────────────────────────────────────────────────────────
    size_kb = len(json_str) / 1024
    print(f"✅ stats.json written to {output_path}")
    print(f"   Size: {size_kb:.1f} KB")
    print(f"   Generated: {payload.generated_at.isoformat()}")
    print()

    # Quick summary of key metrics
    s = payload.sources
    print(f"📊 Summary:")
    print(f"   Sources:  {s.active}/{s.total} active")
    print(f"   Articles: {s.articles_total} total, {s.articles_today} today")
    if payload.lusa_dependency.global_pct is not None:
        print(f"   Lusa dependency: {payload.lusa_dependency.global_pct:.1f}%")
    if payload.divergence.global_avg is not None:
        print(f"   Divergence avg:  {payload.divergence.global_avg:.0%}")
    print(f"   Silence today:   {payload.silence.today}")
    print(f"   Reports loaded:  {len(payload.divergence.per_outlet)} outlets")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Vespeiro daily stats.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path for stats.json (default: ../frontend/public/stats.json)",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports/divergence",
        help="Directory with divergence report JSON files (default: reports/divergence)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Database URL (default: from settings — sqlite+aiosqlite:///data/vespeiro.db). "
            "Use --no-db to skip DB queries."
        ),
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Skip all database queries (divergence-only mode, uses --reports-dir)",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve output path
    if args.output:
        output = Path(args.output)
    else:
        # Default: frontend/public/stats.json relative to project root
        output = Path(__file__).parent.parent / "frontend" / "public" / "stats.json"

    # Resolve reports dir
    reports = args.reports_dir

    # Resolve database URL
    if args.no_db:
        db_url = None
    elif args.db:
        db_url = args.db
    else:
        from src.config.settings import settings
        db_url = settings.database_url

    # Run
    exit_code = asyncio.run(run(
        output_path=output,
        db_url=db_url,
        reports_dir=reports,
    ))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
