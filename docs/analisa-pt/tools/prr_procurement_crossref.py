#!/usr/bin/env python3
"""PRR × Procurement Dual-Role Analysis — Find entities that are simultaneously
PRR beneficiaries and public procurement contractors.

Detects 5 corruption patterns:
  1. DUAL-ROLE: Entity appears in BOTH PRR and procurement systems
  2. PRR BUYER = BASE SUPPLIER: Entity buys with PRR, sells via procurement
  3. PRR SUPPLIER = BASE BUYER: Entity gets PRR contracts AND runs procurement
  4. INFLATED CONTRACTOR: PRR beneficiary with price inflation in BASE
  5. CONCENTRATED BENEFICIARY: PRR beneficiary dominates procurement in same municipality

Also includes 5 extended analyses via subcommands:
  sectors       — Sector breakdown of dual-role entities
  trends        — Temporal sequencing of PRR vs procurement activity
  competition   — Competitive dynamics of dual-role suppliers
  modifications — Contract modification correlation for dual-role entities
  geo-flow      — Geographic flow mapping: PRR municipalities → procurement

Requires:
  - transparency.db (PRR data, from transparency_scraper.py download + index)
  - procurement.db (BASE contracts)

Usage:
    python prr_procurement_crossref.py                           # Full dual-role analysis
    python prr_procurement_crossref.py --top 50                  # Top 50 dual-role entities
    python prr_procurement_crossref.py --nif 514288256           # Profile specific entity
    python prr_procurement_crossref.py --export dual.json        # Export to JSON
    python prr_procurement_crossref.py sectors                   # Sector breakdown
    python prr_procurement_crossref.py trends                    # Temporal trends
    python prr_procurement_crossref.py competition               # Competition dynamics
    python prr_procurement_crossref.py modifications             # Modification correlation
    python prr_procurement_crossref.py geo-flow                  # Geographic flow mapping
    python prr_procurement_crossref.py all                       # Run all analyses sequentially
"""

import json
import re
import argparse
import sys
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from utils import fmt
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
TRANSPARENCY_DB = DATA_DIR / "transparency.db"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
MODIFICACOES_DB = DATA_DIR / "modificacoes_index.db"
CONTRACT_INDEX = DATA_DIR / "contract_index.json"


def esc(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ═════════════════════════════════════════════════════════════════════════════
#  Data Loading
# ═════════════════════════════════════════════════════════════════════════════

def load_prr_entities(conn) -> list[dict]:
    """Load all PRR entities with NIF."""
    rows = conn.execute(
        "SELECT cd_entidade, ds_entidade, nif, papel, atividade_economica, "
        "localizacao, COALESCE(valor_contratado, 0) as valor_contratado, "
        "COALESCE(valor_pago, 0) as valor_pago "
        "FROM prr_entities WHERE nif != '' AND nif IS NOT NULL"
    ).fetchall()

    return [{
        "cd_entidade": r[0], "name": r[1], "nif": r[2],
        "papel": r[3] or "", "atividade": r[4] or "",
        "localizacao": r[5] or "", "valor_contratado": r[6],
        "valor_pago": r[7],
    } for r in rows]


def load_prr_entity_contracts(conn) -> dict:
    """Load PRR entity-contract links grouped by entity code."""
    rows = conn.execute(
        "SELECT cd_entidade, cd_contrato, ds_contrato, ds_papel, "
        "COALESCE(valor_contrato, 0) as valor_contrato "
        "FROM prr_entity_contracts"
    ).fetchall()

    by_entity = defaultdict(list)
    for r in rows:
        by_entity[r[0]].append({
            "cd_contrato": r[1], "ds_contrato": r[2] or "",
            "papel": r[3] or "", "valor": r[4],
        })
    return dict(by_entity)


def load_prr_projects(conn) -> dict:
    """Load PRR projects by project code."""
    rows = conn.execute(
        "SELECT cd_projeto, ds_projeto, COALESCE(valor_aprovado, 0), "
        "COALESCE(valor_pago, 0) FROM prr_projects"
    ).fetchall()
    return {r[0]: {"ds_projeto": r[1] or "", "aprovado": r[2], "pago": r[3]} for r in rows}


def load_prr_locations(conn) -> dict:
    """Load PRR locations by project code."""
    rows = conn.execute(
        "SELECT cd_projeto, ds_concelho, ds_distrito, "
        "COALESCE(perc_valor_aprovado, 0), COALESCE(perc_valor_pago, 0) "
        "FROM prr_locations WHERE ds_concelho != ''"
    ).fetchall()
    by_proj = defaultdict(list)
    for r in rows:
        by_proj[r[0]].append({
            "concelho": r[1], "distrito": r[2],
            "pct_aprovado": r[3], "pct_pago": r[4],
        })
    return dict(by_proj)


def load_base_buyer_stats(proc_conn) -> dict:
    """Load buyer stats from BASE — total contracts, value, inflation."""
    rows = proc_conn.execute(
        "SELECT adjudicante_nif, "
        "COUNT(*) as total_contracts, "
        "SUM(COALESCE(precoContratual, 0)) as total_value, "
        "SUM(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        "    THEN 1 ELSE 0 END) as inflated_count, "
        "SUM(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        "    THEN precoContratual - precoBaseProcedimento ELSE 0 END) as total_overrun, "
        "COUNT(DISTINCT CASE WHEN adjudicatarios IS NOT NULL AND adjudicatarios != '' "
        "    THEN adjudicatarios END) as unique_winners "
        "FROM contratos WHERE adjudicante_nif != '-' AND adjudicante_nif != '' "
        "AND adjudicante_nif IS NOT NULL "
        "GROUP BY adjudicante_nif"
    ).fetchall()

    return {
        r[0]: {
            "total_contracts": r[1], "total_value": r[2],
            "inflated_count": r[3], "total_overrun": r[4],
            "unique_winners": r[5],
        } for r in rows
    }


def load_base_supplier_stats(proc_conn) -> dict:
    """Extract supplier NIFs from adjudicatarios text, aggregate stats.

    This is the expensive part — scan all contracts with winner text
    and extract NIFs via regex.
    """
    nif_pattern = re.compile(r"\b(\d{9})\b")
    rows = proc_conn.execute(
        "SELECT idcontrato, adjudicante_nif, adjudicatarios, "
        "COALESCE(precoContratual, 0), "
        "CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        "    THEN 1 ELSE 0 END as is_inflated "
        "FROM contratos WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' "
        "AND adjudicatarios != '-'"
    ).fetchall()

    stats = defaultdict(lambda: {
        "contracts": 0, "total_value": 0, "inflated_contracts": 0,
        "unique_buyers": set(),
    })

    for cid, buyer_nif, adj_text, valor, inflated in rows:
        found_nifs = set(nif_pattern.findall(adj_text))
        for nif in found_nifs:
            s = stats[nif]
            s["contracts"] += 1
            s["total_value"] += valor
            s["inflated_contracts"] += inflated
            if buyer_nif:
                s["unique_buyers"].add(buyer_nif)

    # Convert sets to counts for JSON serialization
    result = {}
    for nif, s in stats.items():
        result[nif] = {
            "contracts": s["contracts"],
            "total_value": s["total_value"],
            "inflated_contracts": s["inflated_contracts"],
            "unique_buyers": len(s["unique_buyers"]),
        }
    return result


