#!/usr/bin/env python3
"""Sector-Level Dashboard Generator

Aggregates all entities within the same department (entidade) to show
government-wide hiring and contracting patterns across Portuguese public sectors.

Usage:
    python generate_sector_dashboard.py -o sector_dashboard.html
    python generate_sector_dashboard.py --sector "Saúde" -o saude_sector.html
    python generate_sector_dashboard.py --top 10 -o top_sectors.html
    python generate_sector_dashboard.py --detail "Saúde" -o saude_detail.html
    python generate_sector_dashboard.py --region "Lisboa" -o lisboa_dashboard.html
    python generate_sector_dashboard.py --open
"""

import sys
import json
import html as html_mod
import argparse
import webbrowser
from pathlib import Path
from collections import defaultdict
from utils_db import connect as db_connect

# Paths
SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"


def _esc(s: str) -> str:
    """Escape HTML special characters to prevent XSS."""
    return html_mod.escape(str(s)) if s else ""


def _safe_int(val, default=0):
    """Safely convert a value to int."""
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


def get_all_entities() -> list[dict]:
    """Get all BEP entities with their entidade grouping."""
    if not BEP_DB.exists():
        return []
    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT id, display_name, entidade, organismo, nif, listing_count "
        "FROM bep_entities ORDER BY listing_count DESC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "display_name": r[1], "entidade": r[2], "organismo": r[3],
         "nif": r[4], "listing_count": r[5]}
        for r in rows
    ]


def _normalize_region(loc: str) -> str:
    """Normalize a local_trabalho value to a region name.

    Extracts meaningful geographic location from BEP location strings.
    Many entries are application URLs (SIGRHE, IEFP, etc.) which we map
    to generic categories. Others contain city/district names.
    """
    if not loc:
        return "N/A"
    loc_lower = loc.lower().strip()
    # Map known recruitment platforms to categories
    platform_keywords = {
        "sigrhe": "Plataforma SIGRHE",
        "sigefe": "Plataforma SIGEFE",
        "iefp": "IEFP (Instituto do Emprego)",
        "sigrh": "Plataforma SIGRHE",
        "sighre": "Plataforma SIGRHE",
        "recrutamento": "Plataforma de Recrutamento",
        "monday": "Plataforma Monday",
        "sap": "SAP / Intranet",
        "bolseiro": "Portal do Bolseiro",
        "linkedin": "LinkedIn",
        "netemprego": "NetEmpregos",
        "candidatura dever": "Plataforma de Candidatura",
        "formulário": "Formulário Online",
        "email": "Email / Contacto Direto",
        "@": "Email / Contacto Direto",
        "http": "Plataforma Online",
        "www": "Plataforma Online",
        "plataforma": "Plataforma Online",
        "sistema interativo": "Sistema SIGEFE",
    }
    for kw, label in platform_keywords.items():
        if kw in loc_lower:
            return label
    # If it looks like a real location (city name, district, etc.), return as-is
    return loc[:50] if len(loc) > 50 else loc


def load_all_listings(region: str = "") -> dict[str, list[dict]]:
    """Batch-load all BEP listings grouped by entity_id.

    Args:
        region: If provided, only include listings whose local_trabalho
                contains this string (case-insensitive).
    """
    if not BEP_DB.exists():
        return {}
    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT entity_id, titulo, estado, categoria, tipo_oferta, "
        "remuneracao, total_postos, data_publicacao, local_trabalho "
        "FROM bep_listings ORDER BY data_publicacao DESC"
    ).fetchall()
    conn.close()
    grouped = defaultdict(list)
    for r in rows:
        loc = r[8] or ""
        # Apply region filter if specified
        if region and region.lower() not in loc.lower():
            continue
        grouped[r[0]].append({
            "titulo": r[1], "estado": r[2], "categoria": r[3],
            "tipo_oferta": r[4], "remuneracao": r[5],
            "total_postos": r[6], "data_publicacao": r[7],
            "local_trabalho": loc,
        })
    return dict(grouped)


