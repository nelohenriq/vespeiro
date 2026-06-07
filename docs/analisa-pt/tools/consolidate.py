#!/usr/bin/env python3
"""Consolidate Data Pipeline — Collect ALL tool outputs into a single JSON.

Reads export files from all analysis tools and consolidates into one
structured JSON with 8 category buckets for the dashboard.

Categories:
  1. risk_anomalies     — Entity risk scores, municipality rankings, critical flags
  2. financial          — PRR money trail, price inflation, overruns, contract mods
  3. temporal           — Daily/weekly bursts, year-end surges, election timing
  4. procurement_patterns — Rotating winners, bid suppression, closed ecosystems
  5. entities_networks  — Dual-role entities, supplier concentration, exclusive cos
  6. cross_references   — PRR×BASE, TED, BEP, Laws correlations
  7. personnel          — Revolving doors, DRE appointments
  8. alerts             — New contracts detected, threshold breaches

Usage:
    python consolidate.py --from-exports                # Read all data/summary/*.json files
    python consolidate.py --from-exports --dir ./exports # Read from custom directory
    python consolidate.py --run                         # Run each tool (experimental)
    python consolidate.py --out dashboard.json           # Custom output path
    python consolidate.py --incremental fundao.json     # Merge with existing output
    python consolidate.py --list-tools                  # List all known tools and their categories
    python consolidate.py --validate-out existing.json  # Validate an existing consolidated file
"""

import json
import sys
import argparse
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# Size estimate for summary output
_KB = 1024

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SUMMARY_DIR = DATA_DIR / "summary"
TOOLS_DIR = SCRIPT_DIR

# ── Tool Registry ────────────────────────────────────────────────────────────
# Each tool: { command, export_flag, category, default_export_path, description }

TOOL_REGISTRY = {
    "anomaly_scanner": {
        "category": "risk_anomalies",
        "description": "Multi-signal anomaly scanner — price inflation, self-referencing, dominance, etc.",
        "default_export": SUMMARY_DIR / "anomalies.json",
        "run_cmd": ("python", "anomaly_scanner.py", "--export"),
    },
    "municipality_risk": {
        "category": "risk_anomalies",
        "description": "Municipality procurement risk ranking — concentration + inflation + direct award",
        "default_export": SUMMARY_DIR / "municipality_risk.json",
        "run_cmd": ("python", "municipality_risk_report.py", "--export"),
    },
    "bid_patterns": {
        "category": "procurement_patterns",
        "description": "Bid pattern analysis — rotating winners, closed groups, bid suppression",
        "default_export": SUMMARY_DIR / "bid_patterns.json",
        "run_cmd": ("python", "bid_pattern_analyzer.py", "--export"),
    },
    "temporal_clusters": {
        "category": "temporal",
        "description": "Temporal clustering — daily bursts, weekly bursts, year-end surge, buyer bursts",
        "default_export": SUMMARY_DIR / "temporal_bursts.json",
        "run_cmd": ("python", "temporal_clustering.py", "--export"),
    },
    "prr_dual_role": {
        "category": "entities_networks",
        "description": "PRR × Procurement dual-role analysis — entities in both systems",
        "default_export": SUMMARY_DIR / "prr_dual_role.json",
        "run_cmd": ("python", "prr_procurement_crossref.py", "--export"),
    },
    "prr_enhanced": {
        "category": "cross_references",
        "description": "Enhanced PRR × BASE detector — cd_base_gov + text similarity matching",
        "default_export": SUMMARY_DIR / "enhanced_scan.json",
        "run_cmd": ("python", "prr_base_cdgov_detector.py", "all", "--export"),
    },
    "money_trail": {
        "category": "financial",
        "description": "Money trail analyzer — PRR → Budget → Procurement pipeline per concelho",
        "default_export": SUMMARY_DIR / "fundao_trail.json",
        "run_cmd": ("python", "money_trail_analyzer.py", "--concelho", "Fundão", "--export"),
    },
    "revolving_doors": {
        "category": "personnel",
        "description": "Revolving door detector — DRE appointments × procurement contracts",
        "default_export": SUMMARY_DIR / "fundao_doors.json",
        "run_cmd": ("python", "revolving_door_detector.py", "--export"),
    },
    "price_gaps": {
        "category": "financial",
        "description": "Price gap analysis — base price vs final price comparison",
        "default_export": SUMMARY_DIR / "price_gaps.json",
        "run_cmd": ("python", "price_gap_analysis.py", "--export"),
    },
    "entity_network": {
        "category": "entities_networks",
        "description": "Entity relationship network — buyer-seller graph and self-referencing",
        "default_export": SUMMARY_DIR / "entity_network.json",
        "run_cmd": ("python", "entity_network.py", "export"),
    },
    "ted_crossref": {
        "category": "cross_references",
        "description": "TED (EU procurement) cross-reference — Portuguese contracts in EU tender data",
        "default_export": SUMMARY_DIR / "ted_crossref.json",
        "run_cmd": ("python", "ted_crossref.py", "export"),
    },
    "bep_crossref": {
        "category": "cross_references",
        "description": "BEP × Procurement cross-reference — job listings vs procurement activity",
        "default_export": SUMMARY_DIR / "bep_crossref.json",
        "run_cmd": ("python", "bep_procurement_crossref.py", "export"),
    },
    "contract_mods": {
        "category": "financial",
        "description": "Contract modifications analyzer — post-award price changes",
        "default_export": SUMMARY_DIR / "contract_modifications.json",
        "run_cmd": ("python", "contract_modifications_analyzer.py", "export"),
    },
    "contract_alerts": {
        "category": "alerts",
        "description": "Contract alert system — new contracts detected for watched entities",
        "default_export": SUMMARY_DIR / "contract_alerts.json",
        "run_cmd": ("python", "contract_alerts.py", "history"),
    },
    "law_hiring": {
        "category": "cross_references",
        "description": "Laws × BEP hiring correlation — legislation and public sector hiring",
        "default_export": SUMMARY_DIR / "law_hiring.json",
        "run_cmd": ("python", "law_hiring_correlation.py", "--export"),
    },
}

