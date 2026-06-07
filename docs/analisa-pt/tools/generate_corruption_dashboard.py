#!/usr/bin/env python3
"""Comprehensive Corruption Dashboard Generator

Generates a standalone HTML dashboard integrating:
  1. Price Gap Analysis (inflation between base and final contract values)
  2. Entity Network Self-Referencing (same entity as buyer and seller)
  3. Spending Concentration (buyer heavily dependent on single seller)
  4. Entity Rankings (top buyers vs winners)
  5. TED Compliance Gap (contracts above threshold vs TED coverage)

Usage:
    python generate_corruption_dashboard.py
    python generate_corruption_dashboard.py --top 30
    python generate_corruption_dashboard.py -o corruption.html
"""

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
TED_DB = DATA_DIR / "ted_notices.db"
DEFAULT_OUTPUT = DATA_DIR / "corruption_dashboard.html"


# =============================================================================
# DATA QUERIES
# =============================================================================

def query_all_data(top_n: int = 30) -> dict:
    """Query all corruption signals from procurement.db."""
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    conn.row_factory = sqlite3.Row
    data = {}

    # --- Overall Stats ---
    stats = conn.execute("""SELECT
        COUNT(*) as total_contracts,
        SUM(precoContratual) as total_value,
        COUNT(DISTINCT adjudicante_nif) as unique_buyers,
        SUM(CASE WHEN tipoprocedimento LIKE '%direto%' OR tipoprocedimento LIKE '%ajuste%' THEN 1 ELSE 0 END) as direct_awards,
        SUM(CASE WHEN tipoprocedimento LIKE '%concurso%' THEN 1 ELSE 0 END) as public_tenders,
        SUM(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento THEN 1 ELSE 0 END) as inflated_count,
        SUM(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento THEN precoContratual - precoBaseProcedimento ELSE 0 END) as total_overrun,
        COUNT(CASE WHEN precoBaseProcedimento > 0 THEN 1 END) as with_base_price
        FROM contratos""").fetchone()
    data["stats"] = dict(stats) if stats else {}

    # --- Price Inflation: Top inflated contracts ---
    data["inflated_contracts"] = [dict(r) for r in conn.execute("""SELECT
        idcontrato, adjudicante_nif, adjudicante_nome, objectoContrato,
        adjudicatarios, precoBaseProcedimento, precoContratual,
        (precoContratual - precoBaseProcedimento) as overrun,
        ((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) as pct,
        tipoContrato, tipoprocedimento
        FROM contratos
        WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento
        ORDER BY overrun DESC LIMIT ?""", (top_n * 2,)).fetchall()]

    # --- Price Inflation by Municipality ---
    data["inflation_by_muni"] = [dict(r) for r in conn.execute("""SELECT
        adjudicante_nif, adjudicante_nome,
        COUNT(*) as total,
        SUM(CASE WHEN precoContratual > precoBaseProcedimento THEN 1 ELSE 0 END) as inflated,
        SUM(CASE WHEN precoContratual > precoBaseProcedimento THEN precoContratual - precoBaseProcedimento ELSE 0 END) as overrun
        FROM contratos
        WHERE precoBaseProcedimento > 0 AND precoContratual > 0
        GROUP BY adjudicante_nif HAVING total >= 3
        ORDER BY inflated * 1.0 / total DESC LIMIT ?""", (top_n,)).fetchall()]

    # --- Self-Referencing Entities ---
    self_ref = []
    rows = conn.execute("""SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
        precoContratual, objectoContrato, tipoContrato, dataCelebracaoContrato
        FROM contratos
        WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''
        AND adjudicante_nif IS NOT NULL AND adjudicante_nif != ''""").fetchall()
    for r in rows:
        adj_nif = r["adjudicante_nif"]
        adjt = str(r["adjudicatarios"] or "")
        if " - " not in adjt:
            continue
        for part in adjt.split(";"):
            part = part.strip()
            match = re.match(r"(\d{9})\s*-\s*(.+)", part)
            if match and match.group(1) == adj_nif:
                self_ref.append({
                    "nif": adj_nif, "buyer": r["adjudicante_nome"],
                    "seller": match.group(2).strip(),
                    "valor": r["precoContratual"] or 0,
                    "objeto": str(r["objectoContrato"] or "")[:100],
                    "tipo": str(r["tipoContrato"] or "")[:40],
                })
    data["self_referencing"] = self_ref

    # --- Spending Concentration ---
    buyer_totals = {}
    for r in conn.execute("""SELECT adjudicante_nif, adjudicante_nome, SUM(precoContratual) as total
        FROM contratos WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
        GROUP BY adjudicante_nif""").fetchall():
        buyer_totals[r["adjudicante_nif"]] = {"name": r["adjudicante_nome"], "total": r["total"] or 0}

    concentration = []
    for r in conn.execute("""SELECT adjudicante_nif, adjudicatarios,
        SUM(precoContratual) as pair_total, COUNT(*) as cnt
        FROM contratos
        WHERE adjudicante_nif IS NOT NULL AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
        GROUP BY adjudicante_nif, adjudicatarios ORDER BY pair_total DESC""").fetchall():
        bt = buyer_totals.get(r["adjudicante_nif"], {})
        bt_total = bt.get("total", 0)
        if bt_total > 0 and r["pair_total"] > 0:
            share = r["pair_total"] * 100.0 / bt_total
            if share >= 30 and r["pair_total"] >= 500000:
                concentration.append({
                    "buyer_nif": r["adjudicante_nif"], "buyer": bt.get("name", ""),
                    "seller": r["adjudicatarios"][:60], "share": share,
                    "contracts": r["cnt"], "value": r["pair_total"], "buyer_total": bt_total,
                })
    concentration.sort(key=lambda x: -x["value"])
    data["concentration"] = concentration[:top_n]

    # --- Top Buyers ---
    data["top_buyers"] = [dict(r) for r in conn.execute("""SELECT
        nifEntidade, desigEntidade, numContratos,
        totAdjudicanteValorContratIni, totValorContratIni
        FROM entidades WHERE totAdjudicanteValorContratIni > 0
        ORDER BY totAdjudicanteValorContratIni DESC LIMIT ?""", (top_n,)).fetchall()]

    # --- Top Winners ---
    data["top_winners"] = [dict(r) for r in conn.execute("""SELECT
        nifEntidade, desigEntidade, numContratos,
        totValorContratIni, totAdjudicanteValorContratIni
        FROM entidades WHERE totValorContratIni > 0
        ORDER BY totValorContratIni DESC LIMIT ?""", (top_n,)).fetchall()]

    # --- Procedure Breakdown ---
    data["procedures"] = [dict(r) for r in conn.execute("""SELECT
        tipoprocedimento, COUNT(*) as cnt, SUM(precoContratual) as total
        FROM contratos WHERE tipoprocedimento IS NOT NULL AND tipoprocedimento != ''
        GROUP BY tipoprocedimento ORDER BY cnt DESC LIMIT 10""").fetchall()]

    # --- Country mapping (NIF -> AliasPais) from entidades ---
    nif_to_country = {}
    for r in conn.execute("""SELECT nifEntidade, AliasPais FROM entidades
        WHERE AliasPais IS NOT NULL AND AliasPais != ''""").fetchall():
        nif_to_country[r["nifEntidade"]] = r["AliasPais"]
    data["nif_to_country"] = nif_to_country

    conn.close()
    data["ted_stats"] = _query_ted_compliance()
    return data


