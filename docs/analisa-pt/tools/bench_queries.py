#!/usr/bin/env python3
"""Benchmark harness for the analisa-pt hot query patterns.

Runs the 3 patterns documented in QUERY_PERFORMANCE.md so we can
quantify the speedup from each optimization. Designed for before/after
comparison::

    # 1. Capture baseline
    python bench_queries.py --out before.json

    # 2. Make your change (add a column, swap a parser, etc.)

    # 3. Capture the new state
    python bench_queries.py --out after.json

    # 4. Diff
    python bench_queries.py --compare before.json after.json  Patterns timed (matching QUERY_PERFORMANCE.md "Hot Query Baseline"):

  Q1 - per-buyer aggregate
       SELECT adjudicante_nif, COUNT(*), SUM(precoContratual) ...
       GROUP BY adjudicante_nif  on ``procurement.db.contratos``.

  Q2 - crossref regex scan (the pre-Tier 1 pattern)
       Full scan of 1.6 M contratos + Python regex on each
       ``adjudicatarios`` text to extract the first supplier NIF.
       This simulates the OLD pattern even after the
       ``adjudicatario_nif`` column was added, so we can measure
       the speedup a future column/index would yield.

  Q3 - PRR entities streaming parse (openpyxl)
       Parses the largest ``prr_entities_*.xlsx`` file the same way
       ``transparency_scraper._stream_prr_entities`` does (openpyxl
       ``read_only=True``). openpyxl is pure-Python XML parsing;
       a swap to polars/duckdb is the obvious follow-up.

Methodology (per QUERY_PERFORMANCE.md "How to re-measure"):

  - Triple-warm the cache before timing (200 MB cache + page faults
    take 5-10 s on a cold DB; first run is artificially slow)
  - Run each query N times (default 10), report min/median/max/stdev
  - Capture EXPLAIN QUERY PLAN alongside the timing
  - Note DB size, platform, and ``utils_db.PRAGMAS`` in the output
    so before/after JSONs are comparable

Usage:
  python bench_queries.py                       # run all 3 queries, n=10
  python bench_queries.py --query q1            # run a single query
  python bench_queries.py --query q3 --n 3      # Q3 is slow - fewer runs
  python bench_queries.py --out before.json     # write results to JSON
  python bench_queries.py --compare a.json b.json  # diff two result files
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from utils_db import connect, PRAGMAS  # noqa: E402

PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
TRANSPARENCY_DB = SCRIPT_DIR / "data" / "transparency.db"
DATA_DIR = SCRIPT_DIR / "data"

# Same regex as add_adjudicatario_nif.py: extract the first 9-digit NIF.
NIF_RE = re.compile(r"(\d{9})")


# ---------------------------------------------------------------------------
# Query definitions
# ---------------------------------------------------------------------------

def _time_callable(fn, n: int) -> tuple[list[float], int, float]:
    """Time ``fn()`` N times. Returns (sorted_times_ms, row_count, warmup_total_ms).

    Runs ``fn`` 3 times before timing to warm caches. The total
    warmup time is returned separately so callers can surface it in
    the result (a 30 s warmup on a cold DB is a useful signal).
    """
    warmup_total_ms = 0.0
    warmup_row_count = 0
    for _ in range(3):
        t0 = time.time()
        warmup_row_count = fn()
        warmup_total_ms += (time.time() - t0) * 1000
    times = []
    row_count = warmup_row_count
    for _ in range(n):
        t0 = time.time()
        row_count = fn()
        times.append((time.time() - t0) * 1000)
    times.sort()
    return times, row_count, warmup_total_ms


def _explain(conn, sql: str) -> str:
    """Extract the index used from EXPLAIN QUERY PLAN output."""
    plan = conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
    return plan[0][3] if plan else "unknown"


def _stats(name: str, description: str, times: list[float], row_count: int,
           index_used: str, warmup_total_ms: float = 0.0) -> dict:
    """Build the standard result dict for a query."""
    return {
        "name": name,
        "description": description,
        "rows": row_count,
        "n_runs": len(times),
        "min_ms": round(times[0], 1),
        "median_ms": round(times[len(times) // 2], 1),
        "max_ms": round(times[-1], 1),
        "stdev_ms": round(statistics.stdev(times), 1) if len(times) > 1 else 0.0,
        "warmup_total_ms": round(warmup_total_ms, 1),
        "index_used": index_used,
    }


def q1_per_buyer_aggregate(conn, n: int = 10) -> dict:
    """Q1 - per-buyer aggregate over ``contratos``.

    The hot path in ``anomaly_scanner.detect_supplier_dominance``,
    ``detect_closed_ecosystem``, and every other per-buyer detector.
    Should use ``idx_contratos_buyer_value`` (COVERING) post-Tier 1.
    """
    sql = (
        "SELECT adjudicante_nif, COUNT(*), SUM(precoContratual) "
        "FROM contratos "
        "WHERE adjudicante_nif IS NOT NULL AND precoContratual > 0 "
        "GROUP BY adjudicante_nif"
    )
    def run():
        rows = conn.execute(sql).fetchall()
        return len(rows)
    times, row_count, warmup = _time_callable(run, n)
    return _stats(
        name="Q1 per-buyer aggregate",
        description="9,794 buyers grouped with contract counts and total value",
        times=times,
        row_count=row_count,
        index_used=_explain(conn, sql),
        warmup_total_ms=warmup,
    )


def q2_crossref_regex_scan(conn, n: int = 10) -> dict:
    """Q2 - crossref regex scan (the pre-Tier 1 pattern).

    Simulates the OLD pattern that took 3+ min: full scan of 1.6 M
    contratos + Python regex on each ``adjudicatarios`` text to
    extract supplier NIFs. We keep this benchmark even though the
    ``adjudicatario_nif`` column replaced it, so future
    "I just added a column, how much did it help?" scenarios can
    measure the speedup.
    """
    def run():
        nif_counts: dict[str, int] = {}
        rows = conn.execute(
            "SELECT adjudicatarios FROM contratos "
            "WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''"
        )
        for r in rows:
            for nif in NIF_RE.findall(r[0]):
                nif_counts[nif] = nif_counts.get(nif, 0) + 1
        return len(nif_counts)
    times, row_count, warmup = _time_callable(run, n)
    return _stats(
        name="Q2 crossref regex scan (pre-Tier 1 pattern)",
        description="1.6 M rows scanned, Python regex extracts supplier NIFs per row",
        times=times,
        row_count=row_count,
        index_used="none (full table scan + Python regex)",
        warmup_total_ms=warmup,
    )


def q3_prr_streaming(n: int = 3) -> dict:
    """Q3 - PRR entities streaming parse via openpyxl.

    Parses the largest ``prr_entities_*.xlsx`` file the same way
    ``transparency_scraper._stream_prr_entities`` does. openpyxl is
    pure-Python XML parsing; a swap to ``polars.read_excel`` or
    ``duckdb.read_xlsx`` is the obvious follow-up.

    Defaults to ``n=3`` because each parse takes ~30 s for a 307 K-row
    file. Override with ``--n`` for a tighter confidence interval.
    """
    try:
        import openpyxl
    except ImportError:
        return {
            "name": "Q3 PRR entities streaming (openpyxl)",
            "error": "openpyxl not installed; pip install openpyxl",
        }

    xlsx_files = sorted(DATA_DIR.glob("prr_entities_*.xlsx"))
    if not xlsx_files:
        return {
            "name": "Q3 PRR entities streaming (openpyxl)",
            "error": "no prr_entities_*.xlsx files in data/",
        }
    xlsx_path = max(xlsx_files, key=lambda p: p.stat().st_size)
    file_size_mb = xlsx_path.stat().st_size / (1024 * 1024)

    def run():
        wb = openpyxl.load_workbook(str(xlsx_path), read_only=True)
        try:
            ws = wb.active
            rows = 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0]:
                    rows += 1
        finally:
            wb.close()
        return rows

    times, row_count, warmup = _time_callable(run, n)
    return _stats(
        name="Q3 PRR entities streaming (openpyxl)",
        description=f"Parse {xlsx_path.name} ({file_size_mb:.0f} MB) via openpyxl read_only=True",
        times=times,
        row_count=row_count,
        index_used="n/a (xlsx parsing, not SQL)",
        warmup_total_ms=warmup,
    )


# ---------------------------------------------------------------------------
# Runner + output
# ---------------------------------------------------------------------------

QUERIES = {
    "q1": q1_per_buyer_aggregate,
    "q2": q2_crossref_regex_scan,
    "q3": q3_prr_streaming,
}


def run_queries(n: int, only: list[str] | None) -> dict:
    """Run the requested queries and return the result dict."""
    if not PROCUREMENT_DB.exists():
        print(f"ERROR: {PROCUREMENT_DB} not found", file=sys.stderr)
        sys.exit(1)
    conn = connect(str(PROCUREMENT_DB))
    try:
        target = only if only else list(QUERIES.keys())
        results: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "db_path": str(PROCUREMENT_DB),
            "db_size_mb": round(PROCUREMENT_DB.stat().st_size / (1024 * 1024), 1),
            "pragma_tuning": list(PRAGMAS),
            "n_runs": n,
            "queries": {},
        }
        for q in target:
            fn = QUERIES.get(q)
            if fn is None:
                print(f"  unknown query: {q} (available: {list(QUERIES)})", file=sys.stderr)
                continue
            # Q3 has its own per-query n default; respect --n override otherwise
            kwargs = {"n": n} if q != "q3" else {"n": max(3, n // 3)}
            results["queries"][q] = fn(conn, **kwargs) if q in ("q1", "q2") else fn(**kwargs)
        return results
    finally:
        conn.close()


def print_summary(results: dict) -> None:
    """Print a clean summary table (ASCII-only for Windows console compat)."""
    print(f"\n{'=' * 110}")
    print(f"  BENCHMARK RESULTS - {results['timestamp']}")
    print(f"  Platform: {results['platform']}  |  Python: {results['python']}")
    print(f"  DB: {results['db_size_mb']:.0f} MB  |  PRAGMAs: {results['pragma_tuning']}")
    print(f"  Runs per query: {results['n_runs']}")
    print(f"{'=' * 110}\n")

    header = f"  {'Query':<38} {'Rows':>10}  {'Min':>8}  {'Median':>8}  {'Max':>8}  {'Stdev':>8}"
    print(header)
    print(f"  {'-' * 38} {'-' * 10}  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 8}")
    for q, r in results["queries"].items():
        if "error" in r:
            print(f"  {r['name']:<38} ERROR: {r['error']}")
            continue
        print(
            f"  {r['name']:<38} {r['rows']:>10,}  "
            f"{r['min_ms']:>6.1f}ms  {r['median_ms']:>6.1f}ms  "
            f"{r['max_ms']:>6.1f}ms  {r['stdev_ms']:>6.1f}ms"
        )
    print()
    print("  Index / method used:")
    for q, r in results["queries"].items():
        if "index_used" in r:
            print(f"    {q}: {r['index_used']}")
    print()


def compare_results(before_path: str, after_path: str, strict: bool = False) -> int:
    """Diff two result JSONs and print the speedup per query.

    Returns the exit code: 0 if all queries are within tolerance
    (or improved), 1 if any query regressed by more than 5 % (or
    ``--strict``'s 0 % threshold). Use this in CI to catch slowdowns.
    """
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    print(f"\n{'=' * 110}")
    print(f"  COMPARISON")
    print(f"  Before: {before_path}  ({before['timestamp']}, {before['db_size_mb']:.0f} MB)")
    print(f"  After:  {after_path}   ({after['timestamp']}, {after['db_size_mb']:.0f} MB)")
    if before["pragma_tuning"] != after["pragma_tuning"]:
        print(f"  WARNING: PRAGMAs differ - {before['pragma_tuning']} -> {after['pragma_tuning']}")
    print(f"{'=' * 110}\n")
    print(f"  {'Query':<38} {'Before':>12}  {'After':>12}  {'Speedup':>10}  {'Diff rows':>10}")
    print(f"  {'-' * 38} {'-' * 12}  {'-' * 12}  {'-' * 10}  {'-' * 10}")
    regressions = 0
    tolerance = 0.0 if strict else 0.05  # 5 % default, 0 % with --strict
    for q in before["queries"]:
        if q not in after["queries"]:
            continue
        b = before["queries"][q]
        a = after["queries"][q]
        if "error" in b or "error" in a:
            label = b.get("name") or a.get("name") or q
            err = (b.get("error") or a.get("error") or "")
            print(f"  {label:<38} (error in one or both): {err}")
            continue
        # Speedup ratio: < 1.0 means regression, > 1.0 means speedup
        if a["median_ms"] == 0 and b["median_ms"] == 0:
            speedup = 1.0
        elif a["median_ms"] == 0:
            speedup = float("inf")
        else:
            speedup = b["median_ms"] / a["median_ms"]
        delta_rows = a["rows"] - b["rows"]
        print(
            f"  {b['name']:<38} {b['median_ms']:>8.1f}ms  {a['median_ms']:>8.1f}ms  "
            f"{speedup:>8.2f}x  {delta_rows:>+10,}"
        )
        if speedup < 1.0 - tolerance and delta_rows >= 0:
            regressions += 1
    print()
    if regressions:
        print(f"  [FAIL] {regressions} regression(s) detected "
              f"(tolerance: {tolerance:.0%}). CI should fail.")
        return 1
    print(f"  [PASS] No regressions (tolerance: {tolerance:.0%})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark harness for the analisa-pt hot queries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--query", "-q",
        choices=list(QUERIES.keys()),
        help="Run a single query (default: run all 3)",
    )
    parser.add_argument(
        "--n", type=int, default=10,
        help="Number of runs per query (default 10). Q3 caps at n//3 since each parse is ~30 s.",
    )
    parser.add_argument(
        "--out",
        help="Write results to a JSON file for later --compare",
    )
    parser.add_argument(
        "--compare", nargs=2, metavar=("BEFORE", "AFTER"),
        help="Diff two JSON result files and print the speedup per query. "
             "Pass --strict before this flag to enable strict mode.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="With --compare, exit 1 on ANY regression (not just >5%%). "
             "Must be placed before --compare due to argparse nargs=2.",
    )
    args = parser.parse_args()

    if args.compare:
        sys.exit(compare_results(args.compare[0], args.compare[1], strict=args.strict))

    results = run_queries(n=args.n, only=[args.query] if args.query else None)
    print_summary(results)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))
        print(f"  Results written to {args.out}\n")


if __name__ == "__main__":
    main()
