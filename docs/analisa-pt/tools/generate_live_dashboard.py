#!/usr/bin/env python3
"""Live Dashboard Generator — Reads directly from all SQLite databases.

Unlike generate_dashboard.py (which reads consolidated.json snapshots),
this tool queries the actual databases on every run, so the dashboard
always reflects the latest data.

Handles:
  - 9 SQLite databases with graceful missing-DB fallback
  - Dynamic metric computation (anomalies, inflation, concentration, etc.)
  - Temporal trends (contracts over time, spending patterns)
  - Extensible sections (new DBs = new tabs automatically)

Usage:
    python generate_live_dashboard.py                          # Full dashboard
    python generate_live_dashboard.py -o live.html             # Custom output
    python generate_live_dashboard.py --open                   # Generate + open in browser
    python generate_live_dashboard.py --concelho "Fundão"      # Include concelho deep-dive
"""

import json
import os
import re
import sqlite3
import argparse
import webbrowser
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from utils import fmt
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"

# ── Database paths ────────────────────────────────────────────────────────────
DB_PATHS = {
    "procurement": DATA_DIR / "procurement.db",
    "transparency": DATA_DIR / "transparency.db",
    "bep": SCRIPT_DIR / "bep_index.db",
    "dre": SCRIPT_DIR / "dre_index.db",
    "law": SCRIPT_DIR / "law_index.db",
    "ted": DATA_DIR / "ted_notices.db",
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
    """Open a database connection, returning None if not found."""
    path = DB_PATHS.get(name)
    if not path or not path.exists():
        return None
    try:
        conn = db_connect(str(path))
        return conn
    except Exception:
        return None


def table_exists(conn, name):
    """Check if a table exists in the connected database."""
    try:
        r = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        return r[0] > 0
    except Exception:
        return False


def safe_query(conn, sql, params=()):
    """Execute a query safely, returning results or empty list."""
    if not conn:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def safe_scalar(conn, sql, params=()):
    """Execute a query safely, returning a single scalar value."""
    if not conn:
        return 0
    try:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else 0
    except Exception:
        return 0


# ═════════════════════════════════════════════════════════════════════════════
#  DATA QUERIES — Each section queries its own database
# ═════════════════════════════════════════════════════════════════════════════

def query_procurement_overview(conn):
    """Core procurement statistics from procurement.db."""
    if not conn or not table_exists(conn, "contratos"):
        return {"error": "procurement.db not available"}

    tc = safe_scalar(conn, "SELECT COUNT(*) FROM contratos")
    tv = safe_scalar(conn, "SELECT SUM(COALESCE(precoContratual, 0)) FROM contratos")
    buyers = safe_scalar(conn, "SELECT COUNT(DISTINCT adjudicante_nif) FROM contratos WHERE adjudicante_nif != '' AND adjudicante_nif != '-'")
    direct = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE tipoprocedimento LIKE '%ajuste%' OR tipoprocedimento LIKE '%direto%'")
    public = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE tipoprocedimento LIKE '%concurso%'")
    inflated = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento")
    overrun = safe_scalar(conn, "SELECT SUM(precoContratual - precoBaseProcedimento) FROM contratos WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento")
    with_base = max(safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE precoBaseProcedimento > 0"), 1)
    entities = safe_scalar(conn, "SELECT COUNT(*) FROM entidades") if table_exists(conn, "entidades") else 0

    # Self-referencing
    self_ref_count = 0
    if table_exists(conn, "contratos"):
        rows = safe_query(conn, "SELECT adjudicante_nif, adjudicatarios FROM contratos WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' AND adjudicante_nif IS NOT NULL AND adjudicante_nif != '' LIMIT 50000")
        for r in rows:
            adj_nif = r["adjudicante_nif"]
            adjt = str(r["adjudicatarios"] or "")
            if " - " in adjt:
                for part in adjt.split(";"):
                    m = re.match(r"(\d{9})\s*-\s*", part.strip())
                    if m and m.group(1) == adj_nif:
                        self_ref_count += 1
                        break

    return {
        "total_contracts": tc,
        "total_value": tv,
        "unique_buyers": buyers,
        "unique_entities": entities,
        "direct_awards": direct,
        "public_tenders": public,
        "inflated_count": inflated,
        "total_overrun": overrun,
        "with_base_price": with_base,
        "inflation_rate": round(inflated * 100 / with_base, 1),
        "direct_rate": round(direct * 100 / max(tc, 1), 1),
        "self_referencing": self_ref_count,
    }


def query_top_inflated(conn, limit=20):
    """Top inflated contracts."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
               precoBaseProcedimento, precoContratual,
               (precoContratual - precoBaseProcedimento) as overrun,
               ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) as pct,
               objectoContrato
        FROM contratos
        WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento
        ORDER BY overrun DESC LIMIT ?
    """, (limit,))
    return [dict(r) for r in rows]


def query_top_concentration(conn, limit=20):
    """Buyer-seller concentration pairs."""
    if not conn:
        return []
    # Get buyer totals
    buyer_totals = {}
    for r in safe_query(conn, "SELECT adjudicante_nif, SUM(precoContratual) as total FROM contratos WHERE adjudicante_nif IS NOT NULL GROUP BY adjudicante_nif"):
        buyer_totals[r["adjudicante_nif"]] = r["total"] or 0

    rows = safe_query(conn, """
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
               SUM(precoContratual) as pair_total, COUNT(*) as cnt
        FROM contratos
        WHERE adjudicante_nif IS NOT NULL AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
        GROUP BY adjudicante_nif, adjudicatarios
        HAVING pair_total >= 500000
        ORDER BY pair_total DESC LIMIT ?
    """, (limit * 3,))

    result = []
    for r in rows:
        bt = buyer_totals.get(r["adjudicante_nif"], 0)
        if bt > 0:
            share = (r["pair_total"] * 100.0) / bt
            if share >= 30:
                result.append({
                    "buyer_nif": r["adjudicante_nif"],
                    "buyer": r["adjudicante_nome"],
                    "seller": (r["adjudicatarios"] or "")[:60],
                    "share": round(share, 1),
                    "contracts": r["cnt"],
                    "value": r["pair_total"],
                    "buyer_total": bt,
                })
    result.sort(key=lambda x: -x["value"])
    return result[:limit]


def query_temporal_trends(conn):
    """Contracts over time — monthly breakdown."""
    if not conn:
        return {}
    rows = safe_query(conn, """
        SELECT SUBSTR(dataCelebracaoContrato, 1, 7) as month,
               COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val
        FROM contratos
        WHERE dataCelebracaoContrato IS NOT NULL AND dataCelebracaoContrato != ''
        GROUP BY month HAVING cnt >= 5
        ORDER BY month
    """)
    months = [dict(r) for r in rows]

    # December surge analysis
    dec_data = [r for r in months if r["month"] and r["month"].endswith("-12")]
    other_data = [r for r in months if r["month"] and not r["month"].endswith("-12")]
    avg_other = sum(r["val"] for r in other_data) / max(len(other_data), 1)
    dec_total = sum(r["val"] for r in dec_data)
    dec_ratio = dec_total / max(avg_other * len(dec_data), 1) if dec_data else 0

    return {
        "months": months,
        "dec_ratio": round(dec_ratio, 2),
        "is_surge": dec_ratio >= 2.0,
        "total_months": len(months),
    }


def query_procedure_breakdown(conn):
    """Procurement procedure type breakdown."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT tipoprocedimento, COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val
        FROM contratos WHERE tipoprocedimento IS NOT NULL AND tipoprocedimento != ''
        GROUP BY tipoprocedimento ORDER BY cnt DESC LIMIT 10
    """)
    return [dict(r) for r in rows]