# ── Category Definitions ────────────────────────────────────────────────────

CATEGORIES = [
    {
        "id": "risk_anomalies",
        "label": "Risk & Anomalies",
        "icon": "🚨",
        "description": "Entity risk scores, municipality rankings, critical flags",
        "tools": ["anomaly_scanner", "municipality_risk"],
    },
    {
        "id": "financial",
        "label": "Financial",
        "icon": "💰",
        "description": "PRR money trail, price inflation, overruns, contract modifications",
        "tools": ["money_trail", "price_gaps", "contract_mods"],
    },
    {
        "id": "temporal",
        "label": "Temporal",
        "icon": "📅",
        "description": "Daily/weekly bursts, year-end surges, election timing",
        "tools": ["temporal_clusters"],
    },
    {
        "id": "procurement_patterns",
        "label": "Procurement Patterns",
        "icon": "🔄",
        "description": "Rotating winners, bid suppression, closed ecosystems, winner concentration",
        "tools": ["bid_patterns"],
    },
    {
        "id": "entities_networks",
        "label": "Entities & Networks",
        "icon": "🏛️",
        "description": "Dual-role entities, supplier concentration, exclusive companies, entity networks",
        "tools": ["prr_dual_role", "entity_network"],
    },
    {
        "id": "cross_references",
        "label": "Cross-References",
        "icon": "🔗",
        "description": "PRR×BASE, TED, BEP, Laws correlations",
        "tools": ["prr_enhanced", "ted_crossref", "bep_crossref", "law_hiring"],
    },
    {
        "id": "personnel",
        "label": "Personnel",
        "icon": "👤",
        "description": "Revolving doors, DRE appointments, conflict-of-interest chains",
        "tools": ["revolving_doors"],
    },
    {
        "id": "alerts",
        "label": "Alerts",
        "icon": "🔔",
        "description": "New contracts detected, threshold breaches, recent changes",
        "tools": ["contract_alerts"],
    },
]

CATEGORY_MAP = {c["id"]: c for c in CATEGORIES}


# ═════════════════════════════════════════════════════════════════════════════
#  PARSING — Extract structured data from each tool's export JSON
# ═════════════════════════════════════════════════════════════════════════════


def safe_get(data, *keys, default=None):
    """Safely traverse nested dicts."""
    for k in keys:
        if isinstance(data, dict):
            data = data.get(k)
        elif isinstance(data, list) and isinstance(k, int):
            try:
                data = data[k]
            except (IndexError, TypeError):
                return default
        else:
            return default
        if data is None:
            return default
    return data


