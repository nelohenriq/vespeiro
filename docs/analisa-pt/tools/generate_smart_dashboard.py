#!/usr/bin/env python3
"""Smart Dashboard Generator — Adaptive Layouts Based on Data Profile

Analyzes entity/sector data characteristics and generates an HTML dashboard
with the optimal layout for that specific data shape. Different data profiles
get different visualization strategies:

  hiring-heavy  → Timeline-first layout with large hiring chart
  contract-heavy → Value-first layout with large contract chart
  balanced      → 2-column grid with all charts
  sparse        → Single-column summary with minimal charts
  rich          → Full dashboard with all sections expanded

Usage:
    python generate_smart_dashboard.py --nif 500014872 -o smart.html
    python generate_smart_dashboard.py "Câmara Municipal de Gaia" --open
    python generate_smart_dashboard.py --sector "Saúde" -o sector_smart.html
    python generate_smart_dashboard.py --nif 500014872 --profile  # Show data profile only
"""

import sys
import json
import html as html_mod
import argparse
import webbrowser
from pathlib import Path

# Import shared contract lookup from entity_profile (includes name-based fallback)
try:
    from entity_profile import get_entity_contracts
except ImportError:
    pass  # fallback: use local definition if available
from collections import defaultdict
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"

BASE_DETAIL_URL = "https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id="


def _esc(s):
    return html_mod.escape(str(s)) if s else ""


def _safe_int(val, default=0):
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Data loading (from entity_profile.py + generate_html.py)
# ---------------------------------------------------------------------------

def search_entities(query="", nif="", limit=20):
    conn = db_connect(str(BEP_DB))
    if nif:
        rows = conn.execute(
            "SELECT id, display_name, entidade, organismo, nif, listing_count "
            "FROM bep_entities WHERE nif = ? ORDER BY listing_count DESC",
            (nif,),
        ).fetchall()
    elif query:
        rows = conn.execute(
            "SELECT id, display_name, entidade, organismo, nif, listing_count "
            "FROM bep_entities WHERE display_name LIKE ? OR entidade LIKE ? "
            "OR organismo LIKE ? ORDER BY listing_count DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, display_name, entidade, organismo, nif, listing_count "
            "FROM bep_entities ORDER BY listing_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "display_name": r[1], "entidade": r[2], "organismo": r[3],
         "nif": r[4], "listing_count": r[5]}
        for r in rows
    ]


def get_entity_listings(entity_id):
    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT titulo, estado, categoria, tipo_oferta, remuneracao, "
        "total_postos, local_trabalho, data_publicacao, data_limite, url "
        "FROM bep_listings WHERE entity_id = ? ORDER BY data_publicacao DESC",
        (entity_id,),
    ).fetchall()
    conn.close()
    return [
        {"titulo": r[0], "estado": r[1], "categoria": r[2], "tipo_oferta": r[3],
         "remuneracao": r[4], "total_postos": r[5], "local_trabalho": r[6],
         "data_publicacao": r[7], "data_limite": r[8], "url": r[9]}
        for r in rows
    ]


def get_entity_contracts(nif):
    if not nif or not CONTRACT_CACHE.exists():
        return []
    with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
        index = json.load(f)
    contracts = index.get(nif, [])
    for c in contracts:
        cid = c.get("contract_id")
        c["detail_url"] = f"{BASE_DETAIL_URL}{cid}" if cid else ""
    contracts.sort(key=lambda c: c.get("data", ""), reverse=True)
    return contracts


# ---------------------------------------------------------------------------
# Data Profiler — Analyzes data shape to select optimal layout
# ---------------------------------------------------------------------------