def load_all_contracts() -> dict[str, list[dict]]:
    """Load contract index once and return the full mapping."""
    if not CONTRACT_CACHE.exists():
        return {}
    try:
        with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def aggregate_sector_data(entities: list[dict], region: str = "") -> dict:
    """Aggregate data across all entities grouped by entidade (department).

    Args:
        region: If provided, only include listings in this region.
    """
    # Batch-load all data once
    all_listings = load_all_listings(region=region)
    all_contracts = load_all_contracts()

    sectors = defaultdict(lambda: {
        "entities": [],
        "total_listings": 0,
        "total_positions": 0,
        "total_contracts": 0,
        "total_contract_value": 0.0,
        "hiring_by_month": defaultdict(lambda: {"count": 0, "positions": 0}),
        "contract_by_month": defaultdict(lambda: {"count": 0, "value": 0.0}),
        "categories": defaultdict(int),
        "contract_types": defaultdict(int),
        "regions": defaultdict(int),
    })

    for entity in entities:
        entidade = entity.get("entidade") or "Outros"
        if not entidade.strip():
            entidade = "Outros"

        sector = sectors[entidade]
        sector["entities"].append(entity)
        sector["total_listings"] += entity.get("listing_count", 0)

        # Process listings from batch-loaded data
        for l in all_listings.get(entity["id"], []):
            pub = l.get("data_publicacao", "")
            if pub and len(pub) >= 7:
                month = pub[:7]
                sector["hiring_by_month"][month]["count"] += 1
                positions = _safe_int(l.get("total_postos"), 1)
                sector["hiring_by_month"][month]["positions"] += positions
                sector["total_positions"] += positions

            cat = l.get("tipo_oferta") or l.get("categoria") or "Outros"
            sector["categories"][cat] += 1

            # Geographic distribution
            loc = l.get("local_trabalho", "")
            region_name = _normalize_region(loc)
            sector["regions"][region_name] += 1

        # Process contracts from batch-loaded data
        nif = entity.get("nif", "")
        for c in all_contracts.get(nif, []):
            valor = c.get("valor", 0)
            sector["total_contracts"] += 1
            sector["total_contract_value"] += valor

            date = c.get("data", "")
            if date and len(date) >= 7:
                month = date[:7]
                sector["contract_by_month"][month]["count"] += 1
                sector["contract_by_month"][month]["value"] += valor

            tipo = c.get("tipo") or "Outros"
            sector["contract_types"][tipo] += 1

    return dict(sectors)