def query_transparency_overview(conn):
    """PRR + budget overview from transparency.db."""
    if not conn:
        return {"error": "transparency.db not available"}

    result = {}
    if table_exists(conn, "prr_entities"):
        result["prr_entities"] = safe_scalar(conn, "SELECT COUNT(*) FROM prr_entities WHERE nif != '' AND nif IS NOT NULL")
        result["prr_value"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_contratado, 0)) FROM prr_entities")
        result["prr_paid"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_pago, 0)) FROM prr_entities")
    if table_exists(conn, "prr_contracts"):
        result["prr_contracts"] = safe_scalar(conn, "SELECT COUNT(*) FROM prr_contracts")
    if table_exists(conn, "prr_projects"):
        result["prr_projects"] = safe_scalar(conn, "SELECT COUNT(*) FROM prr_projects")
        result["prr_project_value"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_aprovado, 0)) FROM prr_projects")
    if table_exists(conn, "budget"):
        result["budget_rows"] = safe_scalar(conn, "SELECT COUNT(*) FROM budget")
        result["budget_previsto"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_previsto, 0)) FROM budget")
        result["budget_realizado"] = safe_scalar(conn, "SELECT SUM(COALESCE(valor_realizado, 0)) FROM budget")
    return result


def query_bep_overview(conn):
    """BEP job listings overview."""
    if not conn:
        return {"error": "bep_index.db not available"}
    result = {}
    if table_exists(conn, "bep_entities"):
        result["total_entities"] = safe_scalar(conn, "SELECT COUNT(*) FROM bep_entities")
        result["total_listings"] = safe_scalar(conn, "SELECT SUM(listing_count) FROM bep_entities")
    if table_exists(conn, "bep_listings"):
        result["actual_listings"] = safe_scalar(conn, "SELECT COUNT(*) FROM bep_listings")
    return result


def query_dre_overview(conn):
    """DRE publications overview."""
    if not conn:
        return {"error": "dre_index.db not available"}
    result = {}
    if table_exists(conn, "dre_publications"):
        result["total_publications"] = safe_scalar(conn, "SELECT COUNT(*) FROM dre_publications")
        result["total_appointments"] = safe_scalar(conn, "SELECT COUNT(*) FROM dre_publications WHERE title LIKE '%nomeação%' OR title LIKE '%Nomeação%' OR title LIKE '%nomeia%' OR title LIKE '%Nomeia%'")
    return result


