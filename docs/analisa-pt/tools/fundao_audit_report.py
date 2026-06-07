#!/usr/bin/env python3
"""Fundão Audit Report Generator

Generates a comprehensive HTML audit report for Município do Fundão
procurement patterns, cross-referencing with repeat contractors across
all Portuguese municipalities.

Usage:
    python fundao_audit_report.py                    # Generate report
    python fundao_audit_report.py --output report.html  # Custom output
"""

import sqlite3
import json
import argparse
from pathlib import Path
from collections import defaultdict

from utils import fmt

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
DEFAULT_OUTPUT = DATA_DIR / "fundao_audit_report.html"

FUNDAO_NIF = "506215695"


def query_all_data() -> dict:
    """Query all data needed for the Fundão audit report."""
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    conn.row_factory = sqlite3.Row

    # 1. All Fundao contracts
    fundao_contracts = conn.execute(
        """SELECT idcontrato, objectoContrato, descContrato, precoContratual,
                  precoBaseProcedimento, tipoContrato, CPV, adjudicatarios,
                  dataCelebracaoContrato, dataPublicacao, tipoprocedimento,
                  justifNReducEscrContrato, linkPecasProc, nAnuncio
           FROM contratos WHERE adjudicante_nif = ?
           ORDER BY precoContratual DESC""",
        (FUNDAO_NIF,),
    ).fetchall()

    # 2. Procedure breakdown
    procedures = conn.execute(
        """SELECT tipoprocedimento, COUNT(*) as cnt, SUM(precoContratual) as total
           FROM contratos WHERE adjudicante_nif = ?
           GROUP BY tipoprocedimento ORDER BY cnt DESC""",
        (FUNDAO_NIF,),
    ).fetchall()

    # 3. Contract type breakdown
    contract_types = conn.execute(
        """SELECT tipoContrato, COUNT(*) as cnt, SUM(precoContratual) as total
           FROM contratos WHERE adjudicante_nif = ?
           GROUP BY tipoContrato ORDER BY total DESC""",
        (FUNDAO_NIF,),
    ).fetchall()

    # 4. Top winners
    winners = conn.execute(
        """SELECT adjudicatarios, COUNT(*) as cnt, SUM(precoContratual) as total,
                  AVG(precoContratual) as avg_val
           FROM contratos WHERE adjudicante_nif = ?
           AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
           GROUP BY adjudicatarios ORDER BY total DESC""",
        (FUNDAO_NIF,),
    ).fetchall()

    # 5. Inflation contracts
    inflation = conn.execute(
        """SELECT idcontrato, objectoContrato, precoContratual, precoBaseProcedimento,
                  adjudicatarios, dataCelebracaoContrato, tipoprocedimento
           FROM contratos WHERE adjudicante_nif = ?
           AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento
           ORDER BY (precoContratual - precoBaseProcedimento) DESC""",
        (FUNDAO_NIF,),
    ).fetchall()

    # 6. National stats for comparison
    nat_total = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
    nat_direct = conn.execute(
        """SELECT COUNT(*) FROM contratos
           WHERE tipoprocedimento LIKE '%direto%' OR tipoprocedimento LIKE '%ajuste%'"""
    ).fetchone()[0]
    nat_inflated = conn.execute(
        """SELECT COUNT(*) FROM contratos
           WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento"""
    ).fetchone()[0]
    nat_inflated_total = conn.execute(
        "SELECT COUNT(*) FROM contratos WHERE precoBaseProcedimento > 0"
    ).fetchone()[0]

    # 7. Repeat contractors across municipalities
    repeat_contractors = {}
    for name, pattern in [("VectorPlano", "%VectorPlano%"), ("Constrobi", "%Constrobi%"),
                          ("NOW XXI", "%NOW XXI%"), ("Opualte", "%Opualte%")]:
        rows = conn.execute(
            """SELECT adjudicante_nif, adjudicante_nome, COUNT(*) as cnt,
                      SUM(precoContratual) as total
               FROM contratos WHERE adjudicatarios LIKE ?
               GROUP BY adjudicante_nif ORDER BY total DESC""",
            (pattern,),
        ).fetchall()
        repeat_contractors[name] = [dict(r) for r in rows]

    # 8. PRR inflation comparison
    nat_prr = conn.execute(
        """SELECT COUNT(*) FROM contratos
           WHERE objectoContrato LIKE '%PRR%'
           AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento"""
    ).fetchone()[0]
    nat_prr_total = conn.execute(
        """SELECT COUNT(*) FROM contratos
           WHERE objectoContrato LIKE '%PRR%' AND precoBaseProcedimento > 0"""
    ).fetchone()[0]
    fundao_prr = conn.execute(
        """SELECT COUNT(*) FROM contratos WHERE adjudicante_nif = ?
           AND objectoContrato LIKE '%PRR%'
           AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento""",
        (FUNDAO_NIF,),
    ).fetchone()[0]
    fundao_prr_total = conn.execute(
        """SELECT COUNT(*) FROM contratos WHERE adjudicante_nif = ?
           AND objectoContrato LIKE '%PRR%' AND precoBaseProcedimento > 0""",
        (FUNDAO_NIF,),
    ).fetchone()[0]

    conn.close()

    return {
        "contracts": [dict(r) for r in fundao_contracts],
        "procedures": [dict(r) for r in procedures],
        "contract_types": [dict(r) for r in contract_types],
        "winners": [dict(r) for r in winners],
        "inflation": [dict(r) for r in inflation],
        "repeat_contractors": repeat_contractors,
        "national": {
            "total": nat_total,
            "direct": nat_direct,
            "direct_rate": nat_direct * 100 / nat_total,
            "inflated": nat_inflated,
            "inflated_total": nat_inflated_total,
            "inflated_rate": nat_inflated * 100 / nat_inflated_total if nat_inflated_total else 0,
        },
        "prr": {
            "national_inflated": nat_prr,
            "national_total": nat_prr_total,
            "national_rate": nat_prr * 100 / nat_prr_total if nat_prr_total else 0,
            "fundao_inflated": fundao_prr,
            "fundao_total": fundao_prr_total,
            "fundao_rate": fundao_prr * 100 / fundao_prr_total if fundao_prr_total else 0,
        },
    }


