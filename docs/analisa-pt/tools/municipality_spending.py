#!/usr/bin/env python3
"""Municipality Spending Dashboard — Track where public money goes.

Aggregates 245K+ Portuguese public procurement contracts by municipality,
showing total spending with breakdowns by entity and contract type.

This answers the question: "Where is my tax money being spent?"

Usage:
    python municipality_spending.py                     # Top 30 municipalities
    python municipality_spending.py --top 50           # Top 50
    python municipality_spending.py --location "Gaia"  # Specific municipality
    python municipality_spending.py --region norte     # Filter by region
    python municipality_spending.py --min-value 1000000 # Municipalities over €1M
    python municipality_spending.py --html -o spending.html  # HTML dashboard
    python municipality_spending.py --json             # JSON export
"""

import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from unidecode import unidecode
import re
from utils import format_currency, extract_location

SCRIPT_DIR = Path(__file__).parent
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"

# Portuguese NUTS3 regions (simplified mapping by district)
DISTRICT_REGIONS = {
    "viana do castelo": "norte", "braga": "norte", "vila real": "norte",
    "braganca": "norte", "porto": "norte", "aveiro": "centro",
    "viseu": "centro", "guarda": "centro", "coimbra": "centro",
    "castelo branco": "centro", "leiria": "centro", "lisboa": "lisboa",
    "setubal": "lisboa", "evora": "alentejo", "portalegre": "alentejo",
    "beja": "alentejo", "faro": "algarve", "madeira": "madeira",
    "acores": "acores",
}



def guess_region(location: str) -> str:
    """Guess the NUTS3 region from a location name."""
    # This is a simplified mapping - would need full database for production
    loc_lower = location.lower()
    for district, region in DISTRICT_REGIONS.items():
        if district in loc_lower:
            return region
    return "desconhecido"


def load_and_aggregate() -> dict:
    """Load contracts and aggregate by municipality."""
    if not CONTRACT_CACHE.exists():
        print(f"Error: Contract index not found at {CONTRACT_CACHE}")
        sys.exit(1)

    with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
        index = json.load(f)

    # Aggregate by location
    municipalities = defaultdict(lambda: {
        "location": "",
        "total_value": 0.0,
        "contract_count": 0,
        "entities": defaultdict(lambda: {"count": 0, "value": 0.0, "nifs": set()}),
        "types": defaultdict(lambda: {"count": 0, "value": 0.0}),
        "nifs": set(),
        "min_date": "9999-12-31",
        "max_date": "0000-01-01",
    })

    for nif, contracts in index.items():
        for c in contracts:
            entity_name = c.get("entity_name", "")
            location = extract_location(entity_name)

            if not location or len(location) < 3:
                location = "outros"

            m = municipalities[location]
            m["location"] = location
            m["total_value"] += c.get("valor", 0) or 0
            m["contract_count"] += 1
            m["nifs"].add(nif)

            # Entity breakdown
            m["entities"][entity_name]["count"] += 1
            m["entities"][entity_name]["value"] += c.get("valor", 0) or 0
            m["entities"][entity_name]["nifs"].add(nif)

            # Type breakdown
            tipo = c.get("tipo") or "Desconhecido"
            m["types"][tipo]["count"] += 1
            m["types"][tipo]["value"] += c.get("valor", 0) or 0

            # Date range
            d = c.get("data", "")
            if d and d < m["min_date"]:
                m["min_date"] = d
            if d and d > m["max_date"]:
                m["max_date"] = d

    # Convert sets to counts for JSON serialization
    for loc, data in municipalities.items():
        data["entity_count"] = len(data["entities"])
        data["nif_count"] = len(data["nifs"])
        # Sort entities by value
        data["top_entities"] = sorted(
            [{"name": k, "count": v["count"], "value": v["value"], "nifs": len(v["nifs"])}
             for k, v in data["entities"].items()],
            key=lambda x: -x["value"]
        )[:10]
        # Sort types by value
        data["top_types"] = sorted(
            [{"tipo": k, "count": v["count"], "value": v["value"]}
             for k, v in data["types"].items()],
            key=lambda x: -x["value"]
        )[:10]
        # Clean up
        del data["entities"]
        del data["types"]
        del data["nifs"]

    return dict(municipalities)



