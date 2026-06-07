#!/usr/bin/env python3
"""Freguesia Contract Analyzer — Parish-Level Procurement Analysis

Analyzes public procurement contracts at the freguesia (parish) level to
detect spending patterns, seller dominance, and cross-parish anomalies.

Usage:
    # Top parishes by spending
    python freguesia_contract_analyzer.py spending --top 30

    # Sellers dominating parish procurement
    python freguesia_contract_analyzer.py sellers --min-contracts 5

    # Cross-parish patterns (same seller in multiple parishes)
    python freguesia_contract_analyzer.py cross-parish --min-parishes 3

    # Full analysis
    python freguesia_contract_analyzer.py all
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).parent
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
FREGUESIA_NIF_INDEX = SCRIPT_DIR / "data" / "freguesia_nif_index.json"
FREGUESIA_MAP = SCRIPT_DIR / "data" / "freguesia_mapping.json"


# =============================================================================
# DATA LOADING
# =============================================================================

def load_contract_index() -> Dict[str, List[Dict]]:
    if not CONTRACT_INDEX.exists():
        print(f"Error: {CONTRACT_INDEX} not found", file=sys.stderr)
        return {}
    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def load_freguesia_nifs() -> Dict[str, Dict]:
    """Load freguesia NIF index (built by freguesia_nif_mapper.py)."""
    if not FREGUESIA_NIF_INDEX.exists():
        return {}
    with open(FREGUESIA_NIF_INDEX, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("freguesias", {})


def load_freguesia_mapping() -> Dict[str, str]:
    if not FREGUESIA_MAP.exists():
        return {}
    with open(FREGUESIA_MAP, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _is_freguesia(name: str) -> bool:
    """Check if an entity name is a freguesia."""
    nl = name.lower()
    return any(p in nl for p in ["freguesia", "junta de freguesia", "união das freguesias"])


def _extract_parish_name(name: str) -> str:
    """Extract the parish name from a full entity name."""
    for prefix in ["Freguesia de ", "Freguesia do ", "Freguesia da ",
                    "Junta de Freguesia de ", "Junta de Freguesia do ",
                    "Junta de Freguesia da ", "União das Freguesias de ",
                    "União das Freguesias do ", "União das Freguesias da "]:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


# =============================================================================
# ANALYSIS
# =============================================================================

def analyze_spending(contract_index: Dict, freg_nifs: Dict, freg_map: Dict, top_n: int = 30):
    """Which parishes spend the most on procurement."""
    print(f"\n{'='*110}")
    print(f"FREGUESIA SPENDING — Top Parishes by Contract Value")
    print(f"{'='*110}")

    # Group contracts by freguesia NIF
    parish_data: Dict[str, Dict] = defaultdict(lambda: {
        "name": "", "parish_name": "", "municipality": "",
        "contracts": 0, "total_value": 0.0, "sellers": set(),
    })

    for buyer_nif, contracts in contract_index.items():
        if not contracts:
            continue
        name = contracts[0].get("entity_name", "")
        if not _is_freguesia(name):
            continue

        pd = parish_data[buyer_nif]
        pd["name"] = name
        pd["parish_name"] = _extract_parish_name(name)
        pd["municipality"] = freg_map.get(_extract_parish_name(name).lower(), "")

        for c in contracts:
            pd["contracts"] += 1
            pd["total_value"] += c.get("valor", 0) or 0
            wn = c.get("adjudicatario_nif", "")
            if wn:
                pd["sellers"].add(wn)

    if not parish_data:
        print("\n  No freguesia contracts found.")
        return

    # Sort by value
    sorted_parishes = sorted(parish_data.values(), key=lambda x: -x["total_value"])
    total_value = sum(p["total_value"] for p in sorted_parishes)
    total_contracts = sum(p["contracts"] for p in sorted_parishes)

    print(f"\n  📊 {len(sorted_parishes)} parishes with contracts")
    print(f"  Total value: €{total_value:,.2f}")
    print(f"  Total contracts: {total_contracts:,}")

    print(f"\n  {'#':<4}{'Parish':<35}{'Municipality':<20}{'Contracts':>10}{'Value':>16}{'Sellers':>8}")
    print(f"  {'─'*4}{'─'*35}{'─'*20}{'─'*10}{'─'*16}{'─'*8}")

    for i, p in enumerate(sorted_parishes[:top_n], 1):
        parish = p["parish_name"][:33]
        muni = p["municipality"][:18] or "(unknown)"
        print(f"  {i:<4}{parish:<35}{muni:<20}{p['contracts']:>10}€{p['total_value']:>14,.2f}{len(p['sellers']):>8}")


def analyze_sellers(contract_index: Dict, min_contracts: int = 5):
    """Which sellers dominate parish procurement."""
    print(f"\n{'='*110}")
    print(f"PARISH SELLERS — Companies Dominating Freguesia Procurement (>{min_contracts} contracts)")
    print(f"{'='*110}")

    # Group by seller → freguesia
    seller_parishes: Dict[str, Dict] = defaultdict(lambda: {
        "name": "", "parishes": set(), "contracts": 0, "total_value": 0.0,
        "parish_details": defaultdict(lambda: {"name": "", "contracts": 0, "value": 0.0}),
    })

    for buyer_nif, contracts in contract_index.items():
        if not contracts:
            continue
        buyer_name = contracts[0].get("entity_name", "")
        if not _is_freguesia(buyer_name):
            continue

        parish_name = _extract_parish_name(buyer_name)

        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            wn_name = c.get("adjudicatario", "")
            if not wn:
                continue
            valor = c.get("valor", 0) or 0

            sp = seller_parishes[wn]
            sp["name"] = wn_name
            sp["parishes"].add(buyer_nif)
            sp["contracts"] += 1
            sp["total_value"] += valor
            sp["parish_details"][buyer_nif]["name"] = parish_name
            sp["parish_details"][buyer_nif]["contracts"] += 1
            sp["parish_details"][buyer_nif]["value"] += valor

    # Filter and sort
    sellers = [
        (nif, d) for nif, d in seller_parishes.items()
        if d["contracts"] >= min_contracts
    ]
    sellers.sort(key=lambda x: -x[1]["total_value"])

    if not sellers:
        print(f"\n  No sellers with {min_contracts}+ parish contracts found.")
        return

    total_value = sum(d["total_value"] for _, d in sellers)
    print(f"\n  🏢 {len(sellers)} sellers with {min_contracts}+ parish contracts")
    print(f"  Total value: €{total_value:,.2f}")

    print(f"\n  {'#':<4}{'Seller':<35}{'NIF':<12}{'Parishes':>10}{'Contracts':>10}{'Value':>16}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*10}{'─'*10}{'─'*16}")

    for i, (nif, d) in enumerate(sellers[:25], 1):
        print(f"  {i:<4}{d['name'][:35]:<35}{nif:<12}{len(d['parishes']):>10}{d['contracts']:>10}€{d['total_value']:>14,.2f}")

    # Detail top 5
    print(f"\n  🔍 Detailed View — Top 5 Sellers")
    for i, (nif, d) in enumerate(sellers[:5], 1):
        print(f"\n  {'─'*100}")
        print(f"  #{i} {d['name'][:60]} (NIF: {nif})")
        print(f"     Parishes: {len(d['parishes'])}  |  Contracts: {d['contracts']:,}  |  Total: €{d['total_value']:,.2f}")
        sorted_pd = sorted(d["parish_details"].items(), key=lambda x: -x[1]["value"])
        for pnif, pd in sorted_pd[:8]:
            print(f"       [{pnif}] {pd['name'][:45]:<45} {pd['contracts']:>5} contracts  €{pd['value']:>14,.2f}")
        if len(sorted_pd) > 8:
            print(f"       ... and {len(sorted_pd) - 8} more parishes")


def analyze_cross_parish(contract_index: Dict, min_parishes: int = 3):
    """Find sellers winning contracts in multiple parishes (cross-municipality patterns)."""
    print(f"\n{'='*110}")
    print(f"CROSS-PARISH PATTERNS — Sellers in {min_parishes}+ Parishes (Potential Network)")
    print(f"{'='*110}")

    # Group by seller → parish
    seller_data: Dict[str, Dict] = defaultdict(lambda: {
        "name": "", "parishes": set(), "municipalities": set(),
        "contracts": 0, "total_value": 0.0,
        "parish_list": [],
    })

    for buyer_nif, contracts in contract_index.items():
        if not contracts:
            continue
        buyer_name = contracts[0].get("entity_name", "")
        if not _is_freguesia(buyer_name):
            continue

        parish_name = _extract_parish_name(buyer_name)

        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            wn_name = c.get("adjudicatario", "")
            if not wn:
                continue
            valor = c.get("valor", 0) or 0

            sd = seller_data[wn]
            sd["name"] = wn_name
            if buyer_nif not in sd["parishes"]:
                sd["parishes"].add(buyer_nif)
                sd["parish_list"].append({"nif": buyer_nif, "name": parish_name})
            sd["contracts"] += 1
            sd["total_value"] += valor

    # Filter and sort
    multi = [
        (nif, d) for nif, d in seller_data.items()
        if len(d["parishes"]) >= min_parishes
    ]
    multi.sort(key=lambda x: -x[1]["total_value"])

    if not multi:
        print(f"\n  No sellers found in {min_parishes}+ parishes.")
        return

    total_value = sum(d["total_value"] for _, d in multi)
    print(f"\n  🕸️  {len(multi)} sellers in {min_parishes}+ parishes")
    print(f"  Total cross-parish value: €{total_value:,.2f}")

    print(f"\n  {'#':<4}{'Seller':<35}{'NIF':<12}{'Parishes':>10}{'Contracts':>10}{'Value':>18}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*10}{'─'*10}{'─'*18}")

    for i, (nif, d) in enumerate(multi[:25], 1):
        print(f"  {i:<4}{d['name'][:35]:<35}{nif:<12}{len(d['parishes']):>10}{d['contracts']:>10}€{d['total_value']:>16,.2f}")

    # Detail top 5
    print(f"\n  🔍 Detailed View — Top 5 Cross-Parish Sellers")
    for i, (nif, d) in enumerate(multi[:5], 1):
        print(f"\n  {'─'*100}")
        print(f"  #{i} {d['name'][:60]} (NIF: {nif})")
        print(f"     Parishes: {len(d['parishes'])}  |  Contracts: {d['contracts']:,}  |  Total: €{d['total_value']:,.2f}")
        for pl in d["parish_list"][:10]:
            print(f"       • {pl['name'][:50]}")
        if len(d["parish_list"]) > 10:
            print(f"       ... and {len(d['parish_list']) - 10} more")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Freguesia Contract Analyzer — Parish-Level Procurement Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s spending --top 30          # Top parishes by spending
  %(prog)s sellers --min-contracts 5  # Sellers dominating parishes
  %(prog)s cross-parish --min-parishes 3  # Cross-parish patterns
  %(prog)s all                        # Full analysis
        """,
    )
    sub = parser.add_subparsers(dest="command")

    spend_p = sub.add_parser("spending", help="Top parishes by spending")
    spend_p.add_argument("--top", "-t", type=int, default=30)

    seller_p = sub.add_parser("sellers", help="Sellers dominating parish procurement")
    seller_p.add_argument("--min-contracts", "-m", type=int, default=5)

    cross_p = sub.add_parser("cross-parish", help="Cross-parish seller patterns")
    cross_p.add_argument("--min-parishes", "-p", type=int, default=3)

    sub.add_parser("all", help="Full analysis")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    contract_index = load_contract_index()
    if not contract_index:
        return

    freg_nifs = load_freguesia_nifs()
    freg_map = load_freguesia_mapping()

    if args.command == "spending":
        analyze_spending(contract_index, freg_nifs, freg_map, top_n=args.top)
    elif args.command == "sellers":
        analyze_sellers(contract_index, min_contracts=args.min_contracts)
    elif args.command == "cross-parish":
        analyze_cross_parish(contract_index, min_parishes=args.min_parishes)
    elif args.command == "all":
        analyze_spending(contract_index, freg_nifs, freg_map, top_n=20)
        analyze_sellers(contract_index, min_contracts=5)
        analyze_cross_parish(contract_index, min_parishes=3)


if __name__ == "__main__":
    main()