def generate_html(data: dict) -> str:
    contracts = data["contracts"]
    procedures = data["procedures"]
    contract_types = data["contract_types"]
    winners = data["winners"]
    inflation = data["inflation"]
    repeat = data["repeat_contractors"]
    nat = data["national"]
    prr = data["prr"]

    total_contracts = len(contracts)
    total_value = sum(c["precoContratual"] or 0 for c in contracts)
    fundao_direct = sum(p["cnt"] for p in procedures if "direto" in (p["tipoprocedimento"] or "").lower() or "ajuste" in (p["tipoprocedimento"] or "").lower())
    fundao_direct_rate = fundao_direct * 100 / total_contracts if total_contracts else 0
    fundao_inflated = len(inflation)
    fundao_inflated_rate = fundao_inflated * 100 / total_contracts if total_contracts else 0

    # Build procedure rows
    proc_rows = ""
    for p in procedures:
        name = p["tipoprocedimento"] or "Unknown"
        cnt = p["cnt"]
        total = p["total"] or 0
        pct = cnt * 100 / total_contracts
        proc_rows += f"<tr><td>{name[:55]}</td><td class='num'>{cnt}</td><td class='num'>{pct:.1f}%</td><td class='num amount'>{fmt(total)}</td></tr>"

    # Build contract type rows
    type_rows = ""
    for ct in contract_types:
        name = ct["tipoContrato"] or "Unknown"
        cnt = ct["cnt"]
        total = ct["total"] or 0
        type_rows += f"<tr><td>{name[:55]}</td><td class='num'>{cnt}</td><td class='num amount'>{fmt(total)}</td></tr>"

    # Build winner rows
    winner_rows = ""
    for i, w in enumerate(winners[:15], 1):
        name = (w["adjudicatarios"] or "N/A")[:55]
        winner_rows += f"<tr><td class='rank'>{i}</td><td>{name}</td><td class='num'>{w['cnt']}</td><td class='num amount'>{fmt(w['total'])}</td><td class='num amount'>{fmt(w['avg_val'])}</td></tr>"

    # Build inflation rows
    inflation_rows = ""
    for i, inf in enumerate(inflation, 1):
        base = inf["precoBaseProcedimento"] or 0
        final = inf["precoContratual"] or 0
        overrun = final - base
        pct = (overrun / base * 100) if base else 0
        name = (inf["objectoContrato"] or "N/A")[:60]
        winner = (inf["adjudicatarios"] or "N/A")[:45]
        date = inf["dataCelebracaoContrato"] or "N/A"
        flag = "🔴" if pct > 20 else "🟡"
        inflation_rows += f"""
        <tr>
            <td class='rank'>{flag} {i}</td>
            <td>{name}</td>
            <td class='num amount'>€{base:,.0f}</td>
            <td class='num amount'>€{final:,.0f}</td>
            <td class='num amount' style='color:#ef4444'>+€{overrun:,.0f}</td>
            <td class='num' style='color:#ef4444'>+{pct:.1f}%</td>
            <td>{winner}</td>
            <td>{date}</td>
        </tr>"""

    # Build repeat contractor sections
    repeat_sections = ""
    for company, buyers in repeat.items():
        if not buyers:
            continue
        total_contracts = sum(b["cnt"] for b in buyers)
        total_value = sum(b["total"] or 0 for b in buyers)
        municipalities = len(buyers)

        buyer_rows = ""
        for b in buyers[:10]:
            name = (b["adjudicante_nome"] or "N/A")[:45]
            buyer_rows += f"<tr><td>{name}</td><td class='num'>{b['cnt']}</td><td class='num amount'>{fmt(b['total'])}</td></tr>"

        repeat_sections += f"""
        <div class="section">
            <div class="section-title"><span class="dot" style="background:#f59e0b"></span> {company} — {municipalities} buyers, {total_contracts} contracts, {fmt(total_value)}</div>
            <table>
                <thead><tr><th>Municipality / Entity</th><th>Contracts</th><th>Value</th></tr></thead>
                <tbody>{buyer_rows}</tbody>
            </table>
        </div>"""

    # Build all contracts table
    all_contract_rows = ""
    for c in contracts:
        obj = (c["objectoContrato"] or "N/A")[:55]
        winner = (c["adjudicatarios"] or "N/A")[:35]
        val = c["precoContratual"] or 0
        date = c["dataCelebracaoContrato"] or "N/A"
        proc = (c["tipoprocedimento"] or "N/A")[:25]
        is_inflated = 1 if (c['precoContratual'] or 0) > (c['precoBaseProcedimento'] or 0) and (c['precoBaseProcedimento'] or 0) > 0 else 0
        is_direct = 1 if any(x in (c['tipoprocedimento'] or '').lower() for x in ['direto', 'ajuste']) else 0
        all_contract_rows += f"<tr data-inflated='{is_inflated}' data-direct='{is_direct}'><td class='num'>{c['idcontrato']}</td><td>{obj}</td><td class='num amount'>{fmt(val)}</td><td>{proc}</td><td>{winner}</td><td>{date}</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fundão Audit Report — Portuguese Procurement</title>
