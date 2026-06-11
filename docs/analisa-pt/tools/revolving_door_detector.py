#!/usr/bin/env python3
"""Revolving Door Detector — Cross-reference DRE appointments with procurement contracts.

Detects conflicts of interest by finding temporal proximity between:
  1. A person is appointed to a public position (DRE → appointments table)
  2. That organization then awards contracts to specific companies
  3. The temporal gap between appointment and contract award

Risk signals:
  • Contract awarded within 3 months of appointment → Critical (+40)
  • Same company wins multiple contracts after a single appointment → High (+25)
  • Company had no prior contracts with buyer before appointment → High (+20)
  • Individual (not company) receives contracts → Medium (+15)
  • Contracts show price inflation → High (+15)
  • PRR beneficiary ↔ procurement buyer overlap → Medium (+10)

Data Sources:
  - vespeiro.db (backend) — structured appointments with organization, role, date
  - dre_index.db — broader DRE publication index (fallback)
  - procurement.db — 244K contracts with buyer, winner, date, price

Usage:
    python revolving_door_detector.py                     # Top 30 chains
    python revolving_door_detector.py --top 50            # Top 50
    python revolving_door_detector.py --min-score 50      # Only high-risk
    python revolving_door_detector.py --export doors.json
    python revolving_door_detector.py --person "Maria"    # Find specific person
    python revolving_door_detector.py --org "Fundão"      # Find specific org
"""

import json
import os
import re
import sqlite3
import argparse
import sys
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from utils import fmt

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"

# Vespeiro database path — configurable via env var ANALISA_VESPEIRO_DB
# Default: looks in ../../backend/data/vespeiro.db relative to this file
_DEFAULT_VESPEIRO_DB = SCRIPT_DIR.parent.parent / "backend" / "data" / "vespeiro.db"
VESPEIRO_DB = Path(os.environ.get("ANALISA_VESPEIRO_DB", str(_DEFAULT_VESPEIRO_DB)))

PROCUREMENT_DB = DATA_DIR / "procurement.db"
DRE_DB = DATA_DIR / "dre_index.db"
TRANSPARENCY_DB = DATA_DIR / "transparency.db"


def check_dbs(cli_path_provided: bool = False):
    """Verify required databases exist."""
    missing = []
    if not VESPEIRO_DB.exists():
        if cli_path_provided:
            hint = f"\n  Path provided via --vespeiro-db does not exist: {VESPEIRO_DB}"
        elif "ANALISA_VESPEIRO_DB" in os.environ:
            hint = f"\n  ANALISA_VESPEIRO_DB env var points to non-existent file: {VESPEIRO_DB}"
        else:
            hint = (
                "\n  To fix, either:\n"
                "    1. Set ANALISA_VESPEIRO_DB env var to point at vespeiro.db.\n"
                "    2. Run: python revolving_door_detector.py --vespeiro-db <path to vespeiro.db>\n"
                "    3. Ensure vespeiro DRE spider has been run to collect appointments."
            )
        missing.append(f"vespeiro.db not found at {VESPEIRO_DB}{hint}")
    if not PROCUREMENT_DB.exists():
        missing.append(f"procurement.db not found at {PROCUREMENT_DB}")
    if missing:
        for m in missing:
            print(f"ERROR: {m}")
        sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ═════════════════════════════════════════════════════════════════════════════

