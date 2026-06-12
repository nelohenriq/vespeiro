#!/usr/bin/env python3
"""
Lightweight HTTP API server for the Analisa.pt unified dashboard.

Queries all 6 SQLite databases on-demand and serves JSON endpoints.
Zero external dependencies — uses only Python stdlib (http.server, json, sqlite3).

Usage:
    python api_server.py                     # Start on port 8080
    python api_server.py --port 9000         # Custom port
    python api_server.py --cors-origin "*"   # Custom CORS origin
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs
from utils_db import connect as db_connect

# Top-level import (procurement_cache.py doesn't import api_server, so
# no circular risk). Used by the live handler to compute top_sellers
# (parsed NIF aggregation) so the cache and live paths return identical
# response shapes.
try:
    from procurement_cache import query_top_sellers as _query_top_sellers
except ImportError:
    _query_top_sellers = None

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"

# ── Database paths ──────────────────────────────────────────────────────────

DB_PATHS = {
    "justice": DATA_DIR / "justice.db",
    "ine": DATA_DIR / "ine_stats.db",
    "procurement": DATA_DIR / "procurement.db",
    "transparency": DATA_DIR / "transparency.db",
    "anuncios": DATA_DIR / "anuncios_index.db",
    "modificacoes": DATA_DIR / "modificacoes_index.db",
}


# ── Procurement cache layer ────────────────────────────────────────────────
#
# Reads pre-computed JSON files produced by procurement_cache.py.
# Cache is keyed by DB mtime: stale files (older than procurement.db) are
# ignored and the live query is used as fallback.
# ───────────────────────────────────────────────────────────────────────────

_PROCUREMENT_CACHE_LOCK = threading.Lock()
_CACHE_REBUILD_RUNNING = False


def _read_cache_json(name: str) -> Optional[Any]:
    """Read a cache file if it exists and is fresher than procurement.db.

    Returns None if the cache file is missing, stale, or unreadable
    (e.g. a truncated file from an interrupted atomic write).
    """
    cache_file = CACHE_DIR / f"{name}.json"
    if not cache_file.exists():
        return None
    proc_db = DB_PATHS["procurement"]
    if proc_db.exists() and cache_file.stat().st_mtime < proc_db.stat().st_mtime:
        return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _cache_status() -> dict:
    """Status of all cache files (used by /api/cache/status)."""
    proc_db = DB_PATHS["procurement"]
    result: Dict[str, Any] = {
        "cache_dir": str(CACHE_DIR),
        "db_exists": proc_db.exists(),
        "db_size_mb": round(proc_db.stat().st_size / (1024 * 1024), 1) if proc_db.exists() else 0,
        "db_mtime": datetime.fromtimestamp(proc_db.stat().st_mtime).isoformat() if proc_db.exists() else None,
        "files": {},
    }
    if not CACHE_DIR.exists():
        result["note"] = "Cache dir not found. Run: python procurement_cache.py build"
        return result

    meta_path = CACHE_DIR / "_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            result["built_at"] = meta.get("built_at")
            result["version"] = meta.get("version")
        except Exception:
            pass

    for f in sorted(CACHE_DIR.glob("*.json")):
        if f.name == "_meta.json":
            continue
        size_kb = f.stat().st_size / 1024
        fresh = (
            proc_db.exists()
            and f.stat().st_mtime >= proc_db.stat().st_mtime
        )
        result["files"][f.stem] = {
            "size_kb": round(size_kb, 1),
            "fresh": fresh,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }

    n_fresh = sum(1 for f in result["files"].values() if f["fresh"])
    n_total = len(result["files"])
    result["summary"] = {
        "fresh": n_fresh,
        "stale_or_missing": n_total - n_fresh,
        "total": n_total,
        "all_fresh": n_fresh == n_total and n_total > 0,
    }
    return result


def _trigger_cache_rebuild(force: bool = False) -> dict:
    """Spawn the cache rebuild in a background thread.

    Returns immediately with a status dict. The endpoint can poll
    /api/cache/status to track progress.
    """
    global _CACHE_REBUILD_RUNNING
    with _PROCUREMENT_CACHE_LOCK:
        if _CACHE_REBUILD_RUNNING:
            return {"started": False, "reason": "already_running"}
        _CACHE_REBUILD_RUNNING = True

    cache_script = SCRIPT_DIR / "procurement_cache.py"
    if not cache_script.exists():
        _CACHE_REBUILD_RUNNING = False
        return {"started": False, "reason": "script_not_found"}

    def _run():
        global _CACHE_REBUILD_RUNNING
        try:
            cmd = [sys.executable, str(cache_script), "build"]
            if force:
                cmd.append("--force")
            subprocess.run(cmd, cwd=str(SCRIPT_DIR), check=False)
        finally:
            _CACHE_REBUILD_RUNNING = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"started": True, "force": force, "running": True}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_db(name: str) -> Optional[sqlite3.Connection]:
    """Open a database connection if the file exists."""
    path = DB_PATHS.get(name)
    if not path or not path.exists():
        return None
    timeout = 60 if name == "procurement" else 10
    conn = db_connect(str(path), timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row else {}


def _rows_to_list(rows: list) -> list:
    return [dict(r) for r in rows]


def _safe_query(conn: Optional[sqlite3.Connection], sql: str, params: tuple = ()) -> List[dict]:
    """Run a query safely, returning empty list on error."""
    if not conn:
        return []
    try:
        return _rows_to_list(conn.execute(sql, params).fetchall())
    except Exception:
        return []


def _safe_scalar(conn: Optional[sqlite3.Connection], sql: str, params: tuple = (), default=None):
    """Run a query safely, returning a single scalar value."""
    if not conn:
        return default
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else default
    except Exception:
        return default


# ── Endpoint handlers ───────────────────────────────────────────────────────

def handle_overview() -> dict:
    """Summary metrics across all databases."""
    result: Dict[str, Any] = {"generated_at": datetime.now().isoformat(), "databases": {}}

    # Database status
    for name, path in DB_PATHS.items():
        if path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)
            result["databases"][name] = {"exists": True, "size_mb": round(size_mb, 1)}
        else:
            result["databases"][name] = {"exists": False, "size_mb": 0}

    # Justice summary
    jconn = _get_db("justice")
    if jconn:
        result["justice"] = {
            "corruption_years": _safe_scalar(jconn, "SELECT COUNT(DISTINCT year) FROM corruption_cases WHERE dataset='corrupcaopj'"),
            "corruption_latest": _safe_scalar(jconn, "SELECT value FROM corruption_cases WHERE dataset='corrupcaopj' ORDER BY year DESC LIMIT 1"),
            "corruption_latest_year": _safe_scalar(jconn, "SELECT year FROM corruption_cases WHERE dataset='corrupcaopj' ORDER BY year DESC LIMIT 1"),
            "ml_latest": _safe_scalar(jconn, "SELECT value FROM corruption_cases WHERE dataset='branqueamentopj' ORDER BY year DESC LIMIT 1"),
            "ml_latest_year": _safe_scalar(jconn, "SELECT year FROM corruption_cases WHERE dataset='branqueamentopj' ORDER BY year DESC LIMIT 1"),
            "court_pending": _safe_scalar(jconn, "SELECT pending FROM court_movements ORDER BY year DESC LIMIT 1"),
            "court_pending_year": _safe_scalar(jconn, "SELECT year FROM court_movements ORDER BY year DESC LIMIT 1"),
            "prison_population": _safe_scalar(jconn, "SELECT count FROM prison_population ORDER BY year DESC LIMIT 1"),
            "prison_year": _safe_scalar(jconn, "SELECT year FROM prison_population ORDER BY year DESC LIMIT 1"),
        }
        jconn.close()

    # INE summary
    iconn = _get_db("ine")
    if iconn:
        result["ine"] = {
            "pensionistas": _safe_scalar(iconn, "SELECT value FROM ine_observations WHERE indicator_code='0004325' AND geographic_name='Portugal' ORDER BY year DESC LIMIT 1"),
            "pensionistas_year": _safe_scalar(iconn, "SELECT year FROM ine_observations WHERE indicator_code='0004325' AND geographic_name='Portugal' ORDER BY year DESC LIMIT 1"),
            "foreign_residents": _safe_scalar(iconn, "SELECT SUM(value) FROM ine_observations WHERE indicator_code='0001236' AND year=(SELECT MAX(year) FROM ine_observations WHERE indicator_code='0001236')"),
            "foreign_year": _safe_scalar(iconn, "SELECT MAX(year) FROM ine_observations WHERE indicator_code='0001236'"),
            "crime_rate": _safe_scalar(iconn, "SELECT AVG(value) FROM ine_observations WHERE indicator_code='0008074' AND year=(SELECT MAX(year) FROM ine_observations WHERE indicator_code='0008074')"),
            "crime_year": _safe_scalar(iconn, "SELECT MAX(year) FROM ine_observations WHERE indicator_code='0008074'"),
            "natural_growth": _safe_scalar(iconn, "SELECT value FROM ine_observations WHERE indicator_code='0008263' AND geographic_name='Portugal' ORDER BY year DESC LIMIT 1"),
            "natural_growth_year": _safe_scalar(iconn, "SELECT year FROM ine_observations WHERE indicator_code='0008263' AND geographic_name='Portugal' ORDER BY year DESC LIMIT 1"),
        }
        iconn.close()

    # Procurement summary — prefer the pre-computed cache
    cached_stats = _read_cache_json("stats")
    if cached_stats:
        result["procurement"] = {
            "total_contracts": cached_stats.get("total"),
            "years_available": (cached_stats.get("year_max") or 0) - (cached_stats.get("year_min") or 0) + 1,
            "year_min": cached_stats.get("year_min"),
            "year_max": cached_stats.get("year_max"),
            "total_value": cached_stats.get("total_value"),
        }
    else:
        pconn = _get_db("procurement")
        if pconn:
            try:
                result["procurement"] = {
                    "total_contracts": _safe_scalar(pconn, "SELECT COUNT(*) FROM contratos"),
                    "years_available": _safe_scalar(pconn, "SELECT COUNT(DISTINCT Ano) FROM contratos WHERE Ano IS NOT NULL"),
                    "year_min": _safe_scalar(pconn, "SELECT MIN(Ano) FROM contratos WHERE Ano IS NOT NULL"),
                    "year_max": _safe_scalar(pconn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL"),
                    "total_value": _safe_scalar(pconn, "SELECT SUM(precoContratual) FROM contratos WHERE precoContratual > 0"),
                }
            except Exception:
                result["procurement"] = {"error": "query failed"}
            finally:
                try: pconn.close()
                except Exception: pass

    return result


def handle_justice() -> dict:
    """Full justice data: corruption trends, courts, prison."""
    result: Dict[str, Any] = {}
    conn = _get_db("justice")
    if not conn:
        return {"error": "justice.db not found"}

    # Corruption + Money Laundering trends (joined by year)
    result["corruption_trend"] = _safe_query(conn, """
        SELECT c.year,
               c.value as corruption,
               m.value as money_laundering
        FROM corruption_cases c
        LEFT JOIN corruption_cases m ON c.year = m.year AND m.dataset = 'branqueamentopj'
        WHERE c.dataset = 'corrupcaopj'
        ORDER BY c.year
    """)

    # Court movements
    result["court_movements"] = _safe_query(conn, """
        SELECT year, entered, finalized, pending,
               CASE WHEN entered > 0 THEN ROUND(CAST(finalized AS REAL) / entered, 3) ELSE 0 END as resolution_rate
        FROM court_movements ORDER BY year
    """)

    # Prison population
    result["prison_population"] = _safe_query(conn, """
        SELECT year, count FROM prison_population ORDER BY year
    """)

    # Available datasets
    result["datasets"] = _safe_query(conn, """
        SELECT dataset, category, COUNT(*) as records,
               MIN(year) as year_min, MAX(year) as year_max
        FROM corruption_cases GROUP BY dataset, category
    """)

    conn.close()
    return result


# All procurement fields the dashboard expects. If ANY of these are missing
# from the cache we fall back to the live query — serving a partial response
# would silently break the frontend.
_PROCUREMENT_CACHE_FIELDS = [
    "stats", "by_year", "by_procedure", "direct_awards",
    "price_inflation", "self_referencing", "top_buyers",
    "top_sellers", "top_sellers_hint", "by_municipality",
    "by_cpv", "monthly_trend", "single_bidder_timeline",
]


def handle_procurement() -> dict:
    """Procurement data: contracts, trends, signals.

    Reads from the pre-computed JSON cache when ALL cache files are fresh.
    Falls back to a live query against procurement.db otherwise.
    """
    # Fast path: every cache file must be present and fresh. Partial cache
    # would silently drop fields the frontend depends on. Read each file
    # once into a local dict (avoids 22 stat() calls per request).
    cached: Dict[str, Any] = {}
    for name in _PROCUREMENT_CACHE_FIELDS:
        data = _read_cache_json(name)
        if data is None:
            break  # any miss = fall through to live query
        cached[name] = data
    if len(cached) == len(_PROCUREMENT_CACHE_FIELDS):
        return cached

    # Slow path: live query against the 1.9GB database
    conn = _get_db("procurement")
    if not conn:
        return {"error": "procurement.db not found"}

    result: Dict[str, Any] = {}
    try:
        # Basic stats
        result["stats"] = {
            "total": _safe_scalar(conn, "SELECT COUNT(*) FROM contratos"),
            "total_value": _safe_scalar(conn, "SELECT SUM(precoContratual) FROM contratos WHERE precoContratual > 0"),
            "year_min": _safe_scalar(conn, "SELECT MIN(Ano) FROM contratos WHERE Ano IS NOT NULL"),
            "year_max": _safe_scalar(conn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL"),
        }

        # By year
        result["by_year"] = _safe_query(conn, """
            SELECT Ano as year, COUNT(*) as contracts, SUM(precoContratual) as value
            FROM contratos WHERE Ano IS NOT NULL
            GROUP BY Ano ORDER BY Ano
        """)

        # Single-bidder (non-competitive) timeline. The contratos table has
        # no `numConcorrentes` column, so the closest corruption-risk proxy
        # is the share of contracts awarded via procedures that bypass or
        # limit competition: Ajuste Direto (direct award, no competition)
        # + Consulta Prvia (prior consultation, typically 3 invited firms).
        result["single_bidder_timeline"] = _safe_query(conn, """
            SELECT
                Ano AS year,
                COUNT(*) AS total,
                SUM(CASE
                    WHEN tipoprocedimento LIKE '%ajuste direto%'
                      OR tipoprocedimento LIKE '%consulta pr%'
                    THEN 1 ELSE 0
                END) AS single_bidder,
                ROUND(100.0 * SUM(CASE
                    WHEN tipoprocedimento LIKE '%ajuste direto%'
                      OR tipoprocedimento LIKE '%consulta pr%'
                    THEN 1 ELSE 0
                END) / COUNT(*), 1) AS single_bidder_pct
            FROM contratos
            WHERE Ano IS NOT NULL
            GROUP BY Ano
            ORDER BY Ano
        """)

        # By procedure type
        result["by_procedure"] = _safe_query(conn, """
            SELECT tipoprocedimento, COUNT(*) as contracts, SUM(precoContratual) as value
            FROM contratos WHERE tipoprocedimento IS NOT NULL AND precoContratual > 0
            GROUP BY tipoprocedimento ORDER BY contracts DESC LIMIT 10
        """)

        # Direct awards ratio (ajuste direto)
        total = result["stats"]["total"] or 1
        direct = _safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE tipoprocedimento LIKE '%ajuste direto%'")
        result["direct_awards"] = {"count": direct, "pct": round((direct / total) * 100, 1) if total else 0}

        # Price inflation: contracts where final > base * 1.05
        result["price_inflation"] = {
            "count": _safe_scalar(conn, """
                SELECT COUNT(*) FROM contratos
                WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento * 1.05
            """),
            "with_base_price": _safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE precoBaseProcedimento > 0"),
        }

        # Self-referencing check (sampled for speed on 1.9GB DB)
        try:
            sr = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT idcontrato, adjudicante_nif, adjudicatarios
                    FROM contratos
                    WHERE adjudicante_nif IS NOT NULL AND adjudicatarios IS NOT NULL
                    AND adjudicatarios != ''
                    LIMIT 50000
                ) sub
                WHERE adjudicatarios LIKE '%' || adjudicante_nif || '%'
            """).fetchone()[0]
            result["self_referencing"] = {"count": sr, "sample_size": 50000}
        except Exception:
            result["self_referencing"] = {"count": 0, "sample_size": 0}

        # Top entities by contract value (buyer)
        result["top_buyers"] = _safe_query(conn, """
            SELECT adjudicante_nif as nif, adjudicante_nome as name,
                   COUNT(*) as contracts, SUM(precoContratual) as value
            FROM contratos
            WHERE adjudicante_nif IS NOT NULL AND precoContratual > 0
            GROUP BY adjudicante_nif ORDER BY value DESC LIMIT 15
        """)

        # Top sellers by contract value (from adjudicatarios field)
        result["top_sellers_hint"] = _safe_query(conn, """
            SELECT adjudicatarios, COUNT(*) as cnt, SUM(precoContratual) as value
            FROM contratos
            WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' AND precoContratual > 0
            GROUP BY adjudicatarios ORDER BY value DESC LIMIT 10
        """)

        # Top sellers parsed by NIF (matches the cache's top_sellers.json so
        # the response shape doesn't drift between cache-hit and cache-miss)
        if _query_top_sellers is not None:
            try:
                result["top_sellers"] = _query_top_sellers(conn)
            except (sqlite3.Error, AttributeError, TypeError):
                # Empty list is the same fallback the cache uses when the
                # module isn't available; we narrow to specific errors so
                # real bugs (TypeError from a schema change) get caught
                # by error monitoring.
                result["top_sellers"] = []
        else:
            result["top_sellers"] = []

        # Municipality distribution (if ine columns exist)
        try:
            conn.execute("SELECT ine_municipality FROM contratos LIMIT 1")
            result["by_municipality"] = _safe_query(conn, """
                SELECT ine_municipality as municipality, COUNT(*) as contracts, SUM(precoContratual) as value
                FROM contratos
                WHERE ine_municipality IS NOT NULL AND ine_municipality != '' AND precoContratual > 0
                GROUP BY ine_municipality ORDER BY value DESC LIMIT 20
            """)
        except sqlite3.OperationalError:
            result["by_municipality"] = []

    finally:
        try: conn.close()
        except Exception: pass

    return result


