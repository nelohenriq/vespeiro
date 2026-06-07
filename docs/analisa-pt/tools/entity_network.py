#!/usr/bin/env python3
"""
Entity Relationship Analyzer — Buyer-Seller Network & Fraud Detection

Cross-references adjudicante (buyer) and adjudicatário (winner) data
from BASE.gov.pt to map procurement relationships and detect anomalies
like self-referencing entities or suspicious pricing patterns.

Usage:
    # Analyze buyer-seller relationships
    python entity_network.py analyze

    # Detect self-referencing (same entity as buyer and seller)
    python entity_network.py self-ref

    # Show top buyer-seller pairs
    python entity_network.py pairs --top 30

    # Export relationship graph as JSON
    python entity_network.py export --output data/entity_network.json

    # Show entity profile (all contracts as buyer and seller)
    python entity_network.py profile --nif 500014872
"""

import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"


# =============================================================================
# PARSING
# =============================================================================

def parse_entity_field(text: str) -> List[Dict]:
    """Parse 'NIF - Name' or 'NIF1 - Name1; NIF2 - Name2' format."""
    if not text:
        return []
    text = str(text).strip()
    if text in ("-", "- -", "", "None"):
        return []

    entities = []
    for part in text.split(";"):
        part = part.strip()
        match = re.match(r"(\d{9})\s*-\s*(.+)", part)
        if match:
            entities.append({"nif": match.group(1), "name": match.group(2).strip()})
        elif part and part != "-":
            entities.append({"nif": "", "name": part.strip()})
    return entities


def load_db_relationships() -> Tuple[Dict, List]:
    """Load adjudicante/adjudicatário pairs from procurement.db.

    Returns: (relationships_dict, self_referencing_list)
    """
    import sqlite3

    if not PROCUREMENT_DB.exists():
        print(f"Error: {PROCUREMENT_DB} not found", file=sys.stderr)
        print("Run: python procurement_db.py build", file=sys.stderr)
        return {}, []

    print("Loading from procurement.db...", file=sys.stderr)
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    rows = conn.execute(
        "SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,"
        " precoContratual, tipoContrato, objectoContrato"
        " FROM contratos WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''"
    ).fetchall()
    conn.close()

    relationships = defaultdict(lambda: {
        "contracts": 0, "total_value": 0.0,
        "types": Counter(), "buyer_name": "", "seller_name": ""
    })
    self_referencing = []
    total_rows = 0

    for adj_nif, adj_name, adjt_text, valor, tipo, objeto in rows:
        total_rows += 1
        if not adj_nif:
            continue
        valor = valor or 0
        tipo = tipo or ""
        objeto = objeto or ""

        winners = parse_entity_field(str(adjt_text or ""))

        for w in winners:
            if adj_nif and w["nif"]:
                key = (adj_nif, w["nif"])
                relationships[key]["contracts"] += 1
                relationships[key]["total_value"] += valor
                relationships[key]["types"][tipo] += 1
                if not relationships[key]["buyer_name"]:
                    relationships[key]["buyer_name"] = adj_name or ""
                if not relationships[key]["seller_name"]:
                    relationships[key]["seller_name"] = w["name"]

                if adj_nif == w["nif"]:
                    self_referencing.append({
                        "nif": adj_nif,
                        "buyer_name": adj_name or "",
                        "seller_name": w["name"],
                        "valor": valor,
                        "tipo": tipo,
                        "objeto": str(objeto)[:100],
                    })

    print(f"  Processed {total_rows:,} rows", file=sys.stderr)
    print(f"  Found {len(relationships):,} unique buyer-seller pairs", file=sys.stderr)
    print(f"  Self-referencing cases: {len(self_referencing)}", file=sys.stderr)

    return dict(relationships), self_referencing


# =============================================================================
# ANALYSIS
# =============================================================================

