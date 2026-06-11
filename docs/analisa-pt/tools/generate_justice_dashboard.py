#!/usr/bin/env python3
"""Justice × Procurement Intelligence Dashboard

Generates a self-contained HTML dashboard visualizing:
  - Corruption & money-laundering case trends (justice.db)
  - Court case flow & backlog (justice.db)
  - Prison population trends (justice.db)
  - Procurement anomaly signals (procurement.db)
  - INE crime rate & immigration data (ine_stats.db)
  - Cross-reference risk signals

Usage:
    python generate_justice_dashboard.py                          # Default output
    python generate_justice_dashboard.py -o justice_dash.html     # Custom output
    python generate_justice_dashboard.py --open                   # Generate + open
"""

import argparse
import json
import sqlite3
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from utils import fmt

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SUMMARY_DIR = DATA_DIR / "summary"
JUSTICE_DB = DATA_DIR / "justice.db"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
INE_DB = DATA_DIR / "ine_stats.db"
CROSSREF_JSON = SUMMARY_DIR / "justice_crossref.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def esc(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fmt_num(v):
    if v is None:
        return "0"
    return f"{int(v):,}"


def open_db(path):
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
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


# ── Data queries ─────────────────────────────────────────────────────────────

def query_corruption(conn):
    """Corruption and money-laundering case trends."""
    if not conn:
        return {}, []
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
    # Latest year totals
    latest = {}
    for ds, pts in trends.items():
        if pts:
            latest[ds] = pts[-1]
    return latest, trends


def query_court_flow(conn):
    """Court case entered/finalized/pending trends."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT year, SUM(entered) as entered, SUM(finalized) as finalized,
               SUM(pending) as pending
        FROM court_movements WHERE year IS NOT NULL
        GROUP BY year ORDER BY year
    """)
    return [dict(r) for r in rows]


def query_prison(conn):
    """Prison population trends."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT year, SUM(count) as total
        FROM prison_population WHERE year IS NOT NULL
        GROUP BY year ORDER BY year
    """)
    return [dict(r) for r in rows]


def query_procurement_signals(conn):
    """Key procurement anomaly signals scoped to last 5 years for speed."""
    if not conn:
        return {}
    latest = safe_scalar(conn, "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL")
    min_ano = (latest or 2024) - 5 if latest else 2019
    tc = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano >= ?", (min_ano,))
    tv = safe_scalar(conn, "SELECT SUM(COALESCE(precoContratual, 0)) FROM contratos WHERE Ano >= ? AND precoContratual > 0", (min_ano,))
    direct = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano >= ? AND tipoprocedimento LIKE '%ajuste direto%'", (min_ano,))
    inflated = safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano >= ? AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento * 1.05", (min_ano,))
    with_base = max(safe_scalar(conn, "SELECT COUNT(*) FROM contratos WHERE Ano >= ? AND precoBaseProcedimento > 0 AND precoContratual > 0", (min_ano,)), 1)
    overrun = safe_scalar(conn, "SELECT SUM(precoContratual - precoBaseProcedimento) FROM contratos WHERE Ano >= ? AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento", (min_ano,))

    return {
        "total_contracts": tc,
        "total_value": tv,
        "direct_awards": direct,
        "direct_rate": round(direct * 100 / max(tc, 1), 1),
        "inflated": inflated,
        "inflation_rate": round(inflated * 100 / with_base, 1),
        "overrun": overrun or 0,
        "year_range": f"{min_ano}-present",
    }


def query_proc_yearly(conn):
    """Yearly contract count and value from procurement.db (last 10 years)."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT Ano as year, COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val
        FROM contratos WHERE Ano IS NOT NULL AND Ano > (SELECT MAX(Ano) - 10 FROM contratos WHERE Ano IS NOT NULL)
        GROUP BY Ano ORDER BY Ano
    """)
    return [dict(r) for r in rows]


def query_ine_crime(conn):
    """INE crime rate indicator."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT year, geographic_name as region, value
        FROM ine_observations
        WHERE indicator_code = '0008074' AND value IS NOT NULL
        ORDER BY year
    """)
    return [dict(r) for r in rows]


def query_ine_immigration(conn):
    """INE foreign population indicator."""
    if not conn:
        return []
    rows = safe_query(conn, """
        SELECT year, geographic_name as dimension, value
        FROM ine_observations
        WHERE indicator_code = '0001236' AND value IS NOT NULL
        ORDER BY year
    """)
    return [dict(r) for r in rows]


