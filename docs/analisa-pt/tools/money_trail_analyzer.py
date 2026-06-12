#!/usr/bin/env python3
"""Money Trail Analyzer — Trace PRR → Budget → Procurement pipeline for any concelho.

Detects where public money "expands", "contracts", or "disappears" along the chain:

  Phase 1 — PRR Allocation: EU funds allocated to each concelho (from prr_locations)
  Phase 2 — Budget Execution: Planned vs actual spending (from budget table)
  Phase 3 — Procurement: Contracts signed, inflation, concentration (from contratos)

Anomaly signals:
  • Money expansion: PRR allocates €5M → procurement shows €7.5M (+50%)
  • Execution gap: PRR allocates → procurement never happens
  • Budget variance: planned vs actual > 50% in PRR-related categories
  • Geographic mismatch: PRR flows to concelho X, procurement concentrated elsewhere

Requires:
  - transparency.db (PRR + budget data)
  - procurement.db (BASE contracts)

Usage:
    python money_trail_analyzer.py                          # Top 20 concelhos by PRR allocation
    python money_trail_analyzer.py --concelho "Fundão"      # Single concelho deep-dive
    python money_trail_analyzer.py --concelho "Fundão" --export trail.json
    python money_trail_analyzer.py --concelho "Fundão" --verbose
    python money_trail_analyzer.py --rank                   # Run rank mode explicitly
    python money_trail_analyzer.py --rank --top 50
"""

import json
import re
import sqlite3
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


def check_dbs():
    """Verify both databases exist."""
    missing = []
    if not TRANSPARENCY_DB.exists():
        missing.append(f"transparency.db not found at {TRANSPARENCY_DB}\n  Run: python transparency_scraper.py download && index")
    if not PROCUREMENT_DB.exists():
        missing.append(f"procurement.db not found at {PROCUREMENT_DB}\n  Run: python procurement_db.py build")
    if missing:
        for m in missing:
            print(f"ERROR: {m}")
        sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — PRR Allocation to Concelho
# ═════════════════════════════════════════════════════════════════════════════

def load_prr_locations(conn) -> dict:
    """Load all PRR locations, grouped by concelho.

    Returns {concelho: {projects, pct_aprovado, pct_pago, distrito, nuts3, ...}}
    """
    rows = conn.execute(
        "SELECT cd_projeto, cd_nutsiii, ds_nutsiii, cd_distrito, ds_distrito, "
        "cd_concelho, ds_concelho, "
        "COALESCE(perc_valor_aprovado, 0) as pct_aprovado, "
        "COALESCE(perc_valor_pago, 0) as pct_pago "
        "FROM prr_locations "
        "WHERE ds_concelho != ''"
    ).fetchall()

    by_concelho = defaultdict(lambda: {
        "projects": set(), "project_details": [],
        "total_pct_aprovado": 0.0, "total_pct_pago": 0.0,
        "distritos": set(), "nuts3_codes": set(), "nuts3_names": set(),
        "cd_concelho": "", "ds_concelho": "",
    })

    for r in rows:
        concelho = r[6].strip()
        g = by_concelho[concelho]
        g["cd_concelho"] = r[5] or ""
        g["ds_concelho"] = concelho
        g["projects"].add(r[0])
        g["project_details"].append({
            "cd_projeto": r[0],
            "pct_aprovado": r[7],
            "pct_pago": r[8],
        })
        g["total_pct_aprovado"] += r[7]
        g["total_pct_pago"] += r[8]
        if r[4]:
            g["distritos"].add(r[4])
        if r[1]:
            g["nuts3_codes"].add(r[1])
        if r[2]:
            g["nuts3_names"].add(r[2])

    return dict(by_concelho)


def load_prr_projects(conn) -> dict:
    """Load PRR projects to get absolute values (not just percentages)."""
    rows = conn.execute(
        "SELECT cd_projeto, ds_projeto, COALESCE(valor_aprovado, 0), "
        "COALESCE(valor_pago, 0) FROM prr_projects"
    ).fetchall()
    return {r[0]: {"ds_projeto": r[1] or "", "valor_aprovado": r[2], "valor_pago": r[3]} for r in rows}


def load_prr_entities_for_concelho(conn, concelho: str) -> list[dict]:
    """Find PRR entities related to a specific concelho via PRR locations.

    Traces: concelho → prr_locations.cd_projeto → prr_contracts → prr_entity_contracts → prr_entities
    """
    rows = conn.execute(
        "SELECT DISTINCT e.cd_entidade, e.ds_entidade, e.nif, e.papel, "
        "e.atividade_economica, e.localizacao, "
        "COALESCE(e.valor_contratado, 0) as valor_contratado, "
        "COALESCE(e.valor_pago, 0) as valor_pago "
        "FROM prr_entities e "
        "JOIN prr_entity_contracts ec ON e.cd_entidade = ec.cd_entidade "
        "JOIN prr_contracts c ON ec.cd_contrato = c.cd_contrato "
        "JOIN prr_locations l ON c.cd_projeto = l.cd_projeto "
        "WHERE l.ds_concelho LIKE ?",
        (f"%{concelho}%",)
    ).fetchall()

    return [{
        "cd_entidade": r[0], "name": r[1], "nif": r[2] or "",
        "papel": r[3] or "", "atividade": r[4] or "",
        "localizacao": r[5] or "", "valor_contratado": r[6],
        "valor_pago": r[7],
    } for r in rows]


