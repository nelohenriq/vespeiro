#!/usr/bin/env python3
"""Generate interactive HTML dashboard for Municipality Risk Report.

Produces a self-contained HTML file with:
- Risk ranking table with sorting
- Concentration vs Inflation scatter plot
- Risk signal radar charts
- Detailed breakdown cards for top municipalities

Usage:
    python generate_municipality_dashboard.py
    python generate_municipality_dashboard.py --top 30
    python generate_municipality_dashboard.py --output data/municipality_risk.html
"""

import json
import argparse
from pathlib import Path
from municipality_risk_report import scan_municipalities

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DEFAULT = SCRIPT_DIR / "data" / "municipality_risk_dashboard.html"

CSS = """
:root {
  --bg: #0f1117; --surface: #1a1d29; --surface2: #252836;
  --border: #2d3148; --text: #e1e4ed; --text2: #8b8fa3;
  --accent: #6366f1; --red: #ef4444; --yellow: #eab308; --green: #22c55e;
  --blue: #3b82f6; --purple: #a855f7;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg); color: var(--text); font-family: 'Inter', -apple-system, system-ui, sans-serif; line-height: 1.6; }
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }
h1 { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
h2 { font-size: 20px; font-weight: 600; margin-bottom: 16px; color: var(--accent); }
h3 { font-size: 16px; font-weight: 600; margin-bottom: 12px; }
.subtitle { color: var(--text2); font-size: 14px; margin-bottom: 24px; }
.grid { display: grid; gap: 20px; margin-bottom: 24px; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-label { font-size: 12px; color: var(--text2); text-transform: uppercase; letter-spacing: 1px; }
.stat-red { color: var(--red); }
.stat-yellow { color: var(--yellow); }
.stat-green { color: var(--green); }
.stat-blue { color: var(--blue); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 10px 8px; border-bottom: 2px solid var(--border); color: var(--text2); font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }
th:hover { color: var(--accent); }
td { padding: 10px 8px; border-bottom: 1px solid var(--border); }
tr:hover { background: var(--surface2); }
.risk-bar { height: 6px; border-radius: 3px; background: var(--border); position: relative; }
.risk-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.severity-critical { color: var(--red); font-weight: 600; }
.severity-warning { color: var(--yellow); }
.severity-ok { color: var(--green); }
.chart-container { position: relative; height: 350px; }
.detail-card { background: var(--surface2); border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.detail-score { font-size: 24px; font-weight: 700; }
.detail-signals { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.signal-badge { padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.badge-red { background: rgba(239,68,68,0.15); color: var(--red); }
.badge-yellow { background: rgba(234,179,8,0.15); color: var(--yellow); }
.badge-green { background: rgba(34,197,94,0.15); color: var(--green); }
.badge-blue { background: rgba(59,130,246,0.15); color: var(--blue); }
.signal-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); }
.signal-row:last-child { border-bottom: none; }
.signal-label { font-size: 13px; }
.signal-value { font-size: 13px; font-weight: 600; }
.tab-bar { display: flex; gap: 4px; margin-bottom: 20px; background: var(--surface); border-radius: 8px; padding: 4px; }
.tab-btn { padding: 8px 16px; border: none; background: transparent; color: var(--text2); cursor: pointer; border-radius: 6px; font-size: 13px; font-weight: 500; transition: all 0.2s; }
.tab-btn.active { background: var(--accent); color: white; }
.tab-btn:hover:not(.active) { background: var(--surface2); }
.tab-content { display: none; }
.tab-content.active { display: block; }
@media (max-width: 900px) { .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; } }
"""