# ── HTML generation ──────────────────────────────────────────────────────────

def generate_dashboard():
    now = datetime.now(timezone.utc)
    gen_time = now.strftime("%Y-%m-%d %H:%M UTC")

    jconn = open_db(JUSTICE_DB)
    pconn = open_db(PROCUREMENT_DB)
    iconn = open_db(INE_DB)

    # Load crossref data
    crossref = {}
    if CROSSREF_JSON.exists():
        try:
            crossref = json.loads(CROSSREF_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Query all data
    cor_latest, cor_trends = query_corruption(jconn)
    court_data = query_court_flow(jconn)
    prison_data = query_prison(jconn)
    proc_signals = query_procurement_signals(pconn)
    proc_yearly = query_proc_yearly(pconn)
    ine_crime = query_ine_crime(iconn)
    ine_immig = query_ine_immigration(iconn)

    # Close connections
    for c in (jconn, pconn, iconn):
        if c:
            c.close()

    # ── Chart data ───────────────────────────────────────────────────────────
    # Corruption trend chart
    cor_years = sorted(set(
        pt["year"] for pts in cor_trends.values() for pt in pts
        if pt["year"] and pt["year"] > 2005
    ))
    cor_cj_data = {pt["year"]: pt["cases"] for pt in cor_trends.get("corrupcaopj", [])}
    cor_bl_data = {pt["year"]: pt["cases"] for pt in cor_trends.get("branqueamentopj", [])}
    cor_cj_values = [cor_cj_data.get(y, 0) for y in cor_years]
    cor_bl_values = [cor_bl_data.get(y, 0) for y in cor_years]

    # Court flow chart
    court_years = [r["year"] for r in court_data if r["year"] and r["year"] > 2005]
    court_entered = [r["entered"] for r in court_data if r["year"] and r["year"] > 2005]
    court_finalized = [r["finalized"] for r in court_data if r["year"] and r["year"] > 2005]
    court_pending = [r["pending"] for r in court_data if r["year"] and r["year"] > 2005]

    # Prison chart
    prison_years = [r["year"] for r in prison_data if r["year"] and r["year"] > 2005]
    prison_totals = [r["total"] for r in prison_data if r["year"] and r["year"] > 2005]

    # Procurement yearly
    py_years = [r["year"] for r in proc_yearly if r["year"]]
    py_contracts = [r["cnt"] for r in proc_yearly if r["year"]]
    py_values = [round(r["val"], 0) for r in proc_yearly if r["year"]]

    # INE crime rate — only include years with actual values
    ine_crime_by_year = {}
    for r in ine_crime:
        if r["year"] and r["value"]:
            ine_crime_by_year.setdefault(r["year"], []).append(r["value"])
    ine_crime_years = sorted(ine_crime_by_year.keys())
    ine_crime_values = [round(sum(ine_crime_by_year[y]) / len(ine_crime_by_year[y]), 1) for y in ine_crime_years]

    # INE immigration — aggregate foreign residents by year
    immig_by_year = {}
    for r in ine_immig:
        if r["year"] and r["value"]:
            immig_by_year.setdefault(r["year"], []).append(r["value"])
    immig_years = sorted(immig_by_year.keys())
    immig_values = [round(sum(immig_by_year[y]) / len(immig_by_year[y]), 1) for y in immig_years]

    # Risk signals
    risk_signals = crossref.get("risk_signals", [])
    risk_level = crossref.get("risk_level", "unknown")
    composite = crossref.get("composite_score", 0)

    risk_colors = {"critical": "#ef4444", "elevated": "#f59e0b", "normal": "#22c55e"}
    risk_bg = {"critical": "rgba(239,68,68,.15)", "elevated": "rgba(245,158,11,.15)", "normal": "rgba(34,197,94,.15)"}

    # ── Build HTML ───────────────────────────────────────────────────────────
    p = []
    p.append('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">')
    p.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    p.append('<title>Analisa.pt — Corruption Intelligence Dashboard</title>')
    p.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>')

    p.append('''<style>
:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--muted:#94a3b8;--border:#334155;--accent:#f59e0b;--danger:#ef4444;--success:#22c55e;--info:#3b82f6;--purple:#8b5cf6}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
.container{max-width:1400px;margin:0 auto;padding:16px}
.header{background:linear-gradient(135deg,#1e293b,#0f172a);padding:24px;border-bottom:2px solid var(--accent);border-radius:12px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
.header h1{font-size:22px;color:var(--accent)}
.header .sub{color:var(--muted);font-size:13px;margin-top:4px}
.risk-badge{padding:8px 20px;border-radius:99px;font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:1px}
.summary-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin-bottom:16px}
.summary-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center;transition:transform .2s}
.summary-card:hover{transform:translateY(-2px)}
.sc-icon{font-size:20px}
.sc-value{font-size:18px;font-weight:700;color:var(--accent);margin:4px 0}
.sc-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.sc-sub{font-size:10px;color:var(--muted);margin-top:2px}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px;margin-bottom:16px}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px}
.chart-box h3{font-size:15px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.chart-box h3 .tag{font-size:10px;padding:2px 8px;border-radius:4px;font-weight:600}
.chart-container{position:relative;height:280px}
.section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
.section h3{font-size:16px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.risk-panel{border:2px solid;border-radius:12px;padding:20px;margin-bottom:16px}
.risk-signal{display:flex;align-items:center;gap:12px;padding:10px 16px;border-radius:8px;margin-bottom:8px;background:rgba(255,255,255,.03);border:1px solid var(--border)}
.risk-signal .severity{min-width:70px;font-size:11px;font-weight:700;text-transform:uppercase;padding:3px 10px;border-radius:4px;text-align:center}
.risk-signal .detail{font-size:13px;flex:1}
.scroll-table{max-height:400px;overflow-y:auto;border-radius:8px;border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:8px 10px;border-bottom:2px solid var(--border);color:var(--muted);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.5px;position:sticky;top:0;background:var(--card);z-index:1}
td{padding:6px 10px;border-bottom:1px solid rgba(51,65,85,.5)}
tr:hover{background:rgba(255,255,255,.03)}
.value{text-align:right;font-weight:600;font-family:monospace}
.footer{text-align:center;color:var(--muted);font-size:11px;margin-top:24px;padding:12px;border-top:1px solid var(--border)}
@media(max-width:800px){.chart-grid{grid-template-columns:1fr}.summary-row{grid-template-columns:repeat(2,1fr)}.header{flex-direction:column}}
</style>''')

    p.append('</head><body><div class="container">')

    # ── Header ───────────────────────────────────────────────────────────────
    r_color = risk_colors.get(risk_level, "#94a3b8")
    p.append(f'<div class="header"><div><h1>🛡️ Corruption Intelligence Dashboard</h1>')
    p.append(f'<div class="sub">Justice × Procurement × INE — {gen_time}</div></div>')
    p.append(f'<div class="risk-badge" style="background:{r_color};color:#0f172a">{risk_level.upper()} RISK</div></div>')

    # ── Summary Cards ────────────────────────────────────────────────────────
    p.append('<div class="summary-row">')
    cards = []

    # Corruption
    cor_val = cor_latest.get("corrupcaopj", {}).get("cases", 0)
    cards.append(("⚖️", fmt_num(int(cor_val)) if cor_val else "—", "Corruption Cases (latest)", crossref.get("corruption_direction", "")))

    # Money laundering
    bl_val = cor_latest.get("branqueamentopj", {}).get("cases", 0)
    cards.append(("💸", fmt_num(int(bl_val)) if bl_val else "—", "Money Laundering (latest)", crossref.get("laundering_direction", "")))

    # Court pending
    if court_data:
        latest_court = court_data[-1]
        cards.append(("🏛️", fmt_num(latest_court.get("pending", 0)), f"Cases Pending ({latest_court.get('year', '')})", ""))

    # Prison
    if prison_data:
        latest_prison = prison_data[-1]
        cards.append(("🔒", fmt_num(latest_prison.get("total", 0)), f"Prison Population ({latest_prison.get('year', '')})", ""))

    # Procurement (with year_range)
    yr = proc_signals.get("year_range", "")
    cards.append(("📊", fmt_num(proc_signals.get("total_contracts", 0)), "Procurement Contracts", yr))
    cards.append(("📈", f"{proc_signals.get('inflation_rate', 0)}%", "Price Inflation Rate", f"{yr} • >5% overrun"))
    cards.append(("⚠️", f"{proc_signals.get('direct_rate', 0)}%", "Direct Award Rate", f"{yr} • ajuste direto"))

    # INE crime
    if ine_crime_values:
        cards.append(("🔴", f"{ine_crime_values[-1]:.1f}", "Crime Rate (INE)", f"{ine_crime_years[-1]}"))

    # INE immigration
    if immig_values:
        latest_immig = immig_values[-1]
        if latest_immig >= 1_000_000:
            immig_str = f"{latest_immig/1_000_000:.1f}M"
        elif latest_immig >= 1_000:
            immig_str = f"{latest_immig/1_000:.0f}K"
        else:
            immig_str = f"{int(latest_immig):,}"
        # Compute growth
        immig_growth = ""
        if len(immig_values) >= 2 and immig_values[-2] > 0:
            g = ((immig_values[-1] - immig_values[-2]) / immig_values[-2]) * 100
            immig_growth = f"{g:+.1f}% YoY"
        cards.append(("🌍", immig_str, f"Foreign Residents ({immig_years[-1]})", immig_growth))

    for icon, value, label, sub in cards:
        p.append(f'<div class="summary-card"><div class="sc-icon">{icon}</div><div class="sc-value">{value}</div><div class="sc-label">{label}</div>')
        if sub:
            p.append(f'<div class="sc-sub">{esc(sub)}</div>')
        p.append('</div>')
    p.append('</div>')

    # ── Risk Panel ───────────────────────────────────────────────────────────
    if risk_signals or risk_level != "unknown":
        p.append(f'<div class="risk-panel" style="border-color:{r_color};background:{risk_bg.get(risk_level, "transparent")}">')
        p.append(f'<h3 style="color:{r_color}">🎯 Composite Risk Score: {composite} — {risk_level.upper()}</h3>')
        if risk_signals:
            for sig in risk_signals:
                sev = sig.get("severity", "unknown")
                sev_color = {"high": "#ef4444", "medium": "#f59e0b"}.get(sev, "#94a3b8")
                p.append(f'<div class="risk-signal"><div class="severity" style="background:{sev_color};color:white">{sev}</div><div class="detail">{esc(sig.get("detail", ""))}</div></div>')
        else:
            p.append('<div style="color:var(--muted);font-size:13px;padding:8px">No risk signals detected. Run the full pipeline for deep analysis.</div>')
        p.append('</div>')

    # ── Charts Grid ──────────────────────────────────────────────────────────
    p.append('<div class="chart-grid">')

    # Chart 1: Corruption + Money Laundering Trends
    if cor_years:
        p.append('<div class="chart-box"><h3>⚖️ Corruption & Money-Laundering Trends <span class="tag" style="background:rgba(239,68,68,.2);color:#ef4444">JUSTICE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartCorruption"></canvas></div></div>')

    # Chart 2: Court Case Flow
    if court_years:
        p.append('<div class="chart-box"><h3>🏛️ Court Case Flow <span class="tag" style="background:rgba(59,130,246,.2);color:#3b82f6">JUSTICE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartCourt"></canvas></div></div>')

    # Chart 3: Prison Population
    if prison_years:
        p.append('<div class="chart-box"><h3>🔒 Prison Population <span class="tag" style="background:rgba(139,92,246,.2);color:#8b5cf6">JUSTICE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartPrison"></canvas></div></div>')

    # Chart 4: Procurement Contracts Over Time
    if py_years:
        p.append('<div class="chart-box"><h3>📊 Procurement Volume & Value <span class="tag" style="background:rgba(245,158,11,.2);color:#f59e0b">PROCUREMENT</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartProcurement"></canvas></div></div>')

    # Chart 5: INE Crime Rate
    if ine_crime_years:
        p.append('<div class="chart-box"><h3>🔴 Crime Rate (INE) <span class="tag" style="background:rgba(239,68,68,.2);color:#ef4444">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartCrime"></canvas></div></div>')

    # Chart 5b: Immigration
    if immig_years:
        p.append('<div class="chart-box"><h3>🌍 Foreign Residents (INE) <span class="tag" style="background:rgba(20,184,166,.2);color:#14b8a6">INE</span></h3>')
        p.append('<div class="chart-container"><canvas id="chartImmig"></canvas></div></div>')

    # Chart 6: Risk Signal Radar
    p.append('<div class="chart-box"><h3>🎯 Risk Signal Overview <span class="tag" style="background:rgba(245,158,11,.2);color:#f59e0b">CROSS-REF</span></h3>')
    p.append('<div class="chart-container"><canvas id="chartRadar"></canvas></div></div>')

    p.append('</div>')  # chart-grid

    # ── Data Tables ──────────────────────────────────────────────────────────
    # Corruption trend table
    if cor_years:
        p.append('<div class="section"><h3>⚖️ Corruption Case Trends (Annual)</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>Year</th><th>Corruption (PJ)</th><th>Money Laundering (PJ)</th><th>Total</th><th>YoY Δ</th></tr></thead><tbody>')
        prev_total = None
        for y in cor_years:
            cj = cor_cj_data.get(y, 0)
            bl = cor_bl_data.get(y, 0)
            total = cj + bl
            yoy = ""
            if prev_total and prev_total > 0:
                delta = ((total - prev_total) / prev_total) * 100
                color = "#ef4444" if delta > 10 else "#22c55e" if delta < -10 else "#f59e0b"
                yoy = f'<span style="color:{color};font-weight:600">{delta:+.1f}%</span>'
            prev_total = total
            p.append(f'<tr><td>{y}</td><td class="value">{fmt_num(int(cj))}</td><td class="value">{fmt_num(int(bl))}</td><td class="value" style="font-weight:700">{fmt_num(int(total))}</td><td>{yoy}</td></tr>')
        p.append('</tbody></table></div></div>')

    # Court flow table
    if court_data:
        p.append('<div class="section"><h3>🏛️ Court Case Flow</h3>')
        p.append('<div class="scroll-table"><table><thead><tr><th>Year</th><th>Entered</th><th>Finalized</th><th>Pending</th><th>Resolution %</th></tr></thead><tbody>')
        for r in court_data:
            if not r.get("year"):
                continue
            entered = r.get("entered", 0) or 0
            finalized = r.get("finalized", 0) or 0
            pending = r.get("pending", 0) or 0
            res = round(finalized / entered * 100, 1) if entered > 0 else 0
            res_color = "#ef4444" if res < 70 else "#f59e0b" if res < 90 else "#22c55e"
            p.append(f'<tr><td>{r["year"]}</td><td class="value">{fmt_num(entered)}</td><td class="value">{fmt_num(finalized)}</td><td class="value">{fmt_num(pending)}</td><td style="color:{res_color};font-weight:600">{res}%</td></tr>')
        p.append('</tbody></table></div></div>')

    # Footer
    p.append(f'<div class="footer">Analisa.pt Corruption Intelligence Dashboard — Generated {gen_time} — Sources: dados.justica.gov.pt, procurement.db, INE API</div>')

    p.append('</div>')  # container

    # ── JavaScript ───────────────────────────────────────────────────────────
    chart_defaults = 'Chart.defaults.color="#94a3b8";Chart.defaults.borderColor="rgba(51,65,85,.5)";'

    p.append(f'<script>{chart_defaults}')

    # Chart 1: Corruption
    if cor_years:
        p.append(f'new Chart(document.getElementById("chartCorruption"),{{type:"line",data:{{labels:{json.dumps(cor_years)},datasets:['
                 f'{{label:"Corruption Cases",data:{json.dumps(cor_cj_values)},borderColor:"#ef4444",backgroundColor:"rgba(239,68,68,.1)",fill:true,tension:.3,pointRadius:3}},'
                 f'{{label:"Money Laundering",data:{json.dumps(cor_bl_values)},borderColor:"#f97316",backgroundColor:"rgba(249,115,22,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{font:{{size:11}}}}}}}},scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Chart 2: Court flow
    if court_years:
        p.append(f'new Chart(document.getElementById("chartCourt"),{{type:"bar",data:{{labels:{json.dumps(court_years)},datasets:['
                 f'{{label:"Entered",data:{json.dumps(court_entered)},backgroundColor:"rgba(59,130,246,.7)",borderRadius:3}},'
                 f'{{label:"Finalized",data:{json.dumps(court_finalized)},backgroundColor:"rgba(34,197,94,.7)",borderRadius:3}},'
                 f'{{label:"Pending",data:{json.dumps(court_pending)},type:"line",borderColor:"#ef4444",borderWidth:2,pointRadius:2,tension:.3,yAxisID:"y1"}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:"index"}},scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}},callback:v=>v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}},y1:{{position:"right",grid:{{drawOnChartArea:false}},ticks:{{font:{{size:10}},callback:v=>v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}}}}}}}});')

    # Chart 3: Prison
    if prison_years:
        p.append(f'new Chart(document.getElementById("chartPrison"),{{type:"line",data:{{labels:{json.dumps(prison_years)},datasets:['
                 f'{{label:"Prison Population",data:{json.dumps(prison_totals)},borderColor:"#8b5cf6",backgroundColor:"rgba(139,92,246,.15)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{font:{{size:11}}}}}}}},scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Chart 4: Procurement
    if py_years:
        p.append(f'new Chart(document.getElementById("chartProcurement"),{{type:"bar",data:{{labels:{json.dumps(py_years)},datasets:['
                 f'{{label:"Contracts",data:{json.dumps(py_contracts)},backgroundColor:"rgba(245,158,11,.7)",borderRadius:3,yAxisID:"y"}},'
                 f'{{label:"Value (€)",data:{json.dumps(py_values)},type:"line",borderColor:"#ef4444",borderWidth:2,pointRadius:2,tension:.3,yAxisID:"y1"}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:"index"}},scales:{{y:{{beginAtZero:true,ticks:{{font:{{size:10}}}}}},y1:{{position:"right",grid:{{drawOnChartArea:false}},ticks:{{font:{{size:10}},callback:v=>v>=1e9?(v/1e9).toFixed(0)+"B":v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v}}}}}}}}}});')

    # Chart 5: INE Crime Rate
    if ine_crime_years:
        p.append(f'new Chart(document.getElementById("chartCrime"),{{type:"line",data:{{labels:{json.dumps(ine_crime_years)},datasets:['
                 f'{{label:"Crime Rate",data:{json.dumps(ine_crime_values)},borderColor:"#ef4444",backgroundColor:"rgba(239,68,68,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{font:{{size:11}}}}}}}},scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Chart 5b: Immigration
    if immig_years:
        p.append(f'new Chart(document.getElementById("chartImmig"),{{type:"line",data:{{labels:{json.dumps(immig_years)},datasets:['
                 f'{{label:"Foreign Residents",data:{json.dumps(immig_values)},borderColor:"#14b8a6",backgroundColor:"rgba(20,184,166,.1)",fill:true,tension:.3,pointRadius:3}}'
                 f']}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{font:{{size:11}}}}}}}},scales:{{y:{{beginAtZero:false,ticks:{{font:{{size:10}}}}}}}}}}}});')

    # Chart 6: Radar
    radar_labels = ["Corruption Trend", "ML Trend", "Court Backlog", "Price Inflation", "Direct Awards"]
    radar_values = [
        1 if crossref.get("corruption_direction") == "rising" else 0.5 if crossref.get("corruption_direction") == "stable" else 0.2,
        1 if crossref.get("laundering_direction") == "rising" else 0.5 if crossref.get("laundering_direction") == "stable" else 0.2,
        min(crossref.get("court_trend", [{}])[-1].get("pending", 0) / max(crossref.get("court_trend", [{}])[-1].get("entered", 1), 1), 1) if crossref.get("court_trend") else 0.5,
        min(proc_signals.get("inflation_rate", 0) / 50, 1),
        min(proc_signals.get("direct_rate", 0) / 100, 1),
    ]
    p.append(f'new Chart(document.getElementById("chartRadar"),{{type:"radar",data:{{labels:{json.dumps(radar_labels)},datasets:['
             f'{{label:"Risk Level",data:{json.dumps(radar_values)},borderColor:"#f59e0b",backgroundColor:"rgba(245,158,11,.2)",pointBackgroundColor:"#f59e0b",pointRadius:4}}'
             f']}},options:{{responsive:true,maintainAspectRatio:false,scales:{{r:{{beginAtZero:true,max:1,ticks:{{display:false}},grid:{{color:"rgba(51,65,85,.5)"}},pointLabels:{{font:{{size:11}},color:"#e2e8f0"}}}}}},plugins:{{legend:{{display:false}}}}}}}});')

    p.append('</script></body></html>')

    return "".join(p)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Justice × Procurement Intelligence Dashboard")
    parser.add_argument("-o", "--output", default=str(SUMMARY_DIR / "justice_intelligence.html"))
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")
    args = parser.parse_args()

    print("  Querying databases...", file=sys.stderr)
    html = generate_dashboard()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✅ Dashboard written to {out_path} ({len(html):,} bytes)", file=sys.stderr)

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