def profile_entity(entity, listings, contracts):
    """Profile an entity's data to determine optimal dashboard layout."""
    n_listings = len(listings)
    n_contracts = len(contracts)
    total_value = sum(c.get("valor", 0) for c in contracts)

    # Temporal coverage
    listing_months = set()
    for l in listings:
        pub = l.get("data_publicacao", "")
        if pub and len(pub) >= 7:
            listing_months.add(pub[:7])
    contract_months = set()
    for c in contracts:
        date = c.get("data", "")
        if date and len(date) >= 7:
            contract_months.add(date[:7])
    all_months = listing_months | contract_months
    temporal_coverage = len(all_months)

    # Category diversity
    categories = set()
    for l in listings:
        cat = l.get("tipo_oferta") or l.get("categoria") or "Outros"
        categories.add(cat)
    category_diversity = len(categories)

    # Geographic spread
    locations = set()
    for l in listings:
        loc = l.get("local_trabalho", "")
        if loc:
            locations.add(loc[:30])
    geo_spread = len(locations)

    # Positions
    total_positions = sum(_safe_int(l.get("total_postos"), 1) for l in listings)

    # Determine data shape
    if n_listings == 0 and n_contracts == 0:
        shape = "empty"
    elif n_listings > 100 and n_contracts < 5:
        shape = "hiring-heavy"
    elif n_contracts > 20 and n_listings < 20:
        shape = "contract-heavy"
    elif n_listings > 50 and n_contracts > 20:
        shape = "rich"
    elif n_listings < 15 and n_contracts < 10:
        shape = "sparse"
    else:
        shape = "balanced"

    return {
        "shape": shape,
        "n_listings": n_listings,
        "n_contracts": n_contracts,
        "total_value": total_value,
        "total_positions": total_positions,
        "temporal_coverage": temporal_coverage,
        "listing_months": sorted(listing_months),
        "contract_months": sorted(contract_months),
        "category_diversity": category_diversity,
        "geo_spread": geo_spread,
    }


# ---------------------------------------------------------------------------
# Chart data computation
# ---------------------------------------------------------------------------

def compute_hiring_trends(listings):
    by_month = defaultdict(lambda: {"count": 0, "positions": 0})
    for l in listings:
        pub = l.get("data_publicacao", "")
        if pub and len(pub) >= 7:
            month = pub[:7]
            by_month[month]["count"] += 1
            by_month[month]["positions"] += _safe_int(l.get("total_postos"), 1)
    return dict(sorted(by_month.items()))


def compute_contract_trends(contracts):
    by_month = defaultdict(lambda: {"count": 0, "value": 0.0})
    for c in contracts:
        date = c.get("data", "")
        if date and len(date) >= 7:
            month = date[:7]
            by_month[month]["count"] += 1
            by_month[month]["value"] += c.get("valor", 0)
    return dict(sorted(by_month.items()))


def compute_category_breakdown(listings):
    cats = defaultdict(int)
    for l in listings:
        cat = l.get("tipo_oferta") or l.get("categoria") or "Outros"
        cats[cat] += 1
    return dict(sorted(cats.items(), key=lambda x: -x[1])[:8])


def compute_contract_types(contracts):
    types = defaultdict(int)
    for c in contracts:
        tipo = c.get("tipo") or "Outros"
        types[tipo] += 1
    return dict(sorted(types.items(), key=lambda x: -x[1])[:8])


def compute_location_breakdown(listings):
    locs = defaultdict(int)
    for l in listings:
        loc = l.get("local_trabalho", "")
        if loc:
            locs[loc[:40]] += 1
    return dict(sorted(locs.items(), key=lambda x: -x[1])[:8])


# ---------------------------------------------------------------------------
# HTML builders — one per layout strategy
# ---------------------------------------------------------------------------