def query_law_overview(conn):
    """Parliamentary law projects overview."""
    if not conn:
        return {"error": "law_index.db not available"}
    result = {}
    if table_exists(conn, "law_projects"):
        result["total_projects"] = safe_scalar(conn, "SELECT COUNT(*) FROM law_projects")
    return result


def query_ted_overview(conn):
    """EU TED notices overview."""
    if not conn:
        return {"error": "ted_notices.db not available"}
    result = {}
    if table_exists(conn, "ted_notices"):
        result["total_notices"] = safe_scalar(conn, "SELECT COUNT(*) FROM ted_notices")
    return result


def query_modifications_overview(conn):
    """Contract modifications overview."""
    if not conn:
        return {"error": "modificacoes_index.db not available"}
    result = {}
    if table_exists(conn, "modificacoes"):
        result["total_modifications"] = safe_scalar(conn, "SELECT COUNT(*) FROM modificacoes")
        result["unique_contracts"] = safe_scalar(conn, "SELECT COUNT(DISTINCT idcontrato) FROM modificacoes")
        result["total_value_change"] = safe_scalar(conn, "SELECT SUM(COALESCE(preco_alterado, 0)) FROM modificacoes")
    return result


def query_risk_distribution(conn):
    """Distribution of contract inflation rates for risk histogram."""
    if not conn or not table_exists(conn, "contratos"):
        return []
    rows = safe_query(conn, """
        SELECT 
            CASE 
                WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 0 THEN '0% or less'
                WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 5 THEN '1-5%'
                WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 10 THEN '5-10%'
                WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 20 THEN '10-20%'
                WHEN ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) <= 50 THEN '20-50%'
                ELSE '50%+'
            END as risk_bucket,
            COUNT(*) as cnt
        FROM contratos 
        WHERE precoBaseProcedimento > 0 AND precoContratual > 0
        GROUP BY risk_bucket
        ORDER BY MIN((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento)
    """)
    return [dict(r) for r in rows]


def query_value_distribution(conn):
    """Distribution of contract values for log-scale histogram."""
    if not conn or not table_exists(conn, "contratos"):
        return []
    rows = safe_query(conn, """
        SELECT 
            CASE 
                WHEN precoContratual < 10000 THEN '<€10K'
                WHEN precoContratual < 50000 THEN '€10K-50K'
                WHEN precoContratual < 100000 THEN '€50K-100K'
                WHEN precoContratual < 500000 THEN '€100K-500K'
                WHEN precoContratual < 1000000 THEN '€500K-1M'
                WHEN precoContratual < 5000000 THEN '€1M-5M'
                ELSE '€5M+'
            END as value_bucket,
            COUNT(*) as cnt,
            SUM(precoContratual) as total_val
        FROM contratos 
        WHERE precoContratual > 0
        GROUP BY value_bucket
        ORDER BY MIN(precoContratual)
    """)
    return [dict(r) for r in rows]


def query_temporal_bursts(conn):
    """Day-of-week and hour distribution for burst detection."""
    if not conn or not table_exists(conn, "contratos"):
        return {}
    
    # Day of week distribution
    dow_rows = safe_query(conn, """
        SELECT 
            CASE CAST(strftime('%w', dataCelebracaoContrato) AS INTEGER)
                WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
                WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri'
                WHEN 6 THEN 'Sat'
            END as day_name,
            COUNT(*) as cnt,
            SUM(COALESCE(precoContratual, 0)) as val
        FROM contratos 
        WHERE dataCelebracaoContrato IS NOT NULL AND dataCelebracaoContrato != ''
        GROUP BY CAST(strftime('%w', dataCelebracaoContrato) AS INTEGER)
        ORDER BY CAST(strftime('%w', dataCelebracaoContrato) AS INTEGER)
    """)
    
    # Year-end surge by month
    month_rows = safe_query(conn, """
        SELECT 
            SUBSTR(dataCelebracaoContrato, 6, 2) as month_num,
            COUNT(*) as cnt,
            SUM(COALESCE(precoContratual, 0)) as val
        FROM contratos 
        WHERE dataCelebracaoContrato IS NOT NULL 
              AND dataCelebracaoContrato LIKE '____-__-__'
        GROUP BY month_num
        ORDER BY month_num
    """)
    
    return {
        "day_of_week": [dict(r) for r in dow_rows],
        "by_month": [dict(r) for r in month_rows]
    }


def query_category_breakdown(connections):
    """Breakdown of data sources for pie chart — queries each DB independently."""
    categories = []
    
    # Map: (table_name, label, db_key)
    tables = [
        ("contratos", "Contracts", "procurement"),
        ("prr_entities", "PRR Entities", "transparency"),
        ("prr_projects", "PRR Projects", "transparency"),
        ("bep_entities", "BEP Entities", "bep"),
        ("dre_publications", "DRE Publications", "dre"),
        ("law_projects", "Law Projects", "law"),
        ("ted_notices", "TED Notices", "ted"),
        ("modificacoes", "Modifications", "mods"),
    ]
    
    for table_name, label, db_key in tables:
        conn = connections.get(db_key)
        if conn and table_exists(conn, table_name):
            count = safe_scalar(conn, f"SELECT COUNT(*) FROM {table_name}")
            if count > 0:
                categories.append({"label": label, "count": count, "source": db_key})
    
    return categories