def build_sector_dashboard(sectors: dict, top_n: int = 0, filter_sector: str = "",
                           region: str = "") -> str:
    """Generate HTML dashboard for sector-level analysis."""
    # Sort sectors by total listings
    sorted_sectors = sorted(sectors.items(), key=lambda x: x[1]["total_listings"], reverse=True)
    if top_n > 0:
        sorted_sectors = sorted_sectors[:top_n]
    if filter_sector:
        sorted_sectors = [(k, v) for k, v in sorted_sectors if filter_sector.lower() in k.lower()]

    # Calculate totals
    total_entities = sum(len(s["entities"]) for _, s in sorted_sectors)
    total_listings = sum(s["total_listings"] for _, s in sorted_sectors)
    total_positions = sum(s["total_positions"] for _, s in sorted_sectors)
    total_contracts = sum(s["total_contracts"] for _, s in sorted_sectors)
    total_value = sum(s["total_contract_value"] for _, s in sorted_sectors)

    # Prepare chart data
    sector_names = json.dumps([s[0][:30] for s in sorted_sectors[:15]])
    sector_listings = json.dumps([s[1]["total_listings"] for s in sorted_sectors[:15]])
    sector_values = json.dumps([round(s[1]["total_contract_value"], 2) for s in sorted_sectors[:15]])

    # Merge all months for temporal chart
    all_months = set()
    for _, s in sorted_sectors:
        all_months.update(s["hiring_by_month"].keys())
        all_months.update(s["contract_by_month"].keys())
    all_months = sorted(all_months)

    # Top 5 sectors hiring trends
    top5_sectors = sorted_sectors[:5]
    hiring_datasets = []
    colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]
    for i, (name, s) in enumerate(top5_sectors):
        data = [s["hiring_by_month"].get(m, {}).get("count", 0) for m in all_months]
        hiring_datasets.append({
            "label": name[:25],
            "data": data,
            "borderColor": colors[i % len(colors)],
            "backgroundColor": f"rgba({int(colors[i%len(colors)][1:3],16)},{int(colors[i%len(colors)][3:5],16)},{int(colors[i%len(colors)][5:7],16)},0.1)",
            "tension": 0.3,
            "fill": True,
        })

    # Top 5 sectors contract value trends
    contract_datasets = []
    for i, (name, s) in enumerate(top5_sectors):
        data = [round(s["contract_by_month"].get(m, {}).get("value", 0), 2) for m in all_months]
        contract_datasets.append({
            "label": name[:25],
            "data": data,
            "borderColor": colors[i % len(colors)],
            "backgroundColor": f"rgba({int(colors[i%len(colors)][1:3],16)},{int(colors[i%len(colors)][3:5],16)},{int(colors[i%len(colors)][5:7],16)},0.1)",
            "tension": 0.3,
            "fill": True,
        })

    # Aggregate categories, types, and regions across all sectors
    all_categories = defaultdict(int)
    all_contract_types = defaultdict(int)
    all_regions = defaultdict(int)
    for _, s in sorted_sectors:
        for cat, count in s["categories"].items():
            all_categories[cat] += count
        for tipo, count in s["contract_types"].items():
            all_contract_types[tipo] += count
        for reg, count in s["regions"].items():
            all_regions[reg] += count

    top_categories = sorted(all_categories.items(), key=lambda x: x[1], reverse=True)[:10]
    top_ct_types = sorted(all_contract_types.items(), key=lambda x: x[1], reverse=True)[:10]
    top_regions = sorted(all_regions.items(), key=lambda x: x[1], reverse=True)[:15]

    cat_labels = json.dumps([c[0][:25] for c in top_categories])
    cat_values = json.dumps([c[1] for c in top_categories])
    ct_labels = json.dumps([c[0][:25] for c in top_ct_types])
    ct_values = json.dumps([c[1] for c in top_ct_types])
    region_labels = json.dumps([r[0][:30] for r in top_regions])
    region_values = json.dumps([r[1] for r in top_regions])

    # Region filter badge
    region_badge = f" <span style=\"background:#f59e0b;color:#0f172a;padding:0.1rem 0.5rem;border-radius:9999px;font-size:0.75rem;margin-left:0.5rem\">📍 {_esc(region)}</span>" if region else ""

    # Sector table rows with expandable entity details
    sector_rows = ""
    for i, (name, s) in enumerate(sorted_sectors):
        avg_positions = s["total_positions"] / s["total_listings"] if s["total_listings"] > 0 else 0
        avg_contract = s["total_contract_value"] / s["total_contracts"] if s["total_contracts"] > 0 else 0
        sid = f"sector-{i}"
        # Sort entities within sector by listing count
        sorted_entities = sorted(s["entities"], key=lambda e: e.get("listing_count", 0), reverse=True)
        entity_rows = ""
        for e in sorted_entities:
            e_nif = e.get("nif", "") or "N/A"
            entity_rows += f"""<tr class="entity-row">
<td></td>
<td style="padding-left:2rem">{_esc(e.get('display_name', '—')[:45])}</td>
<td>{_esc(e.get('organismo', '—')[:35])}</td>
<td>{_esc(e_nif)}</td>
<td>{e.get('listing_count', 0):,}</td>
<td>{"<a href=\"https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id=" + _esc(e_nif) + "\" target=\"_blank\" style=\"color:#60a5fa\">BASE.gov</a>" if e_nif != "N/A" else ""}</td>
</tr>"""
        sector_rows += f"""<tr class="sector-row" onclick="toggleSector('{sid}')" style="cursor:pointer">
<td>{i+1} <span id="arrow-{sid}" class="arrow">▶</span></td>
<td><strong>{_esc(name[:40])}</strong></td>
<td>{len(s['entities'])}</td>
<td>{s['total_listings']:,}</td>
<td>{s['total_positions']:,}</td>
<td>{avg_positions:.1f}</td>
<td>{s['total_contracts']:,}</td>
<td>€{s['total_contract_value']:,.0f}</td>
<td>€{avg_contract:,.0f}</td>
</tr>
<tr class="detail-row" id="{sid}" style="display:none">
<td colspan="9">
<div class="entity-detail">
<table class="entity-table">
<thead><tr><th></th><th>Entity</th><th>Organization</th><th>NIF</th><th>Listings</th><th>BASE.gov</th></tr></thead>
<tbody>{entity_rows}</tbody>
</table>
</div>
</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sector Dashboard — Government-wide Analysis</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 2rem 0; text-align: center; }}
.header h1 {{ font-size: 1.8rem; color: #f8fafc; margin-bottom: 0.5rem; }}
.header .subtitle {{ color: #94a3b8; font-size: 0.95rem; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 1rem; margin-bottom: 2rem; }}
@media (max-width: 1024px) {{ .cards {{ grid-template-columns: repeat(3, 1fr); }} }}
@media (max-width: 600px) {{ .cards {{ grid-template-columns: 1fr; }} }}
.card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; text-align: center; transition: transform 0.2s, box-shadow 0.2s; }}
.card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }}
.card .icon {{ font-size: 1.5rem; margin-bottom: 0.3rem; }}
.card .value {{ font-size: 1.6rem; font-weight: 700; color: #f8fafc; }}
.card .label {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
@media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
.chart-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.chart-box h3 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1rem; }}
.section {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }}
.section h2 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1.1rem; display: flex; align-items: center; gap: 0.5rem; }}
.section h2 .count {{ background: #3b82f6; color: white; padding: 0.1rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 2px solid #334155; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; position: sticky; top: 0; background: #1e293b; }}
td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
tr:hover td {{ background: #334155; }}
.table-wrap {{ max-height: 500px; overflow-y: auto; }}
.footer {{ text-align: center; padding: 2rem; color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; }}
.sector-row {{ cursor: pointer; transition: background 0.15s; }}
.sector-row:hover td {{ background: #334155 !important; }}
.arrow {{ display: inline-block; transition: transform 0.2s; color: #60a5fa; font-size: 0.7rem; margin-right: 0.3rem; }}
.arrow.open {{ transform: rotate(90deg); }}
.detail-row td {{ padding: 0 !important; background: #0f172a !important; border-bottom: 2px solid #334155 !important; }}
.entity-detail {{ padding: 0.5rem 1rem 1rem 2rem; }}
.entity-table {{ width: 100%; font-size: 0.8rem; }}
.entity-table th {{ background: #1e293b; color: #64748b; font-size: 0.7rem; padding: 0.4rem 0.6rem; }}
.entity-table td {{ padding: 0.35rem 0.6rem; color: #cbd5e1; border-bottom: 1px solid #1e293b; }}
.entity-table tr:hover td {{ background: #1e293b; }}
</style>
</head>
<body>

<div class="header">
<h1>🏛️ Sector Dashboard{region_badge}</h1>
<div class="subtitle">Government-wide Hiring & Contracting Patterns — Analisa.pt</div>
</div>

<div class="container">

<div class="cards">
<div class="card">
<div class="icon">🏢</div>
<div class="value">{total_entities:,}</div>
<div class="label">Total Entities</div>
</div>
<div class="card">
<div class="icon">📊</div>
<div class="value">{len(sorted_sectors)}</div>
<div class="label">Sectors</div>
</div>
<div class="card">
<div class="icon">📋</div>
<div class="value">{total_listings:,}</div>
<div class="label">BEP Listings</div>
</div>
<div class="card">
<div class="icon">👥</div>
<div class="value">{total_positions:,}</div>
<div class="label">Total Positions</div>
</div>
<div class="card">
<div class="icon">💰</div>
<div class="value">€{total_value:,.0f}</div>
<div class="label">Contract Value</div>
</div>
</div>

<div class="charts">
<div class="chart-box">
<h3>📊 Listings by Sector (Top 15)</h3>
<canvas id="listingsChart"></canvas>
</div>
<div class="chart-box">
<h3>💰 Contract Value by Sector (Top 15)</h3>
<canvas id="valueChart"></canvas>
</div>
<div class="chart-box">
<h3>📈 Hiring Trends — Top 5 Sectors</h3>
<canvas id="hiringTrendChart"></canvas>
</div>
<div class="chart-box">
<h3>📈 Contract Value Trends — Top 5 Sectors</h3>
<canvas id="contractTrendChart"></canvas>
</div>
<div class="chart-box">
<h3>👥 Hiring Categories (All Sectors)</h3>
<canvas id="categoryChart"></canvas>
</div>
<div class="chart-box">
<h3>🔄 Contract Types (All Sectors)</h3>
<canvas id="contractTypeChart"></canvas>
</div>
<div class="chart-box" style="grid-column: 1 / -1">
<h3>📍 Geographic Distribution — Top Locations (All Sectors)</h3>
<canvas id="regionChart"></canvas>
</div>
</div>

<div class="section">
<h2>🏛️ Sector Breakdown <span class="count">{len(sorted_sectors)}</span></h2>
<div class="table-wrap">
<table>
<thead>
<tr>
<th>#</th>
<th>Sector (Entidade)</th>
<th>Entities</th>
<th>Listings</th>
<th>Positions</th>
<th>Avg Pos/Listing</th>
<th>Contracts</th>
<th>Contract Value</th>
<th>Avg Value/Contract</th>
</tr>
</thead>
<tbody>{sector_rows}</tbody>
</table>
</div>
</div>

</div>

<div class="footer">
Generated by Analisa.pt Sector Dashboard — Government-wide Transparency Analysis
</div>

<script>
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

// Sector drill-down toggle
function toggleSector(id) {{
    const row = document.getElementById(id);
    const arrow = document.getElementById('arrow-' + id);
    if (row.style.display === 'none') {{
        row.style.display = '';
        arrow.classList.add('open');
    }} else {{
        row.style.display = 'none';
        arrow.classList.remove('open');
    }}
}}

// Listings by Sector
new Chart(document.getElementById('listingsChart'), {{
    type: 'bar',
    data: {{
        labels: {sector_names},
        datasets: [{{
            label: 'Listings',
            data: {sector_listings},
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderColor: '#3b82f6',
            borderWidth: 1,
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

// Contract Value by Sector
new Chart(document.getElementById('valueChart'), {{
    type: 'bar',
    data: {{
        labels: {sector_names},
        datasets: [{{
            label: 'Contract Value (€)',
            data: {sector_values},
            backgroundColor: 'rgba(16, 185, 129, 0.7)',
            borderColor: '#10b981',
            borderWidth: 1,
            borderRadius: 4,
        }}]
    }},
    options: {{
        responsive: true,
        indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }} }}
    }}
}});

// Hiring Trends
new Chart(document.getElementById('hiringTrendChart'), {{
    type: 'line',
    data: {{
        labels: {json.dumps(all_months)},
        datasets: {json.dumps(hiring_datasets)}
    }},
    options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{ y: {{ beginAtZero: true }} }},
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, pointStyle: 'circle' }} }}
        }}
    }}
}});

// Contract Value Trends
new Chart(document.getElementById('contractTrendChart'), {{
    type: 'line',
    data: {{
        labels: {json.dumps(all_months)},
        datasets: {json.dumps(contract_datasets)}
    }},
    options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }} }},
        plugins: {{
            legend: {{ position: 'top', labels: {{ usePointStyle: true, pointStyle: 'circle' }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': €' + ctx.parsed.y.toLocaleString() }} }}
        }}
    }}
}});

// Categories
new Chart(document.getElementById('categoryChart'), {{
    type: 'doughnut',
    data: {{
        labels: {cat_labels},
        datasets: [{{
            data: {cat_values},
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22d3ee'],
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

// Contract Types
new Chart(document.getElementById('contractTypeChart'), {{
    type: 'doughnut',
    data: {{
        labels: {ct_labels},
        datasets: [{{
            data: {ct_values},
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22d3ee'],
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

// Geographic Distribution
new Chart(document.getElementById('regionChart'), {{
    type: 'bar',
    data: {{
        labels: {region_labels},
        datasets: [{{
            label: 'Listings',
            data: {region_values},
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22d3ee', '#84cc16', '#f43f5e', '#06b6d4', '#a855f7', '#eab308'],
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


def build_sector_detail(name: str, sector: dict, all_listings: dict) -> str:
    """Generate a standalone HTML detail page for a single sector."""
    entities = sorted(sector["entities"], key=lambda e: e.get("listing_count", 0), reverse=True)
    total_listings = sector["total_listings"]
    total_positions = sector["total_positions"]
    total_contracts = sector["total_contracts"]
    total_value = sector["total_contract_value"]

    # Chart data
    hiring_months = sorted(sector["hiring_by_month"].keys())
    contract_months = sorted(sector["contract_by_month"].keys())
    ht_labels = json.dumps(hiring_months)
    ht_counts = json.dumps([sector["hiring_by_month"].get(m, {}).get("count", 0) for m in hiring_months])
    ht_positions = json.dumps([sector["hiring_by_month"].get(m, {}).get("positions", 0) for m in hiring_months])
    ct_labels = json.dumps(contract_months)
    ct_values = json.dumps([round(sector["contract_by_month"].get(m, {}).get("value", 0), 2) for m in contract_months])
    ct_counts = json.dumps([sector["contract_by_month"].get(m, {}).get("count", 0) for m in contract_months])

    # Category / type / region breakdowns
    cat_sorted = sorted(sector["categories"].items(), key=lambda x: x[1], reverse=True)[:10]
    ct_sorted = sorted(sector["contract_types"].items(), key=lambda x: x[1], reverse=True)[:10]
    reg_sorted = sorted(sector["regions"].items(), key=lambda x: x[1], reverse=True)[:15]
    cat_labels = json.dumps([c[0][:25] for c in cat_sorted])
    cat_values = json.dumps([c[1] for c in cat_sorted])
    ct_type_labels = json.dumps([c[0][:25] for c in ct_sorted])
    ct_type_values = json.dumps([c[1] for c in ct_sorted])
    reg_labels = json.dumps([r[0][:30] for r in reg_sorted])
    reg_values = json.dumps([r[1] for r in reg_sorted])

    # Entity table rows with expandable listings
    entity_rows = ""
    for i, e in enumerate(entities):
        eid = f"entity-{i}"
        e_nif = e.get("nif", "") or "N/A"
        # Listings for this entity
        entity_listings = all_listings.get(e["id"], [])
        listing_rows = ""
        for l in entity_listings[:15]:
            status_cls = "open" if "aberta" in (l.get("estado") or "").lower() else "closed"
            loc = l.get("local_trabalho", "")
            loc_display = _esc(loc[:30]) if loc else "—"
            listing_rows += f"""<tr>