def _build_css():
    return """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; }
.header { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 1.5rem 2rem; }
.header h1 { font-size: 1.6rem; color: #f8fafc; margin-bottom: 0.3rem; }
.header .subtitle { color: #94a3b8; font-size: 0.9rem; }
.header .meta { display: flex; gap: 1.5rem; margin-top: 0.8rem; flex-wrap: wrap; }
.header .meta-item { color: #cbd5e1; font-size: 0.85rem; }
.header .meta-item a { color: #60a5fa; text-decoration: none; }
.header .meta-item a:hover { text-decoration: underline; }
.profile-badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; margin-left: 0.5rem; vertical-align: middle; }
.container { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.8rem; margin-bottom: 1.5rem; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1rem; text-align: center; transition: transform 0.2s, box-shadow 0.2s; }
.card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
.card .icon { font-size: 1.5rem; margin-bottom: 0.3rem; }
.card .value { font-size: 1.5rem; font-weight: 700; color: #f8fafc; }
.card .label { font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
.charts { display: grid; gap: 1rem; margin-bottom: 1.5rem; }
.charts.cols-2 { grid-template-columns: 1fr 1fr; }
.charts.cols-1 { grid-template-columns: 1fr; }
@media (max-width: 768px) { .charts.cols-2 { grid-template-columns: 1fr; } }
.chart-box { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; }
.chart-box h3 { color: #f8fafc; margin-bottom: 0.8rem; font-size: 0.95rem; }
.chart-box canvas { max-height: 250px; }
.section { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; margin-bottom: 1.2rem; }
.section h2 { color: #f8fafc; margin-bottom: 0.8rem; font-size: 1rem; display: flex; align-items: center; gap: 0.5rem; }
.section h2 .count { background: #3b82f6; color: white; padding: 0.1rem 0.4rem; border-radius: 9999px; font-size: 0.7rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 2px solid #334155; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.04em; position: sticky; top: 0; background: #1e293b; }
td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }
tr:hover td { background: #334155; }
.table-wrap { max-height: 350px; overflow-y: auto; }
.badge { padding: 0.12rem 0.4rem; border-radius: 9999px; font-size: 0.68rem; font-weight: 600; }
.badge.open { background: #166534; color: #86efac; }
.badge.closed { background: #7f1d1d; color: #fca5a5; }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
.footer { text-align: center; padding: 1.5rem; color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; }
"""


def _build_header(entity, profile):
    shape = profile["shape"]
    badge_colors = {
        "hiring-heavy": "#10b981", "contract-heavy": "#3b82f6",
        "rich": "#8b5cf6", "balanced": "#f59e0b", "sparse": "#64748b", "empty": "#ef4444"
    }
    badge_labels = {
        "hiring-heavy": "Hiring-Focused", "contract-heavy": "Contract-Focused",
        "rich": "Rich Data", "balanced": "Balanced", "sparse": "Sparse Data", "empty": "No Data"
    }
    color = badge_colors.get(shape, "#64748b")
    label = badge_labels.get(shape, shape)

    nif = entity.get("nif", "")
    html = '<div class="header">\n'
    html += '<div class="container">\n'
    html += '<h1>\U0001f50d ' + _esc(entity["display_name"])
    html += ' <span class="profile-badge" style="background:' + color + ';color:white">' + label + '</span></h1>\n'
    html += '<div class="subtitle">Smart Dashboard — Analisa.pt</div>\n'
    html += '<div class="meta">\n'
    html += '<div class="meta-item">\U0001f4cb NIF: <strong>' + _esc(nif or "N/A") + '</strong></div>\n'
    html += '<div class="meta-item">\U0001f3db\ufe0f ' + _esc((entity.get("entidade") or "")[:60]) + '</div>\n'
    if nif:
        html += '<div class="meta-item">\U0001f517 <a href="https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id=' + nif + '" target="_blank">BASE.gov.pt</a></div>\n'
    html += '</div>\n</div>\n</div>\n'
    return html


def _build_cards(profile):
    html = '<div class="cards">\n'
    html += '<div class="card"><div class="icon">\U0001f4cb</div><div class="value">' + str(profile["n_listings"]) + '</div><div class="label">BEP Listings</div></div>\n'
    html += '<div class="card"><div class="icon">\U0001f4e6</div><div class="value">' + str(profile["n_contracts"]) + '</div><div class="label">Contracts</div></div>\n'
    html += '<div class="card"><div class="icon">\U0001f4b0</div><div class="value">\u20ac' + f'{profile["total_value"]:,.0f}' + '</div><div class="label">Contract Value</div></div>\n'
    html += '<div class="card"><div class="icon">\U0001f465</div><div class="value">' + str(profile["total_positions"]) + '</div><div class="label">Positions</div></div>\n'
    if profile["temporal_coverage"] > 0:
        html += '<div class="card"><div class="icon">\U0001f4c5</div><div class="value">' + str(profile["temporal_coverage"]) + '</div><div class="label">Months of Data</div></div>\n'
    html += '</div>\n'
    return html


