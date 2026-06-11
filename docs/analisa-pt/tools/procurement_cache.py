#!/usr/bin/env python3
"""
Pre-computed Procurement Cache — Fast JSON responses for the dashboard.

The full procurement.db is 1.9GB+ with 4M+ contracts. Querying it on every
API request is slow and blocks the dashboard from loading.

This script pre-computes all the expensive queries the dashboard needs and
saves them as small JSON files. The API server then serves these JSON files
directly (instant) instead of re-running the SQL queries.

Cache invalidation: any cache file older than procurement.db is considered
stale and triggers a rebuild.

Usage:
    python procurement_cache.py build          # Build all caches
    python procurement_cache.py build --force  # Force rebuild even if fresh
    python procurement_cache.py status         # Show cache status
    python procurement_cache.py clean          # Delete all cache files
"""

import argparse
import heapq
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "procurement.db"
CACHE_DIR = DATA_DIR / "cache"


# ---------------------------------------------------------------------------
# Cache metadata
# ---------------------------------------------------------------------------

CACHE_VERSION = 1  # bump when query shape changes to invalidate all caches


def _meta_path() -> Path:
    return CACHE_DIR / "_meta.json"


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _db_mtime() -> float:
    if not DB_PATH.exists():
        return 0
    return DB_PATH.stat().st_mtime


def _is_fresh(cache_file: Path) -> bool:
    """A cache is fresh if it exists, is newer than the DB, and version matches."""
    if not cache_file.exists():
        return False
    try:
        meta = json.loads(_meta_path().read_text())
        if meta.get("version") != CACHE_VERSION:
            return False
        if meta.get("db_mtime", 0) < _db_mtime():
            return False
        return True
    except Exception:
        return False


def _write_meta():
    """Write the cache metadata file with current DB mtime + version."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _meta_path().write_text(json.dumps({
        "version": CACHE_VERSION,
        "db_mtime": _db_mtime(),
        "db_size_mb": round(DB_PATH.stat().st_size / (1024 * 1024), 1) if DB_PATH.exists() else 0,
        "built_at": datetime.now().isoformat(),
    }, indent=2))


# ---------------------------------------------------------------------------
# Query functions — each returns a serializable dict, all expensive work
# ---------------------------------------------------------------------------

def query_stats(conn: sqlite3.Connection) -> dict:
    return {
        "total": conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0],
        "total_value": conn.execute(
            "SELECT COALESCE(SUM(precoContratual), 0) FROM contratos WHERE precoContratual > 0"
        ).fetchone()[0],
        "year_min": conn.execute(
            "SELECT MIN(Ano) FROM contratos WHERE Ano IS NOT NULL"
        ).fetchone()[0],
        "year_max": conn.execute(
            "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL"
        ).fetchone()[0],
        "with_nif": conn.execute(
            "SELECT COUNT(*) FROM contratos WHERE adjudicante_nif != '' AND adjudicante_nif IS NOT NULL"
        ).fetchone()[0],
        "with_price": conn.execute(
            "SELECT COUNT(*) FROM contratos WHERE precoContratual > 0"
        ).fetchone()[0],
    }


def query_by_year(conn: sqlite3.Connection) -> list:
    rows = conn.execute("""
        SELECT Ano as year,
               COUNT(*) as contracts,
               SUM(precoContratual) as value,
               COUNT(DISTINCT adjudicante_nif) as buyers
        FROM contratos
        WHERE Ano IS NOT NULL
        GROUP BY Ano
        ORDER BY Ano
    """).fetchall()
    return [dict(r) for r in rows]


def query_by_procedure(conn: sqlite3.Connection) -> list:
    rows = conn.execute("""
        SELECT tipoprocedimento as procedure,
               COUNT(*) as contracts,
               SUM(precoContratual) as value
        FROM contratos
        WHERE tipoprocedimento IS NOT NULL
          AND tipoprocedimento != ''
          AND precoContratual > 0
        GROUP BY tipoprocedimento
        ORDER BY contracts DESC
        LIMIT 10
    """).fetchall()
    return [dict(r) for r in rows]


def query_direct_awards(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] or 1
    direct = conn.execute(
        "SELECT COUNT(*) FROM contratos WHERE tipoprocedimento LIKE '%ajuste direto%'"
    ).fetchone()[0]
    return {
        "count": direct,
        "total": total,
        "pct": round((direct / total) * 100, 1) if total else 0,
    }


def query_price_inflation(conn: sqlite3.Connection) -> dict:
    """Contracts where final price > base price * 1.05 (5% overrun)."""
    with_base = conn.execute(
        "SELECT COUNT(*) FROM contratos WHERE precoBaseProcedimento > 0"
    ).fetchone()[0]
    inflated = conn.execute("""
        SELECT COUNT(*) FROM contratos
        WHERE precoBaseProcedimento > 0
          AND precoContratual > precoBaseProcedimento * 1.05
    """).fetchone()[0]
    severely_inflated = conn.execute("""
        SELECT COUNT(*) FROM contratos
        WHERE precoBaseProcedimento > 0
          AND precoContratual > precoBaseProcedimento * 1.20
    """).fetchone()[0]
    return {
        "count": inflated,
        "severe_count": severely_inflated,
        "with_base_price": with_base,
        "pct": round((inflated / with_base) * 100, 1) if with_base else 0,
    }


def query_self_referencing(conn: sqlite3.Connection) -> dict:
    """Buyer NIF appears in the seller list of the same contract.

    Sampled to 100k rows to stay fast on the 1.9GB DB.
    """
    sr = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT idcontrato, adjudicante_nif, adjudicatarios
            FROM contratos
            WHERE adjudicante_nif IS NOT NULL
              AND adjudicante_nif != ''
              AND adjudicatarios IS NOT NULL
              AND adjudicatarios != ''
            LIMIT 100000
        ) sub
        WHERE adjudicatarios LIKE '%' || adjudicante_nif || '%'
    """).fetchone()[0]
    return {"count": sr, "sample_size": 100000}


