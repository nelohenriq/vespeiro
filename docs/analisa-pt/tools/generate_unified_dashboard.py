#!/usr/bin/env python3
"""Unified Analisa.pt Dashboard — All data sources in one view.

Consolidates:
  - Justice: corruption cases, court flow, prison population (justice.db)
  - Procurement: contracts, value, procedures, temporal trends (procurement.db)
  - Corruption signals: inflation, self-referencing, concentration (procurement.db)
  - Social (INE): pensions, crime rate, immigration, demographics (ine_stats.db)
  - Transparency: PRR allocation, budget (transparency.db)
  - Cross-reference: risk signals, composite score (justice_crossref.json)

Usage:
    python generate_unified_dashboard.py                       # Default output
    python generate_unified_dashboard.py -o unified.html      # Custom output
    python generate_unified_dashboard.py --open               # Generate + open
"""

import argparse
import json
import re
import sqlite3
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from utils import fmt
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SUMMARY_DIR = DATA_DIR / "summary"
CROSSREF_JSON = SUMMARY_DIR / "justice_crossref.json"

DB_PATHS = {
    "justice": DATA_DIR / "justice.db",
    "procurement": DATA_DIR / "procurement.db",
    "ine": DATA_DIR / "ine_stats.db",
    "transparency": DATA_DIR / "transparency.db",
    "anuncios": DATA_DIR / "anuncios_index.db",
    "modifications": DATA_DIR / "modificacoes_index.db",
}


# ═════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def esc(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fmt_num(v):
    if v is None:
        return "0"
    return f"{int(v):,}"