JS = """
function initCharts(data) {
  // Scatter plot: Concentration vs Inflation
  const scatterCtx = document.getElementById('scatterChart').getContext('2d');
  new Chart(scatterCtx, {
    type: 'scatter',
    data: {
      datasets: [{
        label: 'Municipalities',
        data: data.map(d => ({x: d.top3_share, y: d.inflation_rate, r: Math.max(5, Math.sqrt(d.total_value / 1e6) * 3)})),
        backgroundColor: data.map(d => d.risk > 60 ? 'rgba(239,68,68,0.6)' : d.risk > 40 ? 'rgba(234,179,8,0.6)' : 'rgba(34,197,94,0.6)'),
        borderColor: data.map(d => d.risk > 60 ? '#ef4444' : d.risk > 40 ? '#eab308' : '#22c55e'),
        borderWidth: 1,
        pointRadius: data.map(d => Math.max(5, Math.sqrt(d.total_value / 1e6) * 3)),
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => {
          const d = data[ctx.dataIndex];
          return `${d.name}: Conc ${d.top3_share}%, Infl ${d.inflation_rate}%, Risk ${d.risk}`;
        }}}
      },
      scales: {
        x: { title: { display: true, text: 'Top 3 Supplier Share (%)', color: '#8b8fa3' }, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b8fa3' } },
        y: { title: { display: true, text: 'Inflation Rate (%)', color: '#8b8fa3' }, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b8fa3' } }
      }
    }
  });

  // Bar chart: Top 10 by risk score
  const top10 = data.slice(0, 10);
  const barCtx = document.getElementById('barChart').getContext('2d');
  new Chart(barCtx, {
    type: 'bar',
    data: {
      labels: top10.map(d => d.name.length > 25 ? d.name.substring(0, 25) + '...' : d.name),
      datasets: [
        { label: 'Concentration', data: top10.map(d => d.top3_share), backgroundColor: 'rgba(99,102,241,0.7)', borderRadius: 4 },
        { label: 'Inflation Rate', data: top10.map(d => d.inflation_rate), backgroundColor: 'rgba(239,68,68,0.7)', borderRadius: 4 },
        { label: 'Direct Award %', data: top10.map(d => d.direct_rate), backgroundColor: 'rgba(234,179,8,0.7)', borderRadius: 4 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: 'y',
      plugins: { legend: { labels: { color: '#8b8fa3' } } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b8fa3' } },
        y: { grid: { display: false }, ticks: { color: '#e1e4ed', font: { size: 11 } } }
      }
    }
  });

  // Risk distribution
  const distCtx = document.getElementById('distChart').getContext('2d');
  const bins = [0, 0, 0]; // low, medium, high
  data.forEach(d => { if (d.risk > 60) bins[2]++; else if (d.risk > 40) bins[1]++; else bins[0]++; });
  new Chart(distCtx, {
    type: 'doughnut',
    data: {
      labels: ['Low Risk (<40)', 'Medium Risk (40-60)', 'High Risk (>60)'],
      datasets: [{ data: bins, backgroundColor: ['rgba(34,197,94,0.7)', 'rgba(234,179,8,0.7)', 'rgba(239,68,68,0.7)'], borderWidth: 0 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: '#8b8fa3', padding: 16 } } }
    }
  });
}

function renderDetailCards(data) {
  const container = document.getElementById('detailCards');
  data.slice(0, 24).forEach((d, i) => {
    const riskClass = d.risk > 60 ? 'stat-red' : d.risk > 40 ? 'stat-yellow' : 'stat-green';
    const badges = [];
    if (d.top3_share > 60) badges.push('<span class="signal-badge badge-red">High Concentration</span>');
    if (d.inflated > 0) badges.push('<span class="signal-badge badge-red">Price Inflation</span>');
    if (d.direct_rate > 50) badges.push('<span class="signal-badge badge-yellow">High Direct Award</span>');
    if (d.exclusive_count > 0) badges.push('<span class="signal-badge badge-yellow">Exclusive Companies</span>');

    container.innerHTML += `
      <div class="detail-card">
        <div class="detail-header">
          <div>
            <h3>${d.name}</h3>
            <span style="color:var(--text2);font-size:12px">NIF: ${d.nif} | ${d.total_contracts} contracts | ${d.num_winners} winners</span>
          </div>
          <div class="detail-score ${riskClass}">${d.risk.toFixed(0)}</div>
        </div>
        <div class="detail-signals">${badges.join('')}</div>
        <div style="margin-top:12px">
          <div class="signal-row"><span class="signal-label">Concentration (Top 3)</span><span class="signal-value">${d.top3_share}%</span></div>
          <div class="signal-row"><span class="signal-label">Inflation Rate</span><span class="signal-value">${d.inflation_rate}%</span></div>
          <div class="signal-row"><span class="signal-label">Direct Award Rate</span><span class="signal-value">${d.direct_rate}%</span></div>
          <div class="signal-row"><span class="signal-label">Overrun Amount</span><span class="signal-value">${d.overrun >= 1e6 ? (d.overrun/1e6).toFixed(1)+'M' : d.overrun >= 1e3 ? (d.overrun/1e3).toFixed(0)+'K' : d.overrun.toFixed(0)} EUR</span></div>
          <div class="signal-row"><span class="signal-label">Exclusive Companies</span><span class="signal-value">${d.exclusive_count}</span></div>
          <div class="signal-row"><span class="signal-label">Top 3 Winners</span><span class="signal-value" style="font-size:11px;max-width:400px;text-align:right">${d.top3_names.join('; ')}</span></div>
        </div>
      </div>`;
  });
}

function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.tab).classList.add('active');
    });
  });
}

function initTableSort(data) {
  const tbody = document.getElementById('riskTableBody');
  const headers = document.querySelectorAll('th[data-sort]');
  headers.forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
      th.dataset.dir = dir;
      data.sort((a, b) => dir === 'asc' ? a[key] - b[key] : b[key] - a[key]);
      renderTable(data);
    });
  });
}

function renderTable(data) {
  const tbody = document.getElementById('riskTableBody');
  tbody.innerHTML = '';
  data.forEach((d, i) => {
    const riskClass = d.risk > 60 ? 'stat-red' : d.risk > 40 ? 'stat-yellow' : 'stat-green';
    tbody.innerHTML += `<tr>
      <td>${i+1}</td>
      <td class="${riskClass}">${d.risk.toFixed(0)}</td>
      <td>${d.top3_share}%</td>
      <td>${d.inflation_rate}%</td>
      <td>${d.inflated}</td>
      <td>${d.overrun >= 1e6 ? (d.overrun/1e6).toFixed(1)+'M' : d.overrun >= 1e3 ? (d.overrun/1e3).toFixed(0)+'K' : '0'} EUR</td>
      <td>${d.direct_rate}%</td>
      <td>${d.exclusive_count}</td>
      <td>${d.name}</td>
      <td style="font-size:11px">${d.top3_names.join('; ')}</td>
    </tr>`;
  });
}

window.addEventListener('DOMContentLoaded', () => {
  const data = __DATA__;
  initTabs();
  initTableSort(data);
  renderTable(data);
  renderDetailCards(data);
  initCharts(data);
});
"""