def query_top_buyers(conn: sqlite3.Connection) -> list:
    rows = conn.execute("""
        SELECT adjudicante_nif as nif,
               adjudicante_nome as name,
               COUNT(*) as contracts,
               SUM(precoContratual) as value
        FROM contratos
        WHERE adjudicante_nif IS NOT NULL
          AND adjudicante_nif != ''
          AND precoContratual > 0
        GROUP BY adjudicante_nif
        ORDER BY value DESC
        LIMIT 15
    """).fetchall()
    return [dict(r) for r in rows]


def _stream_sellers(conn: sqlite3.Connection):
    """Generator that yields (adjudicatarios_str, value) tuples from
    the contratos table in 50k-row batches.

    The two top_sellers query functions consume this to avoid duplicate
    full-table scans.
    """
    BATCH = 50_000
    offset = 0
    while True:
        rows = conn.execute(f"""
            SELECT adjudicatarios, precoContratual
            FROM contratos
            WHERE adjudicatarios IS NOT NULL
              AND adjudicatarios != ''
              AND precoContratual > 0
            LIMIT {BATCH} OFFSET {offset}
        """).fetchall()
        if not rows:
            return
        for r in rows:
            yield r["adjudicatarios"], r["precoContratual"] or 0
        offset += BATCH


def query_top_sellers(conn: sqlite3.Connection) -> list:
    """Top sellers by NIF — parsed, deduped, with cumulative value/contracts.

    Streams via `_stream_sellers` and keeps only the top-K candidates in
    memory via a min-heap. Peak memory is O(K) regardless of unique
    seller count. See _PROCUREMENT_CACHE_FIELDS for why this lives in
    its own file (not merged with top_sellers_hint).
    """
    KEEP = 200
    top_heap: list = []  # [value, nif, name, contracts]
    heap_ready = False

    def _consider(nif: str, name: str, value: float):
        nonlocal heap_ready
        if not nif:
            return
        for entry in top_heap:
            if entry[1] == nif:
                entry[0] += value
                entry[3] += 1
                if len(name) > len(entry[2]):
                    entry[2] = name
                if heap_ready:
                    heapq.heapify(top_heap)
                return
        entry = [value, nif, name, 1]
        if len(top_heap) < KEEP:
            top_heap.append(entry)
            if len(top_heap) == KEEP:
                heapq.heapify(top_heap)
                heap_ready = True
        else:
            heapq.heappushpop(top_heap, entry)

    for adjudicatarios_str, value in _stream_sellers(conn):
        for chunk in adjudicatarios_str.split(";"):
            chunk = chunk.strip()
            if not chunk or "-" not in chunk:
                continue
            nif, _, name = chunk.partition("-")
            _consider(nif.strip(), name.strip(), value)

    top_heap.sort(key=lambda x: -x[0])
    return [
        {"nif": nif, "name": name or "", "contracts": contracts, "value": value}
        for value, nif, name, contracts in top_heap[:20]
    ]


