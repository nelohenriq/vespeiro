#!/usr/bin/env python3
"""Municipality Directory — HTML Dashboard Generator.

Generates an interactive HTML dashboard with sortable tables, Chart.js charts,
and client-side filtering for all 308+ Portuguese municipalities.

Usage:
    python municipality_directory.py --html -o dashboard.html
"""

import json
import sys
from pathlib import Path
from datetime import datetime

from utils import format_currency

SCRIPT_DIR = Path(__file__).parent


def generate_dashboard(directory: list, output_path: str):
    """Generate a self-contained interactive HTML dashboard."""

    total_spending = sum(d["total_spending"] for d in directory)
    total_contracts = sum(d["base_contracts"] for d in directory)
    total_pop = sum(d["population"] for d in directory if d["population"] > 0)
    with_camara = sum(1 for d in directory if d["camara_nif"])
    with_municipio = sum(1 for d in directory if d["municipio_nif"])
    with_both = sum(1 for d in directory if d["camara_nif"] and d["municipio_nif"])

    # Sort by spending for charts
    by_spending = sorted(directory, key=lambda x: -x["total_spending"])
    top20 = by_spending[:20]

    # Per-capita top 20
    by_percapita = sorted(
        [d for d in directory if d["per_capita_spending"] > 0],
        key=lambda x: -x["per_capita_spending"],
    )[:20]

    # Population top 20
    by_pop = sorted(
        [d for d in directory if d["population"] > 0],
        key=lambda x: -x["population"],
    )[:20]

    # JSON data for client-side filtering
    data_json = json.dumps(
        [{k: v for k, v in d.items() if k != "location_normalized"} for d in directory],
        ensure_ascii=False,
    )

    # Chart data
    spending_labels = json.dumps([d["location"][:22] for d in top20])
    spending_values = json.dumps([round(d["total_spending"], 2) for d in top20])

    percapita_labels = json.dumps([d["location"][:22] for d in by_percapita])
    percapita_values = json.dumps([round(d["per_capita_spending"], 2) for d in by_percapita])

    pop_labels = json.dumps([d["location"][:22] for d in by_pop])
    pop_values = json.dumps([d["population"] for d in by_pop])

    # Data source pie chart
    src_counts = {}
    for d in directory:
        src = d.get("data_sources", "none")
        src_counts[src] = src_counts.get(src, 0) + 1
    src_labels = json.dumps(list(src_counts.keys()))
    src_values = json.dumps(list(src_counts.values()))

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Municipality Directory — Analisa.pt</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.5; }}

/* Header */
.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 2rem 0; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 0 2rem; }}
.header h1 {{ font-size: 2rem; color: #f8fafc; display: flex; align-items: center; gap: 0.5rem; }}
.header .subtitle {{ color: #94a3b8; margin-top: 0.5rem; font-size: 0.95rem; }}

/* KPI Cards */
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin: 2rem 0; }}
.kpi {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; transition: border-color 0.2s; }}
.kpi:hover {{ border-color: #3b82f6; }}
.kpi .icon {{ font-size: 1.5rem; }}
.kpi .value {{ font-size: 1.6rem; font-weight: 700; color: #f8fafc; margin: 0.3rem 0; }}
.kpi .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}

/* Charts */
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin: 2rem 0; }}
@media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
.chart-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.chart-card h3 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1rem; }}