def print_ranking(municipalities: dict, top: int = 30, location_filter: str = ""):
    """Print municipality spending ranking."""
    # Sort by total value descending
    ranked = sorted(municipalities.values(), key=lambda x: -x["total_value"])

    if location_filter:
        ranked = [m for m in ranked if location_filter.lower() in m["location"].lower()]

    if not ranked:
        print("\n  No municipalities found matching your criteria.\n")
        return

    print(f"\n  {'='*90}")
    print(f"  🏛️  MUNICIPALITY PUBLIC SPENDING RANKING")
    print(f"  {'='*90}")

    total_spending = sum(m["total_value"] for m in ranked)
    total_contracts = sum(m["contract_count"] for m in ranked)
    print(f"  Total spending: {format_currency(total_spending)} across {total_contracts:,} contracts")
    print(f"  Municipalities: {len(ranked)}")
    print(f"\n  {'Rank':<6} {'Municipality':<35} {'Spending':>15} {'Contracts':>10} {'Entities':>10} {'Avg/Contract':>15}")
    print(f"  {'-'*6} {'-'*35} {'-'*15} {'-'*10} {'-'*10} {'-'*15}")

    for i, m in enumerate(ranked[:top], 1):
        avg = m["total_value"] / m["contract_count"] if m["contract_count"] else 0
        print(f"  {i:<6} {m['location'][:35]:<35} {format_currency(m['total_value']):>15} {m['contract_count']:>10,} {m['entity_count']:>10} {format_currency(avg):>15}")

    print(f"  {'='*90}\n")


def print_detail(municipalities: dict, location: str):
    """Print detailed breakdown for a specific municipality."""
    matches = [m for m in municipalities.values() if location.lower() in m["location"].lower()]

    if not matches:
        print(f"\n  No municipality found matching '{location}'\n")
        return

    for m in matches:
        print(f"\n  {'='*80}")
        print(f"  🏛️  {m['location'].upper()}")
        print(f"  {'='*80}")
        print(f"  Total spending:    {format_currency(m['total_value'])}")
        print(f"  Total contracts:   {m['contract_count']:,}")
        print(f"  NIFs tracked:      {m['nif_count']}")
        print(f"  Entities involved: {m['entity_count']}")
        print(f"  Date range:        {m['min_date']} → {m['max_date']}")
        avg = m["total_value"] / m["contract_count"] if m["contract_count"] else 0
        print(f"  Average contract:  {format_currency(avg)}")

        if m["top_entities"]:
            print(f"\n  Top Entities by Spending:")
            for e in m["top_entities"][:10]:
                print(f"    {format_currency(e['value']):>15}  {e['count']:5d} contracts  {e['name'][:50]}")

        if m["top_types"]:
            print(f"\n  Contract Types:")
            for t in m["top_types"][:10]:
                print(f"    {format_currency(t['value']):>15}  {t['count']:5d} contracts  {t['tipo']}")

        print(f"  {'='*80}\n")