def query_top_sellers_hint(conn: sqlite3.Connection) -> list:
    """Top sellers — raw grouped by adjudicatarios string (same shape as
    the original handle_procurement field for drop-in compat).

    Uses a bounded min-heap (KEEP=200) to avoid OOM on the 1.9GB table:
    building a dict of every unique adjudicatarios string would consume
    1-2GB RAM and crash the cache build subprocess.
    """
    KEEP = 200
    # heap entries: [value, adjudicatarios_str, cnt]
    top_heap: list = []
    heap_ready = False

    def _consider(adjudicatarios_str: str, value: float):
        nonlocal heap_ready
        for entry in top_heap:
            if entry[1] == adjudicatarios_str:
                entry[0] += value
                entry[2] += 1
                if heap_ready:
                    heapq.heapify(top_heap)
                return
        entry = [value, adjudicatarios_str, 1]
        if len(top_heap) < KEEP:
            top_heap.append(entry)
            if len(top_heap) == KEEP:
                heapq.heapify(top_heap)
                heap_ready = True
        else:
            heapq.heappushpop(top_heap, entry)

    for adjudicatarios_str, value in _stream_sellers(conn):
        _consider(adjudicatarios_str, value)

    top_heap.sort(key=lambda x: -x[0])
    return [
        {"adjudicatarios": s, "cnt": cnt, "value": value}
        for value, s, cnt in top_heap[:10]
    ]


def query_by_municipality(conn: sqlite3.Connection) -> list:
    """Top municipalities by contract value. Only meaningful if the
    ine_municipality column has been resolved by freguesia_resolver.py.

    Returns [] when the column doesn't exist, matching the live handler's
    response shape (the cache is a drop-in replacement).
    """
    try:
        conn.execute("SELECT ine_municipality FROM contratos LIMIT 1")
    except sqlite3.OperationalError:
        return []

    rows = conn.execute("""
        SELECT ine_municipality as municipality,
               COUNT(*) as contracts,
               SUM(precoContratual) as value
        FROM contratos
        WHERE ine_municipality IS NOT NULL
          AND ine_municipality != ''
          AND precoContratual > 0
        GROUP BY ine_municipality
        ORDER BY value DESC
        LIMIT 20
    """).fetchall()
    return [dict(r) for r in rows]


def query_by_cpv(conn: sqlite3.Connection) -> list:
    """Top CPV codes (procurement categories) — truncated to 4 digits for grouping."""
    rows = conn.execute("""
        SELECT SUBSTR(CPV, 1, 4) as cpv_code,
               COUNT(*) as contracts,
               SUM(precoContratual) as value
        FROM contratos
        WHERE CPV IS NOT NULL
          AND CPV != ''
          AND LENGTH(CPV) >= 4
          AND precoContratual > 0
        GROUP BY cpv_code
        ORDER BY value DESC
        LIMIT 20
    """).fetchall()
    return [dict(r) for r in rows]


def query_monthly_trend(conn: sqlite3.Connection) -> list:
    """Contracts per month for the last 3 years — for the timeline chart."""
    rows = conn.execute("""
        SELECT SUBSTR(dataPublicacao, 1, 7) as month,
               COUNT(*) as contracts,
               SUM(precoContratual) as value
        FROM contratos
        WHERE dataPublicacao IS NOT NULL
          AND dataPublicacao != ''
          AND dataPublicacao >= '2023'
          AND precoContratual > 0
        GROUP BY month
        ORDER BY month
    """).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

QUERIES = [
    ("stats",            query_stats,            False),
    ("by_year",          query_by_year,          False),
    ("by_procedure",     query_by_procedure,     False),
    ("direct_awards",    query_direct_awards,    False),
    ("price_inflation",  query_price_inflation,  False),
    ("self_referencing", query_self_referencing, True),  # slow — sampled
    ("top_buyers",       query_top_buyers,       True),  # slow — full table scan
    ("top_sellers",      query_top_sellers,      True),  # slow — NIF aggregation
    ("top_sellers_hint", query_top_sellers_hint, True),  # slow — raw grouping
    ("by_municipality",  query_by_municipality,  True),  # slow — only if resolved
    ("by_cpv",           query_by_cpv,           True),  # slow — full scan
    ("monthly_trend",    query_monthly_trend,    True),  # slow — recent only
]


