#!/usr/bin/env python3
"""HTML Dashboard Generator for Entity Transparency Profiles

Generates a self-contained HTML file with interactive Chart.js charts
for any Portuguese public entity.

Usage:
    python generate_html.py "Câmara Municipal de Gaia" -o gaia.html
    python generate_html.py --nif 500014872 -o gaia.html
    python generate_html.py "Saúde" --open
"""

import sys
import json
import html as html_mod
import argparse
import webbrowser
from pathlib import Path

# Import shared data functions
from entity_profile import (
    search_entities, get_entity_listings, get_entity_contracts,
    get_entity_dre, get_entity_laws, compute_contract_trends,
    compute_hiring_trends,
)


def _safe_int(val, default=1):
    """Safely convert a value to int."""
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default

BASE_DETAIL_URL = "https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id="


def _esc(s: str) -> str:
    """Escape HTML special characters to prevent XSS."""
    return html_mod.escape(str(s)) if s else ""


def build_html(entity, listings, contracts, dre, laws) -> str:
    """Generate a self-contained HTML dashboard."""
    contract_trends = compute_contract_trends(contracts)
    hiring_trends = compute_hiring_trends(listings)
    total_value = sum(c.get("valor", 0) for c in contracts)
    nif = entity.get("nif", "")

    # Prepare chart data
    ct_labels = json.dumps(list(contract_trends.keys()))
    ct_values = json.dumps([round(d["value"], 2) for d in contract_trends.values()])
    ct_counts = json.dumps([d["count"] for d in contract_trends.values()])

    ht_labels = json.dumps(list(hiring_trends.keys()))
    ht_counts = json.dumps([d["count"] for d in hiring_trends.values()])
    ht_positions = json.dumps([d["positions"] for d in hiring_trends.values()])

    # Contract type breakdown
    ct_types = {}
    for c in contracts:
        t = c.get("tipo") or "Unknown"
        ct_types[t] = ct_types.get(t, 0) + 1
    ct_type_labels = json.dumps(list(ct_types.keys()))
    ct_type_values = json.dumps(list(ct_types.values()))

    # Hiring category breakdown
    h_types = {}
    for l in listings:
        t = l.get("tipo_oferta") or l.get("categoria") or "Unknown"
        h_types[t] = h_types.get(t, 0) + 1
    h_type_labels = json.dumps(list(h_types.keys())[:10])
    h_type_values = json.dumps(list(h_types.values())[:10])

    # Listings table rows
    listing_rows = ""
    for l in listings[:50]:
        status_cls = "open" if "aberta" in (l.get("estado") or "").lower() else "closed"
        url = _esc(l.get("url", ""))
        listing_rows += f"""<tr>
<td><span class="badge {status_cls}">{_esc(l.get('estado', '—'))}</span></td>
<td>{_esc(l.get('titulo', '—')[:60])}</td>
<td>{_esc(l.get('categoria', '—'))}</td>
<td>€{_esc(l.get('remuneracao', '—'))}</td>
<td>{_esc(l.get('total_postos', '1'))}</td>
<td>{_esc(l.get('data_limite', '—')[:10]) if l.get('data_limite') else '—'}</td>
<td>{"<a href='" + url + "' target='_blank'>🔗</a>" if url else '—'}</td>
</tr>"""

    # Contracts table rows
    contract_rows = ""
    for c in contracts[:50]:
        detail_url = _esc(c.get('detail_url', '#'))
        proc_url = _esc(c.get('link_pecas_proc', ''))
        detail = f"<a href='{detail_url}' target='_blank'>📋</a>" if c.get("detail_url") else "—"
        link = f"<a href='{proc_url}' target='_blank'>📎</a>" if c.get("link_pecas_proc") else "—"
        contract_rows += f"""<tr>
<td>{_esc(c.get('data', '—'))}</td>
<td>€{c.get('valor', 0):,.2f}</td>
<td>{_esc(c.get('tipo', '—'))}</td>
<td title="{_esc(c.get('objeto', ''))}">{_esc((c.get('objeto', '—') or '—')[:50])}</td>
<td>{detail}</td>
<td>{link}</td>
</tr>"""

    # DRE rows
    dre_rows = ""
    for d in dre[:20]:
        title = _esc(d.get("title") or f"Serie {d['serie']} #{d['numero']}/{d['year']}")
        url = _esc(d.get("redirect_url") or d.get("eli_url") or "#")
        dre_rows += f"""<tr>
<td>{_esc(d.get('serie', '—'))}</td>
<td>{_esc(d.get('numero', '—'))}</td>
<td>{_esc(d.get('year', '—'))}</td>
<td>{title[:60]}</td>
<td><a href="{url}" target="_blank">🔗</a></td>
</tr>"""

    # Laws rows
    law_rows = ""
    for l in laws[:20]:
        law_rows += f"""<tr>
<td>{_esc(l.get('ini_desc_tipo', '—'))}</td>
<td>{_esc(l.get('ini_titulo', '—')[:50])}</td>
<td>{_esc(l.get('latest_fase', '—'))}</td>
<td>{_esc(l.get('latest_fase_date', '—'))}</td>
<td>{_esc(l.get('vote_result') or '—')}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Transparency Profile — {_esc(entity['display_name'])}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 2rem 0; }}
.header .container {{ max-width: 1200px; margin: 0 auto; padding: 0 2rem; }}
.header h1 {{ font-size: 1.8rem; color: #f8fafc; margin-bottom: 0.5rem; }}
.header .subtitle {{ color: #94a3b8; font-size: 0.95rem; }}
.header .meta {{ display: flex; gap: 2rem; margin-top: 1rem; flex-wrap: wrap; }}
.header .meta-item {{ display: flex; align-items: center; gap: 0.5rem; color: #cbd5e1; font-size: 0.85rem; }}
.header .meta-item a {{ color: #60a5fa; text-decoration: none; }}
.header .meta-item a:hover {{ text-decoration: underline; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
.card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; transition: transform 0.2s, box-shadow 0.2s; }}
.card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }}
.card .icon {{ font-size: 2rem; margin-bottom: 0.5rem; }}
.card .value {{ font-size: 1.8rem; font-weight: 700; color: #f8fafc; }}
.card .label {{ font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
@media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} }}
.chart-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.chart-box h3 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1rem; }}
.section {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }}
.section h2 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1.1rem; display: flex; align-items: center; gap: 0.5rem; }}
.section h2 .count {{ background: #3b82f6; color: white; padding: 0.1rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 2px solid #334155; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; position: sticky; top: 0; background: #1e293b; }}
td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
tr:hover td {{ background: #334155; }}
.table-wrap {{ max-height: 400px; overflow-y: auto; }}
.badge {{ padding: 0.15rem 0.5rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; }}
.badge.open {{ background: #166534; color: #86efac; }}
.badge.closed {{ background: #7f1d1d; color: #fca5a5; }}
a {{ color: #60a5fa; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.footer {{ text-align: center; padding: 2rem; color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; }}
</style>
</head>
<body>

<div class="header">
<div class="container">
<h1>🔍 {_esc(entity['display_name'])}</h1>
<div class="subtitle">Transparency Profile — Analisa.pt</div>
<div class="meta">
<div class="meta-item">📋 NIF: <strong>{_esc(nif) or 'N/A'}</strong></div>
<div class="meta-item">🏛️ {_esc(entity.get('entidade', '—')[:60])}</div>
<div class="meta-item">🔗 <a href="https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={nif}" target="_blank">BASE.gov.pt</a></div>
</div>
</div>
</div>

<div class="container">

<div class="cards">
<div class="card">
<div class="icon">📋</div>
<div class="value">{entity.get('listing_count', 0)}</div>
<div class="label">BEP Job Listings</div>
</div>
<div class="card">
<div class="icon">📦</div>
<div class="value">{len(contracts)}</div>
<div class="label">BASE Contracts</div>
</div>
<div class="card">
<div class="icon">💰</div>
<div class="value">€{total_value:,.0f}</div>
<div class="label">Total Contract Value</div>
</div>
<div class="card">
<div class="icon">📰</div>
<div class="value">{len(dre)}</div>
<div class="label">DRE Publications</div>
</div>
<div class="card">
<div class="icon">⚖️</div>
<div class="value">{len(laws)}</div>
<div class="label">Law Projects</div>
</div>
</div>

<div class="charts">
<div class="chart-box">
<h3>📈 Contract Value by Month</h3>
<canvas id="contractChart"></canvas>
</div>
<div class="chart-box">
<h3>📊 BEP Hiring by Month</h3>
<canvas id="hiringChart"></canvas>
</div>
<div class="chart-box">
<h3>🔄 Contract Types</h3>
<canvas id="contractTypeChart"></canvas>
</div>
<div class="chart-box">
<h3>👥 Hiring Categories</h3>
<canvas id="hiringTypeChart"></canvas>
</div>
</div>

<div class="section">
<h2>📋 BEP Job Listings <span class="count">{len(listings)}</span></h2>
<div class="table-wrap">
<table>
<thead><tr><th>Status</th><th>Title</th><th>Category</th><th>Salary</th><th>Positions</th><th>Deadline</th><th>Link</th></tr></thead>
<tbody>{listing_rows}</tbody>
</table>
</div>
</div>

<div class="section">
<h2>📦 BASE.gov.pt Contracts <span class="count">{len(contracts)}</span></h2>
<div class="table-wrap">
<table>
<thead><tr><th>Date</th><th>Value</th><th>Type</th><th>Description</th><th>Detail</th><th>Docs</th></tr></thead>
<tbody>{contract_rows}</tbody>
</table>
</div>
</div>

<div class="section">
<h2>📰 DRE Publications <span class="count">{len(dre)}</span></h2>
<div class="table-wrap">
<table>
<thead><tr><th>Serie</th><th>Number</th><th>Year</th><th>Title</th><th>Link</th></tr></thead>
<tbody>{dre_rows}</tbody>
</table>
</div>
</div>

<div class="section">
<h2>⚖️ Law Projects <span class="count">{len(laws)}</span></h2>
<div class="table-wrap">
<table>
<thead><tr><th>Type</th><th>Title</th><th>Phase</th><th>Date</th><th>Vote</th></tr></thead>
<tbody>{law_rows}</tbody>
</table>
</div>
</div>

</div>

<div class="footer">
Generated by Analisa.pt Entity Transparency Profile — {_esc(entity['display_name'])}
</div>

<script>
const chartDefaults = {{
    color: '#94a3b8',
    borderColor: '#334155',
    font: {{ family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" }}
}};
Chart.defaults.color = chartDefaults.color;
Chart.defaults.borderColor = chartDefaults.borderColor;

// Contract Value Chart
new Chart(document.getElementById('contractChart'), {{
    type: 'bar',
    data: {{
        labels: {ct_labels},
        datasets: [{{
            label: 'Contract Value (€)',
            data: {ct_values},
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderRadius: 4,
        }}, {{
            label: 'Number of Contracts',
            data: {ct_counts},
            type: 'line',
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            yAxisID: 'y1',
            tension: 0.3,
            pointRadius: 3,
        }}]
    }},
    options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{
            y: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }},
            y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }}
        }},
        plugins: {{
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.yAxisID === 'y1' ? ctx.parsed.y + ' contracts' : '€' + ctx.parsed.y.toLocaleString() }} }}
        }}
    }}
}});

// Hiring Chart
new Chart(document.getElementById('hiringChart'), {{
    type: 'bar',
    data: {{
        labels: {ht_labels},
        datasets: [{{
            label: 'Listings',
            data: {ht_counts},
            backgroundColor: 'rgba(16, 185, 129, 0.7)',
            borderColor: '#10b981',
            borderWidth: 1,
            borderRadius: 4,
        }}, {{
            label: 'Total Positions',
            data: {ht_positions},
            type: 'line',
            borderColor: '#8b5cf6',
            backgroundColor: 'rgba(139, 92, 246, 0.1)',
            yAxisID: 'y1',
            tension: 0.3,
            pointRadius: 3,
        }}]
    }},
    options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{
            y: {{ beginAtZero: true }},
            y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }}
        }}
    }}
}});

// Contract Type Doughnut
new Chart(document.getElementById('contractTypeChart'), {{
    type: 'doughnut',
    data: {{
        labels: {ct_type_labels},
        datasets: [{{
            data: {ct_type_values},
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'],
            borderWidth: 0,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ position: 'right', labels: {{ padding: 12, usePointStyle: true, pointStyle: 'circle' }} }}
        }}
    }}
}});

// Hiring Category Bar
new Chart(document.getElementById('hiringTypeChart'), {{
    type: 'bar',
    data: {{
        labels: {h_type_labels},
        datasets: [{{
            label: 'Listings',
            data: {h_type_values},
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22d3ee'],
            borderRadius: 4,
        }}]
    }},
    options: {{
        responsive: true,
        indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ beginAtZero: true }} }}
    }}
}});
</script>

</body>
</html>"""


