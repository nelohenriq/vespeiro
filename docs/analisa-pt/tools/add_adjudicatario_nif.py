#!/usr/bin/env python3
"""One-time migration to add ``adjudicatario_nif`` column + composite indexes
to ``procurement.db``.

Why: ``transparency_scraper.py crossref`` (and many other buyer/supplier
lookups) used to scan all 1.6M rows and run a Python regex on
``adjudicatarios`` per row to extract the supplier NIF. That took
3+ minutes. Pre-extracting the first NIF into a dedicated column
and indexing it drops the crossref to a single ``GROUP BY`` query
on an indexed column (sub-second for the same data).

Steps (all idempotent):

1. ``ALTER TABLE contratos ADD COLUMN adjudicatario_nif TEXT`` — first
   9-digit NIF from the ``adjudicatarios`` text, extracted by the same
   regex pattern as ``utils.parse_entity_field`` (NIF, optional ws, "-",
   optional ws, name).
2. Backfill via batched ``UPDATE`` in chunks of 10K rows. ~30-60s for
   1.6M rows. Rows with empty/garbage ``adjudicatarios`` get NULL.
3. Create three new indexes (all idempotent, ``IF NOT EXISTS``):
   * ``idx_contratos_adjudicatario_nif`` — on the new column
   * ``idx_contratos_buyer_date`` — composite (adjudicante_nif,
     dataCelebracaoContrato) for date-filtered buyer queries
   * ``idx_contratos_buyer_value`` — composite (adjudicante_nif,
     precoContratual) for value-filtered buyer queries
4. ``ANALYZE`` to refresh query-planner statistics so the new indexes
   are actually used.

Locking: the table is briefly exclusive-locked during each
``CREATE INDEX`` (~1-3 min each on 1.6M rows). Existing readers
(anomaly_scanner, dashboard) will pause during the builds.

This script is safe to re-run. It will:
* skip the ``ADD COLUMN`` if the column already exists,
* skip the ``CREATE INDEX`` steps (they use ``IF NOT EXISTS``),
* re-run the backfill (which only updates rows where
  ``adjudicatario_nif IS NULL``).

Run with ``python add_adjudicatario_nif.py``. Exit code 0 on success.
"""

import re
import sqlite3
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "data" / "procurement.db"

# Match the first NIF in "NIF - Name" format. Same pattern as
# utils.parse_entity_field, anchored at the start of a ;-separated entry.
_NIF_RE = re.compile(r"(\d{9})\s*-\s*(.+)")