def _query_ted_compliance() -> dict:
    """Query TED compliance gap."""
    result = {"thresholds": [], "ted_total": 0}
    if not TED_DB.exists():
        return result
    ted_conn = sqlite3.connect(str(TED_DB))
    result["ted_total"] = ted_conn.execute("SELECT COUNT(*) FROM ted_notices").fetchone()[0]
    ted_conn.close()
    proc_conn = sqlite3.connect(str(PROCUREMENT_DB))
    for threshold, label in [(5538000, "Works >= €5.5M"), (143000, "Central Services >= €143K"), (221000, "Sub-central Services >= €221K")]:
        row = proc_conn.execute("SELECT COUNT(*), SUM(precoContratual) FROM contratos WHERE precoContratual >= ?", (threshold,)).fetchone()
        result["thresholds"].append({"label": label, "threshold": threshold, "count": row[0], "value": row[1] or 0})
    proc_conn.close()
    return result


# =============================================================================
# HELPERS
# =============================================================================

def classify_entity(name: str) -> str:
    """Classify an entity by name pattern into a type category."""
    if not name:
        return "other"
    n = name.lower()
    # Municipalities
    if "município" in n or ("câmara" in n and "municipal" in n):
        return "municipality"
    # Parish councils
    if "junta de freguesia" in n:
        return "parish"
    # Inter-municipal communities
    if "comunidade intermunicipal" in n or "comunidade urbana" in n:
        return "intermunicipal"
    # Health / Hospitals
    if any(k in n for k in ["hospital", "unidade local de saúde", "centro de saúde", "centro hospitalar"]):
        return "hospital"
    # Schools / Education
    if any(k in n for k in ["escola", "universidade", "instituto politécnico", "instituto superior"]):
        return "education"
    # Military / Security
    if any(k in n for k in ["forças armadas", "exército", "marinha", "força aérea", "g.n.r.", "psp", "polícia", "bombeiros", "segurança pública"]):
        return "security"
    # Central Government / Ministries
    if any(k in n for k in ["ministério", "república", "assembleia da república", "conselho de ministros"]):
        return "central_gov"
    # State Enterprises (E.P., E.M., S.A. with public keywords)
    if any(k in n for k in ["e.p.", "e.p.e."]):
        return "state_enterprise"
    if "e.m." in n:
        return "municipality"  # Empresa Municipal
    # Public Institutes (I.P.)
    if "i.p." in n:
        return "public_institute"
    # Transport
    if any(k in n for k in ["metro", "carris", "comboios", "ferrov", "transportes", "rodoviár"]):
        return "transport"
    # Energy / Water
    if any(k in n for k in ["electricidade", "águas", "gás", "energia", "ren - rede", "eda ", "eem "]):
        return "utility"
    # Ports / Airports
    if any(k in n for k in ["portos", "aeroportos", "nav"]):
        return "transport"
    # Private Companies
    if any(k in n for k in ["lda", "s.a.", "sociedade anónima", "unipessoal"]):
        return "company"
    return "other"