def parse_anomaly_scanner(data: dict) -> dict:
    """Parse anomaly_scanner.py export."""
    if not data:
        return {"error": "No data", "total_flagged": 0, "entities": []}

    results = safe_get(data, "scan_results", default=[])
    summary = safe_get(data, "summary", default={})
    entities = []
    for r in results:
        entities.append({
            "nif": r.get("nif"),
            "name": r.get("name"),
            "composite_score": r.get("composite_score", 0),
            "signal_count": r.get("signal_count", 0),
            "critical_count": r.get("critical_count", 0),
            "signals": [
                {"type": s.get("type"), "severity": s.get("severity"),
                 "score": s.get("score", 0), "description": s.get("description", "")}
                for s in r.get("signals", [])
            ],
        })

    return {
        "total_flagged": summary.get("total_flagged", 0),
        "critical": summary.get("critical", 0),
        "warning": summary.get("warning", 0),
        "entities": entities,
        "top_entities": entities[:30] if entities else [],
        "generated_at": data.get("generated_at"),
    }


def parse_municipality_risk(data: dict) -> dict:
    """Parse municipality_risk_report.py export."""
    if not data:
        return {"error": "No data", "total_municipalities": 0}

    results = safe_get(data, "scan_results", default=[])
    summary = safe_get(data, "summary", default={})

    municipalities = []
    for r in results:
        municipalities.append({
            "nif": r.get("nif"),
            "name": r.get("name"),
            "risk": r.get("risk", 0),
            "total_contracts": r.get("total_contracts", 0),
            "total_value": r.get("total_value", 0),
            "top3_share": r.get("top3_share", 0),
            "hhi": r.get("hhi", 0),
            "inflated": r.get("inflated", 0),
            "inflation_rate": r.get("inflation_rate", 0),
            "overrun": r.get("overrun", 0),
            "direct_rate": r.get("direct_rate", 0),
            "exclusive_count": r.get("exclusive_count", 0),
            "bep_listings": r.get("bep_listings"),
            "top3_names": r.get("top3_names", []),
        })

    return {
        "total_municipalities": summary.get("total_municipalities", 0),
        "high_risk": summary.get("high_risk", 0),
        "medium_risk": summary.get("medium_risk", 0),
        "low_risk": summary.get("low_risk", 0),
        "municipalities": municipalities,
        "top_municipalities": municipalities[:30] if municipalities else [],
    }


def parse_bid_patterns(data: dict) -> dict:
    """Parse bid_pattern_analyzer.py export."""
    if not data:
        return {"error": "No data"}

    summary = safe_get(data, "summary", default={})

    rotating_winners = safe_get(data, "rotating_winners", default=[])
    closed_groups = safe_get(data, "closed_bidder_groups", default=[])
    bid_suppression = safe_get(data, "bid_suppression", default=[])
    similar_pricing = safe_get(data, "similar_pricing", default=[])
    winner_concentration = safe_get(data, "winner_concentration", default=[])

    return {
        "total_contracts": summary.get("total_contracts", 0),
        "total_value": summary.get("total_value", 0),
        "rotating_winners": [
            {"buyer_name": r.get("buyer_name"), "unique_winners": r.get("unique_winners"),
             "total_contracts": r.get("total_contracts"), "rotation_ratio": r.get("rotation_ratio"),
             "winners": r.get("winners", [])}
            for r in rotating_winners
        ],
        "closed_bidder_groups": [
            {"buyer_name": g.get("buyer_name"), "group_size": g.get("group_size"),
             "cooccurrence_rate": g.get("cooccurrence_rate"), "bidders": g.get("bidders", [])}
            for g in closed_groups
        ],
        "bid_suppression": [
            {"buyer_name": s.get("buyer_name"), "dominant_winner_name": s.get("dominant_winner_name"),
             "win_rate": s.get("win_rate"), "decoys": s.get("decoys", [])}
            for s in bid_suppression
        ],
        "similar_pricing": [
            {"buyer_name": p.get("buyer_name"), "cluster_size": p.get("cluster_size"),
             "price": p.get("price")}
            for p in similar_pricing
        ],
        "winner_concentration": [
            {"buyer_name": c.get("buyer_name"), "winner_name": c.get("winner_name"),
             "win_rate": c.get("win_rate"), "wins": c.get("wins")}
            for c in winner_concentration
        ],
        "counts": {
            "rotating_winners": len(rotating_winners),
            "closed_groups": len(closed_groups),
            "bid_suppression": len(bid_suppression),
            "similar_pricing": len(similar_pricing),
            "winner_concentration": len(winner_concentration),
        },
    }