def _chart_script(chart_id, chart_type, labels, data, options_extra=""):
    labels_json = json.dumps(labels, ensure_ascii=False)
    data_json = json.dumps(data, ensure_ascii=False)
    return f"""new Chart(document.getElementById('{chart_id}'), {{
    type: '{chart_type}',
    data: {{ labels: {labels_json}, datasets: [{{ data: {data_json}, backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316'], borderRadius: 4, borderWidth: 0 }}] }},
    options: {{ responsive: true, {options_extra} }}
}});\n"""


# ---------------------------------------------------------------------------
# Layout: hiring-heavy (timeline-first)
# ---------------------------------------------------------------------------

def build_hiring_heavy(entity, listings, contracts, profile):
    ht = compute_hiring_trends(listings)
    cats = compute_category_breakdown(listings)
    ct = compute_contract_trends(contracts)
    c_types = compute_contract_types(contracts)

    all_months = sorted(set(list(ht.keys()) + list(ct.keys())))
    ht_counts = [ht.get(m, {}).get("count", 0) for m in all_months]
    ht_pos = [ht.get(m, {}).get("positions", 0) for m in all_months]
    ct_values = [round(ct.get(m, {}).get("value", 0), 2) for m in all_months]
    ct_counts = [ct.get(m, {}).get("count", 0) for m in all_months]

    cat_keys = list(cats.keys())[:8]
    cat_vals = list(cats.values())[:8]
    ctype_keys = list(c_types.keys())[:8]
    ctype_vals = list(c_types.values())[:8]

    listing_rows = ""
    for l in listings[:30]:
        status_cls = "open" if "aberta" in (l.get("estado") or "").lower() else "closed"
        url = _esc(l.get("url", ""))
        listing_rows += f"""<tr>
<td><span class="badge {status_cls}">{_esc(l.get('estado', '—'))}</span></td>
<td>{_esc(l.get('titulo', '—')[:55])}</td>
<td>{_esc(l.get('categoria', '—'))}</td>
<td>\u20ac{_esc(l.get('remuneracao', '—'))}</td>
<td>{_esc(l.get('total_postos', '1'))}</td>
<td>{_esc(l.get('data_publicacao', '—')[:10]) if l.get('data_publicacao') else '—'}</td>
<td>{"<a href='" + url + "' target='_blank'>\U0001f517</a>" if url else '—'}</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(entity['display_name'])} — Smart Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>{_build_css()}</style>
</head>
<body>
{_build_header(entity, profile)}
{_build_cards(profile)}
<div class="container">
<div class="charts cols-1">
<div class="chart-box"><h3>\U0001f4c8 Hiring Timeline (Primary Focus)</h3><canvas id="hiringChart"></canvas></div>
</div>
<div class="charts cols-2">
<div class="chart-box"><h3>\U0001f4ca Contract Value by Month</h3><canvas id="contractChart"></canvas></div>
<div class="chart-box"><h3>\U0001f465 Hiring Categories</h3><canvas id="catChart"></canvas></div>
</div>
<div class="section">
<h2>\U0001f4cb Recent Listings <span class="count">{len(listings)}</span></h2>
<div class="table-wrap"><table>
<thead><tr><th>Status</th><th>Title</th><th>Category</th><th>Salary</th><th>Positions</th><th>Published</th><th>Link</th></tr></thead>
<tbody>{listing_rows}</tbody>
</table></div>
</div>
</div>
<div class="footer">Smart Dashboard — Hiring-Focused Layout — {_esc(entity['display_name'])}</div>
<script>
Chart.defaults.color = '#94a3b8'; Chart.defaults.borderColor = '#334155';
new Chart(document.getElementById('hiringChart'), {{
    type: 'bar', data: {{ labels: {json.dumps(all_months)}, datasets: [
        {{ label: 'Listings', data: {json.dumps(ht_counts)}, backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 }},
        {{ label: 'Positions', data: {json.dumps(ht_pos)}, type: 'line', borderColor: '#8b5cf6', tension: 0.3, pointRadius: 3, yAxisID: 'y1' }}
    ] }}, options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});
{_chart_script('catChart', 'doughnut', cat_keys, cat_vals, "plugins: { legend: { position: 'right', labels: { padding: 8, usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } }")}
new Chart(document.getElementById('contractChart'), {{
    type: 'bar', data: {{ labels: {json.dumps(all_months)}, datasets: [
        {{ label: 'Value (€)', data: {json.dumps(ct_values)}, backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }},
        {{ label: 'Contracts', data: {json.dumps(ct_counts)}, type: 'line', borderColor: '#f59e0b', tension: 0.3, pointRadius: 3, yAxisID: 'y1' }}
    ] }}, options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});
</script></body></html>"""
    return html