def load_appointments() -> list[dict]:
    """Load all appointments from vespeiro.db with person names.

    Joins appointments.organization + role with people.name.
    """
    conn = sqlite3.connect(str(VESPEIRO_DB))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT a.id, a.person_id, a.organization, a.role,
               a.appointing_body, a.appointment_type,
               a.published_at, a.confidence,
               p.name as person_name
        FROM appointments a
        JOIN people p ON a.person_id = p.id
        WHERE a.organization != '' AND a.organization IS NOT NULL
        ORDER BY a.published_at DESC
    """).fetchall()

    result = []
    for r in rows:
        pub_date = None
        if r["published_at"]:
            try:
                pub_date = r["published_at"]
                if isinstance(pub_date, str):
                    pub_date = pub_date[:10]  # YYYY-MM-DD
            except (ValueError, TypeError):
                pub_date = None

        result.append({
            "id": r["id"],
            "person_id": r["person_id"],
            "person_name": r["person_name"],
            "organization": r["organization"],
            "role": r["role"] or "",
            "appointing_body": r["appointing_body"] or "",
            "appointment_type": r["appointment_type"] or "",
            "published_at": pub_date,
            "confidence": r["confidence"],
        })

    conn.close()

    # Also try dre_index.db for broader coverage
    if DRE_DB.exists():
        try:
            dre_conn = sqlite3.connect(str(DRE_DB))
            dre_conn.row_factory = sqlite3.Row
            # Look for publication titles that mention appointments (nomeação)
            dre_rows = dre_conn.execute("""
                SELECT pub_id, title, publication_date, serie, year
                FROM dre_publications
                WHERE title LIKE '%nomeação%' OR title LIKE '%Nomeação%'
                   OR title LIKE '%designa%' OR title LIKE '%Designa%'
                   OR title LIKE '%nomeia%' OR title LIKE '%Nomeia%'
                ORDER BY year DESC, serie DESC
                LIMIT 200
            """).fetchall()

            for r in dre_rows:
                existing_ids = {a["id"] for a in result}
                pub_id = f"dre_{r['pub_id']}"
                if pub_id not in existing_ids:
                    # Extract organization name from title (use first part before keywords)
                    title = r["title"] or ""
                    org_guess = title.split(",")[0].split(";")[0][:100] if title else ""

                    result.append({
                        "id": pub_id,
                        "person_id": f"dre_pub_{r['pub_id']}",
                        "person_name": _extract_person_name_from_title(title),
                        "organization": org_guess or f"DRE Série {r['serie']} {r['year']}",
                        "role": title[:150] if title else "Nomeação",
                        "appointing_body": "",
                        "appointment_type": "dre_publication",
                        "published_at": r["publication_date"][:10] if r["publication_date"] else None,
                        "confidence": 0.5,
                        "source": "dre_index",
                    })

            dre_conn.close()
        except (sqlite3.OperationalError, Exception):
            pass  # dre_index.db may not have the expected schema

    return result


def _extract_person_name_from_title(title: str) -> str:
    """Extract a person name from a DRE publication title.

    Portuguese DRE titles often contain names in patterns like:
    "Nomeia [Name] para o cargo de ..."
    "Designa [Name] como ..."
    """
    if not title:
        return "Unknown"

    # Pattern: "Nomeia/Nomeiam [Full Name] para"
    m = re.search(r'(?:Nomeia|Nomeiam|nomeia|nomeiam|Designa|designa)\s+'
                  r'([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)+)',
                  title)
    if m:
        return m.group(1).strip()

    # Pattern: "nomeação de [Name]"
    m = re.search(r'(?:nomeação|Nomeação)\s+de\s+'
                  r'([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)+)',
                  title)
    if m:
        return m.group(1).strip()

    # Fallback: first 2-3 uppercase words might be a name
    words = title.split()
    name_words = []
    for w in words[:4]:
        if w[0].isupper() and len(w) > 1:
            name_words.append(w)
        elif name_words and len(name_words) >= 2:
            break
    if len(name_words) >= 2:
        return " ".join(name_words)

    return title[:50]


# ── Organization name matching ────────────────────────────────────────────────

# Portuguese municipality naming patterns for matching appointments → procurement
_ORG_PATTERNS = [
    "Município de", "Município do", "Município da",
    "Câmara Municipal de", "Câmara Municipal do", "Câmara Municipal da",
    "Câmara de", "Câmara do",
    "Junta de Freguesia de", "Junta de Freguesia do", "Junta de Freguesia da",
    "Freguesia de", "Freguesia do",
    "Câmara",
    "Município",
]


def _normalize_org_name(name: str) -> str:
    """Normalize an organization name for matching."""
    name = name.lower().strip()
    # Remove common prefixes for matching
    for prefix in _ORG_PATTERNS:
        prefix_lower = prefix.lower()
        if name.startswith(prefix_lower):
            name = name[len(prefix_lower):].strip()
            break
    # Remove trailing suffixes
    for suffix in [",", ";", "-", "–", "—", "("]:
        if suffix in name:
            name = name.split(suffix)[0].strip()
    return name


def _org_name_matches(appointment_org: str, procurement_name: str) -> int:
    """Score how well two organization names match.

    Returns 0 (no match) to 3 (exact match).
    """
    if not appointment_org or not procurement_name:
        return 0

    a_lower = appointment_org.lower().strip()
    p_lower = procurement_name.lower().strip()

    # Exact match
    if a_lower == p_lower:
        return 3

    # One contains the other
    if a_lower in p_lower or p_lower in a_lower:
        return 2

    # Normalized match: strip prefix/suffix and compare core
    a_norm = _normalize_org_name(a_lower)
    p_norm = _normalize_org_name(p_lower)

    if a_norm and p_norm:
        if a_norm == p_norm:
            return 3
        if a_norm in p_norm or p_norm in a_norm:
            return 2
        # Check if significant word overlap
        a_words = set(a_norm.split())
        p_words = set(p_norm.split())
        overlap = a_words & p_words
        if len(overlap) >= 2 and len(overlap) / max(len(a_words), len(p_words)) > 0.3:
            return 1

    return 0


def find_matching_buyer_nifs(proc_conn, organization: str) -> list[dict]:
    """Find procurement buyer NIFs whose name matches a DRE organization.

    Uses progressive matching: exact → contains → normalized word overlap.
    Returns list of {nif, name, match_score}.
    """
    if not organization:
        return []

    org_lower = organization.lower().strip()

    # Strategy 1: Direct LIKE match
    results = []
    seen_nifs = set()

    rows = proc_conn.execute(
        "SELECT DISTINCT adjudicante_nif, adjudicante_nome, COUNT(*) as cnt "
        "FROM contratos "
        "WHERE adjudicante_nome LIKE ? AND adjudicante_nif != '' "
        "AND adjudicante_nif != '-' AND adjudicante_nif IS NOT NULL "
        "GROUP BY adjudicante_nif ORDER BY cnt DESC",
        (f"%{org_lower}%",)
    ).fetchall()

    for r in rows:
        score = _org_name_matches(organization, r[1])
        if score >= 2 and r[0] not in seen_nifs:
            results.append({"nif": r[0], "name": r[1], "match_score": score, "contracts": r[2]})
            seen_nifs.add(r[0])

    # Strategy 2: Parse each pattern prefix
    if not results:
        norm = _normalize_org_name(organization)
        if norm and len(norm) >= 4:
            for prefix in _ORG_PATTERNS:
                search_name = f"{prefix} {norm[:30]}"
                rows = proc_conn.execute(
                    "SELECT DISTINCT adjudicante_nif, adjudicante_nome, COUNT(*) as cnt "
                    "FROM contratos WHERE adjudicante_nome LIKE ? AND adjudicante_nif != '' "
                    "AND adjudicante_nif != '-' AND adjudicante_nif IS NOT NULL "
                    "GROUP BY adjudicante_nif ORDER BY cnt DESC LIMIT 1",
                    (f"%{search_name}%",)
                ).fetchall()
                for r in rows:
                    if r[0] not in seen_nifs:
                        score = _org_name_matches(organization, r[1])
                        results.append({"nif": r[0], "name": r[1], "match_score": score, "contracts": r[2]})
                        seen_nifs.add(r[0])

    results.sort(key=lambda x: (-x["match_score"], -x["contracts"]))
    return results


def find_contracts_after_date(proc_conn, buyer_nifs: set, after_date: str) -> list[dict]:
    """Find contracts awarded by a set of buyers after a specific date."""
    if not buyer_nifs or not after_date:
        return []

    placeholders = ",".join("?" * len(buyer_nifs))
    nif_list = list(buyer_nifs)

    nif_pattern = re.compile(r"\b(\d{9})\b")

    rows = proc_conn.execute(
        f"SELECT idcontrato, adjudicante_nif, adjudicante_nome, "
        f"adjudicatarios, COALESCE(precoContratual, 0), "
        f"dataCelebracaoContrato, objectoContrato, tipoprocedimento, "
        f"CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        f"    THEN 1 ELSE 0 END as inflated, "
        f"CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        f"    THEN precoContratual - precoBaseProcedimento ELSE 0 END as overrun "
        f"FROM contratos "
        f"WHERE adjudicante_nif IN ({placeholders}) "
        f"AND dataCelebracaoContrato >= ? "
        f"AND dataCelebracaoContrato != '' "
        f"AND dataCelebracaoContrato IS NOT NULL "
        f"AND adjudicatarios IS NOT NULL AND adjudicatarios != '' "
        f"ORDER BY dataCelebracaoContrato",
        nif_list + [after_date]
    ).fetchall()

    results = []
    for r in rows:
        adj_text = r[3]
        supplier_nifs = set(nif_pattern.findall(adj_text))
        # Extract supplier names from "NIF - Name" format
        supplier_names = re.findall(r"\d{9}\s*-\s*([^;]+)", adj_text)

        suppliers = []
        for i, snif in enumerate(supplier_nifs):
            sname = supplier_names[i].strip() if i < len(supplier_names) else snif
            suppliers.append({"nif": snif, "name": sname})

        results.append({
            "idcontrato": r[0],
            "buyer_nif": r[1],
            "buyer_name": r[2],
            "suppliers": suppliers,
            "value": r[4],
            "date": r[5],
            "object": (r[6] or "")[:100],
            "procedure": r[7] or "",
            "inflated": bool(r[8]),
            "overrun": r[9],
        })

    return results


def _days_between(date1: str, date2: str) -> int:
    """Compute days between two date strings (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."""
    try:
        d1 = datetime.strptime(date1[:10], "%Y-%m-%d")
        d2 = datetime.strptime(date2[:10], "%Y-%m-%d")
        return abs((d2 - d1).days)
    except (ValueError, TypeError):
        return 99999


def check_prior_history(proc_conn, buyer_nif: str, supplier_nif: str,
                        before_date: str, lookback_years: int = 3) -> dict:
    """Check if a supplier had contracts with this buyer before the appointment date.

    Returns dict with prior_history (bool), prior_count, prior_value.
    """
    if not before_date or len(before_date) < 10:
        return {"prior_history": True, "prior_count": 0, "prior_value": 0}

    # Calculate lookback date
    try:
        year = int(before_date[:4]) - lookback_years
        lookback = f"{year}-{before_date[5:]}"
    except (ValueError, IndexError):
        lookback = "2020-01-01"

    rows = proc_conn.execute(
        "SELECT COUNT(*) as cnt, SUM(COALESCE(precoContratual, 0)) as val "
        "FROM contratos WHERE adjudicante_nif = ? "
        "AND adjudicatarios LIKE ? "
        "AND dataCelebracaoContrato >= ? "
        "AND dataCelebracaoContrato < ?",
        (buyer_nif, f"%{supplier_nif}%", lookback, before_date)
    ).fetchone()

    prior_count = rows[0] or 0
    prior_value = rows[1] or 0

    return {
        "prior_history": prior_count > 0,
        "prior_count": prior_count,
        "prior_value": prior_value,
    }


def check_dual_role(conn, nif: str) -> dict:
    """Check if a NIF appears in PRR data (potential dual-role signal)."""
    try:
        if not TRANSPARENCY_DB.exists():
            return {"in_prr": False}
        prr_conn = sqlite3.connect(str(TRANSPARENCY_DB))
        row = prr_conn.execute(
            "SELECT COUNT(*) FROM prr_entities WHERE nif = ?", (nif,)
        ).fetchone()
        prr_conn.close()
        return {"in_prr": (row[0] if row else 0) > 0}
    except Exception:
        return {"in_prr": False}


def compute_chain_score(appointment: dict, contracts: list[dict], proc_conn) -> list[dict]:
    """Score each supplier chain for risk.

    For each unique supplier that wins contracts after an appointment,
    compute a risk score based on:
    - Temporal proximity (days between appointment and first contract)
    - Number of contracts won after appointment
    - Prior history with buyer (or lack thereof)
    - Price inflation in post-appointment contracts
    - PRR dual-role status
    """
    if not contracts:
        return []

    # Group by supplier NIF
    by_supplier = defaultdict(lambda: {
        "contracts": [], "total_value": 0, "inflated_count": 0,
        "total_overrun": 0, "first_date": None,
    })

    for c in contracts:
        for s in c["suppliers"]:
            g = by_supplier[s["nif"]]
            g["name"] = s["name"]
            g["contracts"].append(c)
            g["total_value"] += c["value"]
            if c["inflated"]:
                g["inflated_count"] += 1
                g["total_overrun"] += c["overrun"]
            if g["first_date"] is None or c["date"] < g["first_date"]:
                g["first_date"] = c["date"]

    appointment_date = appointment.get("published_at", "")
    results = []

    for supplier_nif, data in by_supplier.items():
        if not data["first_date"]:
            continue

        score = 0
        risk_factors = []

        # Factor 1: Temporal proximity (0-40 points)
        days = _days_between(appointment_date, data["first_date"])
        if days <= 30:
            score += 40
            risk_factors.append(f"Contract within 30 days of appointment ({days}d)")
        elif days <= 90:
            score += 35
            risk_factors.append(f"Contract within 3 months of appointment ({days}d)")
        elif days <= 180:
            score += 25
            risk_factors.append(f"Contract within 6 months of appointment ({days}d)")
        elif days <= 365:
            score += 15
            risk_factors.append(f"Contract within 1 year of appointment ({days}d)")
        elif days <= 730:
            score += 5
            risk_factors.append(f"Contract within 2 years ({days}d)")

        # Factor 2: Multiple contracts after appointment (0-25 points)
        if len(data["contracts"]) >= 5:
            score += 25
            risk_factors.append(f"{len(data['contracts'])} contracts after appointment")
        elif len(data["contracts"]) >= 3:
            score += 15
        elif len(data["contracts"]) >= 2:
            score += 5

        # Factor 3: No prior history with buyer (0-20 points)
        matched = appointment.get("matched_nifs", [])
        buyer_nif = matched[0]["nif"] if matched else None
        history = check_prior_history(
            proc_conn, buyer_nif, supplier_nif, appointment_date
        )
        if not history["prior_history"] and data["total_value"] > 10000:
            score += 20
            risk_factors.append("No prior contracts with buyer before appointment")
        elif not history["prior_history"]:
            score += 10
            risk_factors.append("No prior history — new supplier after appointment")

        # Factor 4: Price inflation (0-15 points)
        if data["inflated_count"] >= 2:
            score += 15
            risk_factors.append(f"{data['inflated_count']} inflated contracts (+{fmt(data['total_overrun'])})")
        elif data["inflated_count"] >= 1:
            score += 10
            risk_factors.append(f"Inflated contract (+{fmt(data['total_overrun'])})")

        # Factor 5: PRR dual-role (0-10 points)
        dual = check_dual_role(None, supplier_nif)
        if dual.get("in_prr"):
            score += 10
            risk_factors.append("Also a PRR beneficiary")

        # Factor 6: Individual (not company) as winner (0-15 points)
        # Individuals typically don't have 9-digit NIFs — but some do
        # Check if name looks like an individual person (2-3 words, no "Lda", "SA", etc.)
        company_indicators = ["lda", "sa", "s.a", "unipessoal", "sociedade", "grupo", "construções",
                              "empresa", "serviços", "obras", "empreendimentos", "investimentos"]
        name_lower = data["name"].lower()
        is_individual = not any(ind in name_lower for ind in company_indicators) and len(name_lower.split()) <= 4
        if is_individual and data["total_value"] > 50000:
            score += 15
            risk_factors.append(f"Individual (not company) wins contracts: {data['name']}")

        score = min(100, score)

        # Find the earliest contract date for display
        first_contract = min(data["contracts"], key=lambda c: c["date"])
        days_from_appt = _days_between(appointment_date, first_contract["date"])

        results.append({
            "supplier_nif": supplier_nif,
            "supplier_name": data["name"],
            "risk_score": round(score, 1),
            "risk_factors": risk_factors,
            "days_from_appointment": days_from_appt,
            "total_contracts": len(data["contracts"]),
            "total_value": data["total_value"],
            "inflated_count": data["inflated_count"],
            "total_overrun": data["total_overrun"],
            "first_contract_date": first_contract["date"],
            "first_contract_value": first_contract["value"],
            "first_contract_object": first_contract["object"][:80],
        })

    results.sort(key=lambda x: -x["risk_score"])
    return results


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def analyze_revolving_doors(top_n: int = 30, min_score: float = 0,
                            person_filter: str = "", org_filter: str = "",
                            cli_path_provided: bool = False) -> list[dict]:
    """Main analysis: find all revolving door chains.

    Returns list of chains, each containing:
    - appointment details (person, org, role, date)
    - matched buyer NIFs from procurement
    - supplier chains with risk scores
    """
    check_dbs(cli_path_provided=cli_path_provided)

    proc_conn = sqlite3.connect(str(PROCUREMENT_DB))

    print("Loading appointments from vespeiro.db...", file=sys.stderr)
    appointments = load_appointments()
    print(f"  Loaded {len(appointments)} appointments", file=sys.stderr)

    if person_filter:
        appointments = [a for a in appointments if person_filter.lower() in a["person_name"].lower()]
        print(f"  Filtered to {len(appointments)} matching person '{person_filter}'", file=sys.stderr)

    if org_filter:
        appointments = [a for a in appointments if org_filter.lower() in a["organization"].lower()]
        print(f"  Filtered to {len(appointments)} matching org '{org_filter}'", file=sys.stderr)

    chains = []

    for i, appt in enumerate(appointments):
        if (i + 1) % 10 == 0:
            print(f"  Processing appointment {i + 1}/{len(appointments)}...", file=sys.stderr)

        org = appt["organization"]
        appt_date = appt.get("published_at", "")

        if not appt_date or not org:
            continue

        # Find matching buyer NIFs in procurement
        matched_buyers = find_matching_buyer_nifs(proc_conn, org)
        if not matched_buyers:
            continue

        appt["matched_nifs"] = matched_buyers

        # Find contracts awarded after appointment date
        buyer_nifs = set(b["nif"] for b in matched_buyers)
        contracts = find_contracts_after_date(proc_conn, buyer_nifs, appt_date)

        if not contracts:
            continue

        # Score each supplier chain
        supplier_chains = compute_chain_score(appt, contracts, proc_conn)
        supplier_chains = [s for s in supplier_chains if s["risk_score"] >= min_score]

        if supplier_chains:
            chains.append({
                "appointment": {
                    "person_name": appt["person_name"],
                    "organization": org,
                    "role": appt["role"],
                    "appointing_body": appt["appointing_body"],
                    "date": appt_date,
                    "confidence": appt["confidence"],
                },
                "matched_buyers": matched_buyers,
                "total_supplier_chains": len(supplier_chains),
                "supplier_chains": supplier_chains[:5],  # Top 5 per appointment
                "max_risk_score": max(s["risk_score"] for s in supplier_chains),
            })

    proc_conn.close()

    chains.sort(key=lambda c: -c["max_risk_score"])
    return chains[:top_n]


# ═════════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ═════════════════════════════════════════════════════════════════════════════

def print_report(chains: list[dict], top_n: int):
    """Print the revolving door report."""
    if not chains:
        print("\n  No revolving door chains found.")
        print("  Ensure vespeiro.db has appointment data (run DRE spider) and procurement.db exists.")
        return

    total_appointments_analyzed = len(chains)
    total_chains = sum(c["total_supplier_chains"] for c in chains)

    print(f"\n{'=' * 110}")
    print(f"  REVOLVING DOOR DETECTOR — Top {min(top_n, len(chains))} Chains by Risk Score")
    print(f"  DRE appointments → Procurement contracts = Conflict of interest signals")
    print(f"{'=' * 110}")

    print(f"\n  📊 Overview")
    print(f"  {'─' * 40}")
    print(f"  Appointments with matching procurement: {total_appointments_analyzed}")
    print(f"  Total supplier chains found: {total_chains}")
    print(f"  Top chains shown: {min(top_n, len(chains))}")

    print(f"\n  {'─' * 108}")
    print(f"  {'#':<4} {'Score':>6} {'Days':>5} {'Person':<30} {'Organization':<35} {'Supplier':<25}")
    print(f"  {'─' * 4} {'─' * 6} {'─' * 5} {'─' * 30} {'─' * 35} {'─' * 25}")

    for i, chain in enumerate(chains[:top_n], 1):
        appt = chain["appointment"]
        top_supplier = chain["supplier_chains"][0]
        icon = "🔴" if top_supplier["risk_score"] >= 70 else ("🟡" if top_supplier["risk_score"] >= 40 else "🟢")
        print(f"  {i:<4} {icon}{top_supplier['risk_score']:>5.0f} {top_supplier['days_from_appointment']:>5}d "
              f"{appt['person_name'][:28]:<30} {appt['organization'][:33]:<35} "
              f"{top_supplier['supplier_name'][:23]:<25}")

    # Detailed view for top chains
    print(f"\n\n{'=' * 110}")
    print(f"  DETAILED CHAINS — Top {min(10, len(chains))}")
    print(f"{'=' * 110}")

    for i, chain in enumerate(chains[:10], 1):
        appt = chain["appointment"]
        print(f"\n{'─' * 100}")
        print(f"  [{i}] {appt['person_name']} → {appt['organization']} ({appt['role'][:50]})")
        print(f"      Appointed: {appt['date']}  |  Confidence: {appt['confidence']}")
        if appt.get("appointing_body"):
            print(f"      Appointing body: {appt['appointing_body']}")

        print(f"      Matched buyers: {', '.join(b['name'][:40] for b in chain['matched_buyers'][:2])}")

        print(f"      Supplier chains: {chain['total_supplier_chains']} total")
        for j, sc in enumerate(chain["supplier_chains"]):
            icon = "🔴" if sc["risk_score"] >= 70 else ("🟡" if sc["risk_score"] >= 40 else "🟢")
            print(f"      {icon} [{j + 1}] {sc['supplier_name'][:40]:40s} "
                  f"Score: {sc['risk_score']:.0f}  "
                  f"{sc['days_from_appointment']}d after appointment  "
                  f"{fmt(sc['total_value'])}  ({sc['total_contracts']} contracts)")
            for factor in sc["risk_factors"][:3]:
                print(f"            ⚠️  {factor}")
            if sc["first_contract_object"]:
                print(f"            First contract: {sc['first_contract_object'][:70]}")

    print(f"\n{'=' * 110}\n")


def export_results(chains: list[dict], path: str):
    """Export revolving door chains to JSON."""
    export = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_appointments_matched": len(chains),
        "total_chains": sum(c["total_supplier_chains"] for c in chains),
        "chains": chains,
    }
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2, default=str)
    print(f"Exported {len(chains)} chains to {out_path}")


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Revolving Door Detector — DRE appointments × procurement contracts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python revolving_door_detector.py                    # Top 30 chains
              python revolving_door_detector.py --top 50
              python revolving_door_detector.py --min-score 50     # Only high-risk
              python revolving_door_detector.py --person "Maria"   # Find specific person
              python revolving_door_detector.py --org "Fundão"     # Find specific org
              python revolving_door_detector.py --vespeiro-db /path/to/vespeiro.db
              python revolving_door_detector.py --export doors.json
        """),
    )

    parser.add_argument("--top", "-t", type=int, default=30, help="Show top N chains (default 30)")
    parser.add_argument("--min-score", type=float, default=0, help="Minimum risk score (default 0)")
    parser.add_argument("--export", help="Export results to JSON")
    parser.add_argument("--person", help="Filter by person name")
    parser.add_argument("--org", help="Filter by organization name")
    parser.add_argument("--vespeiro-db", help="Path to vespeiro.db (overrides ANALISA_VESPEIRO_DB env var and default path)")

    args = parser.parse_args()

    cli_path_provided = args.vespeiro_db is not None
    global VESPEIRO_DB
    if cli_path_provided:
        VESPEIRO_DB = Path(args.vespeiro_db)

    print(f"  Scanning revolving doors (this may take a minute)...", file=sys.stderr)
    chains = analyze_revolving_doors(
        top_n=args.top,
        min_score=args.min_score,
        person_filter=args.person,
        org_filter=args.org,
        cli_path_provided=cli_path_provided,
    )

    print_report(chains, args.top)

    if args.export:
        export_results(chains, args.export)


if __name__ == "__main__":
    main()