def _tune_conn(conn: sqlite3.Connection) -> None:
    """Apply the same PRAGMAs as utils_db.connect for the migration itself."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-500000")   # 500 MB for the migration
    conn.execute("PRAGMA mmap_size=536870912")  # 512 MB


def _existing_columns(conn: sqlite3.Connection) -> set:
    return {r[1] for r in conn.execute("PRAGMA table_info(contratos)").fetchall()}


def _existing_indexes(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='contratos' AND sql IS NOT NULL"
    ).fetchall()}


def step_add_column(conn: sqlite3.Connection) -> bool:
    """Add adjudicatario_nif column. Returns True if added (False if existed)."""
    print("Step 1: Adding adjudicatario_nif column...")
    if "adjudicatario_nif" in _existing_columns(conn):
        print("  already exists, skipping")
        return False
    conn.execute("ALTER TABLE contratos ADD COLUMN adjudicatario_nif TEXT")
    conn.commit()
    print("  added")
    return True


def step_backfill(conn: sqlite3.Connection) -> int:
    """Backfill adjudicatario_nif from adjudicatarios. Returns rows updated."""
    print("Step 2: Backfilling adjudicatario_nif from adjudicatarios...")
    t0 = time.time()

    # Read all rows that need backfill in a single query, then update in batches
    rows = conn.execute(
        "SELECT idcontrato, adjudicatarios FROM contratos "
        "WHERE adjudicatario_nif IS NULL "
        "AND adjudicatarios IS NOT NULL AND adjudicatarios != ''"
    ).fetchall()
    print(f"  {len(rows):,} rows to process")

    if not rows:
        return 0

    updated = 0
    batch = []
    BATCH = 10_000
    for r in rows:
        # adjudicatarios may be "NIF1 - Name1; NIF2 - Name2"; take the first
        first_entry = str(r["adjudicatarios"]).strip().split(";", 1)[0].strip()
        m = _NIF_RE.match(first_entry)
        if m:
            batch.append((m.group(1), r["idcontrato"]))
        if len(batch) >= BATCH:
            conn.executemany(
                "UPDATE contratos SET adjudicatario_nif = ? WHERE idcontrato = ?",
                batch,
            )
            updated += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "UPDATE contratos SET adjudicatario_nif = ? WHERE idcontrato = ?",
            batch,
        )
        updated += len(batch)
    conn.commit()
    print(f"  backfilled {updated:,} rows in {time.time() - t0:.1f}s")
    return updated


def step_create_indexes(conn: sqlite3.Connection) -> list:
    """Create the three new indexes. Returns list of (name, seconds) tuples."""
    print("Step 3: Creating new indexes...")
    existing = _existing_indexes(conn)
    targets = [
        ("idx_contratos_adjudicatario_nif",
         "CREATE INDEX IF NOT EXISTS idx_contratos_adjudicatario_nif "
         "ON contratos(adjudicatario_nif) WHERE adjudicatario_nif IS NOT NULL"),
        ("idx_contratos_buyer_date",
         "CREATE INDEX IF NOT EXISTS idx_contratos_buyer_date "
         "ON contratos(adjudicante_nif, dataCelebracaoContrato)"),
        ("idx_contratos_buyer_value",
         "CREATE INDEX IF NOT EXISTS idx_contratos_buyer_value "
         "ON contratos(adjudicante_nif, precoContratual)"),
    ]
    results = []
    for name, ddl in targets:
        if name in existing:
            print(f"  {name}: already exists, skipping")
            continue
        print(f"  {name}: building... ", end="", flush=True)
        t0 = time.time()
        conn.execute(ddl)
        conn.commit()
        elapsed = time.time() - t0
        print(f"done ({elapsed:.1f}s)")
        results.append((name, elapsed))
    return results


def step_analyze(conn: sqlite3.Connection) -> None:
    print("Step 4: ANALYZE (refresh query-planner stats)...")
    t0 = time.time()
    conn.execute("ANALYZE")
    conn.commit()
    print(f"  done ({time.time() - t0:.1f}s)")


def verify(conn: sqlite3.Connection) -> None:
    print("\n=== Verification ===")
    total = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
    filled = conn.execute(
        "SELECT COUNT(*) FROM contratos WHERE adjudicatario_nif IS NOT NULL"
    ).fetchone()[0]
    print(f"  Total contracts:           {total:,}")
    print(f"  With adjudicatario_nif:     {filled:,} ({filled * 100 / total:.1f}%)")

    # Sample 3 rows
    print("  Sample rows:")
    for r in conn.execute(
        "SELECT idcontrato, adjudicatarios, adjudicatario_nif FROM contratos "
        "WHERE adjudicatario_nif IS NOT NULL LIMIT 3"
    ).fetchall():
        adj = (r["adjudicatarios"] or "")[:50]
        print(f"    {r['idcontrato'][:18]:<20} nif={r['adjudicatario_nif']}  adj={adj!r}")

    # EXPLAIN QUERY PLAN on the crossref-style aggregation
    print("  EXPLAIN QUERY PLAN (crossref-style GROUP BY):")
    for r in conn.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT adjudicatario_nif, COUNT(*) FROM contratos "
        "WHERE adjudicatario_nif IS NOT NULL AND adjudicatario_nif != '' "
        "GROUP BY adjudicatario_nif"
    ).fetchall():
        print(f"    {r[3]}")

    # List all indexes on contratos
    print("  Indexes on contratos:")
    for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='contratos' AND sql IS NOT NULL ORDER BY name"
    ).fetchall():
        print(f"    {r['name']}")


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    print(f"Migrating {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.0f} MB)")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _tune_conn(conn)

    try:
        step_add_column(conn)
        step_backfill(conn)
        step_create_indexes(conn)
        step_analyze(conn)
        verify(conn)
        print("\nMigration complete.")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"\nERROR: migration failed: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