def analyze_relationships(relationships: Dict, self_ref: List):
    """Print analysis summary."""
    print(f"\n{'='*100}")
    print(f"ENTITY RELATIONSHIP ANALYSIS")
    print(f"{'='*100}")

    total_contracts = sum(r["contracts"] for r in relationships.values())
    total_value = sum(r["total_value"] for r in relationships.values())
    unique_buyers = len(set(k[0] for k in relationships.keys()))
    unique_sellers = len(set(k[1] for k in relationships.keys()))

    print(f"\n  📊 Overview")
    print(f"  {'─'*60}")
    print(f"  Total contracts:        {total_contracts:,}")
    print(f"  Total value:            €{total_value:,.2f}")
    print(f"  Unique buyers:          {unique_buyers:,}")
    print(f"  Unique sellers:         {unique_sellers:,}")
    print(f"  Unique relationships:   {len(relationships):,}")
    print(f"  Self-referencing:       {len(self_ref)}")

    # Top buyers
    buyer_totals = defaultdict(lambda: {"contracts": 0, "value": 0.0, "name": ""})
    for (buyer, seller), data in relationships.items():
        buyer_totals[buyer]["contracts"] += data["contracts"]
        buyer_totals[buyer]["value"] += data["total_value"]
        buyer_totals[buyer]["name"] = data["buyer_name"]

    print(f"\n  🏛️  Top 15 Buyers (Adjudicante)")
    print(f"  {'─'*80}")
    print(f"  {'NIF':<12}{'Name':<35}{'Contracts':>12}{'Total Value':>18}")
    print(f"  {'─'*12}{'─'*35}{'─'*12}{'─'*18}")
    for nif, d in sorted(buyer_totals.items(), key=lambda x: -x[1]["value"])[:15]:
        print(f"  {nif:<12}{d['name'][:35]:<35}{d['contracts']:>12,}€{d['value']:>16,.2f}")

    # Top sellers
    seller_totals = defaultdict(lambda: {"contracts": 0, "value": 0.0, "name": ""})
    for (buyer, seller), data in relationships.items():
        seller_totals[seller]["contracts"] += data["contracts"]
        seller_totals[seller]["value"] += data["total_value"]
        seller_totals[seller]["name"] = data["seller_name"]

    print(f"\n  🏢 Top 15 Sellers (Adjudicatário)")
    print(f"  {'─'*80}")
    print(f"  {'NIF':<12}{'Name':<35}{'Contracts':>12}{'Total Value':>18}")
    print(f"  {'─'*12}{'─'*35}{'─'*12}{'─'*18}")
    for nif, d in sorted(seller_totals.items(), key=lambda x: -x[1]["value"])[:15]:
        print(f"  {nif:<12}{d['name'][:35]:<35}{d['contracts']:>12,}€{d['value']:>16,.2f}")


def show_self_referencing(self_ref: List):
    """Show self-referencing cases."""
    print(f"\n{'='*100}")
    print(f"SELF-REFERENCING ANALYSIS (Same Entity as Buyer and Seller)")
    print(f"{'='*100}")

    if not self_ref:
        print("\n  No self-referencing cases found.")
        return

    # Group by NIF
    by_nif = defaultdict(list)
    for c in self_ref:
        by_nif[c["nif"]].append(c)

    total_value = sum(c["valor"] for c in self_ref)
    print(f"\n  Total cases: {len(self_ref)}")
    print(f"  Unique entities: {len(by_nif)}")
    print(f"  Total value: €{total_value:,.2f}")

    print(f"\n  ⚠️  Self-Referencing Entities (by total value)")
    print(f"  {'─'*90}")
    for nif, cases in sorted(by_nif.items(), key=lambda x: -sum(c["valor"] for c in x[1]))[:20]:
        total = sum(c["valor"] for c in cases)
        print(f"  [{nif}] {cases[0]['buyer_name'][:50]}")
        print(f"    Cases: {len(cases)}, Total: €{total:,.2f}")
        for c in cases[:3]:
            print(f"    • €{c['valor']:,.2f} ({c['tipo'][:40]})")
            if c["objeto"]:
                print(f"      {c['objeto'][:70]}")
        if len(cases) > 3:
            print(f"    ... and {len(cases) - 3} more")
        print()


def show_top_pairs(relationships: Dict, top_n: int = 30):
    """Show top buyer-seller pairs."""
    print(f"\n{'='*100}")
    print(f"TOP {top_n} BUYER-SELLER RELATIONSHIPS")
    print(f"{'='*100}")

    sorted_rels = sorted(relationships.items(), key=lambda x: -x[1]["total_value"])

    print(f"\n  {'#':<4}{'Buyer':<30}{'Seller':<30}{'Contracts':>10}{'Value':>16}")
    print(f"  {'─'*4}{'─'*30}{'─'*30}{'─'*10}{'─'*16}")

    for i, ((buyer, seller), data) in enumerate(sorted_rels[:top_n], 1):
        buyer_name = data["buyer_name"][:28] if data["buyer_name"] else buyer
        seller_name = data["seller_name"][:28] if data["seller_name"] else seller
        print(f"  {i:<4}{buyer_name:<30}{seller_name:<30}{data['contracts']:>10}€{data['total_value']:>14,.2f}")