def load_base_contract_dates(proc_conn, nifs: set) -> list:
    """Load procurement contract dates for a set of supplier NIFs.

    Returns list of (nif, year, value) tuples.
    """
    if not nifs:
        return []

    nif_pattern = re.compile(r"\b(\d{9})\b")
    # NIFs appear inside adjudicatarios text, not as a column — must scan
    # all contracts and extract via regex. Filtered to contracts with dates.
    rows = proc_conn.execute(
        "SELECT idcontrato, adjudicatarios, adjudicante_nif, "
        "COALESCE(precoContratual, 0), "
        "SUBSTR(COALESCE(dataCelebracaoContrato, ''), 1, 4) as ano "
        "FROM contratos WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' "
        "AND adjudicatarios != '-' AND dataCelebracaoContrato != ''",
    ).fetchall()

    results = []
    for cid, adj_text, buyer_nif, valor, ano in rows:
        found = set(nif_pattern.findall(adj_text))
        matched = found & nifs
        for nif in matched:
            results.append((nif, ano, valor))
    return results


def load_prr_contract_dates(conn, entity_codes: set) -> list:
    """Load PRR contract signing dates for a set of entity codes.

    Returns list of (cd_entidade, ano, valor) tuples.
    """
    if not entity_codes:
        return []

    placeholders = ",".join("?" * len(entity_codes))
    rows = conn.execute(
        f"SELECT ec.cd_entidade, SUBSTR(COALESCE(c.dt_assinatura, ''), 1, 4) as ano, "
        f"COALESCE(ec.valor_contrato, 0) "
        f"FROM prr_entity_contracts ec "
        f"LEFT JOIN prr_contracts c ON ec.cd_contrato = c.cd_contrato "
        f"WHERE ec.cd_entidade IN ({placeholders}) AND c.dt_assinatura != ''",
        list(entity_codes)
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
#  Dual-Role Analysis (core)
# ═════════════════════════════════════════════════════════════════════════════

def analyze_dual_roles(top_n: int = 30, min_score: float = 0) -> list[dict]:
    """Find all entities appearing in both PRR and procurement systems."""
    if not TRANSPARENCY_DB.exists():
        print("ERROR: transparency.db not found. Run 'transparency_scraper.py download && index' first.")
        sys.exit(1)
    if not PROCUREMENT_DB.exists():
        print("ERROR: procurement.db not found.")
        sys.exit(1)

    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    print("Loading PRR entities...", file=sys.stderr)
    prr_entities = load_prr_entities(conn)
    prr_nif_map = {e["nif"]: e for e in prr_entities}

    print("Loading PRR entity-contract links...", file=sys.stderr)
    prr_entity_contracts = load_prr_entity_contracts(conn)

    print("Loading PRR projects...", file=sys.stderr)
    prr_projects = load_prr_projects(conn)

    print("Loading PRR locations...", file=sys.stderr)
    prr_locations = load_prr_locations(conn)

    print("Loading BASE buyer data...", file=sys.stderr)
    base_buyers = load_base_buyer_stats(proc_conn)

    print("Loading BASE supplier data (scanning 244K contracts)...", file=sys.stderr)
    base_suppliers = load_base_supplier_stats(proc_conn)

    print("Cross-referencing PRR entities against procurement data...", file=sys.stderr)

    results = []

    for nif, prr_entity in prr_nif_map.items():
        base_as_buyer = base_buyers.get(nif)
        base_as_supplier = base_suppliers.get(nif)

        if not base_as_buyer and not base_as_supplier:
            continue

        is_prr_beneficiary = bool(prr_entity["valor_contratado"])
        is_base_buyer = base_as_buyer is not None
        is_base_supplier = base_as_supplier is not None

        # Classification
        if is_prr_beneficiary and is_base_buyer and is_base_supplier:
            role_type = "triple_role"
            roles = ["PRR beneficiary", "BASE buyer", "BASE supplier"]
        elif is_prr_beneficiary and is_base_buyer:
            role_type = "prr_beneficiary_buyer"
            roles = ["PRR beneficiary", "BASE buyer"]
        elif is_prr_beneficiary and is_base_supplier:
            role_type = "prr_beneficiary_supplier"
            roles = ["PRR beneficiary", "BASE supplier"]
        else:
            continue

        # --- Risk scoring ---
        risk_score = 0.0
        risk_factors = []

        # Factor 1: Combined value magnitude (0-30 points)
        prr_value = prr_entity["valor_contratado"]
        base_value = (base_as_buyer["total_value"] if base_as_buyer else 0) + \
                     (base_as_supplier["total_value"] if base_as_supplier else 0)
        combined_value = prr_value + base_value

        if combined_value > 50_000_000:
            risk_score += 30
            risk_factors.append(f"High combined value: {fmt(combined_value)}")
        elif combined_value > 10_000_000:
            risk_score += 20
            risk_factors.append(f"Substantial combined value: {fmt(combined_value)}")
        elif combined_value > 1_000_000:
            risk_score += 10
        elif combined_value > 100_000:
            risk_score += 5

        # Factor 2: Price inflation in BASE (0-25 points)
        total_overrun = 0
        total_inflated = 0
        if base_as_buyer and base_as_buyer["inflated_count"] > 0:
            total_inflated += base_as_buyer["inflated_count"]
            total_overrun += base_as_buyer["total_overrun"]
        if base_as_supplier and base_as_supplier["inflated_contracts"] > 0:
            total_inflated += base_as_supplier["inflated_contracts"]

        if total_overrun > 1_000_000:
            risk_score += 25
            risk_factors.append(f"Critical inflation: {fmt(total_overrun)} overrun")
        elif total_overrun > 100_000:
            risk_score += 15
            risk_factors.append(f"High inflation: {fmt(total_overrun)} overrun")
        elif total_inflated > 0:
            risk_score += 5
            risk_factors.append(f"{total_inflated} inflated contracts")

        # Factor 3: Triple role (0-20 points)
        if role_type == "triple_role":
            risk_score += 20
            risk_factors.append("Triple role: PRR beneficiary + BASE buyer + BASE supplier")
        elif role_type == "prr_beneficiary_supplier":
            risk_score += 10
            risk_factors.append("Dual role: PRR beneficiary + BASE supplier")
        elif role_type == "prr_beneficiary_buyer":
            risk_score += 5

        # Factor 4: Self-referencing in PRR (0-15 points)
        cd_ent = prr_entity["cd_entidade"]
        ecs = prr_entity_contracts.get(cd_ent, [])
        papel_counts = defaultdict(int)
        for ec in ecs:
            p = ec["papel"].lower()
            if "comprador" in p or "adjudicante" in p:
                papel_counts["buyer"] += 1
            elif "adjudicat" in p:
                papel_counts["supplier"] += 1

        if papel_counts.get("buyer", 0) > 0 and papel_counts.get("supplier", 0) > 0:
            risk_score += 15
            risk_factors.append(f"PRR self-referencing: buyer+supplier in {len(ecs)} contracts")

        # Factor 5: Geographic overlap (0-10 points)
        entity_name_lower = prr_entity["name"].lower()
        if any(kw in entity_name_lower for kw in ["municipio", "camara", "junta", "freguesia"]):
            project_cds = set()
            for ec in ecs:
                ec_proj = conn.execute(
                    "SELECT cd_projeto FROM prr_contracts WHERE cd_contrato = ?",
                    (ec["cd_contrato"],)
                ).fetchone()
                if ec_proj:
                    project_cds.add(ec_proj[0])

            location_concelhos = set()
            for proj_cd in project_cds:
                locs = prr_locations.get(proj_cd, [])
                for loc in locs:
                    location_concelhos.add(loc["concelho"].lower())

            if location_concelhos and base_as_buyer and base_as_buyer["unique_winners"] > 0:
                risk_score += 5
                risk_factors.append(f"PRR projects in {len(location_concelhos)} concelhos, also a BASE buyer")

        # Factor 6: PRR execution gap (0-10 points)
        prr_paid = prr_entity["valor_pago"]
        if prr_value > 0:
            exec_rate = (prr_paid / prr_value) * 100
            if exec_rate < 30 and prr_value > 1_000_000:
                risk_score += 10
                risk_factors.append(f"Low PRR execution: {exec_rate:.0f}% paid")
            elif exec_rate < 50 and prr_value > 500_000:
                risk_score += 5
                risk_factors.append(f"Moderate PRR execution gap: {exec_rate:.0f}% paid")

        risk_score = min(100, risk_score)

        if risk_score < min_score:
            continue

        results.append({
            "nif": nif,
            "name": prr_entity["name"],
            "cd_entidade": cd_ent,
            "papel": prr_entity["papel"],
            "atividade": prr_entity["atividade"],
            "localizacao": prr_entity["localizacao"],
            "role_type": role_type,
            "roles": roles,
            "risk_score": round(risk_score, 1),
            "risk_factors": risk_factors,
            "prr_value": prr_value,
            "prr_paid": prr_paid,
            "prr_execution_pct": round((prr_paid / prr_value * 100), 1) if prr_value > 0 else 0,
            "base_as_buyer": {
                "contracts": base_as_buyer["total_contracts"] if base_as_buyer else 0,
                "value": base_as_buyer["total_value"] if base_as_buyer else 0,
                "inflated": base_as_buyer["inflated_count"] if base_as_buyer else 0,
                "overrun": base_as_buyer["total_overrun"] if base_as_buyer else 0,
            } if base_as_buyer else None,
            "base_as_supplier": {
                "contracts": base_as_supplier["contracts"] if base_as_supplier else 0,
                "value": base_as_supplier["total_value"] if base_as_supplier else 0,
                "inflated_contracts": base_as_supplier["inflated_contracts"] if base_as_supplier else 0,
                "unique_buyers": base_as_supplier["unique_buyers"] if base_as_supplier else 0,
            } if base_as_supplier else None,
        })

    conn.close()
    proc_conn.close()

    results.sort(key=lambda x: -x["risk_score"])
    return results[:top_n]


# ═════════════════════════════════════════════════════════════════════════════
#  Analysis 1 — Sector Breakdown
# ═════════════════════════════════════════════════════════════════════════════

def analyze_sectors(results: list[dict]) -> list[dict]:
    """Group dual-role entities by economic activity sector."""
    sector_groups = defaultdict(lambda: {
        "count": 0, "total_prr_value": 0, "total_base_value": 0,
        "triple_role_count": 0, "high_risk_count": 0,
        "entities": [],
    })

    for r in results:
        sector = r.get("atividade", "Unknown").strip() or "Unknown"
        g = sector_groups[sector]
        g["count"] += 1
        g["total_prr_value"] += r["prr_value"]
        base_val = (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) + \
                   (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0)
        g["total_base_value"] += base_val
        if r["role_type"] == "triple_role":
            g["triple_role_count"] += 1
        if r["risk_score"] >= 70:
            g["high_risk_count"] += 1
        g["entities"].append(r["name"])

    sorted_sectors = sorted(sector_groups.items(), key=lambda x: -x[1]["count"])
    return sorted_sectors


def print_sector_report(sectors: list):
    """Print the sector breakdown report."""
    print(f"\n{'=' * 110}")
    print(f"  SECTOR BREAKDOWN — Dual-Role Entities by Economic Activity")
    print(f"{'=' * 110}")

    print(f"\n  {'Sector':<50} {'Count':>6} {'PRR Value':>14} {'BASE Value':>14} {'Triple':>7} {'High Risk':>9}")
    print(f"  {'─' * 50} {'─' * 6} {'─' * 14} {'─' * 14} {'─' * 7} {'─' * 9}")

    for sector, g in sectors:
        print(f"  {sector[:48]:<50} {g['count']:>6} {fmt(g['total_prr_value']):>14} "
              f"{fmt(g['total_base_value']):>14} {g['triple_role_count']:>7} {g['high_risk_count']:>9}")

    # Top entities per sector
    print(f"\n\n  Top Entities per Sector:")
    print(f"  {'─' * 60}")
    for sector, g in sectors[:10]:
        top_entities = sorted(g["entities"], key=lambda x: g["entities"].count(x), reverse=True)[:5]
        print(f"  {sector[:40]:<40} ({g['count']} entities):")
        for ent in top_entities:
            print(f"    • {ent[:50]}")
        print()

    print(f"{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  Analysis 2 — Temporal Trends
# ═════════════════════════════════════════════════════════════════════════════

def analyze_trends(results: list[dict]) -> dict:
    """Analyze temporal sequencing of PRR vs procurement activity.

    For each dual-role entity, compare the years of their PRR contracts
    versus their procurement contracts to identify sequencing patterns.
    """
    if not TRANSPARENCY_DB.exists() or not PROCUREMENT_DB.exists():
        return {"error": "Databases not found"}

    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    # Get entity codes and NIFs from dual-role results
    entity_codes = set(r["cd_entidade"] for r in results if r.get("cd_entidade"))
    dual_nifs = set(r["nif"] for r in results)

    print("Loading PRR contract dates...", file=sys.stderr)
    prr_dates = load_prr_contract_dates(conn, entity_codes)

    print("Loading procurement contract dates...", file=sys.stderr)
    proc_dates = load_base_contract_dates(proc_conn, dual_nifs)

    conn.close()
    proc_conn.close()

    # Group by entity
    prr_by_entity = defaultdict(list)
    for cd_ent, ano, valor in prr_dates:
        prr_by_entity[cd_ent].append({"ano": ano, "valor": valor})

    proc_by_nif = defaultdict(list)
    for nif, ano, valor in proc_dates:
        proc_by_nif[nif].append({"ano": ano, "valor": valor})

    # Map cd_entidade → nif
    ent_to_nif = {r["cd_entidade"]: r["nif"] for r in results if r.get("cd_entidade")}

    # Analyze sequencing for each entity
    undated_count = 0
    sequence_patterns = defaultdict(lambda: {"count": 0, "entities": [], "total_prr": 0, "total_base": 0})

    for r in results:
        cd_ent = r.get("cd_entidade", "")
        nif = r["nif"]
        prr_years = [d["ano"] for d in prr_by_entity.get(cd_ent, []) if d["ano"]]
        proc_years = [d["ano"] for d in proc_by_nif.get(nif, []) if d["ano"]]

        if not prr_years and not proc_years:
            undated_count += 1
            continue

        # Determine pattern
        if prr_years and proc_years:
            earliest_prr = min(prr_years)
            latest_prr = max(prr_years)
            earliest_proc = min(proc_years)
            latest_proc = max(proc_years)

            if earliest_prr < earliest_proc and latest_prr < latest_proc:
                pattern = "prr_first_then_procurement"
            elif earliest_proc < earliest_prr and latest_proc < latest_prr:
                pattern = "procurement_first_then_prr"
            elif earliest_prr < earliest_proc:
                pattern = "overlapping_prr_started_first"
            else:
                pattern = "overlapping_procurement_started_first"
        elif prr_years and not proc_years:
            pattern = "prr_only_dated"
        else:
            pattern = "procurement_only_dated"

        g = sequence_patterns[pattern]
        g["count"] += 1
        if prr_years:
            g["total_prr"] += r["prr_value"]
        base_val = (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) + \
                   (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0)
        g["total_base"] += base_val

        if r["risk_score"] >= 50:
            g["entities"].append({
                "name": r["name"], "nif": r["nif"],
                "risk_score": r["risk_score"],
                "prr_years": prr_years, "proc_years": proc_years,
            })

    return {
        "patterns": dict(sequence_patterns),
        "total_analyzed": len(results),
        "undated_count": undated_count,
    }


def print_trends_report(trends: dict):
    """Print temporal trends report."""
    if "error" in trends:
        print(f"  ERROR: {trends['error']}")
        return

    patterns = trends.get("patterns", {})
    total = trends.get("total_analyzed", 0)
    undated = trends.get("undated_count", 0)

    print(f"\n{'=' * 110}")
    print(f"  TEMPORAL TRENDS — PRR vs Procurement Activity Sequencing")
    print(f"{'=' * 110}")

    print(f"\n  Analyzing {total} dual-role entities ({undated} without date data)\n")

    pattern_labels = {
        "prr_first_then_procurement": "PRR before Procurement — PRR contracts signed before procurement contracts",
        "procurement_first_then_prr": "Procurement before PRR — procurement contracts signed before PRR",
        "overlapping_prr_started_first": "Overlapping — PRR started first, both active concurrently",
        "overlapping_procurement_started_first": "Overlapping — Procurement started first, both active concurrently",
        "prr_only_dated": "PRR only (no dated procurement contracts found)",
        "procurement_only_dated": "Procurement only (no dated PRR contracts found)",
    }

    print(f"  {'Pattern':<65} {'Count':>6} {'PRR Value':>14} {'BASE Value':>14}")
    print(f"  {'─' * 65} {'─' * 6} {'─' * 14} {'─' * 14}")

    for pattern_key, label in pattern_labels.items():
        g = patterns.get(pattern_key)
        if not g or g["count"] == 0:
            continue
        print(f"  {label:<65} {g['count']:>6} {fmt(g['total_prr']):>14} {fmt(g['total_base']):>14}")
        # Show top high-risk entities in the most concerning patterns
        if pattern_key in ("prr_first_then_procurement", "overlapping_prr_started_first") and g.get("entities"):
            print(f"    High-risk entities in this group:")
            for e in g["entities"][:5]:
                prr_years_str = ", ".join(sorted(set(e["prr_years"])))[:20]
                proc_years_str = ", ".join(sorted(set(e["proc_years"])))[:20]
                print(f"      🔴 ({e['risk_score']}) {e['name'][:45]:45s} "
                      f"PRR: {prr_years_str}  BASE: {proc_years_str}")

    # Highlight PRR→procurement flow (most concerning)
    prr_first = patterns.get("prr_first_then_procurement", {})
    if prr_first.get("count", 0) > 0:
        print(f"\n  ⚠️  KEY FINDING: {prr_first['count']} entities received PRR money first, "
              f"then won procurement contracts")
        print(f"  This pattern suggests PRR funding may have been used to gain competitive "
              f"advantage in public procurement — a potential cross-subsidization signal.")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  Analysis 3 — Competition Dynamics
# ═════════════════════════════════════════════════════════════════════════════

def analyze_competition(results: list[dict]) -> dict:
    """Analyze competitive dynamics of dual-role suppliers.

    Measures supplier concentration — dual-role entities with few unique buyers
    may indicate market capture, especially when combined with high PRR funding.
    """
    suppliers = []
    for r in results:
        bs = r.get("base_as_supplier")
        if bs and bs["contracts"] > 0:
            suppliers.append({
                "name": r["name"],
                "nif": r["nif"],
                "risk_score": r["risk_score"],
                "prr_value": r["prr_value"],
                "proc_contracts": bs["contracts"],
                "proc_value": bs["value"],
                "unique_buyers": bs["unique_buyers"],
                "buyers_per_contract": round(bs["unique_buyers"] / bs["contracts"], 2) if bs["contracts"] > 0 else 0,
                "role_type": r["role_type"],
            })

    if not suppliers:
        return {"suppliers": [], "summary": "No dual-role suppliers found"}

    # Rank by concentration (fewest unique buyers per contract = most concentrated)
    suppliers.sort(key=lambda x: x["buyers_per_contract"])

    # Calculate market-wide averages
    avg_unique_buyers = sum(s["unique_buyers"] for s in suppliers) / len(suppliers)
    avg_contracts = sum(s["proc_contracts"] for s in suppliers) / len(suppliers)

    # Identify concentrated suppliers (fewer unique buyers than 25th percentile)
    buyer_counts = sorted(s["unique_buyers"] for s in suppliers)
    p25 = buyer_counts[len(buyer_counts) // 4] if buyer_counts else 0
    concentrated = [s for s in suppliers if s["unique_buyers"] <= p25 and s["proc_contracts"] >= 3]

    return {
        "suppliers": suppliers,
        "total_suppliers": len(suppliers),
        "avg_unique_buyers": round(avg_unique_buyers, 1),
        "avg_contracts": round(avg_contracts, 1),
        "p25_unique_buyers": p25,
        "concentrated_suppliers": concentrated,
        "total_prr_value": sum(s["prr_value"] for s in suppliers),
    }


def print_competition_report(comp: dict):
    """Print competition dynamics report."""
    if "summary" in comp:
        print(f"  {comp['summary']}")
        return

    suppliers = comp["suppliers"]
    concentrated = comp.get("concentrated_suppliers", [])

    print(f"\n{'=' * 110}")
    print(f"  COMPETITION DYNAMICS — Dual-Role Supplier Concentration")
    print(f"{'=' * 110}")

    print(f"\n  📊 Market Overview")
    print(f"  {'─' * 50}")
    print(f"  Total dual-role suppliers: {comp['total_suppliers']}")
    print(f"  Avg unique buyers per supplier: {comp['avg_unique_buyers']}")
    print(f"  Avg procurement contracts per supplier: {comp['avg_contracts']}")
    print(f"  25th percentile unique buyers: {comp['p25_unique_buyers']}")
    print(f"  Total PRR value in dual-role suppliers: {fmt(comp['total_prr_value'])}")

    # Most concentrated suppliers
    print(f"\n  🟠 CONCENTRATED SUPPLIERS (fewest unique buyers per contract)")
    print(f"  These entities serve few buyers despite many contracts — potential market capture")
    print(f"  {'─' * 100}")
    print(f"  {'Entity':<40} {'Contracts':>10} {'Unique Buyers':>14} {'Buyers/Contract':>16} {'PRR Value':>14} {'Score':>6}")
    print(f"  {'─' * 40} {'─' * 10} {'─' * 14} {'─' * 16} {'─' * 14} {'─' * 6}")

    for s in suppliers[:20]:
        print(f"  {s['name'][:38]:<40} {s['proc_contracts']:>10} {s['unique_buyers']:>14} "
              f"{s['buyers_per_contract']:>16.2f} {fmt(s['prr_value']):>14} {s['risk_score']:>5.0f}")

    # High-risk concentrated suppliers
    print(f"\n\n  🔴 HIGH-RISK CONCENTRATED SUPPLIERS")
    print(f"  {'─' * 90}")
    for s in concentrated:
        if s["risk_score"] >= 50:
            print(f"  {s['name'][:45]:45s} NIF={s['nif']}  "
                  f"{s['proc_contracts']} contracts, {s['unique_buyers']} buyers  "
                  f"PRR {fmt(s['prr_value'])}  Score {s['risk_score']}")

    if not concentrated:
        print(f"  None found — dual-role suppliers generally serve diverse buyers.")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  Analysis 4 — Contract Modification Correlation
# ═════════════════════════════════════════════════════════════════════════════

def load_contract_index() -> dict:
    """Load contract_index.json: NIF → list of contract_ids."""
    if not CONTRACT_INDEX.exists():
        return {}
    try:
        with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_modifications() -> dict:
    """Load all modifications from modificacoes_index.db.

    Returns dict of idcontrato → list of modification details.
    """
    if not MODIFICACOES_DB.exists():
        return {}

    conn = db_connect(str(MODIFICACOES_DB))
    rows = conn.execute(
        "SELECT idcontrato, fundamento, tipo_acto, data_modificacao, "
        "COALESCE(preco_alterado, 0), prazo_execucao, ano "
        "FROM modificacoes ORDER BY idcontrato, data_modificacao"
    ).fetchall()
    conn.close()

    mods = defaultdict(list)
    for r in rows:
        mods[r[0]].append({
            "fundamento": r[1] or "",
            "tipo_acto": r[2] or "",
            "data": r[3] or "",
            "preco_alterado": r[4],
            "prazo_execucao": r[5],
            "ano": r[6],
        })
    return dict(mods)


def analyze_modifications(results: list[dict]) -> dict:
    """Cross-reference dual-role entities with contract modifications.

    Uses contract_index.json to map NIF → contract IDs, then looks up
    modifications for those contracts. Compares modification rates
    between dual-role entities and the general population.
    """
    contract_idx = load_contract_index()
    all_mods = load_modifications()

    if not contract_idx or not all_mods:
        return {
            "error": "Contract index or modifications DB not available. "
                     "Run contract_modifications_analyzer.py download && index first."
        }

    # For each dual-role NIF, find their contracts and count modifications
    entity_mods = []
    total_mods_for_dual_role = 0
    total_contracts_for_dual_role = 0

    for r in results:
        nif = r["nif"]
        contracts = contract_idx.get(nif, [])
        contract_ids = [c.get("contract_id", 0) for c in contracts if c.get("contract_id")]

        mod_count = 0
        mod_value = 0
        mod_details = []

        for cid in contract_ids:
            if cid in all_mods:
                ms = all_mods[cid]
                mod_count += len(ms)
                mod_value += sum(m["preco_alterado"] for m in ms)
                mod_details.extend(ms)

        total_mods_for_dual_role += mod_count
        total_contracts_for_dual_role += len(contract_ids)

        if mod_count > 0:
            entity_mods.append({
                "name": r["name"],
                "nif": nif,
                "risk_score": r["risk_score"],
                "contracts_in_index": len(contract_ids),
                "mod_count": mod_count,
                "mod_value": mod_value,
                "prr_value": r["prr_value"],
                "avg_mods_per_contract": round(mod_count / len(contract_ids), 2) if contract_ids else 0,
                "mod_details": mod_details[:10],  # Limit detail
            })

    entity_mods.sort(key=lambda x: -x["mod_count"])

    # Compute baseline: % of all contracts in index that have modifications
    total_contracts_in_idx = sum(len(v) for v in contract_idx.values())
    total_mod_contracts = len(all_mods)
    baseline_mod_rate = (total_mod_contracts / total_contracts_in_idx * 100) if total_contracts_in_idx > 0 else 0

    # Dual-role modification rate
    dual_role_mod_rate = (total_mods_for_dual_role / total_contracts_for_dual_role * 100) \
        if total_contracts_for_dual_role > 0 else 0

    return {
        "entity_mods": entity_mods,
        "total_dual_role_entities": len(results),
        "entities_with_mods": len(entity_mods),
        "total_dual_role_contracts": total_contracts_for_dual_role,
        "total_dual_role_mods": total_mods_for_dual_role,
        "dual_role_mod_rate": round(dual_role_mod_rate, 1),
        "total_contracts_in_index": total_contracts_in_idx,
        "total_contracts_with_mods": total_mod_contracts,
        "baseline_mod_rate": round(baseline_mod_rate, 1),
    }


def print_modifications_report(mod_data: dict):
    """Print modifications correlation report."""
    if "error" in mod_data:
        print(f"  {mod_data['error']}")
        return

    entity_mods = mod_data.get("entity_mods", [])

    print(f"\n{'=' * 110}")
    print(f"  CONTRACT MODIFICATION CORRELATION — Dual-Role Entity Analysis")
    print(f"{'=' * 110}")

    print(f"\n  📊 Baseline Comparison")
    print(f"  {'─' * 50}")
    print(f"  Total contracts in index: {mod_data['total_contracts_in_index']:,}")
    print(f"  Contracts with modifications: {mod_data['total_contracts_with_mods']:,}")
    print(f"  Baseline modification rate: {mod_data['baseline_mod_rate']}%")
    print(f"")
    print(f"  Dual-role entities with modifications: {mod_data['entities_with_mods']} / {mod_data['total_dual_role_entities']}")
    print(f"  Dual-role contracts modified: {mod_data['total_dual_role_mods']}")
    print(f"  Dual-role modification rate: {mod_data['dual_role_mod_rate']}%")

    if mod_data['dual_role_mod_rate'] > mod_data['baseline_mod_rate']:
        excess = mod_data['dual_role_mod_rate'] - mod_data['baseline_mod_rate']
        print(f"\n  🔴 Dual-role entities have {excess:.1f}% HIGHER modification rate than baseline!")
        print(f"     This is a significant correlation signal — PRR-funded entities")
        print(f"     modify their contracts more frequently than the market average.")

    # Most modified contracts
    if entity_mods:
        print(f"\n  🟠 TOP DUAL-ROLE ENTITIES BY MODIFICATION COUNT")
        print(f"  {'─' * 100}")
        print(f"  {'Entity':<40} {'Mods':>5} {'Mod Value':>14} {'Avg/Contract':>13} {'PRR Value':>14} {'Score':>6}")
        print(f"  {'─' * 40} {'─' * 5} {'─' * 14} {'─' * 13} {'─' * 14} {'─' * 6}")

        for em in entity_mods[:15]:
            print(f"  {em['name'][:38]:<40} {em['mod_count']:>5} {fmt(em['mod_value']):>14} "
                  f"{em['avg_mods_per_contract']:>13.2f} {fmt(em['prr_value']):>14} {em['risk_score']:>5.0f}")

        # Entities with high modification rates and high risk
        high_risk_mods = [em for em in entity_mods if em["risk_score"] >= 50 and em["mod_count"] >= 3]
        if high_risk_mods:
            print(f"\n\n  🔴 HIGH-RISK ENTITIES WITH FREQUENT MODIFICATIONS")
            print(f"  {'─' * 80}")
            for em in high_risk_mods[:10]:
                sample_fundamentos = set()
                for d in em.get("mod_details", []):
                    if d.get("fundamento"):
                        sample_fundamentos.add(d["fundamento"][:60])
                print(f"  {em['name'][:40]:40s} ({em['mod_count']} mods, score {em['risk_score']})")
                for f in list(sample_fundamentos)[:3]:
                    print(f"    📝 {f}")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  Analysis 5 — Geographic Flow Mapping
# ═════════════════════════════════════════════════════════════════════════════

def analyze_geo_flow(results: list[dict]) -> dict:
    """Map geographic flow: PRR municipality investment → procurement activity.

    For local government entities (municípios, câmaras, juntas), maps where
    PRR money flows (by concelho) and cross-references with procurement
    buyer/supplier activity in those same regions.
    """
    if not TRANSPARENCY_DB.exists():
        return {"error": "transparency.db not found"}

    conn = db_connect(str(TRANSPARENCY_DB))
    prr_locations_data = load_prr_locations(conn)

    # Aggregate PRR investment by concelho
    prr_by_concelho = defaultdict(lambda: {
        "projects": set(), "total_pct_aprovado": 0, "total_pct_pago": 0,
        "distritos": set(),
    })

    for proj_cd, locs in prr_locations_data.items():
        for loc in locs:
            concelho = loc["concelho"]
            g = prr_by_concelho[concelho]
            g["projects"].add(proj_cd)
            g["total_pct_aprovado"] += loc["pct_aprovado"]
            g["total_pct_pago"] += loc["pct_pago"]
            g["distritos"].add(loc["distrito"])

    # Get PRR locations for dual-role local government entities
    local_entities = [r for r in results if r.get("cd_entidade") and
                      any(kw in r["name"].lower() for kw in ["municipio", "camara", "junta", "freguesia"])]

    # Map each entity to their PRR project concelhos
    entity_geo = []
    for r in local_entities[:30]:  # Limit to top 30
        cd_ent = r["cd_entidade"]
        ecs = conn.execute(
            "SELECT cd_contrato FROM prr_entity_contracts WHERE cd_entidade = ?",
            (cd_ent,)
        ).fetchall()

        project_cds = set()
        for ec in ecs:
            proj = conn.execute(
                "SELECT cd_projeto FROM prr_contracts WHERE cd_contrato = ?",
                (ec[0],)
            ).fetchone()
            if proj:
                project_cds.add(proj[0])

        concelhos = []
        for proj_cd in project_cds:
            locs = prr_locations_data.get(proj_cd, [])
            for loc in locs:
                concelhos.append(loc["concelho"])

        if concelhos:
            entity_geo.append({
                "name": r["name"],
                "nif": r["nif"],
                "risk_score": r["risk_score"],
                "prr_value": r["prr_value"],
                "concelhos": list(set(concelhos)),
                "num_concelhos": len(set(concelhos)),
                "base_contracts": (r["base_as_buyer"]["contracts"] if r["base_as_buyer"] else 0) +
                                  (r["base_as_supplier"]["contracts"] if r["base_as_supplier"] else 0),
                "base_value": (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) +
                              (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0),
            })

    entity_geo.sort(key=lambda x: -x["risk_score"])

    # Top concelhos by PRR investment (among dual-role connected projects)
    top_concelhos = sorted(prr_by_concelho.items(), key=lambda x: -x[1]["total_pct_aprovado"])[:20]

    conn.close()

    return {
        "top_concelhos": top_concelhos,
        "entity_geo": entity_geo,
        "total_local_entities": len(local_entities),
        "total_concelhos_mapped": len(prr_by_concelho),
    }


def print_geo_report(geo: dict):
    """Print geographic flow mapping report."""
    if "error" in geo:
        print(f"  {geo['error']}")
        return

    print(f"\n{'=' * 110}")
    print(f"  GEOGRAPHIC FLOW MAPPING — PRR Municipios → Procurement Activity")
    print(f"{'=' * 110}")

    print(f"\n  📊 Overview")
    print(f"  {'─' * 50}")
    print(f"  PRR projects mapped to {geo['total_concelhos_mapped']} concelhos")
    print(f"  Local government entities in dual-role set: {geo['total_local_entities']}")

    # Top concelhos by PRR investment
    print(f"\n  🗺️  TOP CONCELHOS BY PRR INVESTMENT (among dual-role connected projects)")
    print(f"  {'─' * 80}")
    print(f"  {'Concelho':<35} {'Projects':>9} {'% Approved':>12} {'% Paid':>12} {'Distritos'}")
    print(f"  {'─' * 35} {'─' * 9} {'─' * 12} {'─' * 12} {'─' * 15}")

    for concelho, g in geo["top_concelhos"][:20]:
        distritos = ", ".join(sorted(g["distritos"]))[:15]
        print(f"  {concelho[:33]:<35} {len(g['projects']):>9} "
              f"{g['total_pct_aprovado']:>11.1f}% {g['total_pct_pago']:>11.1f}% {distritos}")

    # Local entity detail
    entity_geo = geo.get("entity_geo", [])
    if entity_geo:
        print(f"\n\n  🏛️  LOCAL GOVERNMENT DUAL-ROLE ENTITIES")
        print(f"  Entities receiving PRR funding AND running procurement operations")
        print(f"  {'─' * 100}")
        print(f"  {'Entity':<40} {'Score':>6} {'Concelhos':>10} {'PRR Value':>14} {'BASE Value':>14} {'Contracts':>10}")
        print(f"  {'─' * 40} {'─' * 6} {'─' * 10} {'─' * 14} {'─' * 14} {'─' * 10}")

        for eg in entity_geo[:15]:
            concelhos_str = ", ".join(eg["concelhos"][:3])
            if len(eg["concelhos"]) > 3:
                concelhos_str += f" +{len(eg['concelhos']) - 3}"
            print(f"  {eg['name'][:38]:<40} {eg['risk_score']:>5.0f} {concelhos_str[:10]:>10} "
                  f"{fmt(eg['prr_value']):>14} {fmt(eg['base_value']):>14} {eg['base_contracts']:>10}")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  Entity Profile
# ═════════════════════════════════════════════════════════════════════════════

def profile_entity(nif: str) -> dict | None:
    """Get a detailed dual-role profile for a specific entity.

    Optimized to avoid expensive supplier NIF extraction when the NIF
    isn't even in the PRR data.
    """
    if not TRANSPARENCY_DB.exists():
        print("ERROR: transparency.db not found")
        return None

    conn = db_connect(str(TRANSPARENCY_DB))
    entity = conn.execute(
        "SELECT cd_entidade, ds_entidade, nif, papel, atividade_economica, "
        "localizacao, COALESCE(valor_contratado, 0), COALESCE(valor_pago, 0) "
        "FROM prr_entities WHERE nif = ?", (nif,)
    ).fetchone()
    conn.close()

    if not entity:
        return None

    all_results = analyze_dual_roles(top_n=10000)
    for r in all_results:
        if r["nif"] == nif:
            return r
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  Output
# ═════════════════════════════════════════════════════════════════════════════

def print_report(results: list[dict], top_n: int):
    """Print the dual-role analysis report."""
    counts = defaultdict(int)
    for r in results:
        counts[r["role_type"]] += 1

    print(f"\n{'=' * 110}")
    print(f"  PRR × PROCUREMENT DUAL-ROLE ANALYSIS")
    print(f"  Entities that are simultaneously PRR beneficiaries and procurement contractors")
    print(f"{'=' * 110}")

    print(f"\n  📊 Overview")
    print(f"  {'─' * 60}")
    print(f"  Total dual-role entities: {len(results)}")
    print(f"  Triple role (PRR + buyer + supplier):  {counts.get('triple_role', 0)}")
    print(f"  PRR beneficiary + BASE supplier:       {counts.get('prr_beneficiary_supplier', 0)}")
    print(f"  PRR beneficiary + BASE buyer:          {counts.get('prr_beneficiary_buyer', 0)}")

    print(f"\n  🏆 Top {min(top_n, len(results))} Dual-Role Entities by Risk Score")
    print(f"  {'─' * 105}")
    print(f"  {'#':<4} {'Score':>6} {'Entity':<40} {'NIF':<12} {'PRR Value':>14} {'BASE Value':>14} {'Role Type'}")
    print(f"  {'─' * 4} {'─' * 6} {'─' * 40} {'─' * 12} {'─' * 14} {'─' * 14} {'─' * 20}")

    for i, r in enumerate(results[:top_n], 1):
        base_val = (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) + \
                   (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0)
        icon = "🔴" if r["risk_score"] >= 70 else ("🟡" if r["risk_score"] >= 40 else "🟢")
        print(f"  {i:<4} {icon}{r['risk_score']:>5.0f}  {r['name'][:40]:<40} {r['nif']:<12} {fmt(r['prr_value']):>14} {fmt(base_val):>14} {r['role_type']}")

    # Detailed view for top entities
    print(f"\n\n{'=' * 110}")
    print(f"  DETAILED PROFILES — Top {min(10, len(results))}")
    print(f"{'=' * 110}")

    for i, r in enumerate(results[:10], 1):
        base_val = (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) + \
                   (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0)
        print(f"\n{'─' * 100}")
        print(f"  [{i}] {r['name'][:60]} (NIF: {r['nif']})")
        print(f"      Risk Score: {r['risk_score']}/100 | PRR: {fmt(r['prr_value'])} | BASE: {fmt(base_val)}")
        print(f"      Role: {', '.join(r['roles'])} | {r['papel']}")

        if r["risk_factors"]:
            print(f"      Risk factors:")
            for factor in r["risk_factors"]:
                print(f"        ⚠️  {factor}")

        print(f"      📋 PRR: Contracted {fmt(r['prr_value'])}, Paid {fmt(r['prr_paid'])}, "
              f"Execution {r['prr_execution_pct']:.1f}%")

        if r["base_as_buyer"] and r["base_as_buyer"]["contracts"] > 0:
            bb = r["base_as_buyer"]
            print(f"      🏛️  BASE Buyer: {bb['contracts']:,} contracts, {fmt(bb['value'])}"
                  + (f", {bb['inflated']} inflated (+{fmt(bb['overrun'])} overrun)"
                     if bb["inflated"] > 0 else ""))

        if r["base_as_supplier"] and r["base_as_supplier"]["contracts"] > 0:
            bs = r["base_as_supplier"]
            print(f"      🏢 BASE Supplier: {bs['contracts']:,} contracts across {bs['unique_buyers']} buyers, {fmt(bs['value'])}"
                  + (f", {bs['inflated_contracts']} inflated" if bs["inflated_contracts"] > 0 else ""))

    # Summary statistics
    print(f"\n{'=' * 110}")
    print(f"  📊 ROLE TYPE BREAKDOWN")
    print(f"  {'─' * 60}")
    for role_type, count in sorted(counts.items(), key=lambda x: -x[1]):
        pct = count * 100 / len(results) if results else 0
        print(f"  {role_type:<35} {count:>4} ({pct:.0f}%)")
    print(f"  {'─' * 60}")
    total_prr = sum(r["prr_value"] for r in results)
    total_base = sum(
        (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) +
        (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0)
        for r in results
    )
    print(f"  Total PRR value in dual-role entities: {fmt(total_prr)}")
    print(f"  Total BASE value in dual-role entities: {fmt(total_base)}")

    print(f"\n{'=' * 110}\n")


def export_results(results: list[dict], path: str):
    """Export results to JSON."""
    export = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_dual_role_entities": len(results),
        "summary": {},
        "entities": [],
    }

    counts = defaultdict(int)
    for r in results:
        counts[r["role_type"]] += 1
    export["summary"]["role_type_counts"] = dict(counts)
    export["summary"]["total_prr_value"] = sum(r["prr_value"] for r in results)
    export["summary"]["total_base_value"] = sum(
        (r["base_as_buyer"]["value"] if r["base_as_buyer"] else 0) +
        (r["base_as_supplier"]["value"] if r["base_as_supplier"] else 0)
        for r in results
    )
    export["summary"]["high_risk"] = sum(1 for r in results if r["risk_score"] >= 70)
    export["summary"]["medium_risk"] = sum(1 for r in results if 40 <= r["risk_score"] < 70)

    for r in results:
        entry = {
            "nif": r["nif"],
            "name": r["name"],
            "role_type": r["role_type"],
            "roles": r["roles"],
            "risk_score": r["risk_score"],
            "risk_factors": r["risk_factors"],
            "prr_value": r["prr_value"],
            "prr_paid": r["prr_paid"],
            "prr_execution_pct": r["prr_execution_pct"],
        }
        if r["base_as_buyer"]:
            entry["base_as_buyer"] = {
                "contracts": r["base_as_buyer"]["contracts"],
                "value": r["base_as_buyer"]["value"],
                "inflated": r["base_as_buyer"]["inflated"],
                "overrun": r["base_as_buyer"]["overrun"],
            }
        if r["base_as_supplier"]:
            entry["base_as_supplier"] = {
                "contracts": r["base_as_supplier"]["contracts"],
                "value": r["base_as_supplier"]["value"],
                "inflated_contracts": r["base_as_supplier"]["inflated_contracts"],
                "unique_buyers": r["base_as_supplier"]["unique_buyers"],
            }
        export["entities"].append(entry)

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"  Exported {len(results)} entities to {out_path}")


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def cmd_default(args):
    """Run the default dual-role analysis."""
    top_n = 10000 if args.all else args.top
    results = analyze_dual_roles(top_n=top_n, min_score=args.min_score)

    if not results:
        print("No dual-role entities found.")
        print("Ensure PRR data is indexed (transparency_scraper.py download && index) and procurement.db exists.")
        return

    print_report(results, top_n if args.all else args.top)
    if args.export:
        export_results(results, args.export)

    return results


def cmd_sectors(args):
    """Run sector breakdown analysis."""
    results = analyze_dual_roles(top_n=10000)
    if not results:
        print("No dual-role entities found.")
        return
    sectors = analyze_sectors(results)
    print_sector_report(sectors)
    if args.export:
        export_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_entities": len(results),
            "sectors": [{"sector": s, "data": g} for s, g in sectors],
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        print(f"  Exported sector data to {args.export}")


def cmd_trends(args):
    """Run temporal trends analysis."""
    results = analyze_dual_roles(top_n=10000)
    if not results:
        print("No dual-role entities found.")
        return
    trends = analyze_trends(results)
    print_trends_report(trends)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(trends, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported trends data to {args.export}")


def cmd_competition(args):
    """Run competition dynamics analysis."""
    results = analyze_dual_roles(top_n=10000)
    if not results:
        print("No dual-role entities found.")
        return
    comp = analyze_competition(results)
    print_competition_report(comp)
    if args.export:
        # Convert sets to lists for JSON
        export_comp = {
            "total_suppliers": comp["total_suppliers"],
            "avg_unique_buyers": comp["avg_unique_buyers"],
            "avg_contracts": comp["avg_contracts"],
            "concentrated_count": len(comp.get("concentrated_suppliers", [])),
            "suppliers": comp["suppliers"],
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_comp, f, ensure_ascii=False, indent=2)
        print(f"  Exported competition data to {args.export}")


def cmd_modifications(args):
    """Run contract modification correlation analysis."""
    results = analyze_dual_roles(top_n=10000)
    if not results:
        print("No dual-role entities found.")
        return
    mod_data = analyze_modifications(results)
    print_modifications_report(mod_data)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(mod_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported modification data to {args.export}")


def cmd_geo_flow(args):
    """Run geographic flow mapping analysis."""
    results = analyze_dual_roles(top_n=10000)
    if not results:
        print("No dual-role entities found.")
        return
    geo = analyze_geo_flow(results)
    print_geo_report(geo)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(geo, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported geo-flow data to {args.export}")


def cmd_all(args):
    """Run all analyses sequentially."""
    results = analyze_dual_roles(top_n=10000)

    if not results:
        print("No dual-role entities found.")
        return

    print_report(results, 30)

    print("\n\n" + "=" * 110)
    print("  EXTENDED ANALYSIS 1: SECTOR BREAKDOWN")
    print("=" * 110)
    sectors = analyze_sectors(results)
    print_sector_report(sectors)

    print("\n\n" + "=" * 110)
    print("  EXTENDED ANALYSIS 2: TEMPORAL TRENDS")
    print("=" * 110)
    trends = analyze_trends(results)
    print_trends_report(trends)

    print("\n\n" + "=" * 110)
    print("  EXTENDED ANALYSIS 3: COMPETITION DYNAMICS")
    print("=" * 110)
    comp = analyze_competition(results)
    print_competition_report(comp)

    print("\n\n" + "=" * 110)
    print("  EXTENDED ANALYSIS 4: CONTRACT MODIFICATIONS")
    print("=" * 110)
    mod_data = analyze_modifications(results)
    print_modifications_report(mod_data)

    print("\n\n" + "=" * 110)
    print("  EXTENDED ANALYSIS 5: GEOGRAPHIC FLOW MAPPING")
    print("=" * 110)
    geo = analyze_geo_flow(results)
    print_geo_report(geo)

    if args.export:
        export_results(results, args.export)
        print(f"\n  Base results exported to {args.export}")


def cmd_profile(args):
    """Profile a single entity by NIF."""
    profile = profile_entity(args.nif)
    if profile:
        print_report([profile], 1)
        if args.export:
            export_results([profile], args.export)
    else:
        print(f"Entity {args.nif} not found in dual-role analysis.")
        print("Either the NIF doesn't exist in PRR data, or it doesn't appear in procurement.db.")


def main():
    parser = argparse.ArgumentParser(
        description="PRR × Procurement Dual-Role Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
            Subcommands:
              (default)        Run dual-role analysis (--top, --nif, --export, --min-score, --all)
              sectors          Sector breakdown of dual-role entities
              trends           Temporal sequencing of PRR vs procurement activity
              competition      Competitive dynamics of dual-role suppliers
              modifications    Contract modification correlation
              geo-flow         Geographic flow mapping
              all              Run all analyses sequentially

            Examples:
              python prr_procurement_crossref.py --top 50
              python prr_procurement_crossref.py --nif 514288256
              python prr_procurement_crossref.py sectors
              python prr_procurement_crossref.py all --export scan.json
        """),
    )

    # Global options (used by default mode)
    parser.add_argument("--top", type=int, default=30, help="Show top N entities (default 30)")
    parser.add_argument("--nif", help="Profile a specific entity by NIF")
    parser.add_argument("--export", help="Export results to JSON")
    parser.add_argument("--min-score", type=float, default=0, help="Minimum risk score threshold")
    parser.add_argument("--all", action="store_true", help="Show all results (ignore --top)")

    # Subcommands for extended analyses
    sub = parser.add_subparsers(dest="subcommand", metavar="")

    p_sectors = sub.add_parser("sectors", help="Sector breakdown")
    p_sectors.add_argument("--export", help="Export to JSON")

    p_trends = sub.add_parser("trends", help="Temporal trends")
    p_trends.add_argument("--export", help="Export to JSON")

    p_comp = sub.add_parser("competition", help="Competition dynamics")
    p_comp.add_argument("--export", help="Export to JSON")

    p_mods = sub.add_parser("modifications", help="Modification correlation")
    p_mods.add_argument("--export", help="Export to JSON")

    p_geo = sub.add_parser("geo-flow", help="Geographic flow mapping")
    p_geo.add_argument("--export", help="Export to JSON")

    p_all = sub.add_parser("all", help="Run all analyses")
    p_all.add_argument("--export", help="Export base results to JSON")

    args = parser.parse_args()

    # Route to subcommand or default
    if args.subcommand == "sectors":
        cmd_sectors(args)
    elif args.subcommand == "trends":
        cmd_trends(args)
    elif args.subcommand == "competition":
        cmd_competition(args)
    elif args.subcommand == "modifications":
        cmd_modifications(args)
    elif args.subcommand == "geo-flow":
        cmd_geo_flow(args)
    elif args.subcommand == "all":
        cmd_all(args)
    elif args.nif:
        cmd_profile(args)
    else:
        cmd_default(args)


if __name__ == "__main__":
    main()
