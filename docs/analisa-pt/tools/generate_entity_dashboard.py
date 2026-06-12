#!/usr/bin/env python3
"""Entity Ranking Dashboard Generator

Generates a standalone HTML dashboard from procurement.db showing
buyer vs winner rankings by contract value, with interactive charts.

Usage:
    python generate_entity_dashboard.py                    # Default: top 50
    python generate_entity_dashboard.py --top 100          # Top 100 entities
    python generate_entity_dashboard.py --output dashboard.html  # Custom output
"""

import json
import sqlite3
import argparse
from pathlib import Path

from utils import fmt
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
DEFAULT_OUTPUT = DATA_DIR / "entity_dashboard.html"


def query_data(top_n: int = 50) -> dict:
    """Query procurement.db for entity ranking data."""
    conn = db_connect(str(PROCUREMENT_DB))

    # Top buyers
    buyers = conn.execute(
        """SELECT nifEntidade, desigEntidade, numContratos,
                  totAdjudicanteValorContratIni, totValorContratIni
           FROM entidades
           WHERE totAdjudicanteValorContratIni > 0
           ORDER BY totAdjudicanteValorContratIni DESC
           LIMIT ?""",
        (top_n,),
    ).fetchall()

    # Top winners
    winners = conn.execute(
        """SELECT nifEntidade, desigEntidade, numContratos,
                  totValorContratIni, totAdjudicanteValorContratIni
           FROM entidades
           WHERE totValorContratIni > 0
           ORDER BY totValorContratIni DESC
           LIMIT ?""",
        (top_n,),
    ).fetchall()

    # Entity type distribution (buyer-heavy vs winner-heavy)
    distribution = conn.execute(
        """SELECT
            CASE
                WHEN totAdjudicanteValorContratIni > totValorContratIni * 2 THEN 'buyer_heavy'
                WHEN totValorContratIni > totAdjudicanteValorContratIni * 2 THEN 'winner_heavy'
                ELSE 'balanced'
            END as category,
            COUNT(*) as cnt,
            SUM(totAdjudicanteValorContratIni) as buyer_total,
            SUM(totValorContratIni) as winner_total
        FROM entidades
        WHERE totAdjudicanteValorContratIni > 0 OR totValorContratIni > 0
        GROUP BY category"""
    ).fetchall()

    # Stats
    stats = conn.execute(
        """SELECT
            COUNT(*) as total_entities,
            SUM(totAdjudicanteValorContratIni) as total_buyer_value,
            SUM(totValorContratIni) as total_winner_value,
            AVG(totAdjudicanteValorContratIni) as avg_buyer,
            AVG(totValorContratIni) as avg_winner
        FROM entidades
        WHERE totAdjudicanteValorContratIni > 0 OR totValorContratIni > 0"""
    ).fetchone()

    conn.close()

    return {
        "buyers": [dict(r) for r in buyers],
        "winners": [dict(r) for r in winners],
        "distribution": [dict(r) for r in distribution],
        "stats": dict(stats) if stats else {},
        "top_n": top_n,
    }