# ═════════════════════════════════════════════════════════════════════════════
#  HTML GENERATION
# ═════════════════════════════════════════════════════════════════════════════

def generate_live_dashboard(concelho=None):
    """Generate the complete live dashboard by querying all databases."""
    now = datetime.now(timezone.utc)

    # ── Query all databases ───────────────────────────────────────────────
    db_status = {}
    connections = {}
    for name in DB_PATHS:
        conn = open_db(name)
        connections[name] = conn
        db_status[name] = {"available": conn is not None, "path": str(DB_PATHS[name])}

    # Core procurement
    procurement = query_procurement_overview(connections.get("procurement"))
    top_inflated = query_top_inflated(connections.get("procurement"))
    concentration = query_top_concentration(connections.get("procurement"))
    temporal = query_temporal_trends(connections.get("procurement"))
    procedures = query_procedure_breakdown(connections.get("procurement"))
    risk_dist = query_risk_distribution(connections.get("procurement"))
    value_dist = query_value_distribution(connections.get("procurement"))
    burst_data = query_temporal_bursts(connections.get("procurement"))

    # Cross-source
    transparency = query_transparency_overview(connections.get("transparency"))
    bep = query_bep_overview(connections.get("bep"))
    dre = query_dre_overview(connections.get("dre"))
    law = query_law_overview(connections.get("law"))
    ted = query_ted_overview(connections.get("ted"))
    mods = query_modifications_overview(connections.get("modifications"))
    category_data = query_category_breakdown(connections)

    # Close connections
    for conn in connections.values():
        if conn:
            conn.close()

    # ── Compute derived metrics ───────────────────────────────────────────
    tc = procurement.get("total_contracts", 0)
    tv = procurement.get("total_value", 0) or 0
    ic = procurement.get("inflated_count", 0)
    to_val = procurement.get("total_overrun", 0) or 0
    da = procurement.get("direct_awards", 0)
    dp = procurement.get("direct_rate", 0)
    ip = procurement.get("inflation_rate", 0)
    sr = procurement.get("self_referencing", 0)
    cc = len(concentration)

    prr_entities = transparency.get("prr_entities", 0)
    prr_value = transparency.get("prr_value", 0) or 0
    prr_paid = transparency.get("prr_paid", 0) or 0
    prr_exec = round(prr_paid / prr_value * 100, 1) if prr_value > 0 else 0

    # ── Build HTML ────────────────────────────────────────────────────────
    parts = []
    parts.append('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('<title>Analisa.pt — Live Dashboard</title>')
    parts.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>')

    # CSS
    parts.append('''<style>
  :root { --bg:#0f172a; --card:#1e293b; --text:#e2e8f0; --muted:#94a3b8; --border:#334155; --accent:#f59e0b; --danger:#ef4444; --success:#22c55e; --info:#3b82f6; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }
  .container { max-width:1400px; margin:0 auto; padding:16px; }
  .header { background:linear-gradient(135deg,#1e293b,#0f172a); padding:24px; border-bottom:2px solid var(--accent); border-radius:12px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; }
  .header h1 { font-size:24px; color:var(--accent); }
  .header .sub { color:var(--muted); font-size:13px; margin-top:4px; }
  .header .live-badge { background:var(--success); color:#0f172a; padding:4px 12px; border-radius:99px; font-size:11px; font-weight:700; }
  .db-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:8px; margin-bottom:16px; }
  .db-chip { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:8px 12px; font-size:11px; display:flex; align-items:center; gap:6px; }
  .db-dot { width:8px; height:8px; border-radius:50%; }
  .db-dot.ok { background:var(--success); }
  .db-dot.miss { background:var(--danger); }
  .summary-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:16px; }
  .summary-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; text-align:center; transition:transform .2s; }
  .summary-card:hover { transform:translateY(-2px); }
  .summary-card.warn { border-color:var(--accent); }
  .summary-card.danger { border-color:var(--danger); }
  .sc-icon { font-size:20px; }
  .sc-value { font-size:20px; font-weight:700; color:var(--accent); margin:4px 0; }
  .sc-label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
  .tab-bar { display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:8px; }
  .tab-btn { padding:8px 16px; border:none; border-radius:8px; cursor:pointer; font-size:13px; font-weight:500; background:transparent; color:var(--muted); transition:all .2s; white-space:nowrap; }
  .tab-btn:hover { color:var(--text); background:rgba(255,255,255,.05); }
  .tab-btn.active { background:var(--accent); color:#0f172a; font-weight:600; }
  .tab-panel { display:none; }
  .tab-panel.active { display:block; }
  .section { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:16px; }
  .section h3 { font-size:16px; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
  .section h3 .count { background:var(--info); color:white; padding:2px 8px; border-radius:99px; font-size:11px; }
  .info-bar { background:rgba(245,158,11,.08); border:1px solid rgba(245,158,11,.2); border-radius:8px; padding:10px 16px; margin-bottom:16px; font-size:13px; color:var(--accent); }
  .empty-state { text-align:center; padding:40px; color:var(--muted); font-size:13px; }
  .metric-row { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
  .metric { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:12px 20px; flex:1; min-width:140px; text-align:center; }
  .metric-value { font-size:18px; font-weight:700; color:var(--accent); }
  .metric-label { font-size:11px; color:var(--muted); text-transform:uppercase; margin-top:2px; }
  .scroll-table { max-height:500px; overflow-y:auto; border-radius:8px; border:1px solid var(--border); }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th { text-align:left; padding:8px 10px; border-bottom:2px solid var(--border); color:var(--muted); font-weight:600; font-size:10px; text-transform:uppercase; letter-spacing:.5px; position:sticky; top:0; background:var(--card); z-index:1; }
  td { padding:6px 10px; border-bottom:1px solid rgba(51,65,85,.5); }
  tr:hover { background:rgba(255,255,255,.03); }
  .entity-name { max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500; }
  .nif { font-family:monospace; font-size:11px; color:var(--muted); }
  .value { text-align:right; font-weight:600; font-family:monospace; }
  .overrun { color:var(--danger); }
  .score-badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; color:white; min-width:32px; text-align:center; }
  .chart-box { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; margin-bottom:16px; }
  .chart-box h4 { font-size:14px; margin-bottom:12px; }
  .chart-container { position:relative; height:300px; }
  .footer { text-align:center; color:var(--muted); font-size:11px; margin-top:24px; padding:12px; border-top:1px solid var(--border); }
  @media(max-width:800px) { .summary-row { grid-template-columns:repeat(2,1fr); } .header { flex-direction:column; gap:12px; } }
  </style>''')

    parts.append('</head><body><div class="container">')

    # ── Header ────────────────────────────────────────────────────────────
    gen_time = now.strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f'<div class="header"><div><h1>🛡️ Analisa.pt — Live Dashboard</h1>')
    parts.append(f'<div class="sub">Dynamically generated from live databases — {gen_time}</div></div>')
    parts.append(f'<div class="live-badge">● LIVE</div></div>')

    # ── Database Status ───────────────────────────────────────────────────
    parts.append('<div class="db-grid">')
    for name, info in db_status.items():
        cls = "ok" if info["available"] else "miss"
        parts.append(f'<div class="db-chip"><div class="db-dot {cls}"></div>{esc(name)}</div>')
    parts.append('</div>')

    # ── Summary Cards ─────────────────────────────────────────────────────
    parts.append('<div class="summary-row">')
    cards = [
        ("📊", fmt_num(tc), "Contracts", tc > 0),
        ("💰", fmt(tv), "Total Value", True),
        ("🏛️", fmt_num(buyers := procurement.get("unique_buyers", 0)), "Unique Buyers", True),
        ("📈", f"{ip}%", "Inflation Rate", ip > 10),
        ("⚠️", fmt(to_val), "Price Overrun", to_val > 0),
        ("🔄", fmt_num(sr), "Self-Referencing", sr > 0),
        ("🏗️", f"{dp}%", "Direct Award Rate", dp > 50),
    ]
    if prr_entities > 0:
        cards.append(("🇪🇺", fmt_num(prr_entities), "PRR Entities", True))
        cards.append(("💶", fmt(prr_value), "PRR Value", True))
    if bep.get("total_entities", 0) > 0:
        cards.append(("📋", fmt_num(bep["total_entities"]), "BEP Entities", True))
    if dre.get("total_publications", 0) > 0:
        cards.append(("📰", fmt_num(dre["total_publications"]), "DRE Publications", True))
    if law.get("total_projects", 0) > 0:
        cards.append(("📜", fmt_num(law["total_projects"]), "Law Projects", True))
    if mods.get("total_modifications", 0) > 0:
        cards.append(("📝", fmt_num(mods["total_modifications"]), "Contract Modifications", True))

    for icon, value, label, has_data in cards:
        cls = "" if has_data else ' style="opacity:0.4"'
        parts.append(f'<div class="summary-card{cls}"><div class="sc-icon">{icon}</div><div class="sc-value">{value}</div><div class="sc-label">{label}</div></div>')
    parts.append('</div>')

    # ── Tab Bar ───────────────────────────────────────────────────────────
    tabs = [
        ("overview", "📊 Overview"),
        ("financial", "💰 Financial"),
        ("temporal", "📅 Temporal"),
        ("patterns", "🔄 Patterns"),
        ("crossref", "🔗 Cross-Ref"),
        ("entities", "🏛️ Entities"),
    ]
    parts.append('<div class="tab-bar">')
    for i, (tid, label) in enumerate(tabs):
        active = " active" if i == 0 else ""
        parts.append(f'<button class="tab-btn{active}" data-tab="{tid}">{label}</button>')
    parts.append('</div>')

    # ── Tab 1: Overview ───────────────────────────────────────────────────
    parts.append('<div class="tab-panel active" id="panel-overview">')

    # Procedure breakdown
    if procedures:
        parts.append('<div class="section"><h3>⚙️ Procurement Procedures</h3>')
        parts.append('<div class="scroll-table"><table><thead><tr><th>Procedure</th><th>Contracts</th><th>Share</th><th>Value</th></tr></thead><tbody>')
        for p in procedures:
            share = p["cnt"] * 100 / max(tc, 1)
            is_direct = "direto" in (p["tipoprocedimento"] or "").lower() or "ajuste" in (p["tipoprocedimento"] or "").lower()
            fc = "background:rgba(245,158,11,.2);color:#f59e0b" if is_direct else ""
            parts.append(f'<tr><td>{esc((p["tipoprocedimento"] or "N/A")[:50])}</td><td>{p["cnt"]:,}</td><td><span class="score-badge" style="{fc}">{share:.1f}%</span></td><td class="value">{fmt(p["val"])}</td></tr>')
        parts.append('</tbody></table></div></div>')

    # Database summary
    parts.append('<div class="section"><h3>📦 Data Sources</h3>')
    parts.append('<div class="scroll-table"><table><thead><tr><th>Database</th><th>Status</th><th>Key Metrics</th></tr></thead><tbody>')
    db_summaries = [
        ("procurement.db", procurement, f'{fmt_num(tc)} contracts, {fmt(tv)}'),
        ("transparency.db", transparency, f'{fmt_num(prr_entities)} PRR entities, {fmt(prr_value)}'),
        ("bep_index.db", bep, f'{fmt_num(bep.get("total_entities", 0))} entities'),
        ("dre_index.db", dre, f'{fmt_num(dre.get("total_publications", 0))} publications'),
        ("law_index.db", law, f'{fmt_num(law.get("total_projects", 0))} projects'),
        ("ted_notices.db", ted, f'{fmt_num(ted.get("total_notices", 0))} notices'),
        ("modificacoes_index.db", mods, f'{fmt_num(mods.get("total_modifications", 0))} modifications'),
    ]
    for name, data, metric in db_summaries:
        status = "✅ Available" if "error" not in data else "❌ Missing"
        parts.append(f'<tr><td>{esc(name)}</td><td>{status}</td><td>{esc(metric)}</td></tr>')
    parts.append('</tbody></table></div></div>')
    parts.append('</div>')

    # ── Tab 2: Financial ──────────────────────────────────────────────────
    parts.append('<div class="tab-panel" id="panel-financial">')

    # Risk Distribution Chart
    if risk_dist:
        risk_labels = json.dumps([r["risk_bucket"] for r in risk_dist])
        risk_counts = json.dumps([r["cnt"] for r in risk_dist])
        risk_colors = json.dumps(["#22c55e", "#84cc16", "#f59e0b", "#f97316", "#ef4444", "#dc2626"])
        parts.append('<div class="chart-box"><h4>📊 Risk Score Distribution</h4><div class="chart-container"><canvas id="riskChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("riskChart"),{{type:"bar",data:{{labels:{risk_labels},datasets:[{{label:"Contracts",data:{risk_counts},backgroundColor:{risk_colors},borderRadius:4}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true}}}}}}}});</script>')

    # Value Distribution Chart
    if value_dist:
        val_labels = json.dumps([v["value_bucket"] for v in value_dist])
        val_counts = json.dumps([v["cnt"] for v in value_dist])
        val_colors = json.dumps(["#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899", "#f43f5e"])
        parts.append('<div class="chart-box"><h4>💰 Contract Value Distribution</h4><div class="chart-container"><canvas id="valueChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("valueChart"),{{type:"doughnut",data:{{labels:{val_labels},datasets:[{{data:{val_counts},backgroundColor:{val_colors},borderWidth:0}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:"right",labels:{{font:{{size:11}},color:"#e2e8f0"}}}}}}}}}});</script>')

    if top_inflated:
        parts.append(f'<div class="section"><h3>📈 Top Inflated Contracts <span class="count">{len(top_inflated)}</span></h3>')
        parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Winner</th><th>Base</th><th>Final</th><th>Overrun</th><th>%</th></tr></thead><tbody>')
        for i, c in enumerate(top_inflated[:25], 1):
            sev = "#ef4444" if c["pct"] > 20 else "#f59e0b" if c["pct"] > 10 else "#22c55e"
            parts.append(f'<tr><td>{i}</td><td class="entity-name">{esc((c["adjudicante_nome"] or "")[:45])}</td><td class="entity-name">{esc((c["adjudicatarios"] or "")[:45])}</td><td class="value">{fmt(c["precoBaseProcedimento"])}</td><td class="value">{fmt(c["precoContratual"])}</td><td class="value overrun">+{fmt(c["overrun"])}</td><td><span class="score-badge" style="background:{sev}">{c["pct"]:+.0f}%</span></td></tr>')
        parts.append('</tbody></table></div></div>')

    if concentration:
        parts.append(f'<div class="section"><h3>🎯 Spending Concentration <span class="count">{len(concentration)}</span></h3>')
        parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Top Supplier</th><th>Share</th><th>#</th><th>Value</th></tr></thead><tbody>')
        for i, c in enumerate(concentration[:20], 1):
            sev = "#ef4444" if c["share"] >= 70 else "#f59e0b" if c["share"] >= 50 else "#3b82f6"
            parts.append(f'<tr><td>{i}</td><td class="entity-name">{esc((c["buyer"] or "")[:45])}</td><td class="entity-name">{esc(c["seller"][:45])}</td><td><span class="score-badge" style="background:{sev}">{c["share"]:.0f}%</span></td><td>{c["contracts"]}</td><td class="value">{fmt(c["value"])}</td></tr>')
        parts.append('</tbody></table></div></div>')

    # PRR Money Trail
    if prr_entities > 0:
        parts.append('<div class="section"><h3>🇪🇺 PRR Allocation</h3>')
        parts.append('<div class="metric-row">')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt(prr_value)}</div><div class="metric-label">Total Contracted</div></div>')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt(prr_paid)}</div><div class="metric-label">Total Paid ({prr_exec}%)</div></div>')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt_num(transparency.get("prr_projects", 0))}</div><div class="metric-label">Projects</div></div>')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt(transparency.get("prr_project_value", 0))}</div><div class="metric-label">Project Value</div></div>')
        parts.append('</div></div>')

    if not top_inflated and not concentration:
        parts.append('<div class="empty-state">No financial data available. Ensure procurement.db exists.</div>')
    parts.append('</div>')

    # ── Tab 3: Temporal ───────────────────────────────────────────────────
    parts.append('<div class="tab-panel" id="panel-temporal">')
    months = temporal.get("months", [])
    
    # Temporal Burst Charts
    if burst_data.get("day_of_week"):
        dow_labels = json.dumps([d["day_name"] for d in burst_data["day_of_week"]])
        dow_counts = json.dumps([d["cnt"] for d in burst_data["day_of_week"]])
        parts.append('<div class="chart-box"><h4>📅 Day-of-Week Contract Distribution</h4><div class="chart-container"><canvas id="dowChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("dowChart"),{{type:"bar",data:{{labels:{dow_labels},datasets:[{{label:"Contracts",data:{dow_counts},backgroundColor:"rgba(59,130,246,.7)",borderRadius:4}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true}}}}}}}});</script>')
    
    if burst_data.get("by_month"):
        month_labels = json.dumps([f"Month {m["month_num"]}" for m in burst_data["by_month"]])
        month_counts = json.dumps([m["cnt"] for m in burst_data["by_month"]])
        month_values = json.dumps([round(m["val"], 2) for m in burst_data["by_month"]])
        parts.append('<div class="chart-box"><h4>📈 Monthly Contract Burst Analysis</h4><div class="chart-container"><canvas id="burstChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("burstChart"),{{type:"bar",data:{{labels:{month_labels},datasets:[{{label:"Contracts",data:{month_counts},backgroundColor:"rgba(245,158,11,.7)",borderRadius:4,yAxisID:"y"}},{{label:"Value (€)",data:{month_values},type:"line",borderColor:"#ef4444",tension:.3,pointRadius:2,yAxisID:"y1"}}]}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:"index",intersect:false}},scales:{{y:{{beginAtZero:true}},y1:{{position:"right",beginAtZero:true,grid:{{drawOnChartArea:false}},ticks:{{callback:v=>v>=1e6?"€"+(v/1e6).toFixed(0)+"M":"€"+(v/1e3).toFixed(0)+"K"}}}}}}}}}});</script>')
    
    if months:
        surge = "🚨 SURGE DETECTED" if temporal.get("is_surge") else "✅ Normal"
        parts.append(f'<div class="info-bar">📅 {len(months)} months of data — December surge ratio: {temporal.get("dec_ratio", 0)}x {surge}</div>')

        # Chart data
        chart_labels = json.dumps([m["month"] for m in months])
        chart_counts = json.dumps([m["cnt"] for m in months])
        chart_values = json.dumps([round(m["val"], 2) for m in months])

        parts.append('<div class="chart-box"><h4>📊 Contracts Over Time</h4><div class="chart-container"><canvas id="temporalChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("temporalChart"),{{type:"bar",data:{{labels:{chart_labels},datasets:[{{label:"Contracts",data:{chart_counts},backgroundColor:"rgba(59,130,246,.7)",borderRadius:4,yAxisID:"y"}},{{label:"Value (€)",data:{chart_values},type:"line",borderColor:"#f59e0b",tension:.3,pointRadius:2,yAxisID:"y1"}}]}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:"index",intersect:false}},scales:{{y:{{beginAtZero:true}},y1:{{position:"right",beginAtZero:true,grid:{{drawOnChartArea:false}},ticks:{{callback:v=>v>=1e6?"€"+(v/1e6).toFixed(0)+"M":"€"+(v/1e3).toFixed(0)+"K"}}}}}}}}}});</script>')
    else:
        parts.append('<div class="empty-state">No temporal data available. Ensure procurement.db has date fields populated.</div>')
    parts.append('</div>')

    # ── Tab 4: Patterns ───────────────────────────────────────────────────
    parts.append('<div class="tab-panel" id="panel-patterns">')

    if sr > 0:
        parts.append(f'<div class="info-bar">🔄 {sr} self-referencing cases detected in procurement data</div>')
    if cc > 0:
        parts.append(f'<div class="info-bar">🎯 {cc} high-concentration buyer-seller pairs (≥30% share, ≥€500K)</div>')

    # Procedure chart
    if procedures:
        proc_labels = json.dumps([p["tipoprocedimento"][:25] for p in procedures[:8]])
        proc_counts = json.dumps([p["cnt"] for p in procedures[:8]])
        parts.append('<div class="chart-box"><h4>⚙️ Procedure Type Distribution</h4><div class="chart-container"><canvas id="procChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("procChart"),{{type:"doughnut",data:{{labels:{proc_labels},datasets:[{{data:{proc_counts},backgroundColor:["#f59e0b","#3b82f6","#22c55e","#ef4444","#8b5cf6","#ec4899","#14b8a6","#f97316"],borderWidth:0}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:"right",labels:{{font:{{size:11}},padding:8,color:"#e2e8f0"}}}}}}}}}});</script>')

    if not sr and not concentration and not procedures:
        parts.append('<div class="empty-state">No pattern data available.</div>')
    parts.append('</div>')

    # ── Tab 5: Cross-Reference ────────────────────────────────────────────
    parts.append('<div class="tab-panel" id="panel-crossref">')

    # Category Breakdown Chart
    if category_data:
        cat_labels = json.dumps([c["label"] for c in category_data])
        cat_counts = json.dumps([c["count"] for c in category_data])
        cat_colors = json.dumps(["#f59e0b", "#3b82f6", "#22c55e", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"])
        parts.append('<div class="chart-box"><h4>🔗 Data Source Distribution</h4><div class="chart-container"><canvas id="categoryChart"></canvas></div></div>')
        parts.append(f'<script>new Chart(document.getElementById("categoryChart"),{{type:"pie",data:{{labels:{cat_labels},datasets:[{{data:{cat_counts},backgroundColor:{cat_colors},borderWidth:0}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:"right",labels:{{font:{{size:11}},color:"#e2e8f0"}}}}}}}}}});</script>')

    crossref_items = [
        ("🇪🇺", "TED Notices", ted.get("total_notices", 0), "ted_notices.db"),
        ("📋", "BEP Entities", bep.get("total_entities", 0), "bep_index.db"),
        ("📰", "DRE Publications", dre.get("total_publications", 0), "dre_index.db"),
        ("📜", "Law Projects", law.get("total_projects", 0), "law_index.db"),
        ("📝", "Contract Modifications", mods.get("total_modifications", 0), "modificacoes_index.db"),
        ("🇪🇺", "PRR Entities", prr_entities, "transparency.db"),
    ]

    has_crossref = any(v > 0 for _, _, v, _ in crossref_items)
    if has_crossref:
        parts.append('<div class="section"><h3>🔗 Cross-Reference Data Sources</h3>')
        parts.append('<div class="scroll-table"><table><thead><tr><th>Source</th><th>Database</th><th>Count</th><th>Status</th></tr></thead><tbody>')
        for icon, label, count, db in crossref_items:
            status = "✅" if count > 0 else "⚠️ Empty"
            parts.append(f'<tr><td>{icon} {label}</td><td class="nif">{esc(db)}</td><td class="value">{fmt_num(count)}</td><td>{status}</td></tr>')
        parts.append('</tbody></table></div></div>')
    else:
        parts.append('<div class="empty-state">No cross-reference data available. Run the scrapers to populate databases.</div>')
    parts.append('</div>')

    # ── Tab 6: Entities ───────────────────────────────────────────────────
    parts.append('<div class="tab-panel" id="panel-entities">')
    entities_count = procurement.get("unique_entities", 0)
    buyers_count = procurement.get("unique_buyers", 0)

    if entities_count > 0 or buyers_count > 0:
        parts.append('<div class="metric-row">')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt_num(entities_count)}</div><div class="metric-label">Total Entities</div></div>')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt_num(buyers_count)}</div><div class="metric-label">Unique Buyers</div></div>')
        parts.append(f'<div class="metric"><div class="metric-value">{fmt_num(sr)}</div><div class="metric-label">Self-Referencing</div></div>')
        parts.append('</div>')
    else:
        parts.append('<div class="empty-state">No entity data available. Ensure procurement.db and entidades table exist.</div>')
    parts.append('</div>')

    # ── Footer ────────────────────────────────────────────────────────────
    active_dbs = sum(1 for v in db_status.values() if v["available"])
    parts.append(f'<div class="footer">Analisa.pt Live Dashboard — {active_dbs}/{len(DB_PATHS)} databases connected — Generated {gen_time}</div>')

    parts.append('</div>')

    # ── Tab switching JS ──────────────────────────────────────────────────
    parts.append('''<script>
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});
</script></body></html>''')

    return "".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate Live Dashboard from SQLite databases")
    parser.add_argument("-o", "--output", default=str(DATA_DIR / "live_dashboard.html"), help="Output path")
    parser.add_argument("--concelho", help="Include concelho deep-dive (requires money_trail data)")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")
    args = parser.parse_args()

    print("  Querying databases...", file=sys.stderr)
    html = generate_live_dashboard(concelho=args.concelho)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✅ Live dashboard written to {out_path} ({len(html):,} bytes)", file=sys.stderr)

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