def handle_social() -> dict:
    """INE social indicators: immigration, pensions, crime, demographics."""
    conn = _get_db("ine")
    if not conn:
        return {"error": "ine_stats.db not found"}

    result: Dict[str, Any] = {}

    # Immigration by year (national total)
    result["immigration"] = _safe_query(conn, """
        SELECT year, SUM(value) as total
        FROM ine_observations WHERE indicator_code = '0001236' AND value IS NOT NULL
        GROUP BY year ORDER BY year
    """)

    # Pensionistas by year
    result["pensionistas"] = _safe_query(conn, """
        SELECT year, SUM(value) as total
        FROM ine_observations WHERE indicator_code = '0004325' AND value IS NOT NULL
        GROUP BY year ORDER BY year
    """)

    # Average pension value
    result["avg_pension"] = _safe_query(conn, """
        SELECT year, SUM(value) as total
        FROM ine_observations WHERE indicator_code = '0004347' AND value IS NOT NULL
        GROUP BY year ORDER BY year
    """)

    # Early retirement
    result["early_retirement"] = _safe_query(conn, """
        SELECT year, SUM(value) as total
        FROM ine_observations WHERE indicator_code = '0006712' AND value IS NOT NULL
        GROUP BY year ORDER BY year
    """)

    # Natural population growth
    result["natural_growth"] = _safe_query(conn, """
        SELECT year, SUM(value) as total
        FROM ine_observations WHERE indicator_code = '0008263' AND value IS NOT NULL
        GROUP BY year ORDER BY year
    """)

    # Crime rate by year
    result["crime_rate"] = _safe_query(conn, """
        SELECT year, AVG(value) as rate
        FROM ine_observations WHERE indicator_code = '0008074' AND value IS NOT NULL
        GROUP BY year ORDER BY year
    """)

    # Immigration by region (latest year)
    result["immigration_by_region"] = _safe_query(conn, """
        SELECT geographic_name as region, value
        FROM ine_observations
        WHERE indicator_code = '0001236' AND value IS NOT NULL
        AND year = (SELECT MAX(year) FROM ine_observations WHERE indicator_code = '0001236')
        AND geographic_name != 'Portugal'
        ORDER BY value DESC LIMIT 20
    """)

    # Indicator metadata
    result["indicators"] = _safe_query(conn, """
        SELECT indicator_code, indicator_name, category, COUNT(*) as records,
               MIN(year) as year_min, MAX(year) as year_max
        FROM ine_observations GROUP BY indicator_code
    """)

    conn.close()
    return result