# ---------------------------------------------------------------------------
# Layout: contract-heavy (value-first)
# ---------------------------------------------------------------------------

def build_contract_heavy(entity, listings, contracts, profile):
    ct = compute_contract_trends(contracts)
    c_types = compute_contract_types(contracts)
    ht = compute_hiring_trends(listings)
    cats = compute_category_breakdown(listings)

    all_months = sorted(set(list(ct.keys()) + list(ht.keys())))
    ct_values = [round(ct.get(m, {}).get("value", 0), 2) for m in all_months]
    ct_counts = [ct.get(m, {}).get("count", 0) for m in all_months]
    ht_counts = [ht.get(m, {}).get("count", 0) for m in all_months]

    ctype_keys = list(c_types.keys())[:8]
    ctype_vals = list(c_types.values())[:8]

    contract_rows = ""
    for c in contracts[:25]:
        valor = f"\u20ac{c.get('valor', 0):,.2f}" if c.get("valor") else "N/A"
        detail = f"<a href='{_esc(c.get('detail_url', '#'))}' target='_blank'>\U0001f4cb</a>" if c.get("detail_url") else "—"
        contract_rows += f"""<tr>
<td>{_esc(c.get('data', '—'))}</td>
<td>{valor}</td>
<td>{_esc(c.get('tipo', '—'))}</td>
<td title="{_esc(c.get('objeto', ''))}">{_esc((c.get('objeto', '—') or '—')[:50])}</td>
<td>{detail}</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(entity['display_name'])} — Smart Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>{_build_css()}</style>
</head>
<body>
{_build_header(entity, profile)}
{_build_cards(profile)}
<div class="container">
<div class="charts cols-1">
<div class="chart-box"><h3>\U0001f4b0 Contract Value by Month (Primary Focus)</h3><canvas id="contractChart"></canvas></div>
</div>
<div class="charts cols-2">
<div class="chart-box"><h3>\U0001f4ca Hiring Trend</h3><canvas id="hiringChart"></canvas></div>
<div class="chart-box"><h3>\U0001f4e6 Contract Types</h3><canvas id="ctTypeChart"></canvas></div>
</div>
<div class="section">
<h2>\U0001f4e6 BASE.gov.pt Contracts <span class="count">{len(contracts)}</span></h2>
<div class="table-wrap"><table>
<thead><tr><th>Date</th><th>Value</th><th>Type</th><th>Description</th><th>Detail</th></tr></thead>
<tbody>{contract_rows}</tbody>
</table></div>
</div>
</div>
<div class="footer">Smart Dashboard — Contract-Focused Layout — {_esc(entity['display_name'])}</div>
<script>
Chart.defaults.color = '#94a3b8'; Chart.defaults.borderColor = '#334155';
new Chart(document.getElementById('contractChart'), {{
    type: 'bar', data: {{ labels: {json.dumps(all_months)}, datasets: [
        {{ label: 'Value (€)', data: {json.dumps(ct_values)}, backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }},
        {{ label: 'Contracts', data: {json.dumps(ct_counts)}, type: 'line', borderColor: '#f59e0b', tension: 0.3, pointRadius: 3, yAxisID: 'y1' }}
    ] }}, options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});
{_chart_script('ctTypeChart', 'doughnut', ctype_keys, ctype_vals, "plugins: { legend: { position: 'right', labels: { padding: 8, usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } }")}
new Chart(document.getElementById('hiringChart'), {{
    type: 'bar', data: {{ labels: {json.dumps(all_months)}, datasets: [{{ label: 'Listings', data: {json.dumps(ht_counts)}, backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 }}] }},
    options: {{ responsive: true, scales: {{ y: {{ beginAtZero: true }} }} }}
}});
</script></body></html>"""
    return html