def parse_temporal(data: dict) -> dict:
    """Parse temporal_clustering.py export."""
    if not data:
        return {"error": "No data"}

    summary = safe_get(data, "summary", default={})
    daily_bursts = safe_get(data, "daily_bursts", default=[])
    weekly_bursts = safe_get(data, "weekly_bursts", default=[])
    year_end = safe_get(data, "year_end")
    buyer_bursts = safe_get(data, "buyer_bursts", default=[])
    price_patterns = safe_get(data, "price_patterns", default=[])

    return {
        "total_contracts": summary.get("total_contracts", 0),
        "total_value": summary.get("total_value", 0),
        "daily_bursts": [
            {"date": b.get("date"), "contracts": b.get("contracts"),
             "total_value": b.get("total_value"), "is_year_end": b.get("is_year_end", False),
             "days_to_election": b.get("days_to_election")}
            for b in daily_bursts
        ],
        "weekly_bursts": [
            {"start_date": b.get("start_date"), "contracts": b.get("contracts"),
             "total_value": b.get("total_value")}
            for b in weekly_bursts
        ],
        "year_end": {
            "december_value": safe_get(year_end, "december_value", default=0),
            "dec_value_ratio": safe_get(year_end, "dec_value_ratio", default=0),
            "is_surge": safe_get(year_end, "is_surge", default=False),
            "dec_late_count": safe_get(year_end, "dec_late_count", default=0),
        } if year_end else None,
        "buyer_bursts": [
            {"buyer_name": b.get("buyer_name"), "start_date": b.get("start_date"),
             "contracts": b.get("contracts"), "total_value": b.get("total_value")}
            for b in buyer_bursts
        ],
        "price_patterns": [
            {"buyer_name": p.get("buyer_name"), "cluster_size": p.get("cluster_size"),
             "price_range": p.get("price_range"), "total_value": p.get("total_value")}
            for p in price_patterns
        ],
        "counts": {
            "daily_bursts": len(daily_bursts),
            "weekly_bursts": len(weekly_bursts),
            "buyer_bursts": len(buyer_bursts),
            "price_patterns": len(price_patterns),
        },
    }


def parse_prr_dual_role(data: dict) -> dict:
    """Parse prr_procurement_crossref.py export."""
    if not data:
        return {"error": "No data", "total": 0}

    entities = safe_get(data, "entities", default=[])
    summary = safe_get(data, "summary", default={})

    parsed = []
    for r in entities:
        parsed.append({
            "nif": r.get("nif"),
            "name": r.get("name"),
            "role_type": r.get("role_type"),
            "roles": r.get("roles", []),
            "risk_score": r.get("risk_score", 0),
            "risk_factors": r.get("risk_factors", []),
            "prr_value": r.get("prr_value", 0),
            "prr_paid": r.get("prr_paid", 0),
            "prr_execution_pct": r.get("prr_execution_pct", 0),
            "base_as_buyer": r.get("base_as_buyer"),
            "base_as_supplier": r.get("base_as_supplier"),
        })

    return {
        "total": len(entities),
        "triple_role": summary.get("role_type_counts", {}).get("triple_role", 0),
        "beneficiary_supplier": summary.get("role_type_counts", {}).get("prr_beneficiary_supplier", 0),
        "beneficiary_buyer": summary.get("role_type_counts", {}).get("prr_beneficiary_buyer", 0),
        "total_prr_value": summary.get("total_prr_value", 0),
        "total_base_value": summary.get("total_base_value", 0),
        "high_risk": summary.get("high_risk", 0),
        "medium_risk": summary.get("medium_risk", 0),
        "entities": parsed,
        "top_entities": parsed[:30] if parsed else [],
    }


def parse_prr_enhanced(data: dict) -> dict:
    """Parse prr_base_cdgov_detector.py export."""
    if not data:
        return {"error": "No data"}

    return {
        "cd_base_gov_matches": safe_get(data, "cd_base_gov", "results", default=[]),
        "text_similarity_matches": safe_get(data, "text_similarity", "results", default=[]),
        "composite_risk": safe_get(data, "composite_risk", default=[]),
        "fundao_deep_dive": safe_get(data, "fundao_deep_dive"),
        "counts": {
            "cd_base_gov": len(safe_get(data, "cd_base_gov", "results", default=[])),
            "text_similarity": len(safe_get(data, "text_similarity", "results", default=[])),
        },
    }