<td><span class="badge {status_cls}">{_esc(l.get('estado', '—'))}</span></td>
<td>{_esc(l.get('titulo', '—')[:55])}</td>
<td>{_esc(l.get('categoria', '—'))}</td>
<td>€{_esc(l.get('remuneracao', '—'))}</td>
<td>{_esc(l.get('total_postos', '1'))}</td>
<td>{loc_display}</td>
<td>{_esc(l.get('data_publicacao', '—')[:10]) if l.get('data_publicacao') else '—'}</td>
</tr>"""
        more_note = f"<tr><td colspan=\"7\" style=\"color:#64748b;font-style:italic\">... and {len(entity_listings) - 15} more listings</td></tr>" if len(entity_listings) > 15 else ""
        base_link = f"<a href=\"https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={_esc(e_nif)}\" target=\"_blank\" style=\"color:#60a5fa\">BASE.gov</a>" if e_nif != "N/A" else ""
        entity_rows += f"""<tr class="entity-row" onclick="toggleEntity('{eid}')" style="cursor:pointer">
<td>{i+1} <span id="arrow-{eid}" class="arrow">▶</span></td>
<td><strong>{_esc(e.get('display_name', '—')[:50])}</strong></td>
<td>{_esc(e_nif)}</td>
<td>{e.get('listing_count', 0):,}</td>
<td>{base_link}</td>
</tr>
<tr class="detail-row" id="{eid}" style="display:none">
<td colspan="5">
<div class="entity-detail">
<table class="listing-table">
<thead><tr><th>Status</th><th>Title</th><th>Category</th><th>Salary</th><th>Positions</th><th>Location</th><th>Published</th></tr></thead>
<tbody>{listing_rows}{more_note}</tbody>
</table>
</div>
</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sector Detail — {_esc(name)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 2rem 0; text-align: center; }}
.header h1 {{ font-size: 1.8rem; color: #f8fafc; margin-bottom: 0.5rem; }}
.header .subtitle {{ color: #94a3b8; font-size: 0.95rem; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 1rem; margin-bottom: 2rem; }}
@media (max-width: 1024px) {{ .cards {{ grid-template-columns: repeat(3, 1fr); }} }}
@media (max-width: 600px) {{ .cards {{ grid-template-columns: 1fr; }} }}
.card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.2rem; text-align: center; transition: transform 0.2s, box-shadow 0.2s; }}
.card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }}
.card .icon {{ font-size: 1.5rem; margin-bottom: 0.3rem; }}
.card .value {{ font-size: 1.6rem; font-weight: 700; color: #f8fafc; }}
.card .label {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
@media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
.chart-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.chart-box h3 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1rem; }}
.section {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }}
.section h2 {{ color: #f8fafc; margin-bottom: 1rem; font-size: 1.1rem; display: flex; align-items: center; gap: 0.5rem; }}
.section h2 .count {{ background: #3b82f6; color: white; padding: 0.1rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 2px solid #334155; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; position: sticky; top: 0; background: #1e293b; }}
td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
.table-wrap {{ max-height: 500px; overflow-y: auto; }}
.footer {{ text-align: center; padding: 2rem; color: #64748b; font-size: 0.8rem; border-top: 1px solid #1e293b; }}
.entity-row {{ cursor: pointer; transition: background 0.15s; }}
.entity-row:hover td {{ background: #334155 !important; }}
.arrow {{ display: inline-block; transition: transform 0.2s; color: #60a5fa; font-size: 0.7rem; margin-right: 0.3rem; }}
.arrow.open {{ transform: rotate(90deg); }}
.detail-row td {{ padding: 0 !important; background: #0f172a !important; border-bottom: 2px solid #334155 !important; }}
.entity-detail {{ padding: 0.5rem 1rem 1rem 2rem; }}
.listing-table {{ width: 100%; font-size: 0.8rem; }}
.listing-table th {{ background: #1e293b; color: #64748b; font-size: 0.7rem; padding: 0.4rem 0.6rem; }}
.listing-table td {{ padding: 0.35rem 0.6rem; color: #cbd5e1; border-bottom: 1px solid #1e293b; }}
.listing-table tr:hover td {{ background: #1e293b; }}
.badge {{ padding: 0.15rem 0.5rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; }}
.badge.open {{ background: #166534; color: #86efac; }}
.badge.closed {{ background: #7f1d1d; color: #fca5a5; }}
a {{ color: #60a5fa; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>

<div class="header">
<h1>🏛️ {_esc(name)}</h1>
<div class="subtitle">Sector Detail — Analisa.pt</div>
</div>

<div class="container">

<div class="cards">
<div class="card">
<div class="icon">🏢</div>
<div class="value">{len(entities)}</div>
<div class="label">Entities</div>
</div>
<div class="card">
<div class="icon">📋</div>
<div class="value">{total_listings:,}</div>
<div class="label">BEP Listings</div>
</div>
<div class="card">
<div class="icon">👥</div>
<div class="value">{total_positions:,}</div>
<div class="label">Total Positions</div>
</div>
<div class="card">
<div class="icon">📦</div>
<div class="value">{total_contracts:,}</div>
<div class="label">Contracts</div>
</div>
<div class="card">
<div class="icon">💰</div>
<div class="value">€{total_value:,.0f}</div>
<div class="label">Contract Value</div>
</div>
</div>

<div class="charts">
<div class="chart-box">
<h3>📈 Hiring by Month</h3>
<canvas id="hiringChart"></canvas>
</div>
<div class="chart-box">
<h3>📈 Contract Value by Month</h3>
<canvas id="contractChart"></canvas>
</div>
<div class="chart-box">
<h3>👥 Hiring Categories</h3>
<canvas id="catChart"></canvas>
</div>
<div class="chart-box">
<h3>🔄 Contract Types</h3>
<canvas id="ctChart"></canvas>
</div>
<div class="chart-box" style="grid-column: 1 / -1">
<h3>📍 Geographic Distribution — Work Locations</h3>
<canvas id="regionChart"></canvas>
</div>
</div>

<div class="section">
<h2>🏢 Entities in Sector <span class="count">{len(entities)}</span></h2>
<p style="color:#64748b;font-size:0.85rem;margin-bottom:1rem">Click an entity to expand its job listings</p>
<div class="table-wrap" style="max-height:none">
<table>
<thead>
<tr>
<th>#</th>
<th>Entity</th>
<th>NIF</th>
<th>Listings</th>
<th>BASE.gov</th>
</tr>
</thead>
<tbody>{entity_rows}</tbody>
</table>
</div>
</div>

</div>

<div class="footer">
Generated by Analisa.pt — Sector Detail: {_esc(name)}
</div>

<script>
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

function toggleEntity(id) {{
    const row = document.getElementById(id);
    const arrow = document.getElementById('arrow-' + id);
    if (row.style.display === 'none') {{
        row.style.display = '';
        arrow.classList.add('open');
    }} else {{
        row.style.display = 'none';
        arrow.classList.remove('open');
    }}
}}

new Chart(document.getElementById('hiringChart'), {{
    type: 'bar',
    data: {{ labels: {ht_labels}, datasets: [{{ label: 'Listings', data: {ht_counts}, backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 }}, {{ label: 'Positions', data: {ht_positions}, type: 'line', borderColor: '#8b5cf6', backgroundColor: 'rgba(139,92,246,0.1)', yAxisID: 'y1', tension: 0.3, pointRadius: 3 }}] }},
    options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});

new Chart(document.getElementById('contractChart'), {{
    type: 'bar',
    data: {{ labels: {ct_labels}, datasets: [{{ label: 'Value (€)', data: {ct_values}, backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }}, {{ label: 'Contracts', data: {ct_counts}, type: 'line', borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', yAxisID: 'y1', tension: 0.3, pointRadius: 3 }}] }},
    options: {{ responsive: true, interaction: {{ mode: 'index', intersect: false }}, scales: {{ y: {{ beginAtZero: true, ticks: {{ callback: v => '€' + v.toLocaleString() }} }}, y1: {{ position: 'right', beginAtZero: true, grid: {{ drawOnChartArea: false }} }} }} }}
}});

new Chart(document.getElementById('catChart'), {{
    type: 'doughnut',
    data: {{ labels: {cat_labels}, datasets: [{{ data: {cat_values}, backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#22d3ee'], borderWidth: 0 }}] }},
    options: {{ responsive: true, plugins: {{ legend: {{ position: 'right', labels: {{ padding: 12, usePointStyle: true, pointStyle: 'circle' }} }} }} }}
}});

new Chart(document.getElementById('ctChart'), {{
    type: 'doughnut',
    data: {{ labels: {ct_type_labels}, datasets: [{{ data: {ct_type_values}, backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#22d3ee'], borderWidth: 0 }}] }},
    options: {{ responsive: true, plugins: {{ legend: {{ position: 'right', labels: {{ padding: 12, usePointStyle: true, pointStyle: 'circle' }} }} }} }}
}});

new Chart(document.getElementById('regionChart'), {{
    type: 'bar',
    data: {{ labels: {reg_labels}, datasets: [{{ label: 'Listings', data: {reg_values}, backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#22d3ee','#84cc16','#f43f5e','#06b6d4','#a855f7','#eab308'], borderRadius: 4 }}] }},
    options: {{ responsive: true, indexAxis: 'y', plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true }} }} }}
}});
</script>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate Sector-Level Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-o", "--output", default="", help="Output HTML file")
    parser.add_argument("--sector", default="", help="Filter by specific sector name")
    parser.add_argument("--top", type=int, default=0, help="Show only top N sectors")
    parser.add_argument("--detail", default="", help="Generate standalone detail page for a sector")
    parser.add_argument("--region", default="", help="Filter by work location (substring match on local_trabalho)")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")

    args = parser.parse_args()

    print("Loading all entities...")
    entities = get_all_entities()
    if not entities:
        print("No entities found in database.")
        sys.exit(1)
    print(f"  Found {len(entities)} entities")

    region_filter = args.region
    if region_filter:
        print(f"Filtering by region: {region_filter}...")

    print("Aggregating sector data...")
    sectors = aggregate_sector_data(entities, region=region_filter)
    print(f"  Found {len(sectors)} unique sectors")

    if args.detail:
        # Find matching sector
        match = None
        for name, data in sectors.items():
            if args.detail.lower() in name.lower():
                match = (name, data)
                break
        if not match:
            print(f"No sector found matching '{args.detail}'")
            print("Available sectors:")
            for name in sorted(sectors.keys()):
                print(f"  - {name}")
            sys.exit(1)
        name, data = match
        print(f"Generating detail page for {name} ({len(data['entities'])} entities)...")
        all_listings = load_all_listings(region=region_filter)
        html = build_sector_detail(name, data, all_listings)
        output = args.output or f"sector_{name.replace(' ', '_')[:30]}.html"
    else:
        title = "All Sectors"
        if args.sector:
            title = f"Sector: {args.sector}"
        elif args.top:
            title = f"Top {args.top} Sectors"
        if region_filter:
            title += f" ({region_filter})"

        print(f"Generating dashboard: {title}...")
        html = build_sector_dashboard(sectors, top_n=args.top, filter_sector=args.sector,
                                      region=region_filter)
        output = args.output or f"sector_dashboard.html"

    Path(output).write_text(html, encoding="utf-8")
    print(f"  ✅ Dashboard saved to {output}")

    if args.open:
        webbrowser.open(Path(output).resolve().as_uri())


if __name__ == "__main__":
    main()