def entity_profile(nif: str, relationships: Dict):
    """Show all relationships for a specific entity."""
    print(f"\n{'='*100}")
    print(f"ENTITY PROFILE: {nif}")
    print(f"{'='*100}")

    # As buyer
    as_buyer = {k: v for k, v in relationships.items() if k[0] == nif}
    # As seller
    as_seller = {k: v for k, v in relationships.items() if k[1] == nif}

    buyer_total = sum(d["total_value"] for d in as_buyer.values())
    seller_total = sum(d["total_value"] for d in as_seller.values())

    print(f"\n  📊 Summary")
    print(f"  {'─'*60}")
    print(f"  As buyer (adjudicante):   {len(as_buyer):,} partners, €{buyer_total:,.2f}")
    print(f"  As seller (adjudicatário): {len(as_seller):,} partners, €{seller_total:,.2f}")

    if as_buyer:
        print(f"\n  🏛️  Buys from (as adjudicante)")
        print(f"  {'─'*80}")
        for (b, s), data in sorted(as_buyer.items(), key=lambda x: -x[1]["total_value"])[:15]:
            print(f"    [{s}] {data['seller_name'][:40]} ({data['contracts']} contracts, €{data['total_value']:,.2f})")

    if as_seller:
        print(f"\n  🏢 Sells to (as adjudicatário)")
        print(f"  {'─'*80}")
        for (b, s), data in sorted(as_seller.items(), key=lambda x: -x[1]["total_value"])[:15]:
            print(f"    [{b}] {data['buyer_name'][:40]} ({data['contracts']} contracts, €{data['total_value']:,.2f})")