def esc(text):
    """Escape HTML special characters."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fmt(val):
    if val is None:
        return "€0"
    if val >= 1_000_000_000:
        return f"€{val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"€{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"€{val / 1_000:.0f}K"
    return f"€{val:.0f}"


def risk_color(score):
    if score >= 70:
        return "#dc2626"
    if score >= 40:
        return "#f59e0b"
    return "#22c55e"


def risk_label(score):
    if score >= 70:
        return "CRITICAL"
    if score >= 40:
        return "WARNING"
    return "LOW"


def _compute_risk_scores(data, top_n):
    """Compute composite risk scores for entities."""
    scores = defaultdict(lambda: {"name": "", "nif": "", "value": 0, "flags": 0, "details": []})

    for c in data.get("concentration", []):
        nif = c["buyer_nif"]
        s = scores[nif]
        s["name"] = c["buyer"]
        s["nif"] = nif
        s["value"] = max(s["value"], c["value"])
        if c["share"] >= 70:
            s["flags"] += 2
        elif c["share"] >= 50:
            s["flags"] += 1

    for c in data.get("self_referencing", []):
        nif = c["nif"]
        s = scores[nif]
        s["name"] = c["buyer"]
        s["nif"] = nif
        s["value"] = max(s["value"], c["valor"])
        s["flags"] += 3

    for m in data.get("inflation_by_muni", []):
        nif = m["adjudicante_nif"]
        rate = m["inflated"] * 100 / m["total"] if m["total"] else 0
        if rate >= 20:
            s = scores[nif]
            s["name"] = m["adjudicante_nome"]
            s["nif"] = nif
            s["value"] = max(s["value"], m["overrun"])
            s["flags"] += 2
        elif rate >= 10:
            s = scores[nif]
            s["name"] = m["adjudicante_nome"]
            s["nif"] = nif
            s["flags"] += 1

    top_buyer_nifs = {b["nifEntidade"] for b in data.get("top_buyers", [])[:top_n]}
    top_winner_nifs = {w["nifEntidade"] for w in data.get("top_winners", [])[:top_n]}
    for nif in top_buyer_nifs & top_winner_nifs:
        s = scores[nif]
        s["flags"] += 1
        for b in data.get("top_buyers", []):
            if b["nifEntidade"] == nif:
                s["name"] = b["desigEntidade"]
                s["nif"] = nif
                s["value"] = max(s["value"], b.get("totAdjudicanteValorContratIni") or 0)
                break

    result = [{"nif": k, "name": v["name"], "value": v["value"], "flags": v["flags"],
               "score": min(100, v["flags"] * 15)} for k, v in scores.items()]
    result.sort(key=lambda x: (-x["score"], -x["value"]))
    return result


# =============================================================================
# HTML GENERATION — uses string concatenation to avoid f-string brace issues
# =============================================================================

def generate_html(data, top_n=30):
    """Generate the comprehensive corruption dashboard HTML."""
    stats = data["stats"]
    tc = stats.get("total_contracts", 0)
    tv = stats.get("total_value", 0) or 0
    da = stats.get("direct_awards", 0) or 0
    ic = stats.get("inflated_count", 0) or 0
    to_val = stats.get("total_overrun", 0) or 0
    wb = stats.get("with_base_price", 0) or 1
    sr_count = len(data.get("self_referencing", []))
    sr_value = sum(c["valor"] for c in data.get("self_referencing", []))
    cc = len(data.get("concentration", []))
    ip = ic * 100 / wb if wb else 0
    dp = da * 100 / tc if tc else 0
    ted_total = data.get("ted_stats", {}).get("ted_total", 0)

    # Prepare chart data
    inflated = data.get("inflated_contracts", [])[:15]
    inf_labels = json.dumps([c["objectoContrato"][:40] if c["objectoContrato"] else f"#{c['idcontrato']}" for c in inflated])
    inf_values = json.dumps([c["overrun"] for c in inflated])

    inf_muni = data.get("inflation_by_muni", [])[:15]
    muni_labels = json.dumps([m["adjudicante_nome"][:35] if m["adjudicante_nome"] else "N/A" for m in inf_muni])
    muni_rates = json.dumps([round(m["inflated"] * 100 / m["total"], 1) if m["total"] else 0 for m in inf_muni])

    conc = data.get("concentration", [])[:10]
    conc_labels = json.dumps([c["buyer"][:30] if c["buyer"] else "N/A" for c in conc])
    conc_shares = json.dumps([round(c["share"], 1) for c in conc])
    conc_bg = json.dumps(['rgba(220,38,38,0.7)' if c['share'] >= 70 else 'rgba(245,158,11,0.7)' if c['share'] >= 50 else 'rgba(59,130,246,0.7)' for c in conc])
    conc_border = json.dumps(['#dc2626' if c['share'] >= 70 else '#f59e0b' if c['share'] >= 50 else '#3b82f6' for c in conc])

    buyers = data.get("top_buyers", [])[:10]
    winners = data.get("top_winners", [])[:10]
    buyer_labels = json.dumps([b["desigEntidade"][:30] if b["desigEntidade"] else "N/A" for b in buyers])
    buyer_values = json.dumps([b["totAdjudicanteValorContratIni"] for b in buyers])
    winner_labels = json.dumps([w["desigEntidade"][:30] if w["desigEntidade"] else "N/A" for w in winners])
    winner_values = json.dumps([w["totValorContratIni"] for w in winners])

    procs = data.get("procedures", [])[:8]
    proc_labels = json.dumps([p["tipoprocedimento"][:30] if p["tipoprocedimento"] else "N/A" for p in procs])
    proc_counts = json.dumps([p["cnt"] for p in procs])

    # --- Build table rows ---
    nif_to_country = data.get("nif_to_country", {})
    inflated_rows = []
    for i, c in enumerate(data.get("inflated_contracts", [])[:20], 1):
        sev = "critical" if c["pct"] > 20 else ("warning" if c["pct"] > 10 else "info")
        etype = classify_entity(c.get("adjudicante_nome", ""))
        ecountry = nif_to_country.get(c.get("adjudicante_nif", ""), "PT")
        inflated_rows.append(
            f'<tr class="severity-{sev}" data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td class="entity-name" title="{esc(c.get("adjudicante_nome",""))}">{esc(str(c.get("adjudicante_nome","N/A"))[:40])}</td>'
            f'<td class="entity-name" title="{esc(c.get("adjudicatarios",""))}">{esc(str(c.get("adjudicatarios","N/A"))[:40])}</td>'
            f'<td class="value">{fmt(c.get("precoBaseProcedimento",0))}</td>'
            f'<td class="value">{fmt(c.get("precoContratual",0))}</td>'
            f'<td class="value overrun">+{fmt(c.get("overrun",0))}</td>'
            f'<td class="pct"><span class="flag flag-{sev}">+{c["pct"]:.0f}%</span></td></tr>'
        )

    conc_rows = []
    for i, c in enumerate(data.get("concentration", [])[:20], 1):
        sev = "critical" if c["share"] >= 70 else ("warning" if c["share"] >= 50 else "info")
        etype = classify_entity(c["buyer"])
        ecountry = nif_to_country.get(c.get("buyer_nif", ""), "PT")
        conc_rows.append(
            f'<tr data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td class="entity-name" title="{esc(c["buyer"])}">{esc(str(c["buyer"])[:40])}</td>'
            f'<td class="entity-name" title="{esc(c["seller"])}">{esc(str(c["seller"])[:40])}</td>'
            f'<td class="pct"><span class="flag flag-{sev}">{c["share"]:.0f}%</span></td>'
            f'<td class="num">{c["contracts"]}</td>'
            f'<td class="value">{fmt(c["value"])}</td>'
            f'<td class="value muted">{fmt(c["buyer_total"])}</td></tr>'
        )

    self_ref_rows = []
    for i, c in enumerate(data.get("self_referencing", []), 1):
        etype = classify_entity(c.get("buyer", ""))
        ecountry = nif_to_country.get(c.get("nif", ""), "PT")
        self_ref_rows.append(
            f'<tr data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td class="entity-name">{esc(str(c.get("buyer","N/A"))[:50])}</td>'
            f'<td class="nif">{c["nif"]}</td>'
            f'<td class="value">{fmt(c["valor"])}</td>'
            f'<td>{esc(str(c.get("tipo",""))[:35])}</td>'
            f'<td class="objeto">{esc(str(c.get("objeto",""))[:60])}</td></tr>'
        )
    sr_table_body = "\n".join(self_ref_rows) if self_ref_rows else '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px;">No self-referencing entities detected</td></tr>'

    buyer_rows = []
    for i, b in enumerate(data.get("top_buyers", [])[:top_n], 1):
        bv = b.get("totAdjudicanteValorContratIni") or 0
        wv = b.get("totValorContratIni") or 0
        ratio = (wv / bv * 100) if bv else 0
        flag = f'<span class="flag flag-warning">{ratio:.0f}% as winner</span>' if ratio > 50 else ""
        etype = classify_entity(b.get("desigEntidade", ""))
        ecountry = nif_to_country.get(b.get("nifEntidade", ""), "PT")
        buyer_rows.append(
            f'<tr data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td class="entity-name" title="{esc(b.get("desigEntidade",""))}">{esc(str(b.get("desigEntidade","N/A"))[:50])}</td>'
            f'<td class="nif">{b.get("nifEntidade","")}</td>'
            f'<td class="num">{b.get("numContratos",0):,}</td>'
            f'<td class="value buyer">{fmt(bv)}</td>'
            f'<td class="value winner">{fmt(wv)}</td><td>{flag}</td></tr>'
        )

    winner_rows = []
    for i, w in enumerate(data.get("top_winners", [])[:top_n], 1):
        wv = w.get("totValorContratIni") or 0
        bv = w.get("totAdjudicanteValorContratIni") or 0
        ratio = (bv / wv * 100) if wv else 0
        flag = f'<span class="flag flag-warning">{ratio:.0f}% as buyer</span>' if ratio > 50 else ""
        etype = classify_entity(w.get("desigEntidade", ""))
        ecountry = nif_to_country.get(w.get("nifEntidade", ""), "PT")
        winner_rows.append(
            f'<tr data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td class="entity-name" title="{esc(w.get("desigEntidade",""))}">{esc(str(w.get("desigEntidade","N/A"))[:50])}</td>'
            f'<td class="nif">{w.get("nifEntidade","")}</td>'
            f'<td class="num">{w.get("numContratos",0):,}</td>'
            f'<td class="value winner">{fmt(wv)}</td>'
            f'<td class="value buyer">{fmt(bv)}</td><td>{flag}</td></tr>'
        )

    muni_rows = []
    for i, m in enumerate(data.get("inflation_by_muni", [])[:15], 1):
        rate = m["inflated"] * 100 / m["total"] if m["total"] else 0
        sev = "critical" if rate >= 30 else ("warning" if rate >= 15 else "info")
        etype = classify_entity(m.get("adjudicante_nome", ""))
        ecountry = nif_to_country.get(m.get("adjudicante_nif", ""), "PT")
        muni_rows.append(
            f'<tr data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td class="entity-name" title="{esc(m.get("adjudicante_nome",""))}">{esc(str(m.get("adjudicante_nome","N/A"))[:50])}</td>'
            f'<td class="num">{m["inflated"]}/{m["total"]}</td>'
            f'<td class="pct"><span class="flag flag-{sev}">{rate:.0f}%</span></td>'
            f'<td class="value overrun">{fmt(m["overrun"])}</td></tr>'
        )

    ted_rows = []
    for t in data.get("ted_stats", {}).get("thresholds", []):
        ted_rows.append(
            f'<div class="ted-row"><div class="ted-label">{t["label"]}</div>'
            f'<div class="ted-value">{t["count"]:,} contracts</div>'
            f'<div class="ted-amount">{fmt(t["value"])}</div>'
            f'<div class="ted-gap"><span class="flag flag-warning">TED DB: {ted_total} notices</span></div></div>'
        )

    proc_rows = []
    for p in data.get("procedures", [])[:8]:
        share = p["cnt"] * 100 / tc if tc else 0
        is_direct = "direto" in (p["tipoprocedimento"] or "").lower() or "ajuste" in (p["tipoprocedimento"] or "").lower()
        fc = "flag-warning" if is_direct else "flag-info"
        proc_rows.append(
            f'<tr><td>{esc(str(p.get("tipoprocedimento","N/A"))[:50])}</td>'
            f'<td class="num">{p["cnt"]:,}</td>'
            f'<td class="pct"><span class="flag {fc}">{share:.1f}%</span></td>'
            f'<td class="value">{fmt(p["total"])}</td></tr>'
        )

    risk_scores = _compute_risk_scores(data, top_n)
    risk_rows = []
    for i, r in enumerate(risk_scores[:20], 1):
        color = risk_color(r["score"])
        rl = risk_label(r["score"])
        rc = "critical" if r["score"] >= 70 else ("warning" if r["score"] >= 40 else "info")
        etype = classify_entity(r["name"])
        ecountry = nif_to_country.get(r.get("nif", ""), "PT")
        risk_rows.append(
            f'<tr data-etype="{etype}" data-country="{ecountry}"><td class="rank">{i}</td>'
            f'<td><div class="risk-bar"><div class="risk-fill" style="width:{r["score"]}%;background:{color}"></div></div>'
            f'<span class="risk-score">{r["score"]}</span></td>'
            f'<td class="entity-name">{esc(r["name"][:50])}</td>'
            f'<td class="nif">{r["nif"]}</td>'
            f'<td class="num">{r["flags"]}</td>'
            f'<td class="value">{fmt(r["value"])}</td>'
            f'<td><span class="flag flag-{rc}">{rl}</span></td></tr>'
        )

    # --- Assemble HTML using concatenation (no f-string braces for JS) ---
    parts = []
    parts.append('<!DOCTYPE html>\n<html lang="pt">\n<head>\n<meta charset="UTF-8">\n')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
    parts.append('<title>Corruption Detection Dashboard — Analisa.pt</title>\n')
    parts.append('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n')
    parts.append(CSS_TEMPLATE)
    parts.append('<body>\n<div class="container">\n')

    # Header
    parts.append(f'<div class="header"><h1>🛡️ Corruption Detection Dashboard</h1>')
    parts.append(f'<p class="subtitle">Comprehensive procurement anomaly analysis — {tc:,} contracts, {fmt(tv)} total value — Analisa.pt</p></div>\n')

    # Entity type filter bar
    # Count entities by type across all data sources
    etype_counts = {}
    all_names = []
    for c in data.get("inflated_contracts", []):
        all_names.append(c.get("adjudicante_nome", ""))
    for c in data.get("concentration", []):
        all_names.append(c.get("buyer", ""))
    for c in data.get("self_referencing", []):
        all_names.append(c.get("buyer", ""))
    for b in data.get("top_buyers", []):
        all_names.append(b.get("desigEntidade", ""))
    for w in data.get("top_winners", []):
        all_names.append(w.get("desigEntidade", ""))
    for m in data.get("inflation_by_muni", []):
        all_names.append(m.get("adjudicante_nome", ""))
    for n in all_names:
        et = classify_entity(n)
        etype_counts[et] = etype_counts.get(et, 0) + 1

    # Entity type labels and icons
    etype_meta = {
        "municipality": ("🏛️", "Municipalities"),
        "hospital": ("🏥", "Hospitals"),
        "education": ("🎓", "Education"),
        "central_gov": ("🏢", "Central Gov"),
        "state_enterprise": ("🏗️", "State Enterprises"),
        "public_institute": ("📋", "Public Institutes"),
        "company": ("💼", "Companies"),
        "security": ("🛡️", "Security"),
        "transport": ("🚂", "Transport"),
        "utility": ("⚡", "Utilities"),
        "parish": ("🏘️", "Parishes"),
        "intermunicipal": ("🌐", "Inter-municipal"),
        "other": ("❓", "Other"),
    }

    filter_buttons = []
    filter_buttons.append('<div class="filter-bar"><span class="filter-label">Filter by entity type:</span>')
    filter_buttons.append('<button class="filter-btn active" onclick="filterByType(\'all\')">All</button>')
    # Sort by count descending, skip types with 0 count
    sorted_types = sorted(etype_counts.items(), key=lambda x: -x[1])
    for etype, count in sorted_types:
        if count > 0 and etype in etype_meta:
            icon, label = etype_meta[etype]
            filter_buttons.append(f'<button class="filter-btn" onclick="filterByType(\'{etype}\')">{icon} {label} ({count})</button>')
    filter_buttons.append('</div>')
    filter_bar_html = "\n".join(filter_buttons)

    # Country filter bar
    nif_to_country = data.get("nif_to_country", {})
    country_counts = {}
    for nif in nif_to_country:
        ctry = nif_to_country[nif]
        country_counts[ctry] = country_counts.get(ctry, 0) + 1

    # Country name mapping (ISO codes to display names)
    COUNTRY_NAMES = {
        "PT": "Portugal", "ES": "Spain", "FR": "France", "DE": "Germany",
        "IT": "Italy", "GB": "United Kingdom", "NL": "Netherlands",
        "BE": "Belgium", "AT": "Austria", "IE": "Ireland",
        "SE": "Sweden", "DK": "Denmark", "FI": "Finland",
        "PL": "Poland", "CZ": "Czech Republic", "RO": "Romania",
        "US": "United States", "CN": "China",
        "JP": "Japan", "CH": "Switzerland", "NO": "Norway",
        "LU": "Luxembourg", "GR": "Greece", "HU": "Hungary",
        "BR": "Brazil", "CV": "Cape Verde", "AO": "Angola",
        "MZ": "Mozambique", "TL": "East Timor",
    }

    country_filter = []
    country_filter.append('<div class="filter-bar"><span class="filter-label">🌍 Filter by country:</span>')
    country_filter.append('<button class="filter-btn country-btn active" onclick="filterByCountry(\'all\')">All</button>')
    sorted_countries = sorted(country_counts.items(), key=lambda x: -x[1])
    for ctry, count in sorted_countries[:15]:
        display = COUNTRY_NAMES.get(ctry, ctry)
        country_filter.append(f'<button class="filter-btn country-btn" onclick="filterByCountry(\'{ctry}\')">{display} ({count})</button>')
    country_filter.append('</div>')
    country_filter_html = "\n".join(country_filter)

    # Stats grid
    parts.append(STATS_TEMPLATE.replace("{{TC}}", f"{tc:,}").replace("{{TV}}", fmt(tv))
                 .replace("{{IP}}", f"{ip:.1f}").replace("{{IC}}", f"{ic:,}")
                 .replace("{{TO}}", fmt(to_val)).replace("{{SR}}", str(sr_count))
                 .replace("{{CC}}", str(cc)).replace("{{DP}}", f"{dp:.1f}").replace("{{TT}}", str(ted_total)))

    parts.append(filter_bar_html)
    parts.append(country_filter_html)

    # Price Inflation
    parts.append(f'<div class="section"><div class="section-title"><span class="icon">📈</span> Price Inflation Analysis</div>')
    parts.append(f'<p style="color:var(--muted);margin-bottom:16px;font-size:13px;">Contracts where final price exceeds the announced base price. <strong>{ic:,}</strong> of {wb:,} contracts with base prices show inflation ({ip:.1f}%), with total overrun of <strong>{fmt(to_val)}</strong>.</p>')
    parts.append('<div class="grid-2"><div><h3 style="font-size:14px;color:var(--muted);margin-bottom:12px;">Top Inflated Contracts by Overrun Value</h3>')
    parts.append('<div class="chart-container tall"><canvas id="inflationChart"></canvas></div></div>')
    parts.append('<div><h3 style="font-size:14px;color:var(--muted);margin-bottom:12px;">Inflation Rate by Authority</h3>')
    parts.append('<div class="chart-container tall"><canvas id="muniInflationChart"></canvas></div></div></div></div>\n')

    # Inflated contracts table
    parts.append('<div class="section"><div class="section-title"><span class="icon">📋</span> Inflated Contracts — Detailed View</div>')
    parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Winner</th><th>Base Price</th><th>Final Price</th><th>Overrun</th><th>%</th></tr></thead><tbody>')
    parts.append("\n".join(inflated_rows))
    parts.append('</tbody></table></div></div>\n')

    # Inflation by authority table
    parts.append('<div class="section"><div class="section-title"><span class="icon">📍</span> Inflation by Authority</div>')
    parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Authority</th><th>Inflated/Total</th><th>Rate</th><th>Total Overrun</th></tr></thead><tbody>')
    parts.append("\n".join(muni_rows))
    parts.append('</tbody></table></div></div>\n')

    # Self-referencing
    parts.append(f'<div class="section"><div class="section-title"><span class="icon">🔄</span> Self-Referencing Entities</div>')
    parts.append(f'<p style="color:var(--muted);margin-bottom:16px;font-size:13px;">Entities appearing as <strong>both buyer and seller</strong> in the same contract. Found <strong>{sr_count}</strong> cases totaling <strong>{fmt(sr_value)}</strong>.</p>')
    parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Value</th><th>Type</th><th>Object</th></tr></thead><tbody>')
    parts.append(sr_table_body)
    parts.append('</tbody></table></div></div>\n')

    # Concentration
    parts.append(f'<div class="section"><div class="section-title"><span class="icon">🎯</span> Spending Concentration</div>')
    parts.append(f'<p style="color:var(--muted);margin-bottom:16px;font-size:13px;">Buyers where a single supplier accounts for ≥30% of total spending (≥€500K). <strong>{cc}</strong> high-concentration relationships detected.</p>')
    parts.append('<div class="grid-2"><div><h3 style="font-size:14px;color:var(--muted);margin-bottom:12px;">Concentration Rate by Buyer</h3>')
    parts.append('<div class="chart-container"><canvas id="concentrationChart"></canvas></div></div>')
    parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Top Supplier</th><th>Share</th><th>#</th><th>Value</th><th>Total</th></tr></thead><tbody>')
    parts.append("\n".join(conc_rows))
    parts.append('</tbody></table></div></div></div>\n')

    # Entity Rankings
    parts.append('<div class="section"><div class="section-title"><span class="icon">🏛️</span> Entity Rankings — Buyers vs Winners</div>')
    parts.append('<div class="tabs"><div class="tab active" onclick="showEntityTab(\'buyers\')">📊 Top Buyers</div>')
    parts.append('<div class="tab" onclick="showEntityTab(\'winners\')">📊 Top Winners</div>')
    parts.append('<div class="tab" onclick="showEntityTab(\'chart\')">📈 Comparison</div></div>')
    parts.append(f'<div id="buyers-panel"><div class="scroll-table"><table><thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Contracts</th><th>Buyer Value</th><th>Winner Value</th><th>Flags</th></tr></thead><tbody>')
    parts.append("\n".join(buyer_rows))
    parts.append('</tbody></table></div></div>')
    parts.append(f'<div id="winners-panel" class="hidden"><div class="scroll-table"><table><thead><tr><th>#</th><th>Entity</th><th>NIF</th><th>Contracts</th><th>Winner Value</th><th>Buyer Value</th><th>Flags</th></tr></thead><tbody>')
    parts.append("\n".join(winner_rows))
    parts.append('</tbody></table></div></div>')
    parts.append('<div id="chart-panel" class="hidden"><div class="chart-container tall"><canvas id="rankingChart"></canvas></div></div></div>\n')

    # Risk Scoring
    parts.append('<div class="section"><div class="section-title"><span class="icon">🎯</span> Composite Risk Scoring</div>')
    parts.append('<p style="color:var(--muted);margin-bottom:16px;font-size:13px;">Entities scored by combining: price inflation, spending concentration, self-referencing, and dual-role presence.</p>')
    parts.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Score</th><th>Entity</th><th>NIF</th><th>Signals</th><th>Value</th><th>Risk</th></tr></thead><tbody>')
    parts.append("\n".join(risk_rows))
    parts.append('</tbody></table></div></div>\n')

    # TED Compliance
    parts.append('<div class="section"><div class="section-title"><span class="icon">🇪🇺</span> TED Compliance Gap</div>')
    parts.append(f'<p style="color:var(--muted);margin-bottom:16px;font-size:13px;">Contracts above EU procurement thresholds that should appear in TED. Current TED database has <strong>{ted_total}</strong> notices (limited scope).</p>')
    parts.append("\n".join(ted_rows))
    parts.append('</div>\n')

    # Procedure Breakdown
    parts.append('<div class="section"><div class="section-title"><span class="icon">⚙️</span> Procurement Procedure Breakdown</div>')
    parts.append('<div class="grid-2"><div><div class="chart-container"><canvas id="procedureChart"></canvas></div></div>')
    parts.append('<div><table><thead><tr><th>Procedure</th><th>Contracts</th><th>Share</th><th>Value</th></tr></thead><tbody>')
    parts.append("\n".join(proc_rows))
    parts.append('</tbody></table></div></div></div>\n')

    # Footer
    parts.append(f'<div class="footer">Generated by generate_corruption_dashboard.py — Analisa.pt Corruption Detection<br>Data: procurement.db ({tc:,} contracts, {fmt(tv)}) + ted_notices.db ({ted_total} notices)</div>')
    parts.append('</div>\n')

    # JavaScript — plain string concatenation, NO f-string braces
    parts.append('<script>\n')
    parts.append(JAVASCRIPT_TEMPLATE
                 .replace("__INF_LABELS__", inf_labels)
                 .replace("__INF_VALUES__", inf_values)
                 .replace("__MUNI_LABELS__", muni_labels)
                 .replace("__MUNI_RATES__", muni_rates)
                 .replace("__CONC_LABELS__", conc_labels)
                 .replace("__CONC_SHARES__", conc_shares)
                 .replace("__CONC_BG__", conc_bg)
                 .replace("__CONC_BORDER__", conc_border)
                 .replace("__BUYER_LABELS__", buyer_labels)
                 .replace("__BUYER_VALUES__", buyer_values)
                 .replace("__WINNER_LABELS__", winner_labels)
                 .replace("__WINNER_VALUES__", winner_values)
                 .replace("__PROC_LABELS__", proc_labels)
                 .replace("__PROC_COUNTS__", proc_counts))

    parts.append('</script>\n</body>\n</html>')
    return "".join(parts)


# =============================================================================
# TEMPLATES — plain strings, no f-strings, no brace escaping needed
# =============================================================================

CSS_TEMPLATE = """<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --muted: #94a3b8;
    --border: #334155; --buyer: #2563eb; --winner: #059669;
    --danger: #dc2626; --warning: #f59e0b; --info: #3b82f6; --success: #22c55e;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
  .header { background: linear-gradient(135deg, #1e293b, #334155); padding: 32px; border-bottom: 3px solid var(--warning); margin-bottom: 24px; border-radius: 12px; }
  .header h1 { font-size: 28px; font-weight: 700; color: var(--warning); }
  .header .subtitle { color: var(--muted); margin-top: 8px; font-size: 14px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .stat-card { background: var(--card); border-radius: 12px; padding: 20px; border: 1px solid var(--border); text-align: center; transition: transform 0.2s; }
  .stat-card:hover { transform: translateY(-2px); }
  .stat-card.warning { border-color: var(--warning); }
  .stat-card.danger { border-color: var(--danger); }
  .stat-icon { font-size: 24px; margin-bottom: 8px; }
  .stat-value { font-size: 22px; font-weight: 700; color: var(--warning); }
  .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }
  .section { background: var(--card); border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid var(--border); }
  .section-title { font-size: 18px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
  .section-title .icon { font-size: 20px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 10px 12px; border-bottom: 2px solid var(--border); color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; background: var(--card); }
  td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
  tr:hover { background: rgba(255,255,255,0.03); }
  .rank { color: var(--muted); font-weight: 600; width: 40px; }
  .entity-name { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
  .nif { color: var(--muted); font-family: monospace; font-size: 12px; }
  .num { text-align: right; font-family: monospace; }
  .value { text-align: right; font-weight: 600; font-family: monospace; }
  .value.buyer { color: var(--buyer); }
  .value.winner { color: var(--winner); }
  .value.overrun { color: var(--danger); }
  .value.muted { color: var(--muted); font-weight: 400; }
  .pct { text-align: center; }
  .objeto { color: var(--muted); font-size: 12px; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .scroll-table { max-height: 500px; overflow-y: auto; }
  .flag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .flag-critical { background: var(--danger); color: white; }
  .flag-warning { background: var(--warning); color: #0f172a; }
  .flag-info { background: var(--info); color: white; }
  .severity-critical { background: rgba(220, 38, 38, 0.08); }
  .severity-warning { background: rgba(245, 158, 11, 0.05); }
  .chart-container { position: relative; height: 400px; }
  .chart-container.tall { height: 500px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  .tab { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; border: 1px solid var(--border); background: transparent; color: var(--muted); transition: all 0.2s; }
  .tab.active { background: var(--buyer); color: white; border-color: var(--buyer); }
  .tab:hover { border-color: var(--muted); }
  .hidden { display: none; }
  .risk-bar { display: inline-block; height: 8px; border-radius: 4px; background: var(--bg); width: 80px; vertical-align: middle; margin-right: 8px; }
  .risk-fill { height: 100%; border-radius: 4px; }
  .risk-score { font-family: monospace; font-weight: 600; font-size: 12px; }
  .ted-row { display: flex; align-items: center; gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--border); }
  .ted-row:last-child { border-bottom: none; }
  .ted-label { flex: 1; font-weight: 500; }
  .ted-value { font-family: monospace; font-weight: 600; min-width: 120px; }
  .ted-amount { font-family: monospace; color: var(--muted); min-width: 100px; }
  .footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 32px; padding: 16px; border-top: 1px solid var(--border); }
  .filter-bar { display: flex; align-items: center; gap: 8px; padding: 12px 20px; background: var(--card); border-radius: 12px; border: 1px solid var(--border); margin-bottom: 24px; flex-wrap: wrap; }
  .filter-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 4px; white-space: nowrap; }
  .filter-btn { padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 500; border: 1px solid var(--border); background: transparent; color: var(--muted); transition: all 0.2s; white-space: nowrap; }
  .filter-btn:hover { border-color: var(--muted); color: var(--text); }
  .filter-btn.active { background: var(--warning); color: #0f172a; border-color: var(--warning); font-weight: 600; }
</style>
"""

STATS_TEMPLATE = """<div class="stats-grid">
  <div class="stat-card"><div class="stat-icon">📊</div><div class="stat-value">{{TC}}</div><div class="stat-label">Total Contracts</div></div>
  <div class="stat-card"><div class="stat-icon">💰</div><div class="stat-value">{{TV}}</div><div class="stat-label">Total Value</div></div>
  <div class="stat-card warning"><div class="stat-icon">📈</div><div class="stat-value">{{IP}}%</div><div class="stat-label">Price Inflation Rate ({{IC}} contracts)</div></div>
  <div class="stat-card danger"><div class="stat-icon">⚠️</div><div class="stat-value">{{TO}}</div><div class="stat-label">Total Price Overrun</div></div>
  <div class="stat-card warning"><div class="stat-icon">🔄</div><div class="stat-value">{{SR}}</div><div class="stat-label">Self-Referencing Cases</div></div>
  <div class="stat-card"><div class="stat-icon">🎯</div><div class="stat-value">{{CC}}</div><div class="stat-label">High Concentration Alerts</div></div>
  <div class="stat-card danger"><div class="stat-icon">🏗️</div><div class="stat-value">{{DP}}%</div><div class="stat-label">Direct Award Rate</div></div>
  <div class="stat-card"><div class="stat-icon">🏛️</div><div class="stat-value">{{TT}}</div><div class="stat-label">TED Notices in DB</div></div>
</div>
"""

JAVASCRIPT_TEMPLATE = """// Entity type filtering
let activeFilter = 'all';
function filterByType(etype) {
  activeFilter = etype;
  // Update entity type button states
  document.querySelectorAll('.filter-btn:not(.country-btn)').forEach(btn => {
    const isAll = etype === 'all' && btn.textContent.trim() === 'All';
    const isMatch = btn.getAttribute('onclick') && btn.getAttribute('onclick').includes("'" + etype + "'");
    btn.classList.toggle('active', isAll || isMatch);
  });
  applyFilters();
}

// Country filtering
let activeCountry = 'all';
function filterByCountry(country) {
  activeCountry = country;
  // Update country button states
  document.querySelectorAll('.country-btn').forEach(btn => {
    const isAll = country === 'all' && btn.textContent.trim() === 'All';
    const isMatch = btn.getAttribute('onclick') && btn.getAttribute('onclick').includes("'" + country + "'");
    btn.classList.toggle('active', isAll || isMatch);
  });
  applyFilters();
}

// Compose both entity type and country filters
function applyFilters() {
  document.querySelectorAll('tr[data-etype]').forEach(row => {
    const etypeMatch = activeFilter === 'all' || row.getAttribute('data-etype') === activeFilter;
    const countryMatch = activeCountry === 'all' || row.getAttribute('data-country') === activeCountry;
    row.style.display = (etypeMatch && countryMatch) ? '' : 'none';
  });
  // Update visible row numbers
  document.querySelectorAll('table tbody').forEach(tbody => {
    let rank = 0;
    tbody.querySelectorAll('tr[data-etype]').forEach(row => {
      if (row.style.display !== 'none') {
        rank++;
        const rankCell = row.querySelector('.rank');
        if (rankCell) rankCell.textContent = rank;
      }
    });
  });
}

function showEntityTab(tab) {
  document.getElementById('buyers-panel').classList.toggle('hidden', tab !== 'buyers');
  document.getElementById('winners-panel').classList.toggle('hidden', tab !== 'winners');
  document.getElementById('chart-panel').classList.toggle('hidden', tab !== 'chart');
  document.querySelectorAll('.tabs .tab').forEach((t, i) => {
    t.classList.toggle('active', (tab === 'buyers' && i === 0) || (tab === 'winners' && i === 1) || (tab === 'chart' && i === 2));
  });
}

Chart.defaults.color = '#e2e8f0';
Chart.defaults.borderColor = 'rgba(255,255,255,0.05)';

// 1. Inflation Chart
new Chart(document.getElementById('inflationChart'), {
  type: 'bar',
  data: {
    labels: __INF_LABELS__,
    datasets: [{
      label: 'Overrun Value',
      data: __INF_VALUES__,
      backgroundColor: 'rgba(220, 38, 38, 0.7)',
      borderColor: '#dc2626',
      borderWidth: 1,
      borderRadius: 4,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
    plugins: { legend: { display: false },
      tooltip: { callbacks: { label: function(ctx) {
        let v = ctx.raw;
        if (v >= 1e6) return '\\u20ac' + (v/1e6).toFixed(1) + 'M';
        return '\\u20ac' + (v/1e3).toFixed(0) + 'K';
      }}}
    },
    scales: {
      x: { ticks: { callback: function(v) { return v >= 1e6 ? '\\u20ac'+(v/1e6).toFixed(0)+'M' : '\\u20ac'+(v/1e3).toFixed(0)+'K'; }}, grid: { color: 'rgba(255,255,255,0.05)' }}},
      y: { ticks: { font: { size: 10 }}, grid: { display: false }}
    }
  }
});

// 2. Municipality Inflation Rate
new Chart(document.getElementById('muniInflationChart'), {
  type: 'bar',
  data: {
    labels: __MUNI_LABELS__,
    datasets: [{
      label: 'Inflation Rate (%)',
      data: __MUNI_RATES__,
      backgroundColor: 'rgba(245, 158, 11, 0.7)',
      borderColor: '#f59e0b',
      borderWidth: 1,
      borderRadius: 4,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
    plugins: { legend: { display: false }},
    scales: {
      x: { ticks: { callback: function(v) { return v + '%'; }}, grid: { color: 'rgba(255,255,255,0.05)' }, max: 100 },
      y: { ticks: { font: { size: 10 }}, grid: { display: false }}
    }
  }
});

// 3. Concentration Chart
new Chart(document.getElementById('concentrationChart'), {
  type: 'bar',
  data: {
    labels: __CONC_LABELS__,
    datasets: [{
      label: 'Concentration (%)',
      data: __CONC_SHARES__,
      backgroundColor: __CONC_BG__,
      borderColor: __CONC_BORDER__,
      borderWidth: 1,
      borderRadius: 4,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
    plugins: { legend: { display: false }},
    scales: {
      x: { ticks: { callback: function(v) { return v + '%'; }}, grid: { color: 'rgba(255,255,255,0.05)' }, max: 100 },
      y: { ticks: { font: { size: 10 }}, grid: { display: false }}
    }
  }
});

// 4. Entity Ranking
new Chart(document.getElementById('rankingChart'), {
  type: 'bar',
  data: {
    labels: __BUYER_LABELS__,
    datasets: [
      { label: 'Buyer Value', data: __BUYER_VALUES__, backgroundColor: 'rgba(37, 99, 235, 0.7)', borderColor: '#2563eb', borderWidth: 1, borderRadius: 4 },
      { label: 'Winner Value', data: __WINNER_VALUES__, backgroundColor: 'rgba(5, 150, 105, 0.7)', borderColor: '#059669', borderWidth: 1, borderRadius: 4 }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false, indexAxis: 'y',
    plugins: { legend: { labels: { color: '#e2e8f0' }},
      tooltip: { callbacks: { label: function(ctx) {
        let v = ctx.raw;
        if (v >= 1e9) return ctx.dataset.label + ': \\u20ac' + (v/1e9).toFixed(1) + 'B';
        if (v >= 1e6) return ctx.dataset.label + ': \\u20ac' + (v/1e6).toFixed(1) + 'M';
        return ctx.dataset.label + ': \\u20ac' + (v/1e3).toFixed(0) + 'K';
      }}}
    },
    scales: {
      x: { ticks: { callback: function(v) { return v >= 1e9 ? '\\u20ac'+(v/1e9).toFixed(0)+'B' : v >= 1e6 ? '\\u20ac'+(v/1e6).toFixed(0)+'M' : '\\u20ac'+(v/1e3).toFixed(0)+'K'; }}, grid: { color: 'rgba(255,255,255,0.05)' }}},
      y: { ticks: { font: { size: 11 }}, grid: { display: false }}
    }
  }
});

// 5. Procedure Breakdown
new Chart(document.getElementById('procedureChart'), {
  type: 'doughnut',
  data: {
    labels: __PROC_LABELS__,
    datasets: [{
      data: __PROC_COUNTS__,
      backgroundColor: ['#f59e0b', '#2563eb', '#059669', '#dc2626', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'],
      borderWidth: 0,
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { position: 'right', labels: { font: { size: 11 }, padding: 12, color: '#e2e8f0' }},
      tooltip: { callbacks: { label: function(ctx) {
        return ctx.label + ': ' + ctx.raw.toLocaleString() + ' contracts';
      }}}
    }
  }
});
"""


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate Comprehensive Corruption Dashboard")
    parser.add_argument("--top", type=int, default=30, help="Number of top entities (default 30)")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT), help="Output HTML path")
    args = parser.parse_args()

    print(f"Querying procurement.db for corruption signals (top {args.top})...")
    data = query_all_data(args.top)

    print("Generating comprehensive corruption dashboard...")
    html = generate_html(data, args.top)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    stats = data["stats"]
    tc = stats.get("total_contracts", 0)
    ic = stats.get("inflated_count", 0) or 0
    wb = stats.get("with_base_price", 0) or 1
    da = stats.get("direct_awards", 0) or 0
    print(f"\nDashboard written to {out_path}")
    print(f"  Total contracts: {tc:,}")
    print(f"  Price inflated: {ic:,} ({ic * 100 / wb:.1f}%)")
    print(f"  Self-referencing: {len(data.get('self_referencing', []))}")
    print(f"  Concentration alerts: {len(data.get('concentration', []))}")
    print(f"  Direct award rate: {da * 100 / tc:.1f}%")


if __name__ == "__main__":
    main()