/* Filter Bar */
.filter-bar {{ display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; margin: 2rem 0 1rem; }}
.filter-bar input, .filter-bar select {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 0.6rem 1rem; color: #e2e8f0; font-size: 0.9rem; outline: none; transition: border-color 0.2s; }}
.filter-bar input:focus, .filter-bar select:focus {{ border-color: #3b82f6; }}
.filter-bar input {{ flex: 1; min-width: 200px; }}
.filter-bar select {{ min-width: 160px; }}
.result-count {{ color: #94a3b8; font-size: 0.85rem; white-space: nowrap; }}

/* Table */
.table-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; margin-bottom: 2rem; }}
.table-scroll {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
thead {{ position: sticky; top: 0; z-index: 1; }}
th {{ text-align: left; padding: 0.8rem 0.7rem; border-bottom: 2px solid #334155; color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; cursor: pointer; user-select: none; white-space: nowrap; background: #1e293b; }}
th:hover {{ color: #f8fafc; }}
th .sort-arrow {{ margin-left: 4px; font-size: 0.65rem; }}
td {{ padding: 0.55rem 0.7rem; border-bottom: 1px solid #1a2332; }}
tr:hover td {{ background: #1e3a5f; }}
.nif {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.8rem; color: #94a3b8; }}
.nif-linked {{ color: #3b82f6; }}
.bar-cell {{ display: flex; align-items: center; gap: 6px; }}
.bar-bg {{ background: #334155; border-radius: 3px; height: 16px; min-width: 2px; }}
.bar-fill {{ background: #3b82f6; border-radius: 3px; height: 16px; transition: width 0.3s; }}
.bar-pct {{ font-size: 0.75rem; color: #64748b; white-space: nowrap; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }}
.tag-bep {{ background: #1e3a5f; color: #60a5fa; }}
.tag-base {{ background: #14532d; color: #4ade80; }}
.tag-both {{ background: #1e293b; color: #a78bfa; border: 1px solid #4c1d95; }}
.tag-none {{ background: #1e293b; color: #64748b; }}

.footer {{ text-align: center; padding: 2rem; color: #64748b; font-size: 0.8rem; }}
</style>
</head>
<body>

<div class="header">
<div class="container">
<h1>🏛️ Portuguese Municipality Directory</h1>
<div class="subtitle">Câmara & Município NIFs, BEP listings, BASE contracts, Census 2021 population — {len(directory)} municipalities</div>
</div>
</div>

<div class="container">

<!-- KPI Cards -->
<div class="kpi-grid">
<div class="kpi">
<div class="icon">💰</div>
<div class="value">{format_currency(total_spending)}</div>
<div class="label">Total Spending</div>
</div>
<div class="kpi">
<div class="icon">📦</div>
<div class="value">{total_contracts:,}</div>
<div class="label">BASE Contracts</div>
</div>
<div class="kpi">
<div class="icon">👥</div>
<div class="value">{total_pop:,}</div>
<div class="label">Population</div>
</div>
<div class="kpi">
<div class="icon">🏛️</div>
<div class="value">{len(directory)}</div>
<div class="label">Municipalities</div>
</div>
<div class="kpi">
<div class="icon">🔗</div>
<div class="value">{with_both}</div>
<div class="label">Dual NIF Mapped</div>
</div>
<div class="kpi">
<div class="icon">📊</div>
<div class="value">{format_currency(total_spending / total_pop if total_pop else 0)}</div>
<div class="label">Per Capita Avg</div>
</div>
</div>

<!-- Charts -->
<div class="charts">
<div class="chart-card">
<h3>📊 Top 20 Municipalities by Spending</h3>
<canvas id="spendingChart"></canvas>
</div>
<div class="chart-card">
<h3>🏙️ Top 20 by Per Capita Spending</h3>
<canvas id="percapitaChart"></canvas>
</div>
<div class="chart-card">
<h3>👥 Top 20 by Population</h3>
<canvas id="popChart"></canvas>
</div>
<div class="chart-card">
<h3>📋 Data Source Coverage</h3>
<canvas id="srcChart"></canvas>
</div>
</div>

<!-- Filter + Table -->
<div class="filter-bar">
<input type="text" id="searchInput" placeholder="🔍 Search municipality..." oninput="filterTable()">
<select id="sourceFilter" onchange="filterTable()">
<option value="">All Sources</option>
<option value="BEP+BASE">BEP + BASE</option>
<option value="BASE">BASE only</option>
<option value="BEP">BEP only</option>
<option value="none">No data</option>
</select>
<select id="sortSelect" onchange="sortTable()">
<option value="spending-desc">Spending ↓</option>
<option value="spending-asc">Spending ↑</option>
<option value="percapita-desc">Per Capita ↓</option>
<option value="percapita-asc">Per Capita ↑</option>
<option value="contracts-desc">Contracts ↓</option>
<option value="population-desc">Population ↓</option>
<option value="name-asc">Name A→Z</option>
</select>
<span class="result-count" id="resultCount"></span>
</div>

<div class="table-card">
<div class="table-scroll">
<table id="dirTable">
<thead>
<tr>
<th onclick="sortByCol(0)">#</th>
<th onclick="sortByCol(1)">Municipality</th>
<th onclick="sortByCol(2)">Câmara NIF</th>
<th onclick="sortByCol(3)">Município NIF</th>
<th onclick="sortByCol(4)">Population</th>
<th onclick="sortByCol(5)">Contracts</th>
<th onclick="sortByCol(6)">Spending</th>
<th onclick="sortByCol(7)">Per Capita</th>
<th onclick="sortByCol(8)">Source</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>
</div>

</div>

<div class="footer">
Generated by Analisa.pt Municipality Directory — {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>

<script>
// === DATA ===
const DATA = {data_json};
let filteredData = [...DATA];
let currentSort = {{ col: 6, dir: -1 }};

// === FORMATTING ===
function fmtCurrency(v) {{
    if (v >= 1e9) return '€' + (v/1e9).toFixed(2) + 'B';
    if (v >= 1e6) return '€' + (v/1e6).toFixed(1) + 'M';
    if (v >= 1e3) return '€' + (v/1e3).toFixed(1) + 'K';
    return '€' + v.toFixed(0);
}}
function fmtNum(v) {{ return v.toLocaleString('pt-PT'); }}

function srcTag(s) {{
    if (s === 'BEP+BASE') return '<span class="tag tag-both">BEP+BASE</span>';
    if (s === 'BASE') return '<span class="tag tag-base">BASE</span>';
    if (s === 'BEP') return '<span class="tag tag-bep">BEP</span>';
    return '<span class="tag tag-none">—</span>';
}}

// === TABLE RENDERING ===
function renderTable() {{
    const tbody = document.getElementById('tableBody');
    const maxSpend = Math.max(...filteredData.map(d => d.total_spending), 1);
    let html = '';
    filteredData.forEach((d, i) => {{
        const barW = Math.max(1, Math.round((d.total_spending / maxSpend) * 100));
        const nifC = d.camara_nif ? `<span class="nif nif-linked">${{d.camara_nif}}</span>` : '<span class="nif">—</span>';
        const nifM = d.municipio_nif ? `<span class="nif nif-linked">${{d.municipio_nif}}</span>` : '<span class="nif">—</span>';
        const pop = d.population > 0 ? fmtNum(d.population) : '?';
        const pc = d.per_capita_spending > 0 ? fmtCurrency(d.per_capita_spending) : '—';
        html += `<tr>
<td>${{i + 1}}</td>
<td><strong>${{d.location}}</strong></td>
<td>${{nifC}}</td>
<td>${{nifM}}</td>
<td>${{pop}}</td>
<td>${{fmtNum(d.base_contracts)}}</td>
<td><div class="bar-cell"><div class="bar-bg" style="width:100px"><div class="bar-fill" style="width:${{barW}}%"></div></div><span>${{fmtCurrency(d.total_spending)}}</span></div></td>
<td>${{pc}}</td>
<td>${{srcTag(d.data_sources)}}</td>
</tr>`;
    }});
    tbody.innerHTML = html;
    document.getElementById('resultCount').textContent = `${{filteredData.length}} of ${{DATA.length}} municipalities`;
}}

// === FILTERING ===
function filterTable() {{
    const q = document.getElementById('searchInput').value.toLowerCase();
    const src = document.getElementById('sourceFilter').value;
    filteredData = DATA.filter(d => {{
        if (q && !d.location.toLowerCase().includes(q)) return false;
        if (src && d.data_sources !== src) return false;
        return true;
    }});
    sortTable();
}}

// === SORTING ===
function sortTable() {{
    const val = document.getElementById('sortSelect').value;
    const [key, dir] = val.split('-');
    const mult = dir === 'asc' ? 1 : -1;
    const keyMap = {{
        'spending': 'total_spending',
        'percapita': 'per_capita_spending',
        'contracts': 'base_contracts',
        'population': 'population',
        'name': 'location',
    }};
    const prop = keyMap[key] || 'total_spending';
    filteredData.sort((a, b) => {{
        if (typeof a[prop] === 'string') return mult * a[prop].localeCompare(b[prop]);
        return mult * ((a[prop] || 0) - (b[prop] || 0));
    }});
    renderTable();
}}

function sortByCol(col) {{
    const cols = ['name', 'name', 'name', 'name', 'population', 'contracts', 'spending', 'percapita', 'name'];
    const prop = cols[col] || 'spending';
    const curVal = document.getElementById('sortSelect').value;
    const curKey = curVal.split('-')[0];
    const curDir = curVal.split('-')[1];
    let newDir = 'desc';
    if (curKey === prop && curDir === 'desc') newDir = 'asc';
    document.getElementById('sortSelect').value = prop + '-' + newDir;
    sortTable();
}}

// === CHARTS ===
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';
const COLORS = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16','#f97316','#6366f1'];

// Spending chart
new Chart(document.getElementById('spendingChart'), {{
    type: 'bar',
    data: {{
        labels: {spending_labels},
        datasets: [{{ label: 'Spending (€)', data: {spending_values}, backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }}]
    }},
    options: {{
        responsive: true, indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: v => '€' + (v/1e6).toFixed(0) + 'M' }} }} }}
    }}
}});

// Per capita chart
new Chart(document.getElementById('percapitaChart'), {{
    type: 'bar',
    data: {{
        labels: {percapita_labels},
        datasets: [{{ label: 'Per Capita (€)', data: {percapita_values}, backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 }}]
    }},
    options: {{
        responsive: true, indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: v => '€' + (v/1e3).toFixed(0) + 'K' }} }} }}
    }}
}});

// Population chart
new Chart(document.getElementById('popChart'), {{
    type: 'bar',
    data: {{
        labels: {pop_labels},
        datasets: [{{ label: 'Population', data: {pop_values}, backgroundColor: 'rgba(139,92,246,0.7)', borderRadius: 4 }}]
    }},
    options: {{
        responsive: true, indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: v => (v/1e3).toFixed(0) + 'K' }} }} }}
    }}
}});

// Source coverage doughnut
new Chart(document.getElementById('srcChart'), {{
    type: 'doughnut',
    data: {{
        labels: {src_labels},
        datasets: [{{ data: {src_values}, backgroundColor: ['#6366f1','#4ade80','#60a5fa','#64748b'], borderWidth: 0 }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ position: 'right', labels: {{ padding: 12, usePointStyle: true }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.label + ': ' + ctx.parsed + ' municipalities' }} }}
        }}
    }}
}});

// Initial render
sortTable();
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"\n  ✅ Dashboard saved to {output_path}")