def generate_html(data: dict) -> str:
    """Generate standalone HTML dashboard."""
    buyers = data["buyers"]
    winners = data["winners"]
    stats = data["stats"]
    top_n = data["top_n"]

    # Prepare chart data
    buyer_labels = json.dumps([b["desigEntidade"][:35] for b in buyers[:20]])
    buyer_values = json.dumps([b["totAdjudicanteValorContratIni"] for b in buyers[:20]])
    winner_labels = json.dumps([w["desigEntidade"][:35] for w in winners[:20]])
    winner_values = json.dumps([w["totValorContratIni"] for w in winners[:20]])

    # Top 10 buyers vs winners side by side
    top_buyers_10 = buyers[:10]
    top_winners_10 = winners[:10]
    max_val = max(
        max((b["totAdjudicanteValorContratIni"] for b in top_buyers_10), default=1),
        max((w["totValorContratIni"] for w in top_winners_10), default=1),
    )

    def pct(val):
        return f"{(val / max_val * 100) if max_val else 0:.1f}"

    # Build buyer rows
    buyer_rows = ""
    for i, b in enumerate(buyers, 1):
        buyer_val = b["totAdjudicanteValorContratIni"] or 0
        winner_val = b["totValorContratIni"] or 0
        buyer_rows += f"""
        <tr>
            <td class="rank">{i}</td>
            <td class="entity-name" title="{b['desigEntidade']}">{b['desigEntidade'][:55]}</td>
            <td class="nif">{b['nifEntidade']}</td>
            <td class="num">{b['numContratos']:,}</td>
            <td class="amount buyer">{fmt(buyer_val)}</td>
            <td class="amount winner">{fmt(winner_val)}</td>
        </tr>"""

    # Build winner rows
    winner_rows = ""
    for i, w in enumerate(winners, 1):
        buyer_val = w["totAdjudicanteValorContratIni"] or 0
        winner_val = w["totValorContratIni"] or 0
        winner_rows += f"""
        <tr>
            <td class="rank">{i}</td>
            <td class="entity-name" title="{w['desigEntidade']}">{w['desigEntidade'][:55]}</td>
            <td class="nif">{w['nifEntidade']}</td>
            <td class="num">{w['numContratos']:,}</td>
            <td class="amount winner">{fmt(winner_val)}</td>
            <td class="amount buyer">{fmt(buyer_val)}</td>
        </tr>"""

    # Top 10 comparison bars
    buyer_bars = ""
    for b in top_buyers_10:
        val = b["totAdjudicanteValorContratIni"] or 0
        buyer_bars += f"""
        <div class="bar-row">
            <div class="bar-label" title="{b['desigEntidade']}">{b['desigEntidade'][:40]}</div>
            <div class="bar-track">
                <div class="bar-fill buyer" style="width:{pct(val)}%"></div>
            </div>
            <div class="bar-value">{fmt(val)}</div>
        </div>"""

    winner_bars = ""
    for w in top_winners_10:
        val = w["totValorContratIni"] or 0
        winner_bars += f"""
        <div class="bar-row">
            <div class="bar-label" title="{w['desigEntidade']}">{w['desigEntidade'][:40]}</div>
            <div class="bar-track">
                <div class="bar-fill winner" style="width:{pct(val)}%"></div>
            </div>
            <div class="bar-value">{fmt(val)}</div>
        </div>"""

    total_buyer = stats.get("total_buyer_value") or 0
    total_winner = stats.get("total_winner_value") or 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Entity Ranking Dashboard — Portuguese Public Procurement</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --buyer: #2563eb;
    --buyer-light: #dbeafe;
    --winner: #059669;
    --winner-light: #d1fae5;
    --bg: #0f172a;
    --card: #1e293b;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --border: #334155;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 8px; }}
  .subtitle {{ color: var(--muted); margin-bottom: 32px; font-size: 14px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .stat-card {{ background: var(--card); border-radius: 12px; padding: 20px; border: 1px solid var(--border); }}
  .stat-card .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .stat-card .value {{ font-size: 24px; font-weight: 700; }}
  .stat-card .value.buyer {{ color: var(--buyer); }}
  .stat-card .value.winner {{ color: var(--winner); }}
  .section {{ background: var(--card); border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid var(--border); }}
  .section-title {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
  .section-title .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
  .section-title .dot.buyer {{ background: var(--buyer); }}
  .section-title .dot.winner {{ background: var(--winner); }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 10px 12px; border-bottom: 2px solid var(--border); color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; background: var(--card); }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
  tr:hover {{ background: rgba(255,255,255,0.03); }}
  .rank {{ color: var(--muted); font-weight: 600; width: 40px; }}
  .entity-name {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }}
  .nif {{ color: var(--muted); font-family: monospace; font-size: 12px; }}
  .num {{ text-align: right; font-family: monospace; }}
  .amount {{ text-align: right; font-weight: 600; font-family: monospace; }}
  .amount.buyer {{ color: var(--buyer); }}
  .amount.winner {{ color: var(--winner); }}
  .chart-container {{ position: relative; height: 500px; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 8px; gap: 12px; }}
  .bar-label {{ width: 280px; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; flex-shrink: 0; }}
  .bar-track {{ flex: 1; height: 24px; background: var(--bg); border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.6s ease; }}
  .bar-fill.buyer {{ background: linear-gradient(90deg, var(--buyer), #60a5fa); }}
  .bar-fill.winner {{ background: linear-gradient(90deg, var(--winner), #34d399); }}
  .bar-value {{ width: 80px; font-size: 12px; font-family: monospace; font-weight: 600; text-align: right; flex-shrink: 0; }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .tab {{ padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; border: 1px solid var(--border); background: transparent; color: var(--muted); transition: all 0.2s; }}
  .tab.active {{ background: var(--buyer); color: white; border-color: var(--buyer); }}
  .tab:hover {{ border-color: var(--muted); }}
  .scroll-table {{ max-height: 600px; overflow-y: auto; }}
  .hidden {{ display: none; }}
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 32px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🏛️ Entity Ranking Dashboard</h1>
  <p class="subtitle">Portuguese Public Procurement — Top {top_n} Buyers vs Winners by Contract Value</p>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="label">Total Entities</div>
      <div class="value">{stats.get('total_entities', 0):,}</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Buyer Value</div>
      <div class="value buyer">{fmt(total_buyer)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Winner Value</div>
      <div class="value winner">{fmt(total_winner)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Coverage Ratio</div>
      <div class="value">{(total_winner / total_buyer * 100) if total_buyer else 0:.1f}%</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="section">
      <div class="section-title"><span class="dot buyer"></span> Top 10 Buyers (Adjudicantes)</div>
      {buyer_bars}
    </div>
    <div class="section">
      <div class="section-title"><span class="dot winner"></span> Top 10 Winners (Adjudicatários)</div>
      {winner_bars}
    </div>
  </div>

  <div class="section">
    <div class="section-title">📊 Buyer vs Winner — Value Distribution</div>
    <div class="chart-container">
      <canvas id="comparisonChart"></canvas>
    </div>
  </div>

  <div class="section">
    <div class="tabs">
      <div class="tab active" onclick="showTab('buyers')">🏛️ Top Buyers</div>
      <div class="tab" onclick="showTab('winners')">🏢 Top Winners</div>
    </div>
    <div id="buyers-panel">
      <div class="scroll-table">
        <table>
          <thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Contracts</th><th>Buyer Value</th><th>Winner Value</th></tr></thead>
          <tbody>{buyer_rows}</tbody>
        </table>
      </div>
    </div>
    <div id="winners-panel" class="hidden">
      <div class="scroll-table">
        <table>
          <thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Contracts</th><th>Winner Value</th><th>Buyer Value</th></tr></thead>
          <tbody>{winner_rows}</tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="footer">
    Generated from procurement.db (111K+ entities) — dados.gov.pt / Portal BASE IMPIC
  </div>
</div>

<script>
function showTab(tab) {{
  document.getElementById('buyers-panel').classList.toggle('hidden', tab !== 'buyers');
  document.getElementById('winners-panel').classList.toggle('hidden', tab !== 'winners');
  document.querySelectorAll('.tab').forEach((t, i) => {{
    t.classList.toggle('active', (tab === 'buyers' && i === 0) || (tab === 'winners' && i === 1));
  }});
}}

const ctx = document.getElementById('comparisonChart').getContext('2d');
new Chart(ctx, {{
  type: 'bar',
  data: {{
    labels: {buyer_labels},
    datasets: [
      {{
        label: 'Buyer Value',
        data: {buyer_values},
        backgroundColor: 'rgba(37, 99, 235, 0.7)',
        borderColor: '#2563eb',
        borderWidth: 1,
        borderRadius: 4,
      }},
      {{
        label: 'Winner Value',
        data: {winner_values},
        backgroundColor: 'rgba(5, 150, 105, 0.7)',
        borderColor: '#059669',
        borderWidth: 1,
        borderRadius: 4,
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {{
      legend: {{ labels: {{ color: '#e2e8f0' }} }},
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            let v = ctx.raw;
            if (v >= 1e9) return ctx.dataset.label + ': €' + (v/1e9).toFixed(1) + 'B';
            if (v >= 1e6) return ctx.dataset.label + ': €' + (v/1e6).toFixed(1) + 'M';
            if (v >= 1e3) return ctx.dataset.label + ': €' + (v/1e3).toFixed(0) + 'K';
            return ctx.dataset.label + ': €' + v;
          }}
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{
          color: '#94a3b8',
          callback: function(v) {{
            if (v >= 1e9) return '€' + (v/1e9).toFixed(0) + 'B';
            if (v >= 1e6) return '€' + (v/1e6).toFixed(0) + 'M';
            return '€' + (v/1e3).toFixed(0) + 'K';
          }}
        }},
        grid: {{ color: 'rgba(255,255,255,0.05)' }}
      }},
      y: {{
        ticks: {{ color: '#e2e8f0', font: {{ size: 11 }} }},
        grid: {{ display: false }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate Entity Ranking Dashboard HTML",
    )
    parser.add_argument("--top", type=int, default=50, help="Number of top entities (default 50)")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT), help="Output HTML path")
    args = parser.parse_args()

    print(f"Querying procurement.db for top {args.top} entities...")
    data = query_data(args.top)

    print(f"Generating HTML dashboard...")
    html = generate_html(data)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {out_path}")
    print(f"  Buyers: {len(data['buyers'])} entities")
    print(f"  Winners: {len(data['winners'])} entities")
    print(f"  Stats: {data['stats'].get('total_entities', 0):,} total entities")


if __name__ == "__main__":
    main()