def handle_transparency() -> dict:
    """Transparency / PRR data."""
    conn = _get_db("transparency")
    if not conn:
        return {"error": "transparency.db not found"}

    result: Dict[str, Any] = {}

    # List tables
    tables = _safe_query(conn, "SELECT name FROM sqlite_master WHERE type='table'")
    result["tables"] = [t["name"] for t in tables]

    # For each table, get row count and sample
    for t in result["tables"]:
        try:
            count = _safe_scalar(conn, f"SELECT COUNT(*) FROM [{t}]")
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{t}])").fetchall()]
            result[f"table_{t}"] = {"rows": count, "columns": cols[:15]}
        except Exception:
            pass

    conn.close()
    return result


def handle_crossref() -> dict:
    """Cross-domain correlations and risk signals."""
    result: Dict[str, Any] = {}

    # Justice data
    jconn = _get_db("justice")
    if jconn:
        result["corruption_trend"] = _safe_query(jconn, """
            SELECT year, value FROM corruption_cases
            WHERE dataset = 'corrupcaopj' ORDER BY year
        """)
        result["ml_trend"] = _safe_query(jconn, """
            SELECT year, value FROM corruption_cases
            WHERE dataset = 'branqueamentopj' ORDER BY year
        """)
        result["court_pending_trend"] = _safe_query(jconn, """
            SELECT year, pending FROM court_movements ORDER BY year
        """)
        jconn.close()

    # INE data
    iconn = _get_db("ine")
    if iconn:
        result["crime_trend"] = _safe_query(iconn, """
            SELECT year, AVG(value) as rate FROM ine_observations
            WHERE indicator_code = '0008074' AND value IS NOT NULL
            GROUP BY year ORDER BY year
        """)
        result["immigration_trend"] = _safe_query(iconn, """
            SELECT year, SUM(value) as total FROM ine_observations
            WHERE indicator_code = '0001236' AND value IS NOT NULL
            GROUP BY year ORDER BY year
        """)
        result["pension_trend"] = _safe_query(iconn, """
            SELECT year, SUM(value) as total FROM ine_observations
            WHERE indicator_code = '0004325' AND value IS NOT NULL
            GROUP BY year ORDER BY year
        """)
        iconn.close()

    # Procurement signals (lightweight, with generous timeout for 1.9GB DB)
    pconn = _get_db("procurement")
    if pconn:
        try:
            total = _safe_scalar(pconn, "SELECT COUNT(*) FROM contratos") or 1
            direct = _safe_scalar(pconn, "SELECT COUNT(*) FROM contratos WHERE tipoprocedimento LIKE '%ajuste direto%'")
            result["procurement_signals"] = {
                "direct_award_pct": round((direct / total) * 100, 1),
                "total_contracts": total,
            }
        except Exception as e:
            result["procurement_signals"] = {"error": f"query failed: {e}", "direct_award_pct": 0, "total_contracts": 0}
        finally:
            try: pconn.close()
            except Exception: pass

    # Cross-correlation: immigration vs crime
    if "immigration_trend" in result and "crime_trend" in result:
        immig = {r["year"]: r["total"] for r in result["immigration_trend"]}
        crime = {r["year"]: r["rate"] for r in result["crime_trend"]}
        overlap = sorted(set(immig.keys()) & set(crime.keys()))
        if len(overlap) >= 3:
            iv = [immig[y] for y in overlap]
            cv = [crime[y] for y in overlap]
            n = len(overlap)
            mean_i = sum(iv) / n
            mean_c = sum(cv) / n
            cov = sum((iv[j] - mean_i) * (cv[j] - mean_c) for j in range(n))
            std_i = (sum((v - mean_i) ** 2 for v in iv) / n) ** 0.5
            std_c = (sum((v - mean_c) ** 2 for v in cv) / n) ** 0.5
            r_val = cov / (std_i * std_c) if std_i > 0 and std_c > 0 else 0
            result["immigration_crime_correlation"] = {
                "pearson_r": round(r_val, 4),
                "r_squared": round(r_val ** 2, 4),
                "overlap_years": overlap,
                "n": n,
                "interpretation": (
                    "weak negative" if -0.3 < r_val < 0 else
                    "weak positive" if r_val < 0.3 else
                    "moderate positive" if r_val < 0.7 else
                    "strong positive"
                ),
            }
        else:
            result["immigration_crime_correlation"] = {"error": "insufficient overlap"}

    # Risk signals
    signals = []

    # ML surge signal
    ml_trend = result.get("ml_trend", [])
    if len(ml_trend) >= 2:
        first_val = ml_trend[0].get("value", 0) or 0
        last_val = ml_trend[-1].get("value", 0) or 0
        if first_val > 0 and last_val > first_val * 2:
            signals.append({
                "signal": "money_laundering_surge",
                "severity": "high",
                "detail": f"Money laundering cases grew {round(last_val / first_val, 1)}× since {ml_trend[0]['year']}",
            })

    # Direct awards signal
    ps = result.get("procurement_signals", {})
    direct_pct = ps.get("direct_award_pct", 0)
    if direct_pct > 50:
        signals.append({
            "signal": "high_direct_awards",
            "severity": "high" if direct_pct > 60 else "medium",
            "detail": f"{direct_pct}% of contracts are direct awards (ajuste direto)",
        })

    # Court backlog signal
    court = result.get("court_pending_trend", [])
    if court:
        latest = court[-1].get("pending", 0) or 0
        signals.append({
            "signal": "court_backlog",
            "severity": "medium" if latest > 500000 else "low",
            "detail": f"{latest:,} pending cases in court system ({court[-1]['year']})",
        })

    # Immigration-crime correlation
    ic_corr = result.get("immigration_crime_correlation", {})
    if "pearson_r" in ic_corr:
        signals.append({
            "signal": "immigration_crime_correlation",
            "severity": "info",
            "detail": f"Pearson r={ic_corr['pearson_r']} ({ic_corr['interpretation']}) — no meaningful relationship",
        })

    result["risk_signals"] = signals
    return result