def parse_money_trail(data: dict) -> dict:
    """Parse money_trail_analyzer.py export (concelho deep-dive)."""
    if not data:
        return {"error": "No data"}

    phase1 = safe_get(data, "phase1_prr", default={})
    phase2 = safe_get(data, "phase2_budget", default={})
    phase3 = safe_get(data, "phase3_procurement", default={})
    chain = safe_get(data, "chain", default={})

    return {
        "concelho": data.get("concelho"),
        "analyzed_at": data.get("analyzed_at"),
        "prr_allocation": {
            "total_approved": phase1.get("total_aprovado", 0),
            "total_paid": phase1.get("total_pago", 0),
            "execution_rate": phase1.get("execution_rate_pct", 0),
            "num_projects": phase1.get("num_projects", 0),
            "projects": phase1.get("project_values", []),
            "prr_entities": phase1.get("prr_entities", []),
        },
        "budget": {
            "concelho_previsto": phase2.get("concelho_previsto", 0),
            "concelho_realizado": phase2.get("concelho_realizado", 0),
            "national_execution_rate": phase2.get("national_execution_rate", 0),
        } if phase2 and "error" not in phase2 else {"error": "Budget data unavailable"},
        "procurement": {
            "total_contracts": phase3.get("total_contracts", 0),
            "total_value": phase3.get("total_value", 0),
            "inflated_count": phase3.get("inflated_count", 0),
            "total_overrun": phase3.get("total_overrun", 0),
            "avg_inflation_pct": phase3.get("avg_inflation_pct", 0),
            "top3_share": phase3.get("top3_share", 0),
            "unique_winners": phase3.get("unique_winners", 0),
            "top_winners": [
                {"name": w.get("name"), "value": w.get("value"), "share_pct": w.get("share_pct")}
                for w in phase3.get("top_winners", [])
            ],
        } if phase3 and "error" not in phase3 else {"error": "Procurement data unavailable"},
        "chain_analysis": {
            "total_anomalies": chain.get("total_anomalies", 0),
            "critical_anomalies": chain.get("critical_anomalies", 0),
            "anomalies": chain.get("anomalies", []),
            "phases": chain.get("phases", {}),
        },
    }


def parse_revolving_doors(data: dict) -> dict:
    """Parse revolving_door_detector.py export."""
    if not data:
        return {"error": "No data", "total_chains": 0}

    chains = safe_get(data, "chains", default=[])

    parsed_chains = []
    for c in chains:
        appt = safe_get(c, "appointment", default={})
        supplier_chains = safe_get(c, "supplier_chains", default=[])

        parsed_chains.append({
            "person_name": appt.get("person_name"),
            "organization": appt.get("organization"),
            "role": appt.get("role"),
            "date": appt.get("date"),
            "max_risk_score": c.get("max_risk_score", 0),
            "total_supplier_chains": c.get("total_supplier_chains", 0),
            "suppliers": [
                {"name": s.get("supplier_name"), "risk_score": s.get("risk_score"),
                 "days_from_appointment": s.get("days_from_appointment"),
                 "total_value": s.get("total_value"), "total_contracts": s.get("total_contracts"),
                 "risk_factors": s.get("risk_factors", [])}
                for s in supplier_chains
            ],
        })

    return {
        "total_appointments_matched": data.get("total_appointments_matched", 0),
        "total_chains": data.get("total_chains", 0),
        "chains": parsed_chains,
        "top_chains": parsed_chains[:30] if parsed_chains else [],
    }


def parse_price_gaps(data: dict) -> dict:
    """Parse price_gap_analysis.py export."""
    if not data:
        return {"error": "No data"}

    matches = safe_get(data, "matches", default=[])
    summary = safe_get(data, "summary", default={})

    return {
        "total_matches": len(matches),
        "total_value_delta": summary.get("total_value_delta", 0),
        "matches": matches[:50] if matches else [],
    }


def parse_entity_network(data: dict) -> dict:
    """Parse entity_network.py export."""
    if not data:
        return {"error": "No data"}

    relationships = safe_get(data, "relationships", default=[])
    self_ref = safe_get(data, "self_referencing", default=[])

    return {
        "total_relationships": len(relationships),
        "self_referencing_count": len(self_ref),
        "self_referencing": [
            {"name": s.get("name"), "value": s.get("value")}
            for s in self_ref[:20]
        ],
        "top_relationships": relationships[:50] if relationships else [],
    }


def parse_generic(data: dict, top_keys: list[str] = None) -> dict:
    """Parse a generic tool export — extract summary fields and top-N results."""
    if not data:
        return {"error": "No data"}

    result = {}
    if top_keys:
        for k in top_keys:
            parts = k.split(".")
            v = safe_get(data, *parts) if len(parts) > 1 else data.get(k)
            if v is not None:
                result[k] = v

    # Include full data as fallback
    result["_raw_preview_keys"] = list(data.keys())[:20]
    return result