def open_db(name):
    path = DB_PATHS.get(name)
    if not path or not path.exists():
        return None
    try:
        conn = db_connect(str(path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA cache_size=-64000")
        return conn
    except Exception:
        return None


def safe_query(conn, sql, params=()):
    if not conn:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def safe_scalar(conn, sql, params=()):
    if not conn:
        return 0
    try:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else 0
    except Exception:
        return 0


def table_exists(conn, name):
    if not conn:
        return False
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return r[0] > 0
    except Exception:
        return False


def trend_direction(values):
    """3-year trend direction from a list of numeric values."""
    if len(values) < 2:
        return "stable", 0
    recent = values[-1]
    prev = values[-2]
    if prev == 0:
        return "stable", 0
    pct = ((recent - prev) / prev) * 100
    if pct > 10:
        return "rising", round(pct, 1)
    elif pct < -10:
        return "falling", round(pct, 1)
    return "stable", round(pct, 1)


# ═════════════════════════════════════════════════════════════════════════════
#  DATA QUERIES — each returns a dict ready for HTML generation
# ═════════════════════════════════════════════════════════════════════════════

def query_justice(conn):
    """Corruption cases, court flow, prison population."""
    result = {"corruption": {}, "court": [], "prison": []}
    if not conn:
        return result

    # Corruption + money laundering trends
    rows = safe_query(conn, """
        SELECT dataset, year, SUM(value) as total
        FROM corruption_cases WHERE year IS NOT NULL AND value IS NOT NULL
        GROUP BY dataset, year ORDER BY dataset, year
    """)
    trends = {}
    for r in rows:
        ds = r["dataset"]
        if ds not in trends:
            trends[ds] = []
        trends[ds].append({"year": r["year"], "cases": r["total"]})
    result["corruption"] = trends

    # Court flow
    rows = safe_query(conn, """
        SELECT year, SUM(entered) as entered, SUM(finalized) as finalized,
               SUM(pending) as pending
        FROM court_movements WHERE year IS NOT NULL
        GROUP BY year ORDER BY year
    """)
    result["court"] = [dict(r) for r in rows]

    # Prison
    rows = safe_query(conn, """
        SELECT year, SUM(count) as total
        FROM prison_population WHERE year IS NOT NULL
        GROUP BY year ORDER BY year
    """)
    result["prison"] = [dict(r) for r in rows]

    return result


def query_procurement(conn):
    """Core procurement stats, temporal trends, procedures, risk distribution."""
    result = {
        "stats": {}, "yearly": [], "procedures": [],
        "risk_dist": [], "value_dist": [], "burst": {},
    }
    if not conn or not table_exists(conn, "contratos"):
        return result

    # Scope to last 5 years for speed on 1.9GB DB
    latest = safe_scalar(conn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL")
    yr_cutoff = (latest or 2024) - 5
    tc = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano > ?", (yr_cutoff,))
    tv = safe_scalar(conn, "SELECT SUM(COALESCE(precoContratual, 0)) FROM contratos WHERE Ano > ?", (yr_cutoff,))
    buyers = safe_scalar(conn, "SELECT COUNT(DISTINCT adjudicante_nif) FROM contratos WHERE Ano > ? AND adjudicante_nif != '' AND adjudicante_nif != '-'", (yr_cutoff,))
    direct = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano > ? AND (tipoprocedimento LIKE '%ajuste%' OR tipoprocedimento LIKE '%direto%')", (yr_cutoff,))
    inflated = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano > ? AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento", (yr_cutoff,))
    with_base = max(safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano > ? AND precoBaseProcedimento > 0", (yr_cutoff,)), 1)
    overrun = safe_scalar(conn, "SELECT SUM(precoContratual - precoBaseProcedimento) FROM contratos WHERE Ano > ? AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento", (yr_cutoff,))

    # Self-referencing count (sample for speed, wrapped for timeout safety)
    sr_count = 0
    try:
        rows = safe_query(conn, "SELECT adjudicante_nif, adjudicatarios FROM contratos WHERE Ano > ? AND adjudicatarios IS NOT NULL AND adjudicatarios != '' AND adjudicante_nif IS NOT NULL AND adjudicante_nif != '' LIMIT 50000", (yr_cutoff,))
        for r in rows:
            adjt = str(r["adjudicatarios"] or "")
            if " - " in adjt:
                for part in adjt.split(";"):
                    m = re.match(r"(\d{9})\s*-\s*", part.strip())
                    if m and m.group(1) == r["adjudicante_nif"]:
                        sr_count += 1
                        break
    except Exception:
        pass

    result["stats"] = {
        "total": tc, "value": tv, "buyers": buyers,
        "direct": direct, "direct_rate": round(direct * 100 / max(tc, 1), 1),
        "inflated": inflated, "inflation_rate": round(inflated * 100 / with_base, 1),
        "overrun": overrun or 0, "self_ref": sr_count,
    }

    result["year_range"] = f"{yr_cutoff + 1}-present"

    try:
        rows = safe_query(conn, """
            SELECT Ano as year, COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val
            FROM contratos WHERE Ano IS NOT NULL AND Ano > ?
            GROUP BY Ano ORDER BY Ano
        """, (yr_cutoff,))
        result["yearly"] = [dict(r) for r in rows]
    except Exception:
        pass

    try:
        rows = safe_query(conn, """
            SELECT tipoprocedimento, COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val
            FROM contratos WHERE Ano IS NOT NULL AND Ano > ?
            AND tipoprocedimento IS NOT NULL AND tipoprocedimento != ''
            GROUP BY tipoprocedimento ORDER BY cnt DESC LIMIT 8
        """, (yr_cutoff,))
        result["procedures"] = [dict(r) for r in rows]
    except Exception:
        pass

    try:
        rows = safe_query(conn, """
            SELECT
                CASE
                    WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 0 THEN '0% or less'
                    WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 5 THEN '1-5%'
                    WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 10 THEN '5-10%'
                    WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 20 THEN '10-20%'
                    WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 50 THEN '20-50%'
                    ELSE '50%+'
                END as bucket,
                COUNT(*) as cnt
            FROM contratos
            WHERE Ano IS NOT NULL AND Ano > ?
            AND precoBaseProcedimento > 0 AND precoContratual > 0
            GROUP BY bucket
            ORDER BY MIN((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento)
        """, (yr_cutoff,))
        result["risk_dist"] = [dict(r) for r in rows]
    except Exception:
        pass

    try:
        rows = safe_query(conn, """
            SELECT
                CASE
                    WHEN precoContratual < 10000 THEN '<10K'
                    WHEN precoContratual < 50000 THEN '10K-50K'
                    WHEN precoContratual < 100000 THEN '50K-100K'
                    WHEN precoContratual < 500000 THEN '100K-500K'
                    WHEN precoContratual < 1000000 THEN '500K-1M'
                    WHEN precoContratual < 5000000 THEN '1M-5M'
                    ELSE '5M+'
                END as bucket,
                COUNT(*) as cnt
            FROM contratos WHERE Ano IS NOT NULL AND Ano > ?
            AND precoContratual > 0
            GROUP BY bucket ORDER BY MIN(precoContratual)
        """, (yr_cutoff,))
        result["value_dist"] = [dict(r) for r in rows]
    except Exception:
        pass

    return result


def query_corruption_signals(conn):
    """Self-referencing, concentration, top inflated, entity rankings."""
    result = {
        "self_ref": [], "concentration": [], "inflated": [],
        "top_buyers": [], "top_winners": [],
    }
    if not conn or not table_exists(conn, "contratos"):
        return result

    # Self-referencing (scoped to recent years for speed)
    latest_yr2 = safe_scalar(conn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL")
    yr_cut2 = (latest_yr2 or 2024) - 5
    rows = safe_query(conn, """
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
            precoContratual, objectoContrato, tipoContrato
        FROM contratos
        WHERE Ano > ? AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
        AND adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
        LIMIT 50000
    """, (yr_cut2,))
    for r in rows:
        adj_nif = r["adjudicante_nif"]
        adjt = str(r["adjudicatarios"] or "")
        if " - " not in adjt:
            continue
        for part in adjt.split(";"):
            match = re.match(r"(\d{9})\s*-\s*(.+)", part.strip())
            if match and match.group(1) == adj_nif:
                result["self_ref"].append({
                    "nif": adj_nif, "buyer": r["adjudicante_nome"],
                    "seller": match.group(2).strip(),
                    "valor": r["precoContratual"] or 0,
                    "objeto": str(r["objectoContrato"] or "")[:80],
                    "tipo": str(r["tipoContrato"] or "")[:40],
                })
                break

    # Top inflated (scoped to recent years)
    latest_yr = safe_scalar(conn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL")
    yr_cut = (latest_yr or 2024) - 5
    rows = safe_query(conn, """
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
               precoBaseProcedimento, precoContratual,
               (precoContratual - precoBaseProcedimento) as overrun,
               ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) as pct
        FROM contratos
        WHERE Ano > ? AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento
        ORDER BY overrun DESC LIMIT 15
    """, (yr_cut,))
    result["inflated"] = [dict(r) for r in rows]

    # Concentration (buyer-seller pairs, scoped to last 5 years for speed)
    latest_yr = safe_scalar(conn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL")
    yr_cut = (latest_yr or 2024) - 5
    buyer_totals = {}
    for r in safe_query(conn, "SELECT adjudicante_nif, SUM(precoContratual) as total FROM contratos WHERE adjudicante_nif IS NOT NULL AND Ano > ? GROUP BY adjudicante_nif", (yr_cut,)):
        buyer_totals[r["adjudicante_nif"]] = r["total"] or 0

    rows = safe_query(conn, """
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
            SUM(precoContratual) as pair_total, COUNT(*) as cnt
        FROM contratos
        WHERE Ano IS NOT NULL AND Ano > ?
        AND adjudicante_nif IS NOT NULL AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
        GROUP BY adjudicante_nif, adjudicatarios
        HAVING pair_total >= 500000
        ORDER BY pair_total DESC LIMIT 60
    """, (yr_cut,))
    for r in rows:
        bt = buyer_totals.get(r["adjudicante_nif"], 0)
        if bt > 0:
            share = (r["pair_total"] * 100.0) / bt
            if share >= 30:
                result["concentration"].append({
                    "buyer_nif": r["adjudicante_nif"],
                    "buyer": r["adjudicante_nome"],
                    "seller": (r["adjudicatarios"] or "")[:60],
                    "share": round(share, 1),
                    "contracts": r["cnt"],
                    "value": r["pair_total"],
                })
    result["concentration"] = result["concentration"][:15]

    # Top buyers / winners from entidades
    if table_exists(conn, "entidades"):
        rows = safe_query(conn, """
            SELECT nifEntidade, desigEntidade, numContratos,
                   totAdjudicanteValorContratIni, totValorContratIni
            FROM entidades WHERE totAdjudicanteValorContratIni > 0
            ORDER BY totAdjudicanteValorContratIni DESC LIMIT 15
        """)
        result["top_buyers"] = [dict(r) for r in rows]

        rows = safe_query(conn, """
            SELECT nifEntidade, desigEntidade, numContratos,
                   totValorContratIni, totAdjudicanteValorContratIni
            FROM entidades WHERE totValorContratIni > 0
            ORDER BY totValorContratIni DESC LIMIT 15
        """)
        result["top_winners"] = [dict(r) for r in rows]

    return result


def query_ine(conn):
    """INE social indicators: pensions, crime, immigration, demographics."""
    result = {
        "pensionistas": [], "pension_value": [], "early_retirement": [],
        "crime": [], "immigration": [], "demographics": [],
    }
    if not conn:
        return result

    indicator_map = {
        "0004325": "pensionistas",
        "0004347": "pension_value",
        "0006712": "early_retirement",
        "0008074": "crime",
        "0001236": "immigration",
        "0008263": "demographics",
    }
    for code, key in indicator_map.items():
        # Prefer Nacional-level rows to avoid double-counting
        rows = safe_query(conn, """
            SELECT year, value FROM ine_observations
            WHERE indicator_code = ? AND value IS NOT NULL AND year IS NOT NULL
            AND geographic_level IN ('Nacional', 'Portugal')
            ORDER BY year
        """, (code,))
        # Fall back to all rows if no Nacional-level data exists
        if not rows:
            rows = safe_query(conn, """
                SELECT year, value FROM ine_observations
                WHERE indicator_code = ? AND value IS NOT NULL AND year IS NOT NULL
                ORDER BY year
            """, (code,))
        # Aggregate by year (sum for counts, average for rates/values)
        by_year = defaultdict(list)
        for r in rows:
            by_year[r["year"]].append(r["value"])
        if key in ("crime",):
            result[key] = [{"year": y, "value": round(sum(vals) / len(vals), 1)} for y, vals in sorted(by_year.items())]
        elif key in ("pension_value",):
            result[key] = [{"year": y, "value": round(sum(vals) / len(vals), 1)} for y, vals in sorted(by_year.items())]
        else:
            result[key] = [{"year": y, "value": round(sum(vals), 0)} for y, vals in sorted(by_year.items())]

    return result


def query_transparency(conn):
    """PRR and budget overview."""
    result = {}
    if not conn:
        return result

    if table_exists(conn, "prr_entities"):
        result["prr_entities"] = safe_scalar(conn, "SELECT COUNT(*) FROM prr_entities WHERE nif != '' AND nif IS NOT NULL")
        result["prr_value"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_contratado, 0)) FROM prr_entities")
        result["prr_paid"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_pago, 0)) FROM prr_entities")
    if table_exists(conn, "prr_projects"):
        result["prr_projects"] = safe_scalar(conn, "SELECT COUNT(*) FROM prr_projects")
        result["prr_project_value"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_aprovado, 0)) FROM prr_projects")
    if table_exists(conn, "budget"):
        result["budget_rows"] = safe_scalar(conn, "SELECT COUNT(*) FROM budget")
        result["budget_previsto"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_previsto, 0)) FROM budget")
        result["budget_realizado"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_realizado, 0)) FROM budget")

    # TED notices count
    ted_path = DATA_DIR / "ted_notices.db"
    if ted_path.exists():
        try:
            tc = db_connect(str(ted_path), timeout=10)
            result["ted_notices"] = tc.execute("SELECT COUNT(*) FROM ted_notices").fetchone()[0]
            tc.close()
        except Exception:
            pass

    return result


def load_crossref():
    """Load justice_crossref.json if available."""
    try:
        if CROSSREF_JSON.exists():
            return json.loads(CROSSREF_JSON.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ═════════════════════════════════════════════════════════════════════════════
#  HTML GENERATION
# ═════════════════════════════════════════════════════════════════════════════

def generate_unified_dashboard():
    now = datetime.now(timezone.utc)
    gen_time = now.strftime("%Y-%m-%d %H:%M UTC")

    # ── Query all data ────────────────────────────────────────────────────
    conns = {}
    for name in DB_PATHS:
        conns[name] = open_db(name)

    # Query each source independently — if one times out, others survive
    try:
        justice = query_justice(conns["justice"])
    except Exception:
        justice = {"corruption": {}, "court": [], "prison": []}
    try:
        procurement = query_procurement(conns["procurement"])
    except Exception:
        procurement = {"stats": {}, "yearly": [], "procedures": [], "risk_dist": [], "value_dist": [], "year_range": ""}
    try:
        corruption = query_corruption_signals(conns["procurement"])
    except Exception:
        corruption = {"self_ref": [], "concentration": [], "inflated": [], "top_buyers": [], "top_winners": []}
    try:
        ine = query_ine(conns["ine"])
    except Exception:
        ine = {"pensionistas": [], "pension_value": [], "early_retirement": [], "crime": [], "immigration": [], "demographics": []}
    try:
        transparency = query_transparency(conns["transparency"])
    except Exception:
        transparency = {}
    crossref = load_crossref()

    # Capture DB availability before closing
    db_available = {name: conn is not None for name, conn in conns.items()}

    for c in conns.values():
        if c:
            c.close()

    # ── Extract chart data ────────────────────────────────────────────────
    # Justice
    cor_years = sorted(set(
        pt["year"] for pts in justice["corruption"].values() for pt in pts
        if pt["year"] and pt["year"] > 2005
    ))
    cor_cj = {pt["year"]: pt["cases"] for pt in justice["corruption"].get("corrupcaopj", [])}
    cor_bl = {pt["year"]: pt["cases"] for pt in justice["corruption"].get("branqueamentopj", [])}

    court_data = [r for r in justice["court"] if r.get("year") and r["year"] > 2005]
    prison_data = [r for r in justice["prison"] if r.get("year") and r["year"] > 2005]

    # Procurement
    ps = procurement["stats"]
    py = procurement["yearly"]

    # INE
    def _chart_data(records):
        years = [r["year"] for r in records if r.get("year")]
        values = [r["value"] for r in records if r.get("year")]
        return years, values

    imm_years, imm_values = _chart_data(ine["immigration"])
    crime_years, crime_values = _chart_data(ine["crime"])
    pen_years, pen_values = _chart_data(ine["pensionistas"])
    pen_val_years, pen_val_values = _chart_data(ine["pension_value"])
    demo_years, demo_values = _chart_data(ine["demographics"])

    # Risk signals
    risk_signals = crossref.get("risk_signals", [])
    risk_level = crossref.get("risk_level", "unknown")
    composite = crossref.get("composite_score", 0)
    risk_colors = {"critical": "#ef4444", "elevated": "#f59e0b", "normal": "#22c55e"}
    risk_bg = {"critical": "rgba(239,68,68,.15)", "elevated": "rgba(245,158,11,.15)", "normal": "rgba(34,197,94,.15)"}

    # Active DB count
    active_dbs = sum(1 for v in db_available.values() if v)

    # ── Build HTML ────────────────────────────────────────────────────────
    p = []
    p.append('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">')
    p.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    p.append('<title>Analisa.pt — Unified Intelligence Dashboard</title>')
    p.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>')

    # ── CSS ───────────────────────────────────────────────────────────────
    p.append('''<style>
:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--muted:#94a3b8;--border:#334155;--accent:#f59e0b;--danger:#ef4444;--success:#22c55e;--info:#3b82f6;--purple:#8b5cf6;--teal:#14b8a6;--pink:#ec4899}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
.container{max-width:1440px;margin:0 auto;padding:16px}
.header{background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);padding:24px 28px;border-bottom:2px solid var(--accent);border-radius:12px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
.header h1{font-size:22px;color:var(--accent)}
.header .sub{color:var(--muted);font-size:13px;margin-top:4px}
.header-right{display:flex;align-items:center;gap:12px}
.risk-badge{padding:8px 20px;border-radius:99px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px}
.live-badge{background:var(--success);color:#0f172a;padding:5px 14px;border-radius:99px;font-size:11px;font-weight:700}
.db-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;margin-bottom:16px}
.db-chip{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:11px;display:flex;align-items:center;gap:6px}
.db-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.db-dot.ok{background:var(--success)}.db-dot.miss{background:var(--danger)}
.summary-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin-bottom:16px}
.summary-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center;transition:transform .2s,box-shadow .2s}
.summary-card:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.3)}
.sc-icon{font-size:18px}.sc-value{font-size:17px;font-weight:700;color:var(--accent);margin:3px 0}
.sc-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.sc-sub{font-size:10px;color:var(--muted);margin-top:2px}
.tab-bar{display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:6px}
.tab-btn{padding:8px 14px;border:none;border-radius:8px;cursor:pointer;font-size:12px;font-weight:500;background:transparent;color:var(--muted);transition:all .2s;white-space:nowrap}
.tab-btn:hover{color:var(--text);background:rgba(255,255,255,.05)}
.tab-btn.active{background:var(--accent);color:#0f172a;font-weight:600}
.tab-panel{display:none}.tab-panel.active{display:block}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:14px;margin-bottom:16px}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px}
.chart-box h3{font-size:14px;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.chart-box h3 .tag{font-size:9px;padding:2px 7px;border-radius:4px;font-weight:600}
.chart-container{position:relative;height:260px}
.section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin-bottom:14px}
.section h3{font-size:15px;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.risk-panel{border:2px solid;border-radius:12px;padding:18px;margin-bottom:14px}
.risk-signal{display:flex;align-items:center;gap:12px;padding:8px 14px;border-radius:8px;margin-bottom:6px;background:rgba(255,255,255,.03);border:1px solid var(--border)}
.risk-signal .severity{min-width:65px;font-size:10px;font-weight:700;text-transform:uppercase;padding:3px 8px;border-radius:4px;text-align:center}
.risk-signal .detail{font-size:12px;flex:1}
.scroll-table{max-height:400px;overflow-y:auto;border-radius:8px;border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:7px 10px;border-bottom:2px solid var(--border);color:var(--muted);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.5px;position:sticky;top:0;background:var(--card);z-index:1}
td{padding:5px 10px;border-bottom:1px solid rgba(51,65,85,.5)}
tr:hover{background:rgba(255,255,255,.03)}
.value{text-align:right;font-weight:600;font-family:monospace}
.overrun{color:var(--danger)}
.entity-name{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}
.nif{font-family:monospace;font-size:11px;color:var(--muted)}
.flag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600}
.flag-critical{background:var(--danger);color:white}
.flag-warning{background:var(--accent);color:#0f172a}
.flag-info{background:var(--info);color:white}
.flag-ok{background:var(--success);color:#0f172a}
.footer{text-align:center;color:var(--muted);font-size:11px;margin-top:24px;padding:12px;border-top:1px solid var(--border)}
@media(max-width:800px){.chart-grid{grid-template-columns:1fr}.summary-row{grid-template-columns:repeat(2,1fr)}.header{flex-direction:column}}
</style>''')

    p.append('</head><body><div class="container">')

    # ── Header ────────────────────────────────────────────────────────────
    r_color = risk_colors.get(risk_level, "#94a3b8")
    p.append(f'<div class="header"><div><h1>🛡️ Analisa.pt — Unified Intelligence Dashboard</h1>')
    p.append(f'<div class="sub">{active_dbs}/{len(DB_PATHS)} databases connected — Generated {gen_time}</div></div>')
    p.append(f'<div class="header-right"><div class="live-badge">● LIVE</div>')
    p.append(f'<div class="risk-badge" style="background:{r_color};color:#0f172a">{risk_level.upper()} RISK</div></div></div>')

    # ── Database Status ───────────────────────────────────────────────────
    p.append('<div class="db-grid">')
    for name in DB_PATHS:
        ok = db_available.get(name, False)
        p.append(f'<div class="db-chip"><div class="db-dot {"ok" if ok else "miss"}"></div>{esc(name)}</div>')
    p.append('</div>')

    # ── Summary Cards ─────────────────────────────────────────────────────
    p.append('<div class="summary-row">')
    cards = []
    yr = procurement.get("year_range", "")

    # Justice cards
    cj_latest = cor_cj.get(max(cor_cj.keys())) if cor_cj else 0
    bl_latest = cor_bl.get(max(cor_bl.keys())) if cor_bl else 0
    cj_dir = crossref.get("corruption_direction", "")
    bl_dir = crossref.get("laundering_direction", "")
    if court_data:
        latest_court = court_data[-1]
        cards.append(("⚖️", fmt_num(int(cj_latest)) if cj_latest else "—", "Corruption Cases", cj_dir))
        cards.append(("💸", fmt_num(int(bl_latest)) if bl_latest else "—", "Money Laundering", bl_dir))
        cards.append(("🏛️", fmt_num(latest_court.get("pending", 0)), f"Cases Pending ({latest_court['year']})", ""))
    if prison_data:
        cards.append(("🔒", fmt_num(prison_data[-1].get("total", 0)), f"Prison Pop ({prison_data[-1]['year']})", ""))

    # Procurement cards
    if ps:
        cards.append(("📊", fmt_num(ps.get("total", 0)), "Procurement Contracts", yr))
        cards.append(("💰", fmt(ps.get("value", 0)), "Total Contract Value", yr))
        cards.append(("⚠️", f"{ps.get('direct_rate', 0)}%", "Direct Award Rate", yr))
        cards.append(("📈", f"{ps.get('inflation_rate', 0)}%", "Price Inflation Rate", ">5% overrun"))
        if ps.get("self_ref", 0) > 0:
            cards.append(("🔄", fmt_num(ps["self_ref"]), "Self-Referencing", "buyer=seller"))

    # INE cards
    if imm_values:
        latest_imm = imm_values[-1]
        imm_str = f"{latest_imm/1_000_000:.1f}M" if latest_imm >= 1_000_000 else f"{latest_imm/1_000:.0f}K" if latest_imm >= 1_000 else f"{int(latest_imm):,}"
        imm_growth = ""
        if len(imm_values) >= 2 and imm_values[-2] > 0:
            g = ((imm_values[-1] - imm_values[-2]) / imm_values[-2]) * 100
            imm_growth = f"{g:+.1f}% YoY"
        cards.append(("🌍", imm_str, f"Foreign Residents ({imm_years[-1]})", imm_growth))
    if crime_values:
        cards.append(("🔴", f"{crime_values[-1]:.1f}", f"Crime Rate INE ({crime_years[-1]})", ""))
    if pen_values:
        pen_str = f"{pen_values[-1]/1_000_000:.1f}M" if pen_values[-1] >= 1_000_000 else fmt_num(pen_values[-1])
        cards.append(("👴", pen_str, f"Pensioners SS ({pen_years[-1]})", ""))
    if pen_val_values:
        cards.append(("💶", f"€{pen_val_values[-1]:,.0f}", f"Avg Pension ({pen_val_years[-1]})", ""))

    # Transparency cards
    prr_val = transparency.get("prr_value", 0)
    if prr_val:
        prr_paid = transparency.get("prr_paid", 0) or 0
        prr_exec = round(prr_paid / prr_val * 100, 1) if prr_val > 0 else 0
        cards.append(("🇪🇺", fmt(prr_val), "PRR Contracted", f"{prr_exec}% executed"))
    ted = transparency.get("ted_notices", 0)
    if ted:
        cards.append(("📋", fmt_num(ted), "TED Notices", "EU procurement"))

    for icon, value, label, sub in cards:
        p.append(f'<div class="summary-card"><div class="sc-icon">{icon}</div><div class="sc-value">{value}</div><div class="sc-label">{label}</div>')
        if sub:
            p.append(f'<div class="sc-sub">{esc(sub)}</div>')
        p.append('</div>')
    p.append('</div>')

    # ── Risk Panel ────────────────────────────────────────────────────────
    if risk_signals or risk_level != "unknown":
        p.append(f'<div class="risk-panel" style="border-color:{r_color};background:{risk_bg.get(risk_level, "transparent")}">')
        p.append(f'<h3 style="color:{r_color}">🎯 Composite Risk Score: {composite} — {risk_level.upper()}</h3>')
        if risk_signals:
            for sig in risk_signals:
                sev = sig.get("severity", "unknown")
                sev_color = {"high": "#ef4444", "medium": "#f59e0b"}.get(sev, "#94a3b8")
                p.append(f'<div class="risk-signal"><div class="severity" style="background:{sev_color};color:white">{sev}</div><div class="detail">{esc(sig.get("detail", ""))}</div></div>')
        else:
            p.append('<div style="color:var(--muted);font-size:12px;padding:8px">Run the full pipeline for deep cross-reference analysis.</div>')
        p.append('</div>')

    # ── Tab Bar ───────────────────────────────────────────────────────────
    tabs = [
        ("overview", "📊 Overview"),
        ("justice", "⚖️ Justice"),
        ("procurement", "🏗️ Procurement"),
        ("corruption", "🛡️ Corruption"),
        ("social", "🌍 Social (INE)"),
        ("transparency", "🇪🇺 Transparency"),
        ("crossref", "🔗 Cross-Reference"),
    ]
    p.append('<div class="tab-bar">')
    for i, (tid, label) in enumerate(tabs):
        active = " active" if i == 0 else ""
        p.append(f'<button class="tab-btn{active}" data-tab="{tid}">{label}</button>')
    p.append('</div>')

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: OVERVIEW
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel active" id="panel-overview">')

    # Data source summary
    p.append('<div class="section"><h3>📦 Data Sources</h3>')
    p.append('<div class="scroll-table"><table><thead><tr><th>Database</th><th>Status</th><th>Key Metrics</th></tr></thead><tbody>')
    db_info = [
        ("justice.db", db_available.get("justice", False), f"{len(cor_cj)+len(cor_bl)} corruption obs, {len(court_data)} court years, {len(prison_data)} prison years"),
        ("procurement.db", db_available.get("procurement", False), f"{fmt_num(ps.get('total',0))} contracts, {fmt(ps.get('value',0))}"),
        ("ine_stats.db", db_available.get("ine", False), f"{len(ine['pensionistas'])} pension, {len(ine['crime'])} crime, {len(ine['immigration'])} immigration"),
        ("transparency.db", db_available.get("transparency", False), f"{fmt_num(transparency.get('prr_entities',0))} PRR entities"),
        ("anuncios_index.db", db_available.get("anuncios", False), "Tender announcements"),
        ("modificacoes_index.db", db_available.get("modifications", False), "Contract modifications"),
    ]
    for name, avail, metrics in db_info:
        status = "✅" if avail else "❌"
        p.append(f'<tr><td>{esc(name)}</td><td>{status}</td><td style="color:var(--muted);font-size:11px">{esc(metrics)}</td></tr>')
    p.append('</tbody></table></div></div>')

    # Domain summary cards
    p.append('<div class="section"><h3>📈 Domain Summary</h3>')
    p.append('<div class="scroll-table"><table><thead><tr><th>Domain</th><th>Key Indicator</th><th>Value</th><th>Trend</th></tr></thead><tbody>')
    domains = []
    if cj_latest:
        domains.append(("⚖️ Justice", f"Corruption cases ({max(cor_cj.keys())})", fmt_num(int(cj_latest)), crossref.get("corruption_direction", "—")))
    if bl_latest:
        domains.append(("💸 Financial Crime", f"Money laundering ({max(cor_bl.keys())})", fmt_num(int(bl_latest)), crossref.get("laundering_direction", "—")))
    if court_data:
        domains.append(("🏛️ Courts", f"Pending cases ({court_data[-1]['year']})", fmt_num(court_data[-1]["pending"]), ""))
    if prison_data:
        domains.append(("🔒 Prisons", f"Population ({prison_data[-1]['year']})", fmt_num(prison_data[-1]["total"]), ""))
    if ps.get("total"):
        domains.append(("🏗️ Procurement", f"Contracts ({yr})", fmt_num(ps["total"]), f"{ps['direct_rate']}% direct"))
    if ps.get("inflation_rate"):
        domains.append(("📈 Price Integrity", f"Inflation rate ({yr})", f"{ps['inflation_rate']}%", ""))
    if imm_values:
        domains.append(("🌍 Immigration", f"Foreign residents ({imm_years[-1]})", f"{imm_values[-1]/1_000_000:.1f}M", ""))
    if crime_values:
        domains.append(("🔴 Crime", f"Crime rate ({crime_years[-1]})", f"{crime_values[-1]:.1f}", ""))
    if pen_values:
        domains.append(("👴 Pensions", f"Pensioners ({pen_years[-1]})", f"{pen_values[-1]/1_000_000:.1f}M", ""))
    if prr_val:
        domains.append(("🇪🇺 PRR", "Contracted value", fmt(prr_val), f"{transparency.get('prr_paid',0)/prr_val*100:.0f}% paid"))
    for domain, indicator, value, trend in domains:
        trend_html = f'<span class="flag flag-{"warning" if "rising" in str(trend).lower() else "info"}">{esc(str(trend))}</span>' if trend and trend != "—" else '<span style="color:var(--muted)">—</span>'
        p.append(f'<tr><td style="font-weight:600">{domain}</td><td>{esc(indicator)}</td><td class="value">{value}</td><td>{trend_html}</td></tr>')
    p.append('</tbody></table></div></div>')

    p.append('</div>')  # overview panel

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: JUSTICE
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel" id="panel-justice">')
    p.append('<div class="chart-grid">')

    # Chart: Corruption + ML
    if cor_years:
        p.append('<div class="chart-box"><h3>⚖️ Corruption & Money-Laundering <span class="tag" style="background:rgba(239,68,68,.2);color:#ef4444">JUSTICE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartCorruption"></canvas></div></div>')

    # Chart: Court flow
    if court_data:
        p.append('<div class="chart-box"><h3>🏛️ Court Case Flow <span class="tag" style="background:rgba(59,130,246,.2);color:#3b82f6">JUSTICE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartCourt"></canvas></div></div>')

    # Chart: Prison
    if prison_data:
        p.append('<div class="chart-box"><h3>🔒 Prison Population <span class="tag" style="background:rgba(139,92,246,.2);color:#8b5cf6">JUSTICE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartPrison"></canvas></div></div>')

    p.append('</div>')  # chart-grid

    # Justice data table
    if cor_years:
        p.append('<div class="section"><h3>⚖️ Corruption Case Trends</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>Year</th><th>Corruption (PJ)</th><th>Money Laundering (PJ)</th><th>Total</th><th>YoY</th></tr></thead><tbody>')
        prev_total = None
        for y in cor_years:
            cj = cor_cj.get(y, 0)
            bl = cor_bl.get(y, 0)
            total = cj + bl
            yoy = ""
            if prev_total and prev_total > 0:
                delta = ((total - prev_total) / prev_total) * 100
                color = "#ef4444" if delta > 10 else "#22c55e" if delta < -10 else "#f59e0b"
                yoy = f'<span style="color:{color};font-weight:600">{delta:+.1f}%</span>'
            prev_total = total
            p.append(f'<tr><td>{y}</td><td class="value">{fmt_num(int(cj))}</td><td class="value">{fmt_num(int(bl))}</td><td class="value" style="font-weight:700">{fmt_num(int(total))}</td><td>{yoy}</td></tr>')
        p.append('</tbody></table></div></div>')

    p.append('</div>')  # justice panel

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: PROCUREMENT
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel" id="panel-procurement">')
    p.append('<div class="chart-grid">')

    # Chart: Contracts over time
    if py:
        p.append('<div class="chart-box"><h3>📊 Contracts Over Time <span class="tag" style="background:rgba(245,158,11,.2);color:#f59e0b">PROCUREMENT</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartProcTime"></canvas></div></div>')

    # Chart: Procedure breakdown
    if procurement["procedures"]:
        p.append('<div class="chart-box"><h3>⚙️ Procedure Breakdown <span class="tag" style="background:rgba(59,130,246,.2);color:#3b82f6">PROCUREMENT</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartProcedure"></canvas></div></div>')

    # Chart: Risk distribution
    if procurement["risk_dist"]:
        p.append('<div class="chart-box"><h3>📊 Price Inflation Distribution <span class="tag" style="background:rgba(239,68,68,.2);color:#ef4444">RISK</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartRiskDist"></canvas></div></div>')

    # Chart: Value distribution
    if procurement["value_dist"]:
        p.append('<div class="chart-box"><h3>💰 Contract Value Distribution <span class="tag" style="background:rgba(139,92,246,.2);color:#8b5cf6">PROCUREMENT</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartValueDist"></canvas></div></div>')

    p.append('</div>')  # chart-grid

    # Procedure table
    if procurement["procedures"]:
        p.append('<div class="section"><h3>⚙️ Procurement Procedures</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>Procedure</th><th>Contracts</th><th>Share</th><th>Value</th></tr></thead><tbody>')
        for pr in procurement["procedures"]:
            share = pr["cnt"] * 100 / max(ps.get("total", 1), 1)
            is_direct = "direto" in (pr["tipoprocedimento"] or "").lower() or "ajuste" in (pr["tipoprocedimento"] or "").lower()
            fc = "flag-warning" if is_direct else "flag-info"
            p.append(f'<tr><td>{esc((pr["tipoprocedimento"] or "N/A")[:50])}</td><td class="value">{pr["cnt"]:,}</td><td><span class="flag {fc}">{share:.1f}%</span></td><td class="value">{fmt(pr["val"])}</td></tr>')
        p.append('</tbody></table></div></div>')

    p.append('</div>')  # procurement panel

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: CORRUPTION
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel" id="panel-corruption">')
    p.append('<div class="chart-grid">')

    # Chart: Top inflated
    if corruption["inflated"]:
        p.append('<div class="chart-box"><h3>📈 Top Inflated Contracts <span class="tag" style="background:rgba(239,68,68,.2);color:#ef4444">CORRUPTION</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartInflated"></canvas></div></div>')

    # Chart: Concentration
    if corruption["concentration"]:
        p.append('<div class="chart-box"><h3>🎯 Spending Concentration <span class="tag" style="background:rgba(245,158,11,.2);color:#f59e0b">CORRUPTION</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartConcentration"></canvas></div></div>')

    p.append('</div>')  # chart-grid

    # Self-referencing table
    if corruption["self_ref"]:
        p.append(f'<div class="section"><h3>🔄 Self-Referencing Entities <span class="flag flag-warning">{len(corruption["self_ref"])}</span></h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Value</th><th>Type</th><th>Object</th></tr></thead><tbody>')
        for i, c in enumerate(corruption["self_ref"][:20], 1):
            p.append(f'<tr><td>{i}</td><td class="entity-name">{esc(str(c["buyer"] or "")[:50])}</td><td class="nif">{c["nif"]}</td><td class="value">{fmt(c["valor"])}</td><td>{esc(c["tipo"][:35])}</td><td style="color:var(--muted);font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{esc(c["objeto"][:60])}</td></tr>')
        p.append('</tbody></table></div></div>')

    # Concentration table
    if corruption["concentration"]:
        p.append(f'<div class="section"><h3>🎯 High Concentration Pairs <span class="flag flag-info">{len(corruption["concentration"])}</span></h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Top Supplier</th><th>Share</th><th>#</th><th>Value</th></tr></thead><tbody>')
        for i, c in enumerate(corruption["concentration"][:15], 1):
            sev = "critical" if c["share"] >= 70 else "warning" if c["share"] >= 50 else "info"
            p.append(f'<tr><td>{i}</td><td class="entity-name">{esc(str(c["buyer"] or "")[:45])}</td><td class="entity-name">{esc(c["seller"][:45])}</td><td><span class="flag flag-{sev}">{c["share"]:.0f}%</span></td><td>{c["contracts"]}</td><td class="value">{fmt(c["value"])}</td></tr>')
        p.append('</tbody></table></div></div>')

    # Entity rankings
    if corruption["top_buyers"] or corruption["top_winners"]:
        p.append('<div class="section"><h3>🏛️ Entity Rankings</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Contracts</th><th>As Buyer</th><th>As Winner</th></tr></thead><tbody>')
        # Merge buyers and winners
        all_nifs = {}
        for b in corruption["top_buyers"]:
            nif = b["nifEntidade"]
            all_nifs[nif] = {"name": b["desigEntidade"], "nif": nif, "contracts": b["numContratos"], "buyer_val": b.get("totAdjudicanteValorContratIni") or 0, "winner_val": 0}
        for w in corruption["top_winners"]:
            nif = w["nifEntidade"]
            if nif in all_nifs:
                all_nifs[nif]["winner_val"] = w.get("totValorContratIni") or 0
            else:
                all_nifs[nif] = {"name": w["desigEntidade"], "nif": nif, "contracts": w["numContratos"], "buyer_val": 0, "winner_val": w.get("totValorContratIni") or 0}
        ranked = sorted(all_nifs.values(), key=lambda x: -(x["buyer_val"] + x["winner_val"]))
        for i, e in enumerate(ranked[:15], 1):
            flag = ""
            if e["buyer_val"] > 0 and e["winner_val"] > 0:
                ratio = min(e["winner_val"], e["buyer_val"]) / max(e["winner_val"], e["buyer_val"]) * 100
                if ratio > 50:
                    flag = f'<span class="flag flag-warning">dual role {ratio:.0f}%</span>'
            p.append(f'<tr><td>{i}</td><td class="entity-name">{esc(str(e["name"] or "")[:50])}</td><td class="nif">{e["nif"]}</td><td class="value">{e["contracts"]:,}</td><td class="value" style="color:var(--info)">{fmt(e["buyer_val"])}</td><td class="value" style="color:var(--success)">{fmt(e["winner_val"])} {flag}</td></tr>')
        p.append('</tbody></table></div></div>')

    p.append('</div>')  # corruption panel

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: SOCIAL (INE)
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel" id="panel-social">')
    p.append('<div class="chart-grid">')

    if pen_years:
        p.append('<div class="chart-box"><h3>👴 Pensioners (Social Security) <span class="tag" style="background:rgba(139,92,246,.2);color:#8b5cf6">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartPension"></canvas></div></div>')

    if pen_val_years:
        p.append('<div class="chart-box"><h3>💶 Average Pension Value <span class="tag" style="background:rgba(245,158,11,.2);color:#f59e0b">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartPensionVal"></canvas></div></div>')

    if imm_years:
        p.append('<div class="chart-box"><h3>🌍 Foreign Residents <span class="tag" style="background:rgba(20,184,166,.2);color:#14b8a6">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartImmig"></canvas></div></div>')

    if crime_years:
        p.append('<div class="chart-box"><h3>🔴 Crime Rate <span class="tag" style="background:rgba(239,68,68,.2);color:#ef4444">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartCrime"></canvas></div></div>')

    if demo_years:
        p.append('<div class="chart-box"><h3>👶 Natural Population Growth <span class="tag" style="background:rgba(20,184,166,.2);color:#14b8a6">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartDemo"></canvas></div></div>')

    p.append('</div>')  # chart-grid

    # Social data insights
    p.append('<div class="section"><h3>🌍 Social Indicator Summary</h3>')
    p.append('<div class="scroll-table"><table><thead><tr><th>Indicator</th><th>Latest Year</th><th>Latest Value</th><th>10yr Change</th><th>Trend</th></tr></thead><tbody>')
    social_indicators = []
    if pen_values and len(pen_values) >= 2:
        chg = ((pen_values[-1] - pen_values[-min(11, len(pen_values))]) / pen_values[-min(11, len(pen_values))] * 100) if pen_values[-min(11, len(pen_values))] else 0
        social_indicators.append(("👴 Pensioners (SS)", pen_years[-1], f"{pen_values[-1]/1_000_000:.1f}M", f"{chg:+.1f}%", "rising" if chg > 5 else "falling" if chg < -5 else "stable"))
    if pen_val_values and len(pen_val_values) >= 2:
        chg = ((pen_val_values[-1] - pen_val_values[-min(11, len(pen_val_values))]) / pen_val_values[-min(11, len(pen_val_values))] * 100) if pen_val_values[-min(11, len(pen_val_values))] else 0
        social_indicators.append(("💶 Avg Pension", pen_val_years[-1], f"€{pen_val_values[-1]:,.0f}", f"{chg:+.1f}%", "rising" if chg > 5 else "falling" if chg < -5 else "stable"))
    if imm_values and len(imm_values) >= 2:
        chg = ((imm_values[-1] - imm_values[-min(11, len(imm_values))]) / imm_values[-min(11, len(imm_values))] * 100) if imm_values[-min(11, len(imm_values))] else 0
        social_indicators.append(("🌍 Foreign Residents", imm_years[-1], f"{imm_values[-1]/1_000_000:.1f}M", f"{chg:+.1f}%", "rising" if chg > 5 else "falling" if chg < -5 else "stable"))
    if crime_values and len(crime_values) >= 2:
        chg = ((crime_values[-1] - crime_values[-min(11, len(crime_values))]) / crime_values[-min(11, len(crime_values))] * 100) if crime_values[-min(11, len(crime_values))] else 0
        social_indicators.append(("🔴 Crime Rate", crime_years[-1], f"{crime_values[-1]:.1f}", f"{chg:+.1f}%", "rising" if chg > 10 else "falling" if chg < -10 else "stable"))
    if demo_values and len(demo_values) >= 2:
        chg = demo_values[-1] - demo_values[-min(11, len(demo_values))]
        social_indicators.append(("👶 Natural Growth", demo_years[-1], f"{int(demo_values[-1]):,}", f"{int(chg):+,}", "rising" if chg > 1000 else "falling" if chg < -1000 else "stable"))
    for label, year, value, change, trend in social_indicators:
        tc = "warning" if trend == "rising" and "Crime" in label else "ok" if trend == "stable" else "info"
        if "Pensioners" in label and trend == "rising":
            tc = "warning"
        if "Natural Growth" in label and trend == "falling":
            tc = "critical"
        p.append(f'<tr><td style="font-weight:600">{label}</td><td>{year}</td><td class="value">{value}</td><td class="value">{change}</td><td><span class="flag flag-{tc}">{trend}</span></td></tr>')
    p.append('</tbody></table></div></div>')

    p.append('</div>')  # social panel

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: TRANSPARENCY
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel" id="panel-transparency">')

    if prr_val:
        prr_paid = transparency.get("prr_paid", 0) or 0
        prr_exec = round(prr_paid / prr_val * 100, 1) if prr_val > 0 else 0
        p.append('<div class="section"><h3>🇪🇺 PRR (EU Recovery Fund)</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>')
        p.append(f'<tr><td>Total Contracted</td><td class="value">{fmt(prr_val)}</td></tr>')
        p.append(f'<tr><td>Total Paid</td><td class="value">{fmt(prr_paid)} ({prr_exec}%)</td></tr>')
        p.append(f'<tr><td>Projects</td><td class="value">{fmt_num(transparency.get("prr_projects", 0))}</td></tr>')
        p.append(f'<tr><td>Project Value</td><td class="value">{fmt(transparency.get("prr_project_value", 0))}</td></tr>')
        p.append('</tbody></table></div></div>')

    if transparency.get("budget_previsto"):
        bp = transparency["budget_previsto"]
        br = transparency.get("budget_realizado", 0)
        be = round(br / bp * 100, 1) if bp > 0 else 0
        p.append('<div class="section"><h3>💶 Budget Execution</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>')
        p.append(f'<tr><td>Budget (Previsto)</td><td class="value">{fmt(bp)}</td></tr>')
        p.append(f'<tr><td>Executed (Realizado)</td><td class="value">{fmt(br)} ({be}%)</td></tr>')
        p.append('</tbody></table></div></div>')

    if ted:
        p.append(f'<div class="section"><h3>📋 TED (EU Procurement Notices) — {fmt_num(ted)} notices</h3>')
        p.append('<div style="color:var(--muted);font-size:13px;padding:8px">TED notices are cross-referenced with procurement contracts to detect compliance gaps.</div></div>')

    if not prr_val and not transparency.get("budget_previsto"):
        p.append('<div class="section" style="text-align:center;padding:40px;color:var(--muted)"><div style="font-size:24px;margin-bottom:8px">📦</div>No transparency data available.<br>Ensure transparency.db exists with PRR/budget tables.</div>')

    p.append('</div>')  # transparency panel

    # ══════════════════════════════════════════════════════════════════════
    #  TAB: CROSS-REFERENCE
    # ══════════════════════════════════════════════════════════════════════
    p.append('<div class="tab-panel" id="panel-crossref">')

    # Risk radar chart
    p.append('<div class="chart-grid">')
    p.append('<div class="chart-box"><h3>🎯 Risk Signal Overview <span class="tag" style="background:rgba(245,158,11,.2);color:#f59e0b">CROSS-REF</span></h3>')
    p.append('<div class="chart-container"><canvas id="chartRadar"></canvas></div></div>')

    # Immigration vs Crime correlation
    if imm_years and crime_years:
        overlap_y = sorted(set(imm_years) & set(crime_years))
        if len(overlap_y) >= 3:
            p.append('<div class="chart-box"><h3>🌍 Immigration vs Crime Rate <span class="tag" style="background:rgba(20,184,166,.2);color:#14b8a6">CORRELATION</span></h3>')
            p.append('<div class="chart-container"><canvas id="chartImmigCrime"></canvas></div></div>')
    p.append('</div>')  # chart-grid

    # Cross-reference insights table
    p.append('<div class="section"><h3>🔗 Cross-Domain Insights</h3>')
    p.append('<div class="scroll-table"><table><thead><tr><th>Insight</th><th>Domain A</th><th>Domain B</th><th>Status</th></tr></thead><tbody>')
    insights = []
    if crossref.get("corruption_direction") == "rising" and ps.get("direct_rate", 0) > 50:
        insights.append(("Rising corruption + high direct awards", "Justice", "Procurement", "critical"))
    if crossref.get("laundering_direction") == "rising":
        insights.append(("Money laundering cases surging", "Justice", "Financial Crime", "warning"))
    if ps.get("self_ref", 0) > 0:
        insights.append((f"{ps['self_ref']} self-referencing contracts", "Procurement", "Entity Network", "warning"))
    if imm_values and crime_values:
        overlap = sorted(set(imm_years) & set(crime_years))
        if len(overlap) >= 3:
            imm_v = [next((r["value"] for r in ine["immigration"] if r["year"] == y), 0) for y in overlap]
            cr_v = [next((r["value"] for r in ine["crime"] if r["year"] == y), 0) for y in overlap]
            if len(imm_v) >= 3:
                # Simple correlation check
                mean_i = sum(imm_v) / len(imm_v)
                mean_c = sum(cr_v) / len(cr_v)
                cov = sum((a - mean_i) * (b - mean_c) for a, b in zip(imm_v, cr_v)) / len(imm_v)
                std_i = (sum((a - mean_i) ** 2 for a in imm_v) / len(imm_v)) ** 0.5
                std_c = (sum((b - mean_c) ** 2 for b in cr_v) / len(cr_v)) ** 0.5
                r_val = cov / (std_i * std_c) if std_i > 0 and std_c > 0 else 0
                corr_label = "weak positive" if 0.1 < r_val < 0.5 else "weak negative" if -0.5 < r_val < -0.1 else "no correlation" if abs(r_val) <= 0.1 else "moderate"
                insights.append((f"Immigration × Crime: r={r_val:.2f} ({corr_label})", "INE Immigration", "INE Crime", "ok" if abs(r_val) < 0.3 else "info"))
    if pen_values and len(pen_values) > 5:
        p_dir, p_pct = trend_direction(pen_values)
        if p_dir == "rising" and demo_values and demo_values[-1] < 0:
            insights.append(("Growing pensioners + negative natural growth = demographic pressure", "INE Pensions", "INE Demographics", "warning"))
    if not insights:
        insights.append(("Run the full pipeline to generate cross-reference insights", "—", "—", "info"))
    for insight, dom_a, dom_b, severity in insights:
        p.append(f'<tr><td>{esc(insight)}</td><td>{esc(dom_a)}</td><td>{esc(dom_b)}</td><td><span class="flag flag-{severity}">{severity}</span></td></tr>')
    p.append('</tbody></table></div></div>')

    p.append('</div>')  # crossref panel

    # ── Footer ────────────────────────────────────────────────────────────
    p.append(f'<div class="footer">Analisa.pt Unified Intelligence Dashboard — {active_dbs}/{len(DB_PATHS)} databases — Generated {gen_time}<br>Sources: dados.justica.gov.pt, procurement.db, INE API, transparency.db</div>')

    p.append('</div>')  # container

    # ══════════════════════════════════════════════════════════════════════
    #  JAVASCRIPT
    # ══════════════════════════════════════════════════════════════════════
    chart_defs = 'Chart.defaults.color="#94a3b8";Chart.defaults.borderColor="rgba(51,65,85,.5)";'
    p.append(f'<script>{chart_defs}')

    # Corruption + ML chart
    if cor_years:
        p.append(f'new Chart(document.getElementById("chartCorruption"),{{type:"line",data:{{labels:{json.dumps(cor_years)},datasets:['
                 f'{{label:"Corruption Cases",data:{json.dumps([cor_cj.get(y, 0) for y in cor_years])},borderColor:"#ef4444",backgroundColor:"rgba(239,68,68,.1)",fill:true,tension:.3,pointRadius:3}},'
                 f'{{label:"Money Laundering",data:{json.dumps([cor_bl.get(y, 0) for y in cor_years])},borderColor:"#f97316",backgroundColor:"rgba(249,115,22,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{font:{{size:11}}}}}}}},scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Court flow chart
    if court_data:
        p.append(f'new Chart(document.getElementById("chartCourt"),{{type:"bar",data:{{labels:{json.dumps([r["year"] for r in court_data])},datasets:['
                 f'{{label:"Entered",data:{json.dumps([r["entered"] for r in court_data])},backgroundColor:"rgba(59,130,246,.7)",borderRadius:3}},'
                 f'{{label:"Finalized",data:{json.dumps([r["finalized"] for r in court_data])},backgroundColor:"rgba(34,197,94,.7)",borderRadius:3}},'
                 f'{{label:"Pending",data:{json.dumps([r["pending"] for r in court_data])},type:"line",borderColor:"#ef4444",borderWidth:2,pointRadius:2,tension:.3,yAxisID:"y1"}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:"index"}},scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}},callback:v=>v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}},y1:{{position:"right",grid:{{drawOnChartArea:false}},ticks:{{font:{{size:10}},callback:v=>v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}}}}}}}});')

    # Prison chart
    if prison_data:
        p.append(f'new Chart(document.getElementById("chartPrison"),{{type:"line",data:{{labels:{json.dumps([r["year"] for r in prison_data])},datasets:['
                 f'{{label:"Prison Population",data:{json.dumps([r["total"] for r in prison_data])},borderColor:"#8b5cf6",backgroundColor:"rgba(139,92,246,.15)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{font:{{size:11}}}}}}}},scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Procurement over time
    if py:
        p.append(f'new Chart(document.getElementById("chartProcTime"),{{type:"bar",data:{{labels:{json.dumps([r["year"] for r in py])},datasets:['
                 f'{{label:"Contracts",data:{json.dumps([r["cnt"] for r in py])},backgroundColor:"rgba(245,158,11,.7)",borderRadius:3,yAxisID:"y"}},'
                 f'{{label:"Value (EUR)",data:{json.dumps([round(r["val"], 0) for r in py])},type:"line",borderColor:"#ef4444",borderWidth:2,pointRadius:2,tension:.3,yAxisID:"y1"}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:"index"}},scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}}}}}},y1:{{position:"right",grid:{{drawOnChartArea:false}},ticks:{{font:{{size:10}},callback:v=>v>=1e9?(v/1e9).toFixed(0)+"B":v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}}}}}}}});')

    # Procedure doughnut
    if procurement["procedures"]:
        procs = procurement["procedures"][:8]
        p.append(f'new Chart(document.getElementById("chartProcedure"),{{type:"doughnut",data:{{labels:{json.dumps([pr["tipoprocedimento"][:25] for pr in procs])},datasets:['
                 f'{{data:{json.dumps([pr["cnt"] for pr in procs])},backgroundColor:["#f59e0b","#3b82f6","#22c55e","#ef4444","#8b5cf6","#ec4899","#14b8a6","#f97316"],borderWidth:0}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:"right",labels:{{font:{{size:11}},padding:8,color:"#e2e8f0"}}}}}}}}}});')

    # Risk distribution
    if procurement["risk_dist"]:
        p.append(f'new Chart(document.getElementById("chartRiskDist"),{{type:"bar",data:{{labels:{json.dumps([r["bucket"] for r in procurement["risk_dist"]])},datasets:['
                 f'{{label:"Contracts",data:{json.dumps([r["cnt"] for r in procurement["risk_dist"]])},backgroundColor:["#22c55e","#84cc16","#f59e0b","#f97316","#ef4444","#dc2626"],borderRadius:4}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true}}}}}}}});')

    # Value distribution
    if procurement["value_dist"]:
        p.append(f'new Chart(document.getElementById("chartValueDist"),{{type:"doughnut",data:{{labels:{json.dumps([r["bucket"] for r in procurement["value_dist"]])},datasets:['
                 f'{{data:{json.dumps([r["cnt"] for r in procurement["value_dist"]])},backgroundColor:["#3b82f6","#6366f1","#8b5cf6","#a855f7","#d946ef","#ec4899","#f43f5e"],borderWidth:0}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:"right",labels:{{font:{{size:11}},color:"#e2e8f0"}}}}}}}}}});')

    # Inflated contracts chart
    if corruption["inflated"]:
        inf = corruption["inflated"][:12]
        p.append(f'new Chart(document.getElementById("chartInflated"),{{type:"bar",data:{{labels:{json.dumps([c["objectoContrato"][:35] if c["objectoContrato"] else c["adjudicante_nome"][:35] for c in inf])},datasets:['
                 f'{{label:"Overrun",data:{json.dumps([c["overrun"] for c in inf])},backgroundColor:"rgba(239,68,68,.7)",borderRadius:4}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,indexAxis:"y",plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{callback:v=>v>=1e6?"E"+(v/1e6).toFixed(0)+"M":"E"+(v/1e3).toFixed(0)+"K"}}}}}}}}}});')

    # Concentration chart
    if corruption["concentration"]:
        conc = corruption["concentration"][:10]
        p.append(f'new Chart(document.getElementById("chartConcentration"),{{type:"bar",data:{{labels:{json.dumps([c["buyer"][:30] if c["buyer"] else "N/A" for c in conc])},datasets:['
                 f'{{label:"Share %",data:{json.dumps([c["share"] for c in conc])},backgroundColor:{json.dumps(["rgba(220,38,38,.7)" if c["share"]>=70 else "rgba(245,158,11,.7)" if c["share"]>=50 else "rgba(59,130,246,.7)" for c in conc])},borderRadius:4}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,indexAxis:"y",plugins:{{legend:{{display:false}}}},scales:{{x:{{max:100,ticks:{{callback:v=>v+"%"}}}}}}}}}});')

    # Pension chart
    if pen_years:
        p.append(f'new Chart(document.getElementById("chartPension"),{{type:"line",data:{{labels:{json.dumps(pen_years)},datasets:['
                 f'{{label:"Pensioners",data:{json.dumps(pen_values)},borderColor:"#8b5cf6",backgroundColor:"rgba(139,92,246,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}},callback:v=>v>=1e6?(v/1e6).toFixed(1)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}}}}}}}});')

    # Pension value chart
    if pen_val_years:
        p.append(f'new Chart(document.getElementById("chartPensionVal"),{{type:"line",data:{{labels:{json.dumps(pen_val_years)},datasets:['
                 f'{{label:"Avg Pension (EUR)",data:{json.dumps(pen_val_values)},borderColor:"#f59e0b",backgroundColor:"rgba(245,158,11,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}},callback:v=>"E"+v}}}}}}}}}});')

    # Immigration chart
    if imm_years:
        p.append(f'new Chart(document.getElementById("chartImmig"),{{type:"line",data:{{labels:{json.dumps(imm_years)},datasets:['
                 f'{{label:"Foreign Residents",data:{json.dumps(imm_values)},borderColor:"#14b8a6",backgroundColor:"rgba(20,184,166,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}},callback:v=>v>=1e6?(v/1e6).toFixed(1)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}}}}}}}});')

    # Crime rate chart
    if crime_years:
        p.append(f'new Chart(document.getElementById("chartCrime"),{{type:"line",data:{{labels:{json.dumps(crime_years)},datasets:['
                 f'{{label:"Crime Rate",data:{json.dumps(crime_values)},borderColor:"#ef4444",backgroundColor:"rgba(239,68,68,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Demographics chart
    if demo_years:
        p.append(f'new Chart(document.getElementById("chartDemo"),{{type:"bar",data:{{labels:{json.dumps(demo_years)},datasets:['
                 f'{{label:"Natural Growth",data:{json.dumps(demo_values)},backgroundColor:{json.dumps(["rgba(34,197,94,.7)" if v >= 0 else "rgba(239,68,68,.7)" for v in demo_values])},borderRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{ticks:{{font:{{size:10}},callback:v=>v>=1000?(v/1000).toFixed(0)+"K":v}}}}}}}}}});')

    # Radar chart
    radar_labels = ["Corruption Trend", "ML Trend", "Court Backlog", "Direct Awards", "Price Inflation"]
    radar_values = [
        1 if crossref.get("corruption_direction") == "rising" else 0.5 if crossref.get("corruption_direction") == "stable" else 0.2,
        1 if crossref.get("laundering_direction") == "rising" else 0.5 if crossref.get("laundering_direction") == "stable" else 0.2,
        min(crossref.get("court_trend", [{}])[-1].get("pending", 0) / max(crossref.get("court_trend", [{}])[-1].get("entered", 1), 1), 1) if crossref.get("court_trend") else 0.5,
        min(ps.get("direct_rate", 0) / 100, 1),
        min(ps.get("inflation_rate", 0) / 50, 1),
    ]
    p.append(f'new Chart(document.getElementById("chartRadar"),{{type:"radar",data:{{labels:{json.dumps(radar_labels)},datasets:['
             f'{{label:"Risk Level",data:{json.dumps(radar_values)},borderColor:"#f59e0b",backgroundColor:"rgba(245,158,11,.2)",pointBackgroundColor:"#f59e0b",pointRadius:4}}'
             f']}},options:{{responsive:true,maintainAspectRatio:false,scales:{{r:{{beginAtZero:true,max:1,ticks:{{display:false}},grid:{{color:"rgba(51,65,85,.5)"}},pointLabels:{{font:{{size:11}},color:"#e2e8f0"}}}}}},plugins:{{legend:{{display:false}}}}}}}});')

    # Immigration vs Crime scatter
    if imm_years and crime_years:
        overlap_y = sorted(set(imm_years) & set(crime_years))
        if len(overlap_y) >= 3:
            scatter_data = []
            for y in overlap_y:
                iv = next((r["value"] for r in ine["immigration"] if r["year"] == y), None)
                cv = next((r["value"] for r in ine["crime"] if r["year"] == y), None)
                if iv is not None and cv is not None:
                    scatter_data.append({"x": round(iv / 1_000_000, 2), "y": cv})
            p.append(f'new Chart(document.getElementById("chartImmigCrime"),{{type:"scatter",data:{{datasets:['
                     f'{{label:"Year",data:{json.dumps(scatter_data)},backgroundColor:"rgba(20,184,166,.7)",pointRadius:6}}'
                     f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{title:{{display:true,text:"Foreign Residents (M)",color:"#94a3b8"}},ticks:{{font:{{size:10}}}}}},y:{{title:{{display:true,text:"Crime Rate",color:"#94a3b8"}},ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Tab switching
    p.append('''document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});''')

    p.append('</script></body></html>')

    return "".join(p)


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Unified Analisa.pt Dashboard")
    parser.add_argument("-o", "--output", default=str(SUMMARY_DIR / "unified_dashboard.html"))
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")
    args = parser.parse_args()

    print("  Querying all databases...", file=sys.stderr)
    html = generate_unified_dashboard()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✅ Unified dashboard written to {out_path} ({len(html):,} bytes)", file=sys.stderr)

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