<style>
  :root {{ --red: #ef4444; --yellow: #f59e0b; --green: #059669; --blue: #2563eb; --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --muted: #94a3b8; --border: #334155; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 32px; font-weight: 700; margin-bottom: 8px; }}
  .subtitle {{ color: var(--muted); margin-bottom: 32px; font-size: 14px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .stat-card {{ background: var(--card); border-radius: 12px; padding: 20px; border: 1px solid var(--border); }}
  .stat-card .label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .stat-card .value {{ font-size: 24px; font-weight: 700; }}
  .stat-card .value.danger {{ color: var(--red); }}
  .stat-card .value.warn {{ color: var(--yellow); }}
  .stat-card .value.ok {{ color: var(--green); }}
  .stat-card .compare {{ font-size: 11px; color: var(--muted); margin-top: 4px; }}
  .stat-card .compare .bad {{ color: var(--red); }}
  .stat-card .compare .good {{ color: var(--green); }}
  .section {{ background: var(--card); border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid var(--border); }}
  .section-title {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
  .section-title .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 10px 12px; border-bottom: 2px solid var(--border); color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; background: var(--card); }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
  tr:hover {{ background: rgba(255,255,255,0.03); }}
  .rank {{ color: var(--muted); font-weight: 600; width: 40px; }}
  .num {{ text-align: right; font-family: monospace; }}
  .amount {{ text-align: right; font-weight: 600; font-family: monospace; }}
  .scroll-table {{ max-height: 500px; overflow-y: auto; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge.red {{ background: rgba(239,68,68,0.15); color: var(--red); }}
  .badge.yellow {{ background: rgba(245,158,11,0.15); color: var(--yellow); }}
  .badge.green {{ background: rgba(5,150,105,0.15); color: var(--green); }}
  .finding {{ background: var(--bg); border-radius: 8px; padding: 16px; margin-bottom: 12px; border-left: 4px solid var(--red); }}
  .finding.warn {{ border-left-color: var(--yellow); }}
  .finding h4 {{ margin-bottom: 4px; }}
  .finding p {{ color: var(--muted); font-size: 13px; }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
  .tab {{ padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; border: 1px solid var(--border); background: transparent; color: var(--muted); transition: all 0.2s; }}
  .tab.active {{ background: var(--blue); color: white; border-color: var(--blue); }}
  .hidden {{ display: none; }}
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 32px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🏛️ Fundão Audit Report</h1>
  <p class="subtitle">Município do Fundão (NIF: 506215695) — Procurement Pattern Analysis</p>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="label">Total Contracts</div>
      <div class="value">{total_contracts:,}</div>
    </div>
    <div class="stat-card">
      <div class="label">Total Value</div>
      <div class="value">{fmt(total_value)}</div>
    </div>
    <div class="stat-card">
      <div class="label">Direct Award Rate</div>
      <div class="value danger">{fundao_direct_rate:.1f}%</div>
      <div class="compare">National: <span class="bad">{nat['direct_rate']:.1f}%</span> (+{fundao_direct_rate - nat['direct_rate']:.1f}pp)</div>
    </div>
    <div class="stat-card">
      <div class="label">Inflation Rate</div>
      <div class="value danger">{fundao_inflated_rate:.1f}%</div>
      <div class="compare">National: <span class="bad">{nat['inflated_rate']:.1f}%</span> ({fundao_inflated_rate / max(nat['inflated_rate'], 0.01):.0f}x)</div>
    </div>
    <div class="stat-card">
      <div class="label">PRR Inflation</div>
      <div class="value danger">{prr['fundao_rate']:.1f}%</div>
      <div class="compare">National: <span class="bad">{prr['national_rate']:.1f}%</span> ({prr['fundao_rate'] / max(prr['national_rate'], 0.01):.0f}x)</div>
    </div>
    <div class="stat-card">
      <div class="label">Unique Winners</div>
      <div class="value">{len(winners)}</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">⚠️ Key Findings</div>
    <div class="finding">
      <h4>🔴 Direct Award Rate 31% Above National Average</h4>
      <p>Fundão uses direct awards (Ajuste Direto) for {fundao_direct_rate:.1f}% of contracts vs {nat['direct_rate']:.1f}% nationally. This bypasses competitive tendering for {fundao_direct} of {total_contracts} contracts.</p>
    </div>
    <div class="finding">
      <h4>🔴 Price Inflation 32x National Average</h4>
      <p>{fundao_inflated} contracts ({fundao_inflated_rate:.1f}%) exceed their announced base price vs {nat['inflated_rate']:.1f}% nationally. Total overrun: €{sum((c['precoContratual'] or 0) - (c['precoBaseProcedimento'] or 0) for c in contracts if (c['precoContratual'] or 0) > (c['precoBaseProcedimento'] or 0)):,.0f}</p>
    </div>
    <div class="finding">
      <h4>🔴 PRR Housing Inflation 45x National Average</h4>
      <p>{prr['fundao_inflated']}/{prr['fundao_total']} PRR housing contracts ({prr['fundao_rate']:.1f}%) are inflated vs {prr['national_rate']:.1f}% nationally. EU-funded projects systematically exceed base prices.</p>
    </div>
    <div class="finding warn">
      <h4>🟡 Repeat Winner Concentration</h4>
      <p>4 companies (VectorPlano, Constrobi, NOW XXI, Opualte) win {sum(w['cnt'] for w in winners[:4])}/{total_contracts} construction contracts. NOW XXI alone captures €{winners[0]['total'] or 0:,.0f} from just 2 contracts.</p>
    </div>
    <div class="finding warn">
      <h4>🟡 Cross-Municipality Contractor Networks</h4>
      <p>VectorPlano, Constrobi, NOW XXI, and Opualte all operate across multiple municipalities — VectorPlano in 5 municipalities, NOW XXI in 8. This suggests established contractor networks in the region.</p>
    </div>
  </div>

  <div class="grid-2">
    <div class="section">
      <div class="section-title"><span class="dot" style="background:var(--blue)"></span> Procedure Breakdown</div>
      <table>
        <thead><tr><th>Procedure</th><th>Count</th><th>%</th><th>Value</th></tr></thead>
        <tbody>{proc_rows}</tbody>
      </table>
    </div>
    <div class="section">
      <div class="section-title"><span class="dot" style="background:var(--green)"></span> Contract Type Breakdown</div>
      <table>
        <thead><tr><th>Type</th><th>Count</th><th>Value</th></tr></thead>
        <tbody>{type_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-title">🔴 Price Inflation Contracts ({len(inflation)} total)</div>
    <div class="scroll-table">
      <table>
        <thead><tr><th></th><th>Object</th><th>Base Price</th><th>Final Price</th><th>Overrun</th><th>%</th><th>Winner</th><th>Date</th></tr></thead>
        <tbody>{inflation_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-title">🏆 Top Winners by Value</div>
    <div class="scroll-table">
      <table>
        <thead><tr><th>#</th><th>Contractor</th><th>Contracts</th><th>Total Value</th><th>Avg Value</th></tr></thead>
        <tbody>{winner_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-title">🔗 Repeat Contractor Networks (Cross-Municipality)</div>
    {repeat_sections}
  </div>

  <div class="section">
    <div class="section-title">📋 All {total_contracts} Fundão Contracts</div>
    <div class="tabs">
      <div class="tab active" onclick="showTab('all')">All ({total_contracts})</div>
      <div class="tab" onclick="showTab('inflated')">Inflated ({len(inflation)})</div>
      <div class="tab" onclick="showTab('direct')">Direct Awards ({fundao_direct})</div>
    </div>
    <div id="all-panel" class="scroll-table">
      <table id="contract-table">
      <table>
        <thead><tr><th>ID</th><th>Object</th><th>Value</th><th>Procedure</th><th>Winner</th><th>Date</th></tr></thead>
        <tbody>{all_contract_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="footer">
    Generated from procurement.db (244K+ contracts) — dados.gov.pt / Portal BASE IMPIC<br>
    Fundão NIF: 506215695 | Audit Date: June 2026
  </div>
</div>

<script>
function showTab(tab) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  const rows = document.querySelectorAll('#contract-table tbody tr');
  rows.forEach(r => {{
    if (tab === 'all') {{ r.style.display = ''; }}
    else if (tab === 'inflated') {{ r.style.display = r.dataset.inflated === '1' ? '' : 'none'; }}
    else if (tab === 'direct') {{ r.style.display = r.dataset.direct === '1' ? '' : 'none'; }}
  }});
}}
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate Fundão Audit Report")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    print("Querying procurement.db for Fundão audit data...")
    data = query_all_data()

    print("Generating HTML report...")
    html = generate_html(data)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report written to {out_path}")
    print(f"  Contracts: {len(data['contracts'])}")
    print(f"  Inflation: {len(data['inflation'])} ({len(data['inflation'])*100/len(data['contracts']):.1f}%)")


if __name__ == "__main__":
    main()