def export_network(relationships: Dict, self_ref: List, output: str):
    """Export relationship graph as JSON."""
    output_data = {
        "relationships": [
            {
                "buyer_nif": k[0],
                "seller_nif": k[1],
                "buyer_name": v["buyer_name"],
                "seller_name": v["seller_name"],
                "contracts": v["contracts"],
                "total_value": v["total_value"],
            }
            for k, v in relationships.items()
        ],
        "self_referencing": self_ref,
        "stats": {
            "total_relationships": len(relationships),
            "total_contracts": sum(r["contracts"] for r in relationships.values()),
            "total_value": sum(r["total_value"] for r in relationships.values()),
            "self_referencing_count": len(self_ref),
        },
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    print(f"Exported to {output}", file=sys.stderr)


# =============================================================================
# CROSS-MUNICIPALITY ANALYSIS
# =============================================================================

def load_contract_index() -> Dict:
    """Load contract_index.json (includes adjudicatário data)."""
    if not CONTRACT_INDEX.exists():
        print(f"Error: {CONTRACT_INDEX} not found", file=sys.stderr)
        print("Run `bep_base_crossref.py` first to build the index.", file=sys.stderr)
        return {}
    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_cross_municipality(min_municipalities: int = 3, top_n: int = 30):
    """Find companies winning contracts in multiple municipalities.

    Groups contracts by adjudicatário (winner) NIF, resolves buyer NIFs
    to municipality names, and ranks sellers by number of distinct
    municipalities served and total contract value.
    """
    contract_index = load_contract_index()
    if not contract_index:
        return

    # Build buyer NIF → municipality name mapping
    buyer_nif_to_name: Dict[str, str] = {}
    for nif, contracts in contract_index.items():
        if contracts:
            buyer_nif_to_name[nif] = contracts[0].get("entity_name", nif)

    # Group by adjudicatário NIF
    seller_data: Dict[str, Dict] = defaultdict(lambda: {
        "name": "",
        "municipalities": set(),
        "contracts": 0,
        "total_value": 0.0,
        "buyer_details": defaultdict(lambda: {"contracts": 0, "value": 0.0, "name": ""}),
    })

    total_contracts = 0
    total_with_winner = 0
    total_with_nif = 0

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            total_contracts += 1
            winner_name = c.get("adjudicatario", "")
            winner_nif = c.get("adjudicatario_nif", "")
            if not winner_name:
                continue
            total_with_winner += 1
            if not winner_nif:
                continue
            total_with_nif += 1

            valor = c.get("valor", 0) or 0
            buyer_name = buyer_nif_to_name.get(buyer_nif, buyer_nif)

            sd = seller_data[winner_nif]
            sd["name"] = winner_name
            sd["municipalities"].add(buyer_nif)
            sd["contracts"] += 1
            sd["total_value"] += valor
            sd["buyer_details"][buyer_nif]["contracts"] += 1
            sd["buyer_details"][buyer_nif]["value"] += valor
            sd["buyer_details"][buyer_nif]["name"] = buyer_name

    # Filter to sellers in N+ municipalities and sort by value
    multi_muni = [
        (nif, data) for nif, data in seller_data.items()
        if len(data["municipalities"]) >= min_municipalities
    ]
    multi_muni.sort(key=lambda x: -x[1]["total_value"])

    # Print results
    print(f"\n{'='*110}")
    print(f"CROSS-MUNICIPALITY ANALYSIS — Companies Winning Contracts in {min_municipalities}+ Municipalities")
    print(f"{'='*110}")
    print(f"\n  📊 Dataset Overview")
    print(f"  {'─'*60}")
    print(f"  Total contracts:              {total_contracts:,}")
    print(f"  With adjudicatário name:      {total_with_winner:,} ({total_with_winner*100//max(total_contracts,1)}%)")
    print(f"  With adjudicatário NIF:       {total_with_nif:,} ({total_with_nif*100//max(total_contracts,1)}%)")
    print(f"  Unique sellers:               {len(seller_data):,}")
    print(f"  Sellers in {min_municipalities}+ municipalities: {len(multi_muni):,}")

    if not multi_muni:
        print(f"\n  No companies found winning in {min_municipalities}+ municipalities.")
        return

    total_multi_value = sum(d["total_value"] for _, d in multi_muni)
    print(f"  Total value (multi-muni):     €{total_multi_value:,.2f}")

    print(f"\n  🏢 Top {top_n} Companies by Cross-Municipality Presence")
    print(f"  {'─'*105}")
    print(f"  {'#':<4}{'Seller':<35}{'NIF':<12}{'Municipalities':>14}{'Contracts':>12}{'Total Value':>18}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*14}{'─'*12}{'─'*18}")

    for i, (nif, data) in enumerate(multi_muni[:top_n], 1):
        muni_count = len(data["municipalities"])
        print(f"  {i:<4}{data['name'][:35]:<35}{nif:<12}{muni_count:>14}{data['contracts']:>12,}€{data['total_value']:>16,.2f}")

    # Detail view for top 5
    print(f"\n  🔍 Detailed View — Top 5 Companies")
    for i, (nif, data) in enumerate(multi_muni[:5], 1):
        muni_count = len(data["municipalities"])
        print(f"\n  {'─'*100}")
        print(f"  #{i} {data['name'][:60]}")
        print(f"     NIF: {nif}  |  Municipalities: {muni_count}  |  Contracts: {data['contracts']:,}  |  Total: €{data['total_value']:,.2f}")
        print(f"\n     Top buyers:")
        sorted_buyers = sorted(
            data["buyer_details"].items(),
            key=lambda x: -x[1]["value"]
        )
        for buyer_nif, bd in sorted_buyers[:8]:
            print(f"       [{buyer_nif}] {bd['name'][:45]:<45} {bd['contracts']:>5} contracts  €{bd['value']:>14,.2f}")
        if len(sorted_buyers) > 8:
            print(f"       ... and {len(sorted_buyers) - 8} more municipalities")
    print()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Entity Relationship Analyzer — Buyer-Seller Network",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("analyze", help="Full analysis of buyer-seller relationships")
    sub.add_parser("self-ref", help="Detect self-referencing entities")

    pairs_p = sub.add_parser("pairs", help="Show top buyer-seller pairs")
    pairs_p.add_argument("--top", "-t", type=int, default=30)

    export_p = sub.add_parser("export", help="Export relationship graph")
    export_p.add_argument("--output", "-o", default="data/entity_network.json")

    profile_p = sub.add_parser("profile", help="Entity profile (buyer+seller)")
    profile_p.add_argument("--nif", required=True)

    cross_p = sub.add_parser("cross-municipality", help="Find companies winning in 3+ municipalities")
    cross_p.add_argument("--min", "-m", type=int, default=3, help="Min municipalities (default 3)")
    cross_p.add_argument("--top", "-t", type=int, default=30, help="Show top N results")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if args.command == "cross-municipality":
        analyze_cross_municipality(min_municipalities=args.min, top_n=args.top)
        return

    relationships, self_ref = load_db_relationships()
    if not relationships:
        return

    if args.command == "analyze":
        analyze_relationships(relationships, self_ref)
    elif args.command == "self-ref":
        show_self_referencing(self_ref)
    elif args.command == "pairs":
        show_top_pairs(relationships, args.top)
    elif args.command == "export":
        export_network(relationships, self_ref, args.output)
    elif args.command == "profile":
        entity_profile(args.nif, relationships)


if __name__ == "__main__":
    main()