def generate_html(results, output_path):
    """Generate the HTML dashboard."""
    # Filter to dual-anomaly municipalities (concentration > 60% AND inflated > 0)
    dual = [r for r in results if r["top3_share"] >= 60 and r["inflated"] > 0]

    # Summary stats
    high = sum(1 for r in results if r["risk"] > 60)
    medium = sum(1 for r in results if 40 < r["risk"] <= 60)
    low = sum(1 for r in results if r["risk"] <= 40)
    total_overrun = sum(r["overrun"] for r in results)
    total_inflated = sum(r["inflated"] for r in results)

    data_json = json.dumps(results, ensure_ascii=False, default=str)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Municipality Procurement Risk Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>Municipality Procurement Risk Dashboard</h1>
  <p class="subtitle">Combined analysis of concentration, inflation, direct awards, exclusive companies, and BEP mismatch across {len(results)} municipalities</p>

  <div class="grid grid-4">
    <div class="card stat-card"><div class="stat-value stat-red">{high}</div><div class="stat-label">High Risk</div></div>
    <div class="card stat-card"><div class="stat-value stat-yellow">{medium}</div><div class="stat-label">Medium Risk</div></div>
    <div class="card stat-card"><div class="stat-value stat-green">{low}</div><div class="stat-label">Low Risk</div></div>
    <div class="card stat-card"><div class="stat-value stat-blue">{total_inflated}</div><div class="stat-label">Total Inflated Contracts</div></div>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" data-tab="tabCharts">Charts</button>
    <button class="tab-btn" data-tab="tabTable">Full Table</button>
    <button class="tab-btn" data-tab="tabDetails">Detail Cards</button>
  </div>

  <div id="tabCharts" class="tab-content active">
    <div class="grid grid-2">
      <div class="card"><h2>Concentration vs Inflation</h2><div class="chart-container"><canvas id="scatterChart"></canvas></div></div>
      <div class="card"><h2>Top 10 Risk Signals</h2><div class="chart-container"><canvas id="barChart"></canvas></div></div>
    </div>
    <div class="grid grid-3" style="margin-top:20px">
      <div class="card"><h2>Risk Distribution</h2><div class="chart-container"><canvas id="distChart"></canvas></div></div>
      <div class="card" style="grid-column: span 2">
        <h2>Dual-Anomaly Municipalities ({len(dual)})</h2>
        <p style="color:var(--text2);font-size:13px;margin-bottom:12px">Municipalities with BOTH high concentration (top3 >60%) AND price inflation — the true red flags</p>
        <table>
          <thead><tr><th>#</th><th>Risk</th><th>Conc%</th><th>Infl%</th><th>Overrun</th><th>Municipality</th></tr></thead>
          <tbody>
          {"".join(f'<tr><td>{i+1}</td><td class="{"stat-red" if d["risk"]>60 else "stat-yellow"}">{d["risk"]:.0f}</td><td>{d["top3_share"]}%</td><td>{d["inflation_rate"]}%</td><td>{"%.1fM" % (d["overrun"]/1e6) if d["overrun"]>=1e6 else "%.0fK" % (d["overrun"]/1e3)}</td><td>{d["name"]}</td></tr>' for i, d in enumerate(dual[:24]))}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div id="tabTable" class="tab-content">
    <div class="card">
      <h2>Full Risk Ranking ({len(results)} Municipalities)</h2>
      <p style="color:var(--text2);font-size:12px;margin-bottom:12px">Click column headers to sort</p>
      <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>#</th><th data-sort="risk">Risk</th><th data-sort="top3_share">Conc%</th>
          <th data-sort="inflation_rate">Infl%</th><th data-sort="inflated">Infl#</th>
          <th data-sort="overrun">Overrun</th><th data-sort="direct_rate">Direct%</th>
          <th data-sort="exclusive_count">Excl</th><th>Name</th><th>Top 3 Winners</th>
        </tr></thead>
        <tbody id="riskTableBody"></tbody>
      </table>
      </div>
    </div>
  </div>

  <div id="tabDetails" class="tab-content">
    <div class="card">
      <h2>Detailed Risk Breakdown — Top 24</h2>
      <div id="detailCards"></div>
    </div>
  </div>
</div>
<script>{JS.replace("__DATA__", data_json)}</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written to {output_path} ({len(html):,} bytes)")


def main():
    parser = argparse.ArgumentParser(description="Generate Municipality Risk Dashboard")
    parser.add_argument("--top", type=int, default=30, help="Top N municipalities")
    parser.add_argument("--output", "-o", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--min-contracts", type=int, default=5)
    args = parser.parse_args()

    results = scan_municipalities(min_contracts=args.min_contracts)
    generate_html(results, args.output)


if __name__ == "__main__":
    main()
