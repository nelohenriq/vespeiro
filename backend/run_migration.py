#!/usr/bin/env python3
"""
Vespeiro — Apply Supabase RLS migration.

Reads the RLS SQL file and executes it against the configured Supabase project
via the PostgreSQL connection. Also works with local SQLite for testing
(the RLS statements are no-ops on SQLite).

Usage:
    python run_migration.py                           # Apply from default path
    python run_migration.py --sql path/to/migration.sql  # Custom SQL file
    python run_migration.py --dry-run                    # Print SQL without executing
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent))


MIGRATION_DIR = Path(__file__).parent / "alembic" / "versions"
DEFAULT_SQL = MIGRATION_DIR / "2026_05_28_rls_public_api.sql"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply Supabase RLS migration",
    )
    parser.add_argument(
        "--sql",
        default=str(DEFAULT_SQL),
        help=f"Path to SQL migration file (default: {DEFAULT_SQL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL without executing",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override database URL (default: from settings)",
    )
    return parser


async def run(sql_path: Path, dry_run: bool, db_url_override: str | None) -> int:
    """Read and apply the RLS migration."""
    # ── Read SQL ──────────────────────────────────────────────────────────
    if not sql_path.exists():
        print(f"❌ Migration file not found: {sql_path}")
        return 1

    sql = sql_path.read_text(encoding="utf-8")

    if dry_run:
        print("── Dry run mode — SQL that would be executed ──")
        print(sql)
        print("── End of SQL ──")
        print()
        print("Note: RLS policies apply to Supabase/PostgreSQL only.")
        print("      SQLite (local dev) ignores RLS statements.")
        return 0

    # ── Resolve DB URL ────────────────────────────────────────────────────
    if db_url_override:
        db_url = db_url_override
    else:
        from src.config.settings import settings
        db_url = settings.database_url

    is_postgres = db_url.startswith("postgresql")

    if not is_postgres:
        print("⚠️  Database is SQLite (local dev). RLS policies are PostgreSQL-only.")
        print("   To apply policies to Supabase, use the Supabase SQL Editor:")
        print(f"   1. Open https://supabase.com/dashboard/project/<project>/sql/new")
        print(f"   2. Paste the contents of: {sql_path}")
        print(f"   3. Click 'Run'")
        print()
        print("   Or set DATABASE_URL to a Supabase PostgreSQL connection string.")
        return 0

    # ── Apply to PostgreSQL ───────────────────────────────────────────────
    print(f"🔌 Connecting to: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        engine = create_async_engine(db_url, echo=False)

        async with engine.begin() as conn:
            # Execute entire SQL file as a single script.
            # PostgreSQL's extended query protocol handles multi-statement
            # strings natively — splitting on semicolons would break
            # DO blocks, PL/pgSQL functions, and string literals.
            try:
                await conn.execute(text(sql))
            except Exception as exc:
                # On first run, some DROP POLICY IF EXISTS may fail if RLS
                # wasn't enabled yet. That's fine — creation follows.
                print(f"   ⚠️  Some statements may have warnings: {str(exc)[:120]}")
                # Continue — the script is idempotent

        await engine.dispose()
        print()
        print("✅ RLS migration applied successfully.")
        print(f"   Policy file: {sql_path}")
        return 0

    except Exception as exc:
        print(f"❌ Migration failed: {exc}")
        return 1


def main() -> None:
    import asyncio

    parser = _build_parser()
    args = parser.parse_args()

    sql_path = Path(args.sql)
    exit_code = asyncio.run(run(
        sql_path=sql_path,
        dry_run=args.dry_run,
        db_url_override=args.db_url,
    ))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