def build_comparison_html(ea, la, ca, da, laa, eb, lb, cb, db, lb2) -> str:
    """Generate a side-by-side comparison HTML dashboard."""
    total_a = sum(c.get("valor", 0) for c in ca)
    total_b = sum(c.get("valor", 0) for c in cb)
    ct_trends_a = compute_contract_trends(ca)
    ct_trends_b = compute_contract_trends(cb)
    ht_trends_a = compute_hiring_trends(la)
    ht_trends_b = compute_hiring_trends(lb)

    # Merge all months for consistent x-axis
    all_months = sorted(set(list(ct_trends_a.keys()) + list(ct_trends_b.keys())))
    all_h_months = sorted(set(list(ht_trends_a.keys()) + list(ht_trends_b.keys())))

    ct_a_vals = json.dumps([round(ct_trends_a.get(m, {}).get("value", 0), 2) for m in all_months])
    ct_b_vals = json.dumps([round(ct_trends_b.get(m, {}).get("value", 0), 2) for m in all_months])
    ct_labels = json.dumps(all_months)

    ht_a_vals = json.dumps([ht_trends_a.get(m, {}).get("count", 0) for m in all_h_months])
    ht_b_vals = json.dumps([ht_trends_b.get(m, {}).get("count", 0) for m in all_h_months])
    ht_labels = json.dumps(all_h_months)

    # Contract type breakdown
    def _type_counts(contracts):
        types = {}
        for c in contracts:
            t = c.get("tipo") or "Unknown"
            types[t] = types.get(t, 0) + 1
        return types
    all_ct = {**_type_counts(ca), **_type_counts(cb)}
    ct_type_labels = json.dumps(list(all_ct.keys()))
    ct_type_a = json.dumps([_type_counts(ca).get(k, 0) for k in all_ct.keys()])
    ct_type_b = json.dumps([_type_counts(cb).get(k, 0) for k in all_ct.keys()])

    def _hiring_counts(listings):
        cats = {}
        for l in listings:
            t = l.get("tipo_oferta") or l.get("categoria") or "Unknown"
            cats[t] = cats.get(t, 0) + 1
        return cats
    all_hc = {**_hiring_counts(la), **_hiring_counts(lb)}
    hc_labels = json.dumps(list(all_hc.keys())[:10])
    hc_a = json.dumps([_hiring_counts(la).get(k, 0) for k in list(all_hc.keys())[:10]])
    hc_b = json.dumps([_hiring_counts(lb).get(k, 0) for k in list(all_hc.keys())[:10]])

    name_a = _esc(ea['display_name'][:40])
    name_b = _esc(eb['display_name'][:40])

    # Metric rows
    def metric_row(label, va, vb, fmt="num"):
        if fmt == "money":
            a_s = f"€{va:,.0f}" if va else "—"
            b_s = f"€{vb:,.0f}" if vb else "—"
        else:
            a_s = f"{va:,}" if va else "—"
            b_s = f"{vb:,}" if vb else "—"
        w = "◀" if va > vb else ("▶" if vb > va else "═")
        return f"<tr><td>{label}</td><td class='val-a'>{a_s}</td><td class='sym'>{w}</td><td class='val-b'>{b_s}</td></tr>"

    metric_rows = ""
    metric_rows += metric_row("BEP Listings", len(la), len(lb))
    metric_rows += metric_row("Positions",
        sum(_safe_int(l.get('total_postos')) for l in la),
        sum(_safe_int(l.get('total_postos')) for l in lb))
    metric_rows += metric_row("Contracts", len(ca), len(cb))
    metric_rows += metric_row("Contract Value", total_a, total_b, "money")
    metric_rows += metric_row("DRE Publications", len(da), len(db))
    metric_rows += metric_row("Law Projects", len(laa), len(lb2))

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Comparison — {name_a} vs {name_b}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 2rem 0; text-align: center; }}
.header h1 {{ font-size: 1.6rem; color: #f8fafc; }}
.header h1 .vs {{ color: #60a5fa; margin: 0 0.5rem; }}
.header .subtitle {{ color: #94a3b8; font-size: 0.9rem; margin-top: 0.5rem; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 2rem; }}
.card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; text-align: center; }}
.card .label {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
.card .val-a {{ color: #3b82f6; font-size: 1.4rem; font-weight: 700; }}
.card .val-b {{ color: #10b981; font-size: 1.4rem; font-weight: 700; }}
.card .sym {{ color: #f59e0b; font-size: 1rem; padding: 0 0.3rem; }}
.metrics-table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
.metrics-table th {{ padding: 0.8rem; background: #334155; color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
.metrics-table td {{ padding: 0.6rem 0.8rem; border-bottom: 1px solid #1e293b; font-size: 0.9rem; }}
.metrics-table .val-a {{ color: #3b82f6; font-weight: 600; text-align: right; }}
.metrics-table .val-b {{ color: #10b981; font-weight: 600; text-align: left; }}
.metrics-table .sym {{ text-align: center; color: #f59e0b; width: 30px; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
@media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} .cards {{ grid-template-columns: 1fr; }} }}
.chart-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.chart-box h3 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1rem; }}
.legend {{ display: flex; gap: 1.5rem; justify-content: center; margin-bottom: 1rem; }}
.legend span {{ display: flex; align-items: center; gap: 0.4rem; font-size: 0.8rem; color: #94a3b8; }}
.legend .dot-a {{ width: 10px; height: 10px; border-radius: 50%; background: #3b82f6; }}
.legend .dot-b {{ width: 10px; height: 10px; border-radius: 50%; background: #10b981; }}
.footer {{ text-align: center; padding: 2rem; color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; }}
</style>
</head>
<body>
<div class="header">
<h1>{name_a}<span class="vs">vs</span>{name_b}</h1>
<div class="subtitle">Entity Comparison Dashboard — Analisa.pt</div>
</div>
<div class="container">
<div class="legend">
<span><span class="dot-a"></span>{name_a}</span>
<span><span class="dot-b"></span>{name_b}</span>
</div>
<table class="metrics-table">
<thead><tr><th style='text-align:right'>Entity A</th><th>Metric</th><th>Entity B</th></tr></thead>
<tbody>{metric_rows}</tbody>
</table>
<div class="charts">
<div class="chart-box"><h3>📈 Contract Value by Month</h3><canvas id="ctChart"></canvas></div>
<div class="chart-box"><h3>📊 BEP Hiring by Month</h3><canvas id="htChart"></canvas></div>
<div class="chart-box"><h3>🔄 Contract Types</h3><canvas id="ctTypeChart"></canvas></div>
<div class="chart-box"><h3>👥 Hiring Categories</h3><canvas id="hTypeChart"></canvas></div>
</div>
</div>
<div class="footer">Generated by Analisa.pt — {name_a} vs {name_b}</div>
<script>
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';
new Chart(document.getElementById('ctChart'), {{type:'bar',data:{{labels:{ct_labels},datasets:[{{label:'{name_a}',data:{ct_a_vals},backgroundColor:'rgba(59,130,246,0.7)',borderRadius:4}},{{label:'{name_b}',data:{ct_b_vals},backgroundColor:'rgba(16,185,129,0.7)',borderRadius:4}}]}},options:{{responsive:true,scales:{{y:{{beginAtZero:true,ticks:{{callback:v=>'€'+v.toLocaleString()}}}}}},plugins:{{tooltip:{{callbacks:{{label:ctx=>ctx.dataset.label+': €'+ctx.parsed.y.toLocaleString()}}}}}}}}}});
new Chart(document.getElementById('htChart'), {{type:'bar',data:{{labels:{ht_labels},datasets:[{{label:'{name_a}',data:{ht_a_vals},backgroundColor:'rgba(59,130,246,0.7)',borderRadius:4}},{{label:'{name_b}',data:{ht_b_vals},backgroundColor:'rgba(16,185,129,0.7)',borderRadius:4}}]}},options:{{responsive:true,scales:{{y:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('ctTypeChart'), {{type:'bar',data:{{labels:{ct_type_labels},datasets:[{{label:'{name_a}',data:{ct_type_a},backgroundColor:'rgba(59,130,246,0.7)',borderRadius:4}},{{label:'{name_b}',data:{ct_type_b},backgroundColor:'rgba(16,185,129,0.7)',borderRadius:4}}]}},options:{{responsive:true,indexAxis:'y',scales:{{x:{{beginAtZero:true}}}}}}}});
new Chart(document.getElementById('hTypeChart'), {{type:'bar',data:{{labels:{hc_labels},datasets:[{{label:'{name_a}',data:{hc_a},backgroundColor:'rgba(59,130,246,0.7)',borderRadius:4}},{{label:'{name_b}',data:{hc_b},backgroundColor:'rgba(16,185,129,0.7)',borderRadius:4}}]}},options:{{responsive:true,indexAxis:'y',scales:{{x:{{beginAtZero:true}}}}}}}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML Transparency Dashboard")
    parser.add_argument("query", nargs="?", default="", help="Entity name")
    parser.add_argument("--nif", default="", help="Filter by NIF")
    parser.add_argument("-o", "--output", default="", help="Output HTML file")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")
    parser.add_argument("--compare", nargs="?", default="", help="Compare with another entity (name or NIF)")

    args = parser.parse_args()

    if not args.query and not args.nif:
        parser.print_help()
        sys.exit(1)

    # Resolve entity A
    entities_a = search_entities(query=args.query, nif=args.nif, limit=1)
    if not entities_a:
        print(f"No entity found matching '{args.query or args.nif}'")
        sys.exit(1)
    ea = entities_a[0]

    # Check if comparison mode
    if args.compare:
        # Resolve entity B
        if args.compare.isdigit():
            entities_b = search_entities(nif=args.compare, limit=1)
        else:
            entities_b = search_entities(query=args.compare, limit=1)
        if not entities_b:
            print(f"No entity found matching '{args.compare}'")
            sys.exit(1)
        eb = entities_b[0]

        print(f"Generating comparison: {ea['display_name']} vs {eb['display_name']}...")
        la = get_entity_listings(ea["id"])
        ca = get_entity_contracts(ea.get("nif", ""))
        da = get_entity_dre(ea["display_name"])
        laa = get_entity_laws(ea["display_name"])
        lb = get_entity_listings(eb["id"])
        cb = get_entity_contracts(eb.get("nif", ""))
        db = get_entity_dre(eb["display_name"])
        lb2 = get_entity_laws(eb["display_name"])
        print(f"  A: {len(la)} listings, {len(ca)} contracts | B: {len(lb)} listings, {len(cb)} contracts")
        html = build_comparison_html(ea, la, ca, da, laa, eb, lb, cb, db, lb2)
        output = args.output or f"comparison_{ea.get('nif','a')}_vs_{eb.get('nif','b')}.html"
    else:
        print(f"Generating dashboard for {ea['display_name']}...")
        la = get_entity_listings(ea["id"])
        ca = get_entity_contracts(ea.get("nif", ""))
        da = get_entity_dre(ea["display_name"])
        laa = get_entity_laws(ea["display_name"])
        print(f"  BEP: {len(la)} listings | BASE: {len(ca)} contracts | DRE: {len(da)} | Laws: {len(laa)}")
        html = build_html(ea, la, ca, da, laa)
        output = args.output or f"dashboard_{ea.get('nif', 'entity')}.html"

    Path(output).write_text(html, encoding="utf-8")
    print(f"  ✅ Dashboard saved to {output}")

    if args.open:
        webbrowser.open(Path(output).resolve().as_uri())


if __name__ == "__main__":
    main()