# ── Tool Parser Dispatch ───────────────────────────────────────────────────

PARSERS = {
    "anomaly_scanner": parse_anomaly_scanner,
    "municipality_risk": parse_municipality_risk,
    "bid_patterns": parse_bid_patterns,
    "temporal_clusters": parse_temporal,
    "prr_dual_role": parse_prr_dual_role,
    "prr_enhanced": parse_prr_enhanced,
    "money_trail": parse_money_trail,
    "revolving_doors": parse_revolving_doors,
    "price_gaps": parse_price_gaps,
    "entity_network": parse_entity_network,
    "ted_crossref": lambda d: parse_generic(d, ["total_matches", "threshold_crosses"]),
    "bep_crossref": lambda d: parse_generic(d, ["total_matched", "total_entities"]),
    "contract_mods": lambda d: parse_generic(d, ["total_modifications", "total_contracts"]),
    "contract_alerts": lambda d: parse_generic(d, ["new_contracts", "total_watches"]),
    "law_hiring": lambda d: parse_generic(d, ["total_correlations", "high_impact"]),
}


# ═════════════════════════════════════════════════════════════════════════════
#  CONSOLIDATION
# ═════════════════════════════════════════════════════════════════════════════


def discover_exports(directory: Path = None) -> dict[str, Path]:
    """Auto-discover export files in summary directory.

    Returns {tool_name: path} by matching filenames against known patterns.
    """
    search_dir = directory or SUMMARY_DIR
    if not search_dir.exists():
        return {}

    discovered = {}

    # Pattern-based discovery: tool key → expected filename fragments
    # Patterns are sorted longest-first so specific matches override generic ones
    patterns = {
        "anomaly_scanner": ["anomaly_scan", "anomalies"],
        "municipality_risk": ["municipality_risk"],
        "bid_patterns": ["bid_pattern_analyzer", "bid_pattern"],
        "temporal_clusters": ["temporal_cluster", "temporal_burst"],
        "prr_dual_role": ["prr_dual_role", "dual_role"],
        "prr_enhanced": ["enhanced_scan"],
        "money_trail": ["money_trail", "fundao_trail"],
        "revolving_doors": ["revolving_door_detector", "revolving_door", "fundao_doors"],
        "price_gaps": ["price_gap"],
        "entity_network": ["entity_network"],
        "ted_crossref": ["ted_crossref"],
        "bep_crossref": ["bep_crossref", "bep_procurement"],
        "contract_mods": ["contract_modification"],
        "contract_alerts": ["contract_alert"],
        "law_hiring": ["law_hiring_correlation", "law_hiring"],
    }

    # Sort fragments longest-first for each tool to avoid short-substring collisions
    sorted_patterns = {
        k: sorted(v, key=len, reverse=True)
        for k, v in patterns.items()
    }

    for fpath in sorted(search_dir.glob("*.json")):
        fname = fpath.name.lower()
        for tool_key, fragments in sorted_patterns.items():
            if any(frag in fname for frag in fragments):
                if tool_key not in discovered:  # First match wins
                    discovered[tool_key] = fpath
                break  # Each file only maps to one tool

    return discovered