def build_one(conn: sqlite3.Connection, name: str, fn, slow: bool, force: bool = False) -> float:
    """Build a single cache file. Returns elapsed time.

    Uses atomic write: write to .tmp, then os.replace() to swap.
    """
    cache_file = _cache_path(name)
    if _is_fresh(cache_file) and not force:
        return 0.0
    t0 = time.time()
    result = fn(conn)
    elapsed = time.time() - t0

    # Atomic write: temp file + os.replace() so a reader never sees
    # a half-written file if the API server is serving the cache in parallel.
    tmp_file = cache_file.with_suffix(".json.tmp")
    tmp_file.write_text(
        json.dumps(result, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    os.replace(tmp_file, cache_file)
    return elapsed


def cmd_build(args):
    force = args.force

    if not DB_PATH.exists():
        print(f"  ERROR: {DB_PATH} not found.")
        print(f"  Run 'python procurement_db.py build' first.")
        return

    db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\n  Building procurement cache from {db_size_mb:.0f} MB database\n")
    print(f"  Cache dir: {CACHE_DIR}\n")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Read-only connection — we never write to procurement.db
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # 256MB page cache for the big DB
    conn.execute("PRAGMA cache_size=-256000")
    conn.execute("PRAGMA temp_store=MEMORY")

    total_t0 = time.time()
    total_bytes = 0

    for i, (name, fn, slow) in enumerate(QUERIES, 1):
        tag = "[slow]" if slow else "      "
        sys.stdout.write(f"  [{i:>2}/{len(QUERIES)}] {tag} {name:<22} ")
        sys.stdout.flush()
        try:
            elapsed = build_one(conn, name, fn, slow, force=force)
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        cache_file = _cache_path(name)
        if cache_file.exists():
            size_kb = cache_file.stat().st_size / 1024
            total_bytes += cache_file.stat().st_size
            if elapsed > 0:
                print(f"done ({elapsed:.2f}s, {size_kb:>6.1f} KB)")
            else:
                print(f"cached ({size_kb:>6.1f} KB)")

    conn.close()

    # Write metadata last so other tools can check freshness
    _write_meta()

    total_elapsed = time.time() - total_t0
    print(f"\n  Total: {total_elapsed:.1f}s, {total_bytes/1024:.0f} KB cached")
    print(f"  Cache files in: {CACHE_DIR}\n")


def cmd_status(args):
    if not DB_PATH.exists():
        print(f"  procurement.db: NOT FOUND")
        return

    db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    db_mtime = datetime.fromtimestamp(DB_PATH.stat().st_mtime)

    print(f"\n  procurement.db  {db_size_mb:.0f} MB  built {db_mtime:%Y-%m-%d %H:%M}")
    print(f"  Cache dir:      {CACHE_DIR}\n")

    if not CACHE_DIR.exists():
        print(f"  No cache files. Run 'python procurement_cache.py build'.")
        return

    meta_path = _meta_path()
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            built_at = meta.get("built_at", "?")
            print(f"  Cache built:    {built_at}  (version {meta.get('version')})")
        except Exception:
            pass

    print(f"\n  {'Cache file':<25}{'Size':>10}{'Status':>14}{'Built':>22}")
    print(f"  {'─'*25}{'─'*10}{'─'*14}{'─'*22}")

    for name, fn, slow in QUERIES:
        cache_file = _cache_path(name)
        if not cache_file.exists():
            print(f"  {name:<25}{'?':>10}{'MISS':>14}{'':>22}")
        else:
            size_kb = cache_file.stat().st_size / 1024
            fresh = "FRESH" if _is_fresh(cache_file) else "STALE"
            built = datetime.fromtimestamp(cache_file.stat().st_mtime)
            print(f"  {name:<25}{size_kb:>8.1f}KB{fresh:>14}{built:%Y-%m-%d %H:%M:%S}")


def cmd_clean(args):
    if not CACHE_DIR.exists():
        print(f"  No cache dir to clean.")
        return
    n = 0
    for f in CACHE_DIR.glob("*.json"):
        f.unlink()
        n += 1
    print(f"  Removed {n} cache file(s) from {CACHE_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Pre-compute procurement.db queries as JSON cache files.",
    )
    sub = parser.add_subparsers(dest="command")

    build_p = sub.add_parser("build", help="Build all cache files")
    build_p.add_argument("--force", action="store_true",
                         help="Force rebuild even if cache is fresh")

    sub.add_parser("status", help="Show cache status")
    sub.add_parser("clean", help="Delete all cache files")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {"build": cmd_build, "status": cmd_status, "clean": cmd_clean}
    cmds[args.command](args)


if __name__ == "__main__":
    main()