def handle_health() -> dict:
    """Database health and connectivity status."""
    result: Dict[str, Any] = {"databases": {}, "timestamp": datetime.now().isoformat()}

    for name, path in DB_PATHS.items():
        status: Dict[str, Any] = {"exists": path.exists()}
        if path.exists():
            status["size_mb"] = round(path.stat().st_size / (1024 * 1024), 1)
            status["mtime"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            conn = _get_db(name)
            if conn:
                try:
                    tables = _safe_query(conn, "SELECT name FROM sqlite_master WHERE type='table'")
                    status["tables"] = [t["name"] for t in tables]
                    status["connectable"] = True
                except Exception as e:
                    status["connectable"] = False
                    status["error"] = str(e)
                finally:
                    conn.close()
            else:
                status["connectable"] = False
        result["databases"][name] = status

    return result


# ── Router ──────────────────────────────────────────────────────────────────

def handle_cache_status() -> dict:
    """Report which procurement cache files are present and fresh."""
    return _cache_status()


def handle_cache_rebuild() -> dict:
    """Trigger a background rebuild of the procurement cache."""
    return _trigger_cache_rebuild(force=True)


ENDPOINTS = {
    "/api/overview": handle_overview,
    "/api/justice": handle_justice,
    "/api/procurement": handle_procurement,
    "/api/social": handle_social,
    "/api/transparency": handle_transparency,
    "/api/crossref": handle_crossref,
    "/api/health": handle_health,
    "/api/cache/status": handle_cache_status,
    "/api/cache/rebuild": handle_cache_rebuild,
}


# ── HTTP Handler ────────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler with CORS support and JSON responses."""

    cors_origin = "*"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # CORS preflight
        if path == "":
            self._send_json({"status": "ok", "endpoints": list(ENDPOINTS.keys())})
            return

        handler = ENDPOINTS.get(path)
        if handler:
            start = time.time()
            try:
                data = handler()
                elapsed = round(time.time() - start, 3)
                data["_server_ms"] = round(elapsed * 1000, 1)
                self._send_json(data)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
        else:
            self._send_json({"error": f"Unknown endpoint: {path}", "available": list(ENDPOINTS.keys())}, status=404)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", self.cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        """Suppress default logging, only log errors."""
        if args and str(args[0]).startswith("4"):
            super().log_message(format, *args)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analisa.pt Dashboard API Server")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--cors-origin", default="*", help="CORS origin (default: *)")
    args = parser.parse_args()

    DashboardHandler.cors_origin = args.cors_origin

    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"\n  [Analisa.pt] API Server")
    print(f"  Listening on http://{args.host}:{args.port}")
    print(f"  CORS origin: {args.cors_origin}")
    print(f"\n  Endpoints:")
    for ep in ENDPOINTS:
        print(f"    http://localhost:{args.port}{ep}")
    print(f"\n  Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