# ---------------------------------------------------------------------------
# Layout: balanced / rich (2-column grid)
# ---------------------------------------------------------------------------

def build_balanced(entity, listings, contracts, profile):
    ht = compute_hiring_trends(listings)
    ct = compute_contract_trends(contracts)
    cats = compute_category_breakdown(listings)
    c_types = compute_contract_types(contracts)
    locs = compute_location_breakdown(listings)

    all_months = sorted(set(list(ht.keys()) + list(ct.keys())))
    ht_counts = [ht.get(m, {}).get("count", 0) for m in all_months]
    ht_pos = [ht.get(m, {}).get("positions", 0) for m in all_months]
    ct_values = [round(ct.get(m, {}).get("value", 0), 2) for m in all_months]
    ct_counts = [ct.get(m, {}).get("count", 0) for m in all_months]

    cat_keys = list(cats.keys())[:8]
    cat_vals = list(cats.values())[:8]
    ctype_keys = list(c_types.keys())[:8]
    ctype_vals = list(c_types.values())[:8]
    loc_keys = list(locs.keys())[:8]
    loc_vals = list(locs.values())[:8]

    listing_rows = ""
    for l in listings[:30]:
        status_cls = "open" if "aberta" in (l.get("estado") or "").lower() else "closed"
        url = _esc(l.get("url", ""))
        listing_rows += f"""<tr>
<td><span class="badge {status_cls}">{_esc(l.get('estado', '—'))}</span></td>
<td>{_esc(l.get('titulo', '—')[:55])}</td>
<td>{_esc(l.get('categoria', '—'))}</td>
<td>\u20ac{_esc(l.get('remuneracao', '—'))}</td>
<td>{_esc(l.get('total_postos', '1'))}</td>
<td>{_esc(l.get('data_publicacao', '—')[:10]) if l.get('data_publicacao') else '—'}</td>
<td>{"<a href='" + url + "' target='_blank'>\U0001f517</a>" if url else '—'}</td>
</tr>"""

    contract_rows = ""
    for c in contracts[:25]:
        valor = f"\u20ac{c.get('valor', 0):,.2f}" if c.get("valor") else "N/A"
        contract_rows += f"""<tr>
<td>{_esc(c.get('data', '—'))}</td>
<td>{valor}</td>
<td>{_esc(c.get('tipo', '—'))}</td>
<td title="{_esc(c.get('objeto', ''))}">{_esc((c.get('objeto', '—') or '—')[:50])}</td>
</tr>"""

    loc_chart = ""
    if loc_keys:
        loc_chart = f'<div class="chart-box"><h3>\U0001f4cd Locations</h3><canvas id="locChart"></canvas></div>'

    extra_chart = ""
    if profile["shape"] == "rich":
        extra_chart = f'<div class="chart-box"><h3>\U0001f4ca Contract Types</h3><canvas id="ctTypeChart"></canvas></div>'

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(entity['display_name'])} — Smart Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>{_build_css()}</style>
</head>
<body>
{_build_header(entity, profile)}
{_build_cards(profile)}
<div class="container">
<div class="charts cols-2">
<div class="chart-box"><h3>\U0001f4c8 Hiring by Month</h3><canvas id="hiringChart"></canvas></div>
<div class="chart-box"><h3>\U0001f4b0 Contract Value by Month</h3><canvas id="contractChart"></canvas></div>
<div class="chart-box"><h3>\U0001f465 Hiring Categories</h3><canvas id="catChart"></canvas></div>
{extra_chart}
{loc_chart}
</div>
<div class="section">
<h2>\U0001f4cb Job Listings <span class="count">{len(listings)}</span></h2>
<div class="table-wrap"><table>
<thead><tr><th>Status</th><th>Title</th><th>Category</th><th>Salary</th><th>Positions</th><th>Published</th><th>Link</th></tr></thead>
<tbody>{listing_rows}</tbody>
</table></div>
</div>
<div class="section">
<h2>\U0001f4e6 Contracts <span class="count">{len(contracts)}</span></h2>
<div class="table-wrap"><table>
<thead><tr><th>Date</th><th>Value</th><th>Type</th><th>Description</th></tr></thead>
<tbody>{contract_rows}</tbody>
</table></div>
</div>
</div>
<div class="footer">Smart Dashboard — {_esc(entity['display_name'])}</div>
<script>
Chart.defaults.color = '#94a3b8'; Chart.defaults.borderColor = '#334155';
new Chart(document.getElementById('hiringChart'), {{
    type: 'bar', data: {{ labels: {json.dumps(all_months)}, datasets: [
        {{ label: 'Listings', data: {json.dumps(ht_counts)}, backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 }},
        {{ label: 'Positions', data: {json.dumps(ht_pos)}, type: 'line', borderColor: '#8b5cf6', tension: 0.3, pointRadius: 3, yAxisID: 'y1' }}
    ] }}, options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});
new Chart(document.getElementById('contractChart'), {{
    type: 'bar', data: {{ labels: {json.dumps(all_months)}, datasets: [
        {{ label: 'Value (€)', data: {json.dumps(ct_values)}, backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }},
        {{ label: 'Contracts', data: {json.dumps(ct_counts)}, type: 'line', borderColor: '#f59e0b', tension: 0.3, pointRadius: 3, yAxisID: 'y1' }}
    ] }}, options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});
{_chart_script('catChart', 'doughnut', cat_keys, cat_vals, "plugins: { legend: { position: 'right', labels: { padding: 8, usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } }")}
{_chart_script('ctTypeChart', 'doughnut', ctype_keys, ctype_vals, "plugins: { legend: { position: 'right', labels: { padding: 8, usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } }") if ctype_keys else ""}
{_chart_script('locChart', 'bar', loc_keys, loc_vals, "indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } }") if loc_keys else ""}
</script></body></html>"""
    return html


# ---------------------------------------------------------------------------
# Layout: sparse (single-column summary)
# ---------------------------------------------------------------------------

def build_sparse(entity, listings, contracts, profile):
    listing_rows = ""
    for l in listings[:15]:
        status_cls = "open" if "aberta" in (l.get("estado") or "").lower() else "closed"
        url = _esc(l.get("url", ""))
        listing_rows += f"""<tr>
<td><span class="badge {status_cls}">{_esc(l.get('estado', '—'))}</span></td>
<td>{_esc(l.get('titulo', '—')[:55])}</td>
<td>{_esc(l.get('categoria', '—'))}</td>
<td>\u20ac{_esc(l.get('remuneracao', '—'))}</td>
<td>{"<a href='" + url + "' target='_blank'>\U0001f517</a>" if url else '—'}</td>
</tr>"""

    contract_rows = ""
    for c in contracts[:10]:
        valor = f"\u20ac{c.get('valor', 0):,.2f}" if c.get("valor") else "N/A"
        contract_rows += f"""<tr>
<td>{_esc(c.get('data', '—'))}</td>
<td>{valor}</td>
<td>{_esc(c.get('tipo', '—'))}</td>
</tr>"""

    sections = ""
    if listings:
        sections += f"""<div class="section">
<h2>\U0001f4cb Job Listings <span class="count">{len(listings)}</span></h2>
<div class="table-wrap"><table>
<thead><tr><th>Status</th><th>Title</th><th>Category</th><th>Salary</th><th>Link</th></tr></thead>
<tbody>{listing_rows}</tbody>
</table></div></div>"""
    if contracts:
        sections += f"""<div class="section">
<h2>\U0001f4e6 Contracts <span class="count">{len(contracts)}</span></h2>
<div class="table-wrap"><table>
<thead><tr><th>Date</th><th>Value</th><th>Type</th></tr></thead>
<tbody>{contract_rows}</tbody>
</table></div></div>"""

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(entity['display_name'])} — Smart Dashboard</title>
<style>{_build_css()}</style>
</head>
<body>
{_build_header(entity, profile)}
{_build_cards(profile)}
<div class="container">
{sections if sections else '<div class="section"><h2>No data available for this entity</h2></div>'}
</div>
<div class="footer">Smart Dashboard — Sparse Layout — {_esc(entity['display_name'])}</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Smart Dashboard Generator — Adaptive Layouts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", default="", help="Entity name")
    parser.add_argument("--nif", default="", help="Filter by NIF")
    parser.add_argument("--sector", default="", help="Filter by sector name (generates sector summary)")
    parser.add_argument("-o", "--output", default="", help="Output HTML file")
    parser.add_argument("--profile", action="store_true", help="Show data profile only (no HTML)")
    parser.add_argument("--open", action="store_true", help="Open in browser")

    args = parser.parse_args()

    if args.sector:
        # Sector mode: generate a summary dashboard for a sector
        print(f"Generating sector summary for {args.sector}...")
        entities = search_entities(query=args.sector, limit=50)
        if not entities:
            print(f"No entities found for '{args.sector}'")
            sys.exit(1)
        # Profile each entity and summarize
        shapes = defaultdict(int)
        total_listings = 0
        total_contracts = 0
        for e in entities:
            listings = get_entity_listings(e["id"])
            contracts = get_entity_contracts(e.get("nif", ""), entity_name=e.get("display_name", ""), entidade=e.get("entidade", ""))
            p = profile_entity(e, listings, contracts)
            shapes[p["shape"]] += 1
            total_listings += p["n_listings"]
            total_contracts += p["n_contracts"]
        print(f"\n  Sector: {args.sector}")
        print(f"  Entities: {len(entities)}")
        print(f"  Total listings: {total_listings}")
        print(f"  Total contracts: {total_contracts}")
        print(f"  Data shape distribution:")
        for shape, count in sorted(shapes.items(), key=lambda x: -x[1]):
            print(f"    {shape}: {count} entities")
        return

    if not args.query and not args.nif:
        parser.print_help()
        sys.exit(1)

    entities = search_entities(query=args.query, nif=args.nif, limit=1)
    if not entities:
        print(f"No entity found matching '{args.query or args.nif}'")
        sys.exit(1)

    entity = entities[0]
    print(f"Loading data for {entity['display_name']}...")

    listings = get_entity_listings(entity["id"])
    contracts = get_entity_contracts(entity.get("nif", ""), entity_name=entity.get("display_name", ""), entidade=entity.get("entidade", ""))

    print(f"  BEP listings: {len(listings)}")
    print(f"  BASE contracts: {len(contracts)}")

    profile = profile_entity(entity, listings, contracts)

    print(f"\n  Data Profile:")
    print(f"    Shape: {profile['shape']}")
    print(f"    Listings: {profile['n_listings']}")
    print(f"    Contracts: {profile['n_contracts']}")
    print(f"    Total value: \u20ac{profile['total_value']:,.2f}")
    print(f"    Positions: {profile['total_positions']}")
    print(f"    Temporal coverage: {profile['temporal_coverage']} months")
    print(f"    Categories: {profile['category_diversity']}")
    print(f"    Locations: {profile['geo_spread']}")

    if args.profile:
        return

    print(f"\n  Generating {profile['shape']} layout...")

    shape = profile["shape"]
    if shape == "hiring-heavy":
        html = build_hiring_heavy(entity, listings, contracts, profile)
    elif shape == "contract-heavy":
        html = build_contract_heavy(entity, listings, contracts, profile)
    elif shape in ("balanced", "rich"):
        html = build_balanced(entity, listings, contracts, profile)
    else:
        html = build_sparse(entity, listings, contracts, profile)

    output = args.output or f"smart_{entity.get('nif', 'entity')}.html"
    Path(output).write_text(html, encoding="utf-8")
    print(f"  \u2705 Saved to {output}")

    if args.open:
        webbrowser.open(Path(output).resolve().as_uri())


if __name__ == "__main__":
    main()