def generate_html_dashboard(municipalities: dict, output_path: str):
    """Generate an interactive HTML dashboard."""
    ranked = sorted(municipalities.values(), key=lambda x: -x["total_value"])
    total_spending = sum(m["total_value"] for m in ranked)
    total_contracts = sum(m["contract_count"] for m in ranked)

    # Top 20 for chart
    top20 = ranked[:20]
    chart_labels = json.dumps([m["location"][:20] for m in top20])
    chart_values = json.dumps([round(m["total_value"], 2) for m in top20])
    chart_contracts = json.dumps([m["contract_count"] for m in top20])

    # All municipalities table rows
    table_rows = ""
    for i, m in enumerate(ranked[:100], 1):
        pct = (m["total_value"] / total_spending * 100) if total_spending else 0
        avg = m["total_value"] / m["contract_count"] if m["contract_count"] else 0
        bar_width = int(pct * 3) if pct > 0 else 1
        table_rows += f"""<tr>
<td>{i}</td>
<td><strong>{m['location']}</strong></td>
<td class="val">{format_currency(m['total_value'])}</td>
<td class="bar"><div style="width:{bar_width}%;background:#3b82f6;height:18px;border-radius:4px"></div><span>{pct:.1f}%</span></td>
<td>{m['contract_count']:,}</td>
<td>{m['entity_count']}</td>
<td>{format_currency(avg)}</td>
</tr>"""

    # Region aggregation
    regions = defaultdict(lambda: {"value": 0, "count": 0, "municipalities": 0})
    for m in ranked:
        region = guess_region(m["location"])
        regions[region]["value"] += m["total_value"]
        regions[region]["count"] += m["contract_count"]
        regions[region]["municipalities"] += 1

    region_labels = json.dumps(list(regions.keys()))
    region_values = json.dumps([round(r["value"], 2) for r in regions.values()])

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Municipality Spending Dashboard — Analisa.pt</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }}
.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; padding: 2rem 0; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}
.header h1 {{ font-size: 2rem; color: #f8fafc; }}
.header .subtitle {{ color: #94a3b8; margin-top: 0.5rem; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin: 2rem 0; }}
@media (max-width: 768px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
.card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.card .icon {{ font-size: 2rem; }}
.card .value {{ font-size: 1.8rem; font-weight: 700; color: #f8fafc; margin: 0.5rem 0; }}
.card .label {{ font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; }}
.charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
@media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} }}
.chart-box {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; }}
.chart-box h3 {{ color: #f8fafc; margin-bottom: 1rem; }}
.section {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }}
.section h2 {{ color: #f8fafc; margin-bottom: 1rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; padding: 0.6rem; border-bottom: 2px solid #334155; color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; }}
td {{ padding: 0.5rem 0.6rem; border-bottom: 1px solid #1e293b; }}
tr:hover td {{ background: #334155; }}
.val {{ font-weight: 600; color: #3b82f6; }}
.bar {{ display: flex; align-items: center; gap: 0.5rem; }}
.bar span {{ font-size: 0.75rem; color: #94a3b8; }}
.footer {{ text-align: center; padding: 2rem; color: #64748b; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="header">
<div class="container">
<h1>🏛️ Municipality Public Spending Dashboard</h1>
<div class="subtitle">Where does Portuguese public money go? — {total_contracts:,} contracts analyzed</div>
</div>
</div>
<div class="container">
<div class="cards">
<div class="card">
<div class="icon">💰</div>
<div class="value">{format_currency(total_spending)}</div>
<div class="label">Total Public Spending</div>
</div>
<div class="card">
<div class="icon">📦</div>
<div class="value">{total_contracts:,}</div>
<div class="label">Total Contracts</div>
</div>
<div class="card">
<div class="icon">🏛️</div>
<div class="value">{len(ranked)}</div>
<div class="label">Municipalities</div>
</div>
<div class="card">
<div class="icon">📊</div>
<div class="value">{format_currency(total_spending / len(ranked) if ranked else 0)}</div>
<div class="label">Avg per Municipality</div>
</div>
</div>
<div class="charts">
<div class="chart-box">
<h3>📊 Top 20 Municipalities by Spending</h3>
<canvas id="spendingChart"></canvas>
</div>
<div class="chart-box">
<h3>🗺️ Spending by Region</h3>
<canvas id="regionChart"></canvas>
</div>
</div>
<div class="section">
<h2>🏛️ Municipality Spending Ranking (Top 100)</h2>
<table>
<thead><tr><th>#</th><th>Municipality</th><th>Spending</th><th>% of Total</th><th>Contracts</th><th>Entities</th><th>Avg/Contract</th></tr></thead>
<tbody>{table_rows}</tbody>
</table>
</div>
</div>
<div class="footer">
Generated by Analisa.pt Municipality Spending Dashboard — {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
<script>
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

// Spending Chart
new Chart(document.getElementById('spendingChart'), {{
    type: 'bar',
    data: {{
        labels: {chart_labels},
        datasets: [{{
            label: 'Total Spending (€)',
            data: {chart_values},
            backgroundColor: 'rgba(59, 130, 246, 0.7)',
            borderRadius: 4,
        }}]
    }},
    options: {{
        responsive: true,
        indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ beginAtZero: true, ticks: {{ callback: v => '€' + (v/1000000).toFixed(1) + 'M' }} }} }}
    }}
}});

// Region Doughnut
new Chart(document.getElementById('regionChart'), {{
    type: 'doughnut',
    data: {{
        labels: {region_labels},
        datasets: [{{
            data: {region_values},
            backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'],
            borderWidth: 0,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ position: 'right', labels: {{ padding: 12, usePointStyle: true }} }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.label + ': €' + (ctx.parsed/1000000).toFixed(1) + 'M' }} }}
        }}
    }}
}});
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"\n  ✅ Dashboard saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Municipality Public Spending Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Top 30 municipalities
  %(prog)s --top 50                 Top 50
  %(prog)s --location "Gaia"        Detail for Gaia
  %(prog)s --min-value 1000000      Municipalities over €1M
  %(prog)s --html -o spending.html  Generate HTML dashboard
        """,
    )
    parser.add_argument("--location", default="", help="Filter by location name (partial match)")
    parser.add_argument("--top", type=int, default=30, help="Number of municipalities to show (default: 30)")
    parser.add_argument("--min-value", type=float, default=0, help="Minimum total spending filter")
    parser.add_argument("--html", action="store_true", help="Generate HTML dashboard")
    parser.add_argument("-o", "--output", default="municipality_spending.html", help="Output file path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--detail", action="store_true", help="Show detailed breakdown")

    args = parser.parse_args()

    # Load and aggregate
    print("\n  Loading contracts...")
    municipalities = load_and_aggregate()
    print(f"  Aggregated {len(municipalities)} municipalities")

    # Filter by min value
    if args.min_value > 0:
        municipalities = {k: v for k, v in municipalities.items() if v["total_value"] >= args.min_value}

    # Output
    if args.html:
        generate_html_dashboard(municipalities, args.output)
    elif args.json:
        print(json.dumps(municipalities, ensure_ascii=False, indent=2, default=str))
    elif args.detail and args.location:
        print_detail(municipalities, args.location)
    else:
        print_ranking(municipalities, top=args.top, location_filter=args.location)


if __name__ == "__main__":
    main()