def load_export(path: Path) -> dict | None:
    """Load a JSON export file, returning None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"  ⚠️  Failed to load {path}: {e}", file=sys.stderr)
        return None


def build_consolidated(
    exports: dict[str, Path],
    incremental: dict = None,
) -> dict:
    """Build the consolidated output from discovered exports and parsers.

    Args:
        exports: {tool_name: Path} dict of export files to parse
        incremental: Previously consolidated data to merge (optional)

    Returns:
        Consolidated JSON structure
    """
    now = datetime.now(timezone.utc)

    # Initialize category buckets
    categories = {}
    for cat in CATEGORIES:
        categories[cat["id"]] = {
            "label": cat["label"],
            "icon": cat["icon"],
            "description": cat["description"],
            "tools": {},
        }

    loaded_tools = []
    failed_tools = []

    # Parse each export into its category
    for tool_key, fpath in exports.items():
        tool_info = TOOL_REGISTRY.get(tool_key)
        if not tool_info:
            continue

        category_id = tool_info["category"]
        raw_data = load_export(fpath)

        if raw_data is None:
            categories[category_id]["tools"][tool_key] = {"error": f"Failed to load {fpath}"}
            failed_tools.append(tool_key)
            continue

        # Parse with tool-specific parser
        parser = PARSERS.get(tool_key)
        if parser:
            try:
                parsed = parser(raw_data)
            except Exception as e:
                parsed = {"error": f"Parse error: {e}", "_raw_keys": list(raw_data.keys())[:10]}
        else:
            parsed = parse_generic(raw_data)

        categories[category_id]["tools"][tool_key] = {
            "tool_name": tool_key,
            "description": tool_info["description"],
            "source_file": str(fpath),
            "loaded_at": now.isoformat(),
            "data": parsed,
        }
        loaded_tools.append(tool_key)

    # Merge incremental data (from previous run)
    if incremental:
        for cat_id, cat_data in incremental.get("categories", {}).items():
            if cat_id not in categories:
                categories[cat_id] = cat_data
            else:
                for tool_key, tool_data in cat_data.get("tools", {}).items():
                    if tool_key not in categories[cat_id].get("tools", {}):
                        categories[cat_id].setdefault("tools", {})[tool_key] = tool_data

    # Compute category-level summaries
    category_summaries = {}
    for cat_id, cat_data in categories.items():
        tool_count = len(cat_data["tools"])
        error_count = sum(1 for t in cat_data["tools"].values() if "error" in t.get("data", {}))
        loaded_count = tool_count - error_count
        category_summaries[cat_id] = {
            "tool_count": tool_count,
            "loaded": loaded_count,
            "errors": error_count,
        }

    consolidated = {
        "meta": {
            "generated_at": now.isoformat(),
            "version": "1.0.0",
            "pipeline": "consolidate.py",
            "tools_loaded": len(loaded_tools),
            "tools_failed": len(failed_tools),
            "loaded_tools": loaded_tools,
            "failed_tools": failed_tools,
        },
        "categories": categories,
        "category_summaries": category_summaries,
        "tool_registry": {
            k: {"category": v["category"], "description": v["description"]}
            for k, v in TOOL_REGISTRY.items()
        },
    }

    return consolidated


# ═════════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ═════════════════════════════════════════════════════════════════════════════


def print_summary(consolidated: dict):
    """Print a human-readable summary of the consolidated data."""
    meta = consolidated.get("meta", {})
    categories = consolidated.get("categories", {})
    summaries = consolidated.get("category_summaries", {})

    print(f"\n{'=' * 80}")
    print(f"  📊 CONSOLIDATED DATA PIPELINE — Summary")
    print(f"  Generated: {meta.get('generated_at', '?')[:19]}")
    print(f"{'=' * 80}")

    print(f"\n  Overview:")
    print(f"    Tools loaded: {meta.get('tools_loaded', 0)}  |  Failed: {meta.get('tools_failed', 0)}")
    if meta.get("failed_tools"):
        print(f"    Failed: {', '.join(meta['failed_tools'])}")

    print(f"\n  {'─' * 75}")
    print(f"  {'Category':<30} {'Tools':>6} {'Loaded':>8} {'Errors':>8} {'Key Findings':<30}")
    print(f"  {'─' * 30} {'─' * 6} {'─' * 8} {'─' * 8} {'─' * 30}")

    for cat in CATEGORIES:
        cid = cat["id"]
        s = summaries.get(cid, {})
        cat_data = categories.get(cid, {})
        icon = cat.get("icon", "•")

        # Build a key finding summary per category
        findings = []
        for tool_key, tool_data in cat_data.get("tools", {}).items():
            data = tool_data.get("data", {})
            if "error" in data:
                findings.append("!")
                continue
            # Extract meaningful counts from known data shapes
            for count_key in ["total_flagged", "total_municipalities", "total_chains",
                              "counts", "total_contracts", "high_risk", "total_matches",
                              "self_referencing_count"]:
                val = safe_get(data, count_key) if isinstance(count_key, str) else None
                if val is not None and isinstance(val, (int, float)) and val > 0:
                    label = count_key.replace("total_", "").replace("_", " ").title()
                    findings.append(f"{label}: {val}")
                    break

        finding_str = "; ".join(findings[:2]) if findings else ""
        print(f"  {icon} {cat['label']:<27} {s.get('tool_count', 0):>6} {s.get('loaded', 0):>8} "
              f"{s.get('errors', 0):>8} {finding_str:<30}")

    print(f"\n  {'─' * 75}")

    # Show memory estimate
    size_bytes = sys.getsizeof(json.dumps(consolidated))
    print(f"\n  💾 Output size: {size_bytes / _KB:.1f} KB JSON")
    print(f"\n{'=' * 80}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════


def cmd_list_tools():
    """Print the tool registry grouped by category."""
    print(f"\n{'=' * 100}")
    print(f"  TOOL REGISTRY — Consolidated Data Pipeline")
    print(f"{'=' * 100}")

    for cat in CATEGORIES:
        print(f"\n  {cat['icon']} {cat['label']} — {cat['description']}")
        print(f"  {'─' * 60}")
        for tool_key in cat["tools"]:
            info = TOOL_REGISTRY.get(tool_key, {})
            print(f"    {tool_key:<25} {info.get('description', ''):<50}")
            print(f"    {'':25} Export: {info.get('default_export', 'N/A')}")

    print(f"\n{'=' * 100}\n")


def cmd_validate(path: str):
    """Validate an existing consolidated JSON file."""
    fpath = Path(path)
    if not fpath.exists():
        print(f"ERROR: {fpath} not found")
        return False

    data = load_export(fpath)
    if not data:
        print(f"ERROR: Could not parse {fpath}")
        return False

    required_keys = ["meta", "categories", "category_summaries", "tool_registry"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        print(f"ERROR: Missing required keys: {missing}")
        return False

    print(f"\n✅ Validated: {fpath}")
    print(f"   Tools loaded: {data['meta'].get('tools_loaded', 0)}")
    print(f"   Failed: {data['meta'].get('tools_failed', 0)}")
    print(f"   Categories: {len(data['categories'])}")

    # Check each category has valid tool data
    for cat_id, cat_data in data["categories"].items():
        tools = cat_data.get("tools", {})
        errors = sum(1 for t in tools.values() if "error" in t.get("data", {}))
        if errors:
            print(f"   ⚠️  {cat_id}: {errors}/{len(tools)} tools have errors")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate Data Pipeline — Collect ALL tool outputs into single JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python consolidate.py --from-exports
              python consolidate.py --from-exports --dir ./exports
              python consolidate.py --out dashboard_data.json
              python consolidate.py --incremental previous.json --out merged.json
              python consolidate.py --list-tools
              python consolidate.py --validate-out data/summary/consolidated.json
        """),
    )

    parser.add_argument("--from-exports", action="store_true", default=True,
                        help="Read pre-existing export files (default)")
    parser.add_argument("--dir", help="Directory containing export JSONs (default: data/summary/)")
    parser.add_argument("--out", "-o", default=str(SUMMARY_DIR / "consolidated.json"),
                        help="Output path (default: data/summary/consolidated.json)")
    parser.add_argument("--incremental", help="Merge with previous consolidated JSON")
    parser.add_argument("--list-tools", action="store_true", help="List all known tools")
    parser.add_argument("--validate-out", metavar="FILE", help="Validate an existing consolidated file")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress human-readable summary")

    args = parser.parse_args()

    # Special commands
    if args.list_tools:
        cmd_list_tools()
        return

    if args.validate_out:
        cmd_validate(args.validate_out)
        return

    # Main pipeline
    export_dir = Path(args.dir) if args.dir else SUMMARY_DIR
    print(f"\n  🔍 Discovering exports in {export_dir}...", file=sys.stderr)

    exports = discover_exports(export_dir)

    if not exports:
        print(f"  ⚠️  No export files found in {export_dir}", file=sys.stderr)
        print(f"  Run individual tools with --export first, or use --run mode.", file=sys.stderr)
        sys.exit(1)

    print(f"  Found {len(exports)} tool exports:", file=sys.stderr)
    for tool_key, fpath in sorted(exports.items()):
        tool_info = TOOL_REGISTRY.get(tool_key, {})
        cat = tool_info.get("category", "?")
        print(f"    {tool_key:<25} → {fpath.name:<40} [{cat}]", file=sys.stderr)

    # Load incremental data if provided
    incremental = None
    if args.incremental:
        inc_path = Path(args.incremental)
        if inc_path.exists():
            print(f"  Loading incremental data from {inc_path}...", file=sys.stderr)
            incremental = load_export(inc_path)
        else:
            print(f"  ⚠️  Incremental file not found: {inc_path}", file=sys.stderr)

    print(f"  Building consolidated output...", file=sys.stderr)
    consolidated = build_consolidated(exports, incremental=incremental)

    # Print summary
    if not args.quiet:
        print_summary(consolidated)

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(consolidated, f, ensure_ascii=False, indent=2, default=str)

    print(f"  ✅ Consolidated data written to {out_path}", file=sys.stderr)
    print(f"     {consolidated['meta']['tools_loaded']} tools loaded, "
          f"{consolidated['meta']['tools_failed']} failed", file=sys.stderr)

    # Validate output
    cmd_validate(str(out_path))


if __name__ == "__main__":
    main()