def load_prr_contracts_for_concelho(conn, concelho: str) -> list[dict]:
    """Load PRR contracts whose projects flow to the given concelho."""
    rows = conn.execute(
        "SELECT c.cd_contrato, c.ds_contrato, c.sumario, c.cd_base_gov, "
        "c.dt_assinatura, COALESCE(c.montante, 0) as montante, "
        "c.cd_projeto, c.ds_projeto "
        "FROM prr_contracts c "
        "JOIN prr_locations l ON c.cd_projeto = l.cd_projeto "
        "WHERE l.ds_concelho LIKE ? "
        "ORDER BY c.montante DESC",
        (f"%{concelho}%",)
    ).fetchall()

    return [{
        "cd_contrato": r[0], "ds_contrato": r[1] or "", "sumario": r[2] or "",
        "cd_base_gov": r[3] or "", "dt_assinatura": r[4] or "",
        "montante": r[5], "cd_projeto": r[6] or "", "ds_projeto": r[7] or "",
    } for r in rows]


def compute_phase1(conn, concelho: str) -> dict:
    """Phase 1: PRR money allocated to concelho.

    Returns the PRR allocation profile for the concelho.
    """
    locations = load_prr_locations(conn)
    projects = load_prr_projects(conn)

    # Find concelho in locations (case-insensitive)
    matched_concelho = None
    for name in locations:
        if concelho.lower() in name.lower():
            matched_concelho = name
            break

    if not matched_concelho:
        # Try searching by Like
        loc_row = conn.execute(
            "SELECT ds_concelho FROM prr_locations WHERE ds_concelho LIKE ? LIMIT 1",
            (f"%{concelho}%",)
        ).fetchone()
        if loc_row:
            matched_concelho = loc_row[0]

    if not matched_concelho or matched_concelho not in locations:
        return {"error": f"Concelho '{concelho}' not found in PRR locations data"}

    loc_data = locations[matched_concelho]

    # Compute absolute PRR values per project using prr_projects table
    project_values = []
    total_aprovado = 0
    total_pago = 0

    for pd in loc_data["project_details"]:
        proj = projects.get(pd["cd_projeto"])
        if proj and proj["valor_aprovado"] > 0:
            # The percentage in prr_locations is per-project
            abs_aprovado = proj["valor_aprovado"] * (pd["pct_aprovado"] / 100)
            abs_pago = proj["valor_pago"] * (pd["pct_pago"] / 100) if proj["valor_pago"] > 0 else 0
            project_values.append({
                "cd_projeto": pd["cd_projeto"],
                "ds_projeto": proj["ds_projeto"][:80],
                "pct_aprovado": pd["pct_aprovado"],
                "pct_pago": pd["pct_pago"],
                "valor_aprovado": proj["valor_aprovado"],
                "valor_pago": proj["valor_pago"],
                "abs_aprovado": round(abs_aprovado, 2),
                "abs_pago": round(abs_pago, 2),
            })
            total_aprovado += abs_aprovado
            total_pago += abs_pago

    # Sort by absolute value descending
    project_values.sort(key=lambda x: -x["abs_aprovado"])

    # Load PRR entities linked to this concelho
    prr_entities = load_prr_entities_for_concelho(conn, matched_concelho)
    prr_contracts = load_prr_contracts_for_concelho(conn, matched_concelho)

    return {
        "concelho": matched_concelho,
        "cd_concelho": loc_data["cd_concelho"],
        "distritos": list(loc_data["distritos"]),
        "nuts3_codes": list(loc_data["nuts3_codes"]),
        "nuts3_names": list(loc_data["nuts3_names"]),
        "num_projects": len(loc_data["projects"]),
        "total_pct_aprovado": loc_data["total_pct_aprovado"],
        "total_pct_pago": loc_data["total_pct_pago"],
        "total_aprovado": round(total_aprovado, 2),
        "total_pago": round(total_pago, 2),
        "execution_rate_pct": round(total_pago / total_aprovado * 100, 1) if total_aprovado > 0 else 0,
        "project_values": project_values,
        "prr_entities": prr_entities,
        "prr_contracts": prr_contracts,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — Budget Execution
# ═════════════════════════════════════════════════════════════════════════════

def compute_phase2(conn, concelho: str) -> dict:
    """Phase 2: Budget execution for the concelho.

    Searches budget.descricao for concelho name. Also returns
    national-level budget aggregates for context.
    """
    # Check budget table exists and has data
    try:
        total_budget_rows = conn.execute("SELECT COUNT(*) FROM budget").fetchone()[0]
    except sqlite3.OperationalError:
        return {"error": "Budget table not found in transparency.db", "total_rows": 0}

    if total_budget_rows == 0:
        return {"error": "Budget table is empty — run transparency_scraper.py download && index", "total_rows": 0}

    # National aggregates
    national = conn.execute(
        "SELECT COUNT(*) as total_rows, "
        "SUM(COALESCE(valor_previsto, 0)) as total_previsto, "
        "SUM(COALESCE(valor_realizado, 0)) as total_realizado, "
        "COUNT(DISTINCT dataset_key) as num_datasets, "
        "COUNT(DISTINCT ano) as num_years "
        "FROM budget"
    ).fetchone()

    national_previsto = national[1] or 0
    national_realizado = national[2] or 0

    # Search for concelho mentions in budget descriptions
    concelho_rows = conn.execute(
        "SELECT dataset_key, ano, mes, nivel_orcamental, descricao, "
        "COALESCE(valor_previsto, 0), COALESCE(valor_realizado, 0), "
        "COALESCE(percentagem, 0) "
        "FROM budget WHERE descricao LIKE ? "
        "ORDER BY valor_previsto DESC LIMIT 20",
        (f"%{concelho}%",)
    ).fetchall()

    concelho_entries = []
    concelho_previsto = 0
    concelho_realizado = 0

    for r in concelho_rows:
        concelho_entries.append({
            "dataset_key": r[0], "ano": r[1], "mes": r[2],
            "nivel": r[3], "descricao": r[4][:60],
            "valor_previsto": r[5], "valor_realizado": r[6],
            "percentagem": r[7],
        })
        concelho_previsto += r[5]
        concelho_realizado += r[6]

    concelho_entries.sort(key=lambda x: -x["valor_previsto"])

    return {
        "national_total_previsto": national_previsto,
        "national_total_realizado": national_realizado,
        "national_execution_rate": round(national_realizado / national_previsto * 100, 1) if national_previsto > 0 else 0,
        "num_datasets": national[3],
        "num_years": national[4],
        "concelho_entries": concelho_entries,
        "concelho_previsto": concelho_previsto,
        "concelho_realizado": concelho_realizado,
        "concelho_execution_rate": round(concelho_realizado / concelho_previsto * 100, 1) if concelho_previsto > 0 else 0,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — Procurement in Concelho
# ═════════════════════════════════════════════════════════════════════════════

# Common municipality entity name patterns
MUNICIPIO_PATTERNS = [
    "Município de", "Município do", "Município da", "Câmara Municipal de",
    "Câmara Municipal do", "Câmara Municipal da", "Câmara de",
    "Junta de Freguesia de", "Junta de Freguesia do", "Junta de Freguesia da",
    "Freguesia de", "Freguesia do",
]


def find_procurement_buyer_nifs(proc_conn, concelho: str) -> set:
    """Find NIFs of entities that are likely the concelho's public buyers.

    Matches on entity name patterns and also does direct LIKE search.
    """
    nifs = set()

    # Direct match: entity name contains concelho
    rows = proc_conn.execute(
        "SELECT DISTINCT adjudicante_nif FROM contratos "
        "WHERE adjudicante_nome LIKE ? AND adjudicante_nif != '' "
        "AND adjudicante_nif != '-' AND adjudicante_nif IS NOT NULL",
        (f"%{concelho}%",)
    ).fetchall()
    for r in rows:
        nifs.add(r[0])

    # Pattern match: "Município do {concelho}", "Câmara Municipal do {concelho}", etc.
    for pattern in MUNICIPIO_PATTERNS:
        entity_name = f"{pattern} {concelho}"
        rows = proc_conn.execute(
            "SELECT DISTINCT adjudicante_nif FROM contratos "
            "WHERE adjudicante_nome LIKE ? AND adjudicante_nif != '' "
            "AND adjudicante_nif != '-' AND adjudicante_nif IS NOT NULL",
            (f"%{entity_name}%",)
        ).fetchall()
        for r in rows:
            nifs.add(r[0])

    return nifs


def load_procurement_stats(proc_conn, buyer_nifs: set, nuts_codes: list = None) -> dict:
    """Load procurement statistics for a set of buyer NIFs.

    Returns aggregated stats: contracts, value, inflation, concentration, top companies.
    """
    if not buyer_nifs:
        return {"error": "No buyer NIFs found for this concelho"}

    placeholders = ",".join("?" * len(buyer_nifs))
    nif_list = list(buyer_nifs)

    # Basic stats
    stats = proc_conn.execute(
        f"SELECT "
        f"COUNT(*) as total_contracts, "
        f"SUM(COALESCE(precoContratual, 0)) as total_value, "
        f"SUM(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        f"    THEN 1 ELSE 0 END) as inflated_count, "
        f"SUM(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        f"    THEN precoContratual - precoBaseProcedimento ELSE 0 END) as total_overrun, "
        f"AVG(CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        f"    THEN (precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento "
        f"    ELSE NULL END) as avg_inflation_pct, "
        f"MIN(SUBSTR(COALESCE(dataCelebracaoContrato, ''), 1, 4)) as earliest_year, "
        f"MAX(SUBSTR(COALESCE(dataCelebracaoContrato, ''), 1, 4)) as latest_year "
        f"FROM contratos WHERE adjudicante_nif IN ({placeholders}) AND precoContratual > 0",
        nif_list
    ).fetchone()

    # Procedure type breakdown
    procedures = proc_conn.execute(
        f"SELECT tipoprocedimento, COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val "
        f"FROM contratos WHERE adjudicante_nif IN ({placeholders}) AND precoContratual > 0 "
        f"AND tipoprocedimento != '' AND tipoprocedimento IS NOT NULL "
        f"GROUP BY tipoprocedimento ORDER BY cnt DESC",
        nif_list
    ).fetchall()

    procedure_breakdown = [{
        "tipo": r[0][:40], "count": r[1], "value": r[2],
    } for r in procedures]

    # Top winners (suppliers)
    nif_pattern = re.compile(r"\b(\d{9})\b")
    winner_data = defaultdict(lambda: {"count": 0, "value": 0.0, "name": ""})

    winner_rows = proc_conn.execute(
        f"SELECT adjudicatarios, COALESCE(precoContratual, 0) "
        f"FROM contratos WHERE adjudicante_nif IN ({placeholders}) "
        f"AND adjudicatarios IS NOT NULL AND adjudicatarios != '' "
        f"AND precoContratual > 0",
        nif_list
    ).fetchall()

    for r in winner_rows:
        adj_text = r[0]
        valor = r[1]
        found_nifs = set(nif_pattern.findall(adj_text))
        # Extract names from "NIF - Name" format
        names = re.findall(r"\d{9}\s*-\s*([^;]+)", adj_text)
        for i, nif in enumerate(found_nifs):
            winner_data[nif]["count"] += 1
            winner_data[nif]["value"] += valor
            if i < len(names) and not winner_data[nif]["name"]:
                winner_data[nif]["name"] = names[i].strip()

    sorted_winners = sorted(winner_data.items(), key=lambda x: -x[1]["value"])
    top_winners = [{
        "nif": nif, "name": data["name"][:45] if data["name"] else nif,
        "count": data["count"], "value": data["value"],
        "share_pct": round(data["value"] * 100 / max(stats[1] or 1, 1), 1),
    } for nif, data in sorted_winners[:15]]

    # Concentration: top-3 share
    top3_value = sum(w["value"] for w in top_winners[:3])
    top3_share = round(top3_value * 100 / max(stats[1] or 1, 1), 1)
    total_winners = len(winner_data)

    # NUTs region breakdown
    nuts_breakdown = []
    if nuts_codes:
        nuts_rows = proc_conn.execute(
            f"SELECT NUTs, COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val "
            f"FROM contratos WHERE adjudicante_nif IN ({placeholders}) AND precoContratual > 0 "
            f"AND NUTs != '' AND NUTs IS NOT NULL "
            f"GROUP BY NUTs ORDER BY val DESC",
            nif_list
        ).fetchall()
        nuts_breakdown = [{"NUTs": r[0], "count": r[1], "value": r[2]} for r in nuts_rows]

    result = {
        "total_contracts": stats[0],
        "total_value": stats[1] or 0,
        "inflated_count": stats[2] or 0,
        "total_overrun": stats[3] or 0,
        "avg_inflation_pct": round(stats[4], 1) if stats[4] else 0,
        "earliest_year": stats[5] or "",
        "latest_year": stats[6] or "",
        "top3_share": top3_share,
        "unique_winners": total_winners,
        "top_winners": top_winners,
        "procedure_breakdown": procedure_breakdown,
        "nuts_breakdown": nuts_breakdown,
    }
    return result


def compute_phase3(proc_conn, concelho: str, prr_entity_nifs: set = None,
                   nuts_codes: list = None) -> dict:
    """Phase 3: Procurement activity for the concelho.

    Uses multiple strategies to find relevant contracts:
    1. Match by buyer entity name containing concelho name
    2. Match by PRR entity NIFs (from Phase 1)
    3. Match by NUTs code (broader region)
    """
    # Strategy 1: Buyer name matching
    buyer_nifs = find_procurement_buyer_nifs(proc_conn, concelho)

    # Strategy 2: PRR entity NIFs
    if prr_entity_nifs:
        buyer_nifs.update(prr_entity_nifs)

    # Strategy 3: Also check if these NIFs appear as suppliers
    # (helps detect dual-role entities)
    nif_pattern = re.compile(r"\b(\d{9})\b")
    supplier_as_buyer = set()
    for nif in buyer_nifs:
        row = proc_conn.execute(
            "SELECT COUNT(*) FROM contratos WHERE adjudicante_nif = ?", (nif,)
        ).fetchone()
        if row and row[0] > 0:
            supplier_as_buyer.add(nif)
    buyer_nifs.update(supplier_as_buyer)

    # Load stats
    stats = load_procurement_stats(proc_conn, buyer_nifs, nuts_codes)

    # Also look for contracts with LocalExecucao mentioning the concelho
    location_contracts = proc_conn.execute(
        "SELECT COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val "
        "FROM contratos WHERE LocalExecucao LIKE ? AND precoContratual > 0",
        (f"%{concelho}%",)
    ).fetchone()

    stats["location_match_count"] = location_contracts[0]
    stats["location_match_value"] = location_contracts[1] or 0
    stats["buyer_nifs_found"] = len(buyer_nifs)

    return stats


# ═════════════════════════════════════════════════════════════════════════════
#  CHAIN ANALYSIS — Compare Ratios Across Phases
# ═════════════════════════════════════════════════════════════════════════════

def compute_chain(phase1: dict, phase2: dict, phase3: dict) -> dict:
    """Compare PRR allocation vs budget execution vs procurement spending.

    Identifies anomalies:
    - Money expansion: procurement > PRR allocation
    - Execution gap: PRR allocated but not paid
    - Budget variance: budget planned vs actual
    """
    if "error" in phase1:
        return {"error": phase1["error"]}

    chain = {
        "concelho": phase1["concelho"],
        "phases": {
            "prr_allocation": {
                "total": phase1.get("total_aprovado", 0),
                "paid": phase1.get("total_pago", 0),
                "execution_rate": phase1.get("execution_rate_pct", 0),
            },
            "budget": {
                "previsto": phase2.get("concelho_previsto", 0) if "error" not in phase2 else 0,
                "realizado": phase2.get("concelho_realizado", 0) if "error" not in phase2 else 0,
                "execution_rate": phase2.get("concelho_execution_rate", 0) if "error" not in phase2 else 0,
            },
            "procurement": {
                "total_contracts": phase3.get("total_contracts", 0),
                "total_value": phase3.get("total_value", 0),
                "inflated_count": phase3.get("inflated_count", 0),
                "total_overrun": phase3.get("total_overrun", 0),
                "top3_share": phase3.get("top3_share", 0),
            },
        },
        "anomalies": [],
    }

    prr_total = chain["phases"]["prr_allocation"]["total"]
    proc_total = chain["phases"]["procurement"]["total_value"]
    budget_total = chain["phases"]["budget"]["previsto"]

    # Anomaly 1: Money expansion
    if prr_total > 0 and proc_total > 0:
        ratio = proc_total / prr_total
        if ratio > 1.3:
            chain["anomalies"].append({
                "type": "money_expansion",
                "severity": "critical" if ratio > 1.5 else "warning",
                "detail": f"Procurement ({fmt(proc_total)}) exceeds PRR allocation ({fmt(prr_total)}) by {((ratio - 1) * 100):.0f}%",
                "ratio": round(ratio, 2),
            })
        elif ratio < 0.5:
            chain["anomalies"].append({
                "type": "money_contraction",
                "severity": "warning",
                "detail": f"Procurement ({fmt(proc_total)}) is only {(ratio * 100):.0f}% of PRR allocation ({fmt(prr_total)})",
                "ratio": round(ratio, 2),
            })

    # Anomaly 2: PRR execution gap
    if prr_total > 0:
        exec_rate = phase1.get("execution_rate_pct", 100)
        if exec_rate < 50:
            chain["anomalies"].append({
                "type": "execution_gap",
                "severity": "critical",
                "detail": f"Only {exec_rate:.0f}% of PRR funds paid ({fmt(phase1.get('total_aprovado', 0) - phase1.get('total_pago', 0))} unpaid)",
                "execution_rate": exec_rate,
            })
        elif exec_rate < 80:
            chain["anomalies"].append({
                "type": "execution_gap",
                "severity": "warning",
                "detail": f"Only {exec_rate:.0f}% of PRR funds paid ({fmt(phase1.get('total_aprovado', 0) - phase1.get('total_pago', 0))} unpaid)",
                "execution_rate": exec_rate,
            })

    # Anomaly 3: Price inflation in procurement
    if phase3.get("inflated_count", 0) > 0:
        chain["anomalies"].append({
            "type": "price_inflation",
            "severity": "critical" if phase3.get("total_overrun", 0) > 500_000 else "warning",
            "detail": f"{phase3['inflated_count']} inflated contracts, {fmt(phase3.get('total_overrun', 0))} total overrun, avg +{phase3.get('avg_inflation_pct', 0)}%",
            "inflated_count": phase3["inflated_count"],
            "total_overrun": phase3.get("total_overrun", 0),
        })

    # Anomaly 4: Supplier concentration
    if phase3.get("top3_share", 0) > 60:
        severity = "critical" if phase3["top3_share"] > 80 else "warning"
        chain["anomalies"].append({
            "type": "supplier_concentration",
            "severity": severity,
            "detail": f"Top 3 suppliers take {phase3['top3_share']}% of contract value",
            "top3_share": phase3["top3_share"],
        })

    # Anomaly 5: Budget variance (if budget data available)
    if budget_total > 0:
        budget_real = chain["phases"]["budget"]["realizado"]
        if budget_real > 0:
            variance = abs(budget_real - budget_total) / budget_total * 100
            if variance > 50:
                chain["anomalies"].append({
                    "type": "budget_variance",
                    "severity": "warning",
                    "detail": f"Budget variance: planned {fmt(budget_total)} vs actual {fmt(budget_real)} ({variance:.0f}% difference)",
                    "variance_pct": round(variance, 1),
                })

    chain["total_anomalies"] = len(chain["anomalies"])
    chain["critical_anomalies"] = sum(1 for a in chain["anomalies"] if a["severity"] == "critical")

    return chain


# ═════════════════════════════════════════════════════════════════════════════
#  RANK ALL CONCELHOS
# ═════════════════════════════════════════════════════════════════════════════

def rank_concelhos(conn, proc_conn, top_n: int = 20) -> list[dict]:
    """Rank all concelhos by PRR allocation + procurement activity.

    For each concelho with PRR data, compute:
    - PRR total allocated
    - Estimated procurement volume (by matching entity names)
    - PRR-to-procurement ratio
    """
    locations = load_prr_locations(conn)
    projects = load_prr_projects(conn)

    rankings = []

    for concelho_name, loc_data in locations.items():
        # Compute absolute PRR values
        total_aprovado = 0
        total_pago = 0
        for pd in loc_data["project_details"]:
            proj = projects.get(pd["cd_projeto"])
            if proj and proj["valor_aprovado"] > 0:
                abs_aprovado = proj["valor_aprovado"] * (pd["pct_aprovado"] / 100)
                abs_pago = proj["valor_pago"] * (pd["pct_pago"] / 100) if proj["valor_pago"] > 0 else 0
                total_aprovado += abs_aprovado
                total_pago += abs_pago

        if total_aprovado == 0:
            continue

        # Find procurement buyer NIFs for this concelho
        buyer_nifs = find_procurement_buyer_nifs(proc_conn, concelho_name)
        proc_value = 0
        proc_contracts = 0
        if buyer_nifs:
            placeholders = ",".join("?" * len(buyer_nifs))
            row = proc_conn.execute(
                f"SELECT COUNT(*), SUM(COALESCE(precoContratual, 0)) "
                f"FROM contratos WHERE adjudicante_nif IN ({placeholders}) AND precoContratual > 0",
                list(buyer_nifs)
            ).fetchone()
            proc_contracts = row[0]
            proc_value = row[1] or 0

        rankings.append({
            "concelho": concelho_name,
            "distritos": list(loc_data["distritos"]),
            "prr_projects": len(loc_data["projects"]),
            "prr_aprovado": round(total_aprovado, 2),
            "prr_pago": round(total_pago, 2),
            "prr_execution_pct": round(total_pago / total_aprovado * 100, 1) if total_aprovado > 0 else 0,
            "proc_contracts": proc_contracts,
            "proc_value": proc_value,
            "proc_to_prr_ratio": round(proc_value / total_aprovado, 2) if total_aprovado > 0 else 0,
        })

    rankings.sort(key=lambda x: -x["prr_aprovado"])
    return rankings[:top_n]


# ═════════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ═════════════════════════════════════════════════════════════════════════════

def print_phase1(phase1: dict):
    """Print Phase 1: PRR Allocation report."""
    if "error" in phase1:
        print(f"  ⚠️  Phase 1: {phase1['error']}")
        return

    print(f"\n  {'=' * 100}")
    print(f"  PHASE 1 — PRR Allocation to {phase1['concelho']}")
    print(f"  {'=' * 100}")

    print(f"\n  📊 Overview")
    loc = phase1
    print(f"  NUTS III: {', '.join(loc.get('nuts3_names', []))}  |  "
          f"Distrito: {', '.join(loc.get('distritos', []))}")
    print(f"  PRR Projects: {loc['num_projects']}")
    print(f"  Total Approved: {fmt(loc['total_aprovado'])}")
    print(f"  Total Paid:     {fmt(loc['total_pago'])}")
    print(f"  Execution Rate: {loc['execution_rate_pct']}%")
    print(f"  Execution Gap:  {fmt(loc['total_aprovado'] - loc['total_pago'])}")

    if loc.get("project_values"):
        print(f"\n  📋 Projects by Approved Value")
        print(f"  {'─' * 95}")
        print(f"  {'Project':<40} {'Approved':>12} {'Paid':>12} {'% Approved':>11} {'% Paid':>9} {'Exec%':>7}")
        print(f"  {'─' * 40} {'─' * 12} {'─' * 12} {'─' * 11} {'─' * 9} {'─' * 7}")
        for pv in loc["project_values"][:15]:
            exec_pct = round(pv["abs_pago"] / pv["abs_aprovado"] * 100, 1) if pv["abs_aprovado"] > 0 else 0
            print(f"  {pv['ds_projeto'][:38]:<40} {fmt(pv['abs_aprovado']):>12} "
                  f"{fmt(pv['abs_pago']):>12} {pv['pct_aprovado']:>10.1f}% {pv['pct_pago']:>8.1f}% "
                  f"{exec_pct:>6.0f}%")

    if loc.get("prr_entities"):
        print(f"\n  🏛️  PRR Entities Active in {phase1['concelho']}")
        print(f"  {'─' * 80}")
        for ent in loc["prr_entities"]:
            print(f"  {ent['name'][:45]:45s} NIF: {ent['nif']:<10s} "
                  f"Contracted: {fmt(ent['valor_contratado'])}  Paid: {fmt(ent['valor_pago'])}")
            if ent["papel"]:
                print(f"  {'':45} Role: {ent['papel'][:40]}")
            if ent["atividade"]:
                print(f"  {'':45} Activity: {ent['atividade'][:40]}")

    print()


def print_phase2(phase2: dict, concelho: str):
    """Print Phase 2: Budget Execution report."""
    if "error" in phase2:
        if phase2.get("total_rows", -1) == 0:
            print(f"  ⚠️  Phase 2: Budget data not loaded (run transparency_scraper.py download && index)")
        else:
            print(f"  ⚠️  Phase 2: {phase2['error']}")
        print()
        return

    print(f"\n  {'=' * 100}")
    print(f"  PHASE 2 — Budget Context for {concelho}")
    print(f"  {'=' * 100}")

    print(f"\n  🇵🇹 National Budget Overview")
    print(f"  {'─' * 50}")
    print(f"  Total datasets: {phase2['num_datasets']} over {phase2['num_years']} years")
    print(f"  Total previsto:  {fmt(phase2['national_total_previsto'])}")
    print(f"  Total realizado: {fmt(phase2['national_total_realizado'])}")
    print(f"  National execution rate: {phase2['national_execution_rate']}%")

    if phase2.get("concelho_entries"):
        print(f"\n  🏘️  Budget Entries Matching '{concelho}'")
        print(f"  {'─' * 95}")
        print(f"  {'Descrição':<50} {'Previsto':>12} {'Realizado':>12} {'%':>7} {'Year':>6}")
        print(f"  {'─' * 50} {'─' * 12} {'─' * 12} {'─' * 7} {'─' * 6}")
        for e in phase2["concelho_entries"][:15]:
            print(f"  {e['descricao'][:48]:<50} {fmt(e['valor_previsto']):>12} "
                  f"{fmt(e['valor_realizado']):>12} {e['percentagem']:>6.1f}% {e['ano']:>6}")
        if len(phase2["concelho_entries"]) > 15:
            print(f"  ... and {len(phase2['concelho_entries']) - 15} more entries")
        print(f"\n  Total for '{concelho}': Previsto {fmt(phase2['concelho_previsto'])} → "
              f"Realizado {fmt(phase2['concelho_realizado'])} "
              f"({phase2['concelho_execution_rate']}% executed)")
    else:
        print(f"\n  No budget entries found specifically mentioning '{concelho}'.")
        print(f"  Budget data may be at national/regional level rather than municipality.")

    print()


def print_phase3(phase3: dict):
    """Print Phase 3: Procurement report."""
    if "error" in phase3:
        print(f"  ⚠️  Phase 3: {phase3['error']}")
        return

    print(f"\n  {'=' * 100}")
    print(f"  PHASE 3 — Procurement Activity")
    print(f"  {'=' * 100}")

    print(f"\n  📊 Overview")
    print(f"  {'─' * 60}")
    print(f"  Buyer NIFs found: {phase3.get('buyer_nifs_found', 0)}")
    if phase3.get("location_match_count", 0) > 0:
        print(f"  Contracts with LocalExecucao matching: {phase3['location_match_count']} ({fmt(phase3.get('location_match_value', 0))})")
    print(f"  Total contracts: {phase3['total_contracts']:,}")
    print(f"  Total value:     {fmt(phase3['total_value'])}")
    print(f"  Period:          {phase3.get('earliest_year', '')} — {phase3.get('latest_year', '')}")
    print(f"  Unique suppliers: {phase3['unique_winners']}")

    # Inflation
    if phase3.get("inflated_count", 0) > 0:
        icon = "🔴" if phase3.get("total_overrun", 0) > 500_000 else "🟡"
        print(f"\n  {icon} Price Inflation")
        print(f"  {'─' * 50}")
        print(f"  Inflated contracts: {phase3['inflated_count']}")
        print(f"  Total overrun:      {fmt(phase3.get('total_overrun', 0))}")
        print(f"  Average inflation:  +{phase3.get('avg_inflation_pct', 0)}%")
    else:
        print(f"\n  ✅ No price inflation detected")

    # Concentration
    if phase3.get("top3_share", 0) > 0:
        icon = "🔴" if phase3["top3_share"] > 80 else ("🟡" if phase3["top3_share"] > 60 else "🟢")
        print(f"\n  {icon} Supplier Concentration")
        print(f"  {'─' * 50}")
        print(f"  Top 3 share: {phase3['top3_share']}% of contract value")
        print(f"  Unique winners: {phase3['unique_winners']}")

        if phase3.get("top_winners"):
            print(f"\n  Top Suppliers by Contract Value")
            print(f"  {'─' * 80}")
            print(f"  {'#':<4} {'NIF':<12} {'Name':<30} {'Contracts':>10} {'Value':>14} {'Share':>8}")
            print(f"  {'─' * 4} {'─' * 12} {'─' * 30} {'─' * 10} {'─' * 14} {'─' * 8}")
            for i, w in enumerate(phase3["top_winners"][:10], 1):
                print(f"  {i:<4} {w['nif']:<12} {w['name'][:28]:<30} {w['count']:>10} {fmt(w['value']):>14} {w['share_pct']:>7.1f}%")

    # NUTs breakdown
    if phase3.get("nuts_breakdown"):
        print(f"\n  🗺️  NUTS Region Breakdown")
        print(f"  {'─' * 60}")
        for n in phase3["nuts_breakdown"]:
            print(f"  {n['NUTs']:<15} {n['count']:>6} contracts ({fmt(n['value']):>10})")

    # Procedure breakdown
    if phase3.get("procedure_breakdown"):
        print(f"\n  📋 Procedure Type Breakdown")
        print(f"  {'─' * 60}")
        for p in phase3["procedure_breakdown"]:
            print(f"  {p['tipo'][:35]:<35} {p['count']:>6} contracts ({fmt(p['value']):>10})")

    print()


def print_chain(chain: dict):
    """Print the chain analysis — comparison across all 3 phases."""
    if "error" in chain:
        print(f"  ⚠️  Chain Analysis: {chain['error']}")
        return

    print(f"\n  {'=' * 100}")
    print(f"  MONEY TRAIL CHAIN — {chain['concelho']}")
    print(f"  {'=' * 100}")

    p = chain["phases"]

    # Visual chain diagram
    prr_str = f"PRR: {fmt(p['prr_allocation']['total'])} ({p['prr_allocation']['execution_rate']}% paid)"
    budget_str = f"Budget: {fmt(p['budget']['previsto'])} → {fmt(p['budget']['realizado'])}"
    proc_str = f"Procurement: {fmt(p['procurement']['total_value'])} ({p['procurement']['total_contracts']} contracts)"

    print(f"\n  Money Flow Diagram:\n")
    print(f"    🇪🇺  EU Funds")
    print(f"     ↓")
    print(f"    📋  {prr_str}")
    print(f"     ↓")
    print(f"    💶  {budget_str}")
    print(f"     ↓")
    print(f"    📦  {proc_str}")
    print()

    # Ratios
    prr_total = p["prr_allocation"]["total"]
    proc_total = p["procurement"]["total_value"]

    if prr_total > 0 and proc_total > 0:
        ratio = proc_total / prr_total
        print(f"  🧮 Chain Ratios:")
        print(f"      Procurement / PRR Allocation = {ratio:.2f}x")
        if ratio > 1.3:
            print(f"      ⚠️  This is above 1.0x — procurement spending exceeds PRR allocation")
            print(f"         (money may be coming from other sources or PRR is being matched)")
        elif ratio < 0.5:
            print(f"      ⚠️  This is below 0.5x — most PRR money hasn't reached procurement yet")

    # Anomalies
    if chain["anomalies"]:
        print(f"\n  🚨 Anomalies Detected ({chain['total_anomalies']} total, "
              f"{chain['critical_anomalies']} critical)")
        print(f"  {'─' * 80}")
        for a in chain["anomalies"]:
            icon = "🔴" if a["severity"] == "critical" else "🟡"
            print(f"  {icon} [{a['type']}] {a['detail']}")
    else:
        print(f"\n  ✅ No anomalies detected — money flows as expected")

    print()


def print_rankings(rankings: list[dict], top_n: int):
    """Print concelho rankings by PRR procurement."""
    if not rankings:
        print("No concelho data found.")
        return

    print(f"\n{'=' * 120}")
    print(f"  CONCELHO MONEY TRAIL RANKINGS — Top {min(top_n, len(rankings))} by PRR Allocation")
    print(f"  Phase 1: PRR → Concelho  |  Phase 3: Procurement  |  Chain: Ratio")
    print(f"{'=' * 120}")

    print(f"\n  {'#':<4} {'Concelho':<25} {'Distrito':<20} {'PRR Aprovado':>14} {'PRR Pago':>12} "
          f"{'Exec%':>7} {'Proc Value':>14} {'Ratio':>7}")
    print(f"  {'─' * 4} {'─' * 25} {'─' * 20} {'─' * 14} {'─' * 12} "
          f"{'─' * 7} {'─' * 14} {'─' * 7}")

    for i, r in enumerate(rankings[:top_n], 1):
        exec_pct = r["prr_execution_pct"]
        exec_icon = "🔴" if exec_pct < 50 else ("🟡" if exec_pct < 80 else "🟢")
        ratio = r.get("proc_to_prr_ratio", 0)
        ratio_str = f"{ratio:.1f}x" if ratio else "N/A"
        distrito = list(r.get("distritos", []))[0] if r.get("distritos") else ""
        print(f"  {i:<4} {r['concelho'][:23]:<25} {distrito[:18]:<20} "
              f"{fmt(r['prr_aprovado']):>14} {fmt(r['prr_pago']):>12} "
              f"{exec_icon}{exec_pct:>5.0f}% {fmt(r['proc_value']):>14} {ratio_str:>7}")

    print(f"\n{'=' * 120}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  EXPORT
# ═════════════════════════════════════════════════════════════════════════════

def export_trail(data: dict, path: str):
    """Export money trail analysis to JSON."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Exported to {out_path}")


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def cmd_concelho(args):
    """Run full money trail analysis for a single concelho."""
    check_dbs()

    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    concelho = args.concelho

    print(f"\n  🔍 Money Trail Analysis: {concelho}")
    print(f"  {'─' * 60}")

    # Phase 1 — PRR Allocation
    print(f"\n  Computing Phase 1 (PRR → {concelho})...", file=sys.stderr)
    phase1 = compute_phase1(conn, concelho)

    # Phase 2 — Budget Execution
    print(f"  Computing Phase 2 (Budget → {concelho})...", file=sys.stderr)
    phase2 = compute_phase2(conn, concelho)

    # Phase 3 — Procurement
    print(f"  Computing Phase 3 (Procurement → {concelho})...", file=sys.stderr)
    prr_nifs = set(e["nif"] for e in phase1.get("prr_entities", []) if e.get("nif"))
    nuts_codes = phase1.get("nuts3_codes", [])
    phase3 = compute_phase3(proc_conn, concelho, prr_nifs, nuts_codes)

    # Chain analysis
    print(f"  Computing chain analysis...", file=sys.stderr)
    chain = compute_chain(phase1, phase2, phase3)

    conn.close()
    proc_conn.close()

    # Print report
    print_phase1(phase1)
    print_phase2(phase2, concelho)
    print_phase3(phase3)
    print_chain(chain)

    # Export
    if args.export:
        export_data = {
            "concelho": concelho,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "phase1_prr": phase1,
            "phase2_budget": phase2,
            "phase3_procurement": phase3,
            "chain": chain,
        }
        export_trail(export_data, args.export)

    # Verbose output: show individual PRR contracts
    if args.verbose and "error" not in phase1:
        prr_contracts = phase1.get("prr_contracts", [])
        if prr_contracts:
            print(f"\n  📋 PRR Contracts Flowing to {concelho} ({len(prr_contracts)} total)")
            print(f"  {'─' * 95}")
            print(f"  {'Contract':<25} {'Value':>12} {'Date':>12} {'cd_base_gov':<15} {'Project':<30}")
            print(f"  {'─' * 25} {'─' * 12} {'─' * 12} {'─' * 15} {'─' * 30}")
            for c in prr_contracts[:20]:
                print(f"  {c['cd_contrato'][:23]:<25} {fmt(c['montante']):>12} "
                      f"{c['dt_assinatura'][:10]:>12} {c['cd_base_gov']:<15} "
                      f"{c['ds_projeto'][:28]:<30}")
            if len(prr_contracts) > 20:
                print(f"  ... and {len(prr_contracts) - 20} more contracts")


def cmd_rank(args):
    """Rank all concelhos by PRR allocation."""
    check_dbs()

    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    print(f"\n  Computing concelho rankings...", file=sys.stderr)
    rankings = rank_concelhos(conn, proc_conn, top_n=args.top)
    print_rankings(rankings, args.top)

    conn.close()
    proc_conn.close()

    if args.export:
        export_trail({"rankings": rankings, "analyzed_at": datetime.now(timezone.utc).isoformat()}, args.export)

    return rankings


def main():
    parser = argparse.ArgumentParser(
        description="Money Trail Analyzer — Trace PRR → Budget → Procurement pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python money_trail_analyzer.py                         # Top 20 concelhos
              python money_trail_analyzer.py --concelho "Fundão"      # Single concelho
              python money_trail_analyzer.py --concelho "Fundão" --verbose
              python money_trail_analyzer.py --concelho "Fundão" --export trail.json
              python money_trail_analyzer.py --rank --top 50
        """),
    )

    parser.add_argument("--concelho", help="Concelho name for deep-dive analysis")
    parser.add_argument("--rank", action="store_true", help="Rank all concelhos by PRR allocation")
    parser.add_argument("--top", type=int, default=20, help="Top N results (default 20)")
    parser.add_argument("--export", help="Export results to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed PRR contracts")

    args = parser.parse_args()

    if args.concelho:
        cmd_concelho(args)
    elif args.rank:
        cmd_rank(args)
    else:
        # Default: show rankings
        cmd_rank(args)


if __name__ == "__main__":
    main()
