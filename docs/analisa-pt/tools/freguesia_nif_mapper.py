#!/usr/bin/env python3
"""Freguesia NIF Mapper — Extract and cross-reference parish NIFs.

Builds a comprehensive mapping of Portuguese freguesia (parish) entities
with their NIFs, linking them to their parent municipality. Uses data from:
- contract_index.json (BASE.gov.pt contracts — 1,466 freguesia entities)
- bep_index.db (BEP job listings — 85 freguesia entities)
- freguesia_mapping.json (name→municipality resolution)

Usage:
    python freguesia_nif_mapper.py build         # Build freguesia NIF index
    python freguesia_nif_mapper.py show --top 30  # Show top freguesias by contracts
    python freguesia_nif_mapper.py lookup "Benfica"  # Look up a freguesia
    python freguesia_nif_mapper.py gaps           # Show unmapped freguesias
    python freguesia_nif_mapper.py export > data/freguesia_nif_index.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
BEP_DB = SCRIPT_DIR / "bep_index.db"
FREGUESIA_MAP = SCRIPT_DIR / "data" / "freguesia_mapping.json"
NIF_MAPPING_FILE = SCRIPT_DIR / "data" / "nif_mapping.json"
OUTPUT_FILE = SCRIPT_DIR / "data" / "freguesia_nif_index.json"


# =============================================================================
# DATA LOADING
# =============================================================================

def _normalize(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    from unidecode import unidecode
    n = unidecode(name.lower().strip())
    # Remove common prefixes
    for prefix in ["freguesia de ", "freguesia do ", "freguesia da ",
                    "junta de freguesia de ", "junta de freguesia do ",
                    "junta de freguesia da ", "uniao das freguesias de ",
                    "uniao das freguesias do ", "uniao das freguesias da "]:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    return n.strip()


def load_freguesia_from_contracts() -> Dict[str, Dict]:
    """Extract freguesia entities from contract_index.json."""
    if not CONTRACT_INDEX.exists():
        print(f"Error: {CONTRACT_INDEX} not found", file=sys.stderr)
        return {}

    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        index = json.load(f)

    freguesias: Dict[str, Dict] = {}

    for nif, contracts in index.items():
        if not contracts:
            continue
        name = contracts[0].get("entity_name", "")
        nl = name.lower()

        # Check if this is a freguesia entity
        is_freguesia = any(p in nl for p in [
            "freguesia", "junta de freguesia", "união das freguesias",
        ])
        if not is_freguesia:
            continue

        total_value = sum(c.get("valor", 0) or 0 for c in contracts)

        # Try to extract the parish name
        parish_name = name
        for prefix in ["Freguesia de ", "Freguesia do ", "Freguesia da ",
                        "Junta de Freguesia de ", "Junta de Freguesia do ",
                        "Junta de Freguesia da ", "União das Freguesias de ",
                        "União das Freguesias do ", "União das Freguesias da "]:
            if name.startswith(prefix):
                parish_name = name[len(prefix):]
                break

        # Check for adjudicatário data
        winners = set()
        winner_contracts = 0
        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            if wn:
                winners.add(wn)
                winner_contracts += 1

        freguesias[nif] = {
            "nif": nif,
            "name": name,
            "parish_name": parish_name,
            "normalized": _normalize(name),
            "contracts": len(contracts),
            "total_value": total_value,
            "unique_sellers": len(winners),
            "winner_contracts": winner_contracts,
            "source": "contract_index",
        }

    return freguesias


def load_freguesia_from_bep() -> Dict[str, Dict]:
    """Extract freguesia entities from BEP database."""
    if not BEP_DB.exists():
        return {}

    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT display_name, nif, listing_count FROM bep_entities "
        "WHERE nif IS NOT NULL AND nif != '' "
        "AND (display_name LIKE '%Freguesia%' OR display_name LIKE '%Junta%')"
    ).fetchall()
    conn.close()

    freguesias: Dict[str, Dict] = {}
    for name, nif, count in rows:
        if nif in freguesias:
            freguesias[nif]["bep_listings"] = count
            continue

        parish_name = name
        for prefix in ["Junta de Freguesia de ", "Junta de Freguesia do ",
                        "Junta de Freguesia da ", "Freguesia de ",
                        "Freguesia do ", "Freguesia da "]:
            if name.startswith(prefix):
                parish_name = name[len(prefix):]
                break

        freguesias[nif] = {
            "nif": nif,
            "name": name,
            "parish_name": parish_name,
            "normalized": _normalize(name),
            "bep_listings": count,
            "source": "bep",
        }

    return freguesias


def load_freguesia_mapping() -> Dict[str, str]:
    """Load freguesia→municipality name mapping."""
    if not FREGUESIA_MAP.exists():
        return {}
    with open(FREGUESIA_MAP, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load_nif_mapping() -> Dict[str, str]:
    """Load Câmara→Município NIF mapping for municipality resolution."""
    if not NIF_MAPPING_FILE.exists():
        return {}
    with open(NIF_MAPPING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    mappings = data.get("mappings", []) if isinstance(data, dict) else data
    # Build a lookup: any NIF → municipality name (via location)
    nif_to_muni = {}
    for m in mappings:
        if "location" in m:
            nif_to_muni[m.get("camara_nif", "")] = m["location"]
            nif_to_muni[m.get("municipio_nif", "")] = m["location"]
    return nif_to_muni


# =============================================================================
# BUILD INDEX
# =============================================================================

def build_index() -> Dict:
    """Build comprehensive freguesia NIF index."""
    print("Loading freguesia entities from contracts...", file=sys.stderr)
    from_contracts = load_freguesia_from_contracts()
    print(f"  Found {len(from_contracts)} in contract_index", file=sys.stderr)

    print("Loading freguesia entities from BEP...", file=sys.stderr)
    from_bep = load_freguesia_from_bep()
    print(f"  Found {len(from_bep)} in BEP", file=sys.stderr)

    print("Loading freguesia→municipality mapping...", file=sys.stderr)
    freg_map = load_freguesia_mapping()
    print(f"  Loaded {len(freg_map)} name mappings", file=sys.stderr)

    print("Loading NIF mapping for municipality resolution...", file=sys.stderr)
    nif_map = load_nif_mapping()

    # Merge: contract_index entities take priority (richer data)
    all_freguesias: Dict[str, Dict] = {}

    for nif, data in from_contracts.items():
        all_freguesias[nif] = data

    for nif, data in from_bep.items():
        if nif not in all_freguesias:
            all_freguesias[nif] = data
        else:
            # Merge BEP data into existing
            all_freguesias[nif]["bep_listings"] = data.get("bep_listings", 0)
            if "bep" not in all_freguesias[nif].get("source", ""):
                all_freguesias[nif]["source"] += "+bep"

    # Resolve municipality for each freguesia
    resolved = 0
    for nif, data in all_freguesias.items():
        norm = data.get("normalized", "")
        # Try freguesia_mapping (name-based)
        municipality = freg_map.get(norm, "")
        if not municipality:
            # Try partial match
            for freg_name, muni in freg_map.items():
                if freg_name in norm or norm in freg_name:
                    municipality = muni
                    break
        data["municipality"] = municipality
        if municipality:
            resolved += 1

    # Stats
    total_contracts = sum(d.get("contracts", 0) for d in all_freguesias.values())
    total_value = sum(d.get("total_value", 0) for d in all_freguesias.values())
    total_bep = sum(d.get("bep_listings", 0) for d in all_freguesias.values())

    stats = {
        "total_freguesias": len(all_freguesias),
        "from_contracts": len(from_contracts),
        "from_bep": len(from_bep),
        "merged": len([d for d in all_freguesias.values() if "+" in d.get("source", "")]),
        "municipality_resolved": resolved,
        "total_contracts": total_contracts,
        "total_value": total_value,
        "total_bep_listings": total_bep,
    }

    result = {
        "version": "1.0",
        "stats": stats,
        "freguesias": all_freguesias,
    }

    # Save
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n=== Freguesia NIF Index Built ===", file=sys.stderr)
    print(f"  Total freguesias:    {stats['total_freguesias']}", file=sys.stderr)
    print(f"  From contracts:      {stats['from_contracts']}", file=sys.stderr)
    print(f"  From BEP:            {stats['from_bep']}", file=sys.stderr)
    print(f"  Merged (both):       {stats['merged']}", file=sys.stderr)
    print(f"  Municipality resolved: {stats['municipality_resolved']}", file=sys.stderr)
    print(f"  Total contracts:     {stats['total_contracts']:,}", file=sys.stderr)
    print(f"  Total value:         €{stats['total_value']:,.2f}", file=sys.stderr)
    print(f"  BEP listings:        {stats['total_bep_listings']}", file=sys.stderr)
    print(f"  Saved to:            {OUTPUT_FILE}", file=sys.stderr)

    return result


# =============================================================================
# DISPLAY
# =============================================================================

def show_index(data: Dict, top_n: int = 30):
    """Display the freguesia index."""
    freguesias = data.get("freguesias", {})
    stats = data.get("stats", {})

    print(f"\n{'='*110}")
    print(f"FREGUESIA NIF INDEX — Portuguese Parish Entities")
    print(f"{'='*110}")
    print(f"  Total freguesias: {stats.get('total_freguesias', 0)}")
    print(f"  Municipality resolved: {stats.get('municipality_resolved', 0)}")
    print(f"  Total contracts: {stats.get('total_contracts', 0):,}")
    print(f"  Total value: €{stats.get('total_value', 0):,.2f}")

    # Sort by total value
    sorted_fregs = sorted(
        freguesias.values(),
        key=lambda x: -x.get("total_value", 0)
    )

    print(f"\n  {'#':<4}{'Freguesia':<40}{'Municipality':<20}{'Contracts':>10}{'Value':>16}{'BEP':>6}")
    print(f"  {'─'*4}{'─'*40}{'─'*20}{'─'*10}{'─'*16}{'─'*6}")

    for i, f in enumerate(sorted_fregs[:top_n], 1):
        name = f.get("parish_name", f.get("name", "?"))[:38]
        muni = f.get("municipality", "")[:18] or "(unknown)"
        contracts = f.get("contracts", 0)
        value = f.get("total_value", 0)
        bep = f.get("bep_listings", 0)
        print(f"  {i:<4}{name:<40}{muni:<20}{contracts:>10}€{value:>14,.2f}{bep:>6}")


def lookup_freguesia(query: str, data: Dict):
    """Look up a specific freguesia."""
    freguesias = data.get("freguesias", {})
    q = query.lower()

    matches = []
    for nif, f in freguesias.items():
        searchable = f"{f.get('name', '')} {f.get('parish_name', '')} {f.get('normalized', '')}".lower()
        if q in searchable:
            matches.append(f)

    if not matches:
        print(f"No freguesia found matching '{query}'")
        return

    for f in matches:
        print(f"\n{'='*80}")
        print(f"  📍 {f.get('name', '?')}")
        print(f"{'='*80}")
        print(f"  NIF:           {f['nif']}")
        print(f"  Parish:        {f.get('parish_name', '?')}")
        print(f"  Municipality:  {f.get('municipality', '(unknown)')}")
        print(f"  Source:        {f.get('source', '?')}")
        print(f"  Contracts:     {f.get('contracts', 0)}")
        print(f"  Total value:   €{f.get('total_value', 0):,.2f}")
        print(f"  Sellers:       {f.get('unique_sellers', 0)}")
        print(f"  BEP listings:  {f.get('bep_listings', 0)}")
        print(f"  BASE URL:      https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={f['nif']}")


def show_gaps(data: Dict):
    """Show unmapped freguesias."""
    freguesias = data.get("freguesias", {})

    unmapped = [f for f in freguesias.values() if not f.get("municipality")]
    mapped = [f for f in freguesias.values() if f.get("municipality")]

    print(f"\n{'='*80}")
    print(f"FREGUESIA MAPPING GAPS")
    print(f"{'='*80}")
    print(f"  Mapped:   {len(mapped)}")
    print(f"  Unmapped: {len(unmapped)}")

    if unmapped:
        print(f"\n  Top unmapped freguesias (by contract value):")
        for f in sorted(unmapped, key=lambda x: -x.get("total_value", 0))[:15]:
            print(f"    [{f['nif']}] {f.get('name', '?')[:50]} ({f.get('contracts', 0)} contracts, €{f.get('total_value', 0):,.0f})")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Freguesia NIF Mapper — Parish entity cross-reference",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("build", help="Build freguesia NIF index")

    show_p = sub.add_parser("show", help="Show freguesia index")
    show_p.add_argument("--top", "-t", type=int, default=30)

    lookup_p = sub.add_parser("lookup", help="Look up a freguesia")
    lookup_p.add_argument("query", help="Freguesia name to search")

    sub.add_parser("gaps", help="Show unmapped freguesias")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if args.command == "build":
        build_index()
    elif args.command == "show":
        if not OUTPUT_FILE.exists():
            print("No index found. Run 'build' first.", file=sys.stderr)
            return
        with open(OUTPUT_FILE, "r") as f:
            data = json.load(f)
        show_index(data, args.top)
    elif args.command == "lookup":
        if not OUTPUT_FILE.exists():
            print("No index found. Run 'build' first.", file=sys.stderr)
            return
        with open(OUTPUT_FILE, "r") as f:
            data = json.load(f)
        lookup_freguesia(args.query, data)
    elif args.command == "gaps":
        if not OUTPUT_FILE.exists():
            print("No index found. Run 'build' first.", file=sys.stderr)
            return
        with open(OUTPUT_FILE, "r") as f:
            data = json.load(f)
        show_gaps(data)


if __name__ == "__main__":
    main()
