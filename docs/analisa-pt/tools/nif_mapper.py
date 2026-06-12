#!/usr/bin/env python3
"""
NIF Mapper — Câmara ↔ Município NIF Cross-Reference Tool

Builds and maintains a comprehensive mapping between Câmara Municipal (BEP)
and Município (BASE.gov.pt) NIFs for all Portuguese municipalities.

In Portugal, the same municipality appears as two entities:
- Câmara Municipal (BEP): NIF for hiring/payroll
- Município (BASE): NIF for procurement/contracts

This tool bridges that gap by cross-referencing both databases.

Usage:
    # Build the mapping from BEP + BASE data
    python nif_mapper.py build

    # Show the mapping table
    python nif_mapper.py show --top 50

    # Look up a specific municipality
    python nif_mapper.py lookup "Gaia"

    # Show unmapped entities (gap analysis)
    python nif_mapper.py gaps

    # Export as JSON for use by other tools
    python nif_mapper.py export > data/nif_mapping.json

    # Validate existing mapping
    python nif_mapper.py validate
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from unidecode import unidecode
from utils import format_currency, normalize_name, extract_location_typed as extract_location
from utils_db import connect as db_connect

# Paths
SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"
NIF_MAPPING_FILE = SCRIPT_DIR / "data" / "nif_mapping.json"


# =============================================================================
# ENTITY EXTRACTION
# =============================================================================

# Prefixes that identify municipality-level entities
MUNI_PREFIXES = [
    "camara municipal de ", "camara municipal do ", "camara municipal da ",
    "municipio de ", "municipio do ", "municipio da ",
]

# Prefixes that identify sub-municipal entities (schools, health, etc.)
SUB_PREFIXES = [
    "junta de freguesia de ", "junta de freguesia do ", "junta de freguesia da ",
    "hospital de ", "hospital do ", "hospital da ",
    "hospital distrital de ", "hospital distrital do ",
    "unidade local de saude de ", "unidade local de saude do ", "unidade local de saude da ",
    "centro hospitalar de ", "centro hospitalar do ",
    "escola basica de ", "escola basica do ",
    "agrupamento de escolas de ", "agrupamento de escolas do ", "agrupamento de escolas da ",
    "centro de saude de ", "centro de saude do ",
    "instituto politecnico de ", "universidade de ",
    "servicos municipalizados de ", "emep - ",
    "associacao de municipios ",
]



def load_bep_entities() -> Dict[str, List[Dict]]:
    """Load all BEP entities with NIFs, grouped by normalized location."""
    if not BEP_DB.exists():
        print(f"Error: BEP database not found at {BEP_DB}", file=sys.stderr)
        return {}

    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT display_name, nif, listing_count FROM bep_entities "
        "WHERE nif IS NOT NULL AND nif != ''"
    ).fetchall()
    conn.close()

    by_location = defaultdict(list)
    for name, nif, count in rows:
        result = extract_location(name)
        if result:
            location, etype = result
            by_location[location].append({
                "nif": nif,
                "name": name,
                "type": etype,
                "count": count,
            })
    return dict(by_location)


def load_base_entities() -> Dict[str, List[Dict]]:
    """Load all BASE entities from contract index, grouped by normalized location."""
    if not CONTRACT_CACHE.exists():
        print(f"Error: Contract index not found at {CONTRACT_CACHE}", file=sys.stderr)
        return {}

    with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
        index = json.load(f)

    by_location = defaultdict(list)
    for nif, contracts in index.items():
        if not contracts:
            continue
        name = contracts[0].get("entity_name", "")
        result = extract_location(name)
        if result:
            location, etype = result
            by_location[location].append({
                "nif": nif,
                "name": name,
                "type": etype,
                "count": len(contracts),
            })
    return dict(by_location)


# =============================================================================
# MAPPING BUILDER
# =============================================================================

def build_mapping() -> Dict:
    """Build comprehensive Câmara ↔ Município NIF mapping.

    Enforces strict 1:1 pairs: each Câmara NIF and each Município NIF
    appears at most once.  When the same Câmara NIF appears at multiple
    locations (due to name-matching noise), the pair with the most
    contracts/listings wins.

    Returns a dict with:
    - mappings: list of {location, camara_nif, municipio_nif, ...}
    - stats: coverage statistics
    """
    print("Loading BEP entities...", file=sys.stderr)
    bep = load_bep_entities()
    print(f"  Found {len(bep)} locations in BEP", file=sys.stderr)

    print("Loading BASE entities...", file=sys.stderr)
    base = load_base_entities()
    print(f"  Found {len(base)} locations in BASE", file=sys.stderr)

    # Find common locations
    common = set(bep.keys()) & set(base.keys())
    print(f"  Common locations: {len(common)}", file=sys.stderr)

    # Step 1: Build candidate pairs for every common location.
    # A candidate is (score, location, camara_entry, municipio_entry).
    # Score = camara_listings × municipio_contracts (heavier = more likely correct).
    candidates: list[tuple[int, str, Dict, Dict]] = []

    for location in sorted(common):
        bep_entries = bep[location]
        base_entries = base[location]

        # Câmara entries: name must contain 'camara'
        camaras = [e for e in bep_entries
                   if "camara" in normalize_name(e["name"])]
        # Município entries: name must contain 'municipio'
        municipios = [e for e in base_entries
                      if "municipio" in normalize_name(e["name"])]

        if camaras and municipios:
            best_camara = max(camaras, key=lambda x: x["count"])
            best_municipio = max(municipios, key=lambda x: x["count"])
            score = (best_camara["count"] + 1) * (best_municipio["count"] + 1)
            candidates.append((score, location, best_camara, best_municipio))

    print(f"  Candidate pairs: {len(candidates)}", file=sys.stderr)

    # Step 2: Greedy dedup — sort by score descending, then pick greedily.
    # This ensures the highest-confidence pairs survive when the same
    # Câmara NIF appears at multiple locations.
    candidates.sort(key=lambda c: -c[0])

    mappings = []
    used_camara_nifs: set[str] = set()
    used_municipio_nifs: set[str] = set()
    dropped_camara = 0
    dropped_municipio = 0

    for score, location, camara, municipio in candidates:
        cn = camara["nif"]
        mn = municipio["nif"]

        if cn in used_camara_nifs:
            dropped_camara += 1
            continue
        if mn in used_municipio_nifs:
            dropped_municipio += 1
            continue

        mappings.append({
            "location": location.title(),
            "camara_nif": cn,
            "municipio_nif": mn,
            "camara_name": camara["name"],
            "municipio_name": municipio["name"],
            "camara_listings": camara["count"],
            "municipio_contracts": municipio["count"],
        })
        used_camara_nifs.add(cn)
        used_municipio_nifs.add(mn)

    print(f"  Dropped (duplicate Câmara):  {dropped_camara}", file=sys.stderr)
    print(f"  Dropped (duplicate Município): {dropped_municipio}", file=sys.stderr)

    # Statistics
    all_bep_locations = set(bep.keys())
    all_base_locations = set(base.keys())

    stats = {
        "total_mappings": len(mappings),
        "bep_locations": len(all_bep_locations),
        "base_locations": len(all_base_locations),
        "common_locations": len(common),
        "bep_only": len(all_bep_locations - all_base_locations),
        "base_only": len(all_base_locations - all_bep_locations),
        "dropped_camara": dropped_camara,
        "dropped_municipio": dropped_municipio,
    }

    return {"mappings": mappings, "stats": stats}


# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================


def show_mapping_table(data: Dict, top_n: int = 50):
    """Display the mapping table."""
    mappings = data["mappings"]
    stats = data["stats"]

    print(f"\n{'='*100}")
    print(f"CÂMARA ↔ MUNICÍPIO NIF MAPPING TABLE")
    print(f"{'='*100}")
    print(f"{'#':<4}{'Location':<25}{'Câmara NIF':<14}{'Município NIF':<14}{'BEP Listings':>14}{'BASE Contracts':>16}")
    print(f"{'─'*4}{'─'*25}{'─'*14}{'─'*14}{'─'*14}{'─'*16}")

    for i, m in enumerate(sorted(mappings, key=lambda x: -x["municipio_contracts"])[:top_n], 1):
        print(f"{i:<4}{m['location']:<25}{m['camara_nif']:<14}{m['municipio_nif']:<14}"
              f"{m['camara_listings']:>14}{m['municipio_contracts']:>16}")

    print(f"\n{'─'*100}")
    print(f"  Total mappings: {stats['total_mappings']}")
    print(f"  BEP locations: {stats['bep_locations']}")
    print(f"  BASE locations: {stats['base_locations']}")
    print(f"  Common: {stats['common_locations']}")
    print(f"  BEP-only (no BASE contracts): {stats['bep_only']}")
    print(f"  BASE-only (no BEP listings): {stats['base_only']}")


def lookup_municipality(query: str, data: Dict):
    """Look up a specific municipality."""
    q = normalize_name(query)
    matches = []
    for m in data["mappings"]:
        if q in normalize_name(m["location"]) or q in normalize_name(m.get("camara_name", "")) or q in normalize_name(m.get("municipio_name", "")):
            matches.append(m)

    if not matches:
        print(f"No mapping found for '{query}'")
        return

    for m in matches:
        print(f"\n{'='*80}")
        print(f"  📍 {m['location']}")
        print(f"{'='*80}")
        print(f"  Câmara Municipal:")
        print(f"    NIF:      {m['camara_nif']}")
        print(f"    Name:     {m['camara_name']}")
        print(f"    BEP URL:  https://bep.gov.pt (listings: {m['camara_listings']})")
        print(f"  Município:")
        print(f"    NIF:      {m['municipio_nif']}")
        print(f"    Name:     {m['municipio_name']}")
        print(f"    BASE URL: https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={m['municipio_nif']}")
        print(f"    Contracts: {m['municipio_contracts']}")
        print(f"  Cross-reference:")
        print(f"    entity_profile.py --nif {m['camara_nif']}")


def show_gaps(data: Dict):
    """Show unmapped entities (gap analysis)."""
    mappings = data["mappings"]
    mapped_camara_nifs = {m["camara_nif"] for m in mappings}
    mapped_municipio_nifs = {m["municipio_nif"] for m in mappings}

    print(f"\n{'='*80}")
    print(f"GAP ANALYSIS — Unmapped NIFs")
    print(f"{'='*80}")

    # BEP entities without BASE match
    bep = load_bep_entities()
    unmapped_bep = []
    for location, entries in bep.items():
        for e in entries:
            if e["nif"] not in mapped_municipio_nifs and "camara" in normalize_name(e["name"]):
                unmapped_bep.append(e)

    if unmapped_bep:
        print(f"\n  Câmara Municipal entities in BEP without Município match in BASE:")
        for e in sorted(unmapped_bep, key=lambda x: -x["count"])[:20]:
            print(f"    [{e['nif']}] {e['name'][:50]} ({e['count']} listings)")

    # BASE entities without BEP match
    base = load_base_entities()
    unmapped_base = []
    for location, entries in base.items():
        for e in entries:
            if e["nif"] not in mapped_camara_nifs and "municipio" in normalize_name(e["name"]):
                unmapped_base.append(e)

    if unmapped_base:
        print(f"\n  Município entities in BASE without Câmara match in BEP:")
        for e in sorted(unmapped_base, key=lambda x: -x["count"])[:20]:
            print(f"    [{e['nif']}] {e['name'][:50]} ({e['count']} contracts)")

    print(f"\n  Unmapped Câmara: {len(unmapped_bep)}")
    print(f"  Unmapped Município: {len(unmapped_base)}")


def validate_mapping():
    """Validate the existing NIF mapping file."""
    if not NIF_MAPPING_FILE.exists():
        print(f"No mapping file found at {NIF_MAPPING_FILE}")
        return

    with open(NIF_MAPPING_FILE, "r") as f:
        data = json.load(f)

    if isinstance(data, dict) and "mappings" in data:
        mappings = data["mappings"]
    elif isinstance(data, list):
        mappings = data
    else:
        print("Unknown format")
        return

    print(f"\n{'='*80}")
    print(f"VALIDATION REPORT")
    print(f"{'='*80}")
    print(f"  Total entries: {len(mappings)}")

    # Check for duplicates
    seen_camara = defaultdict(list)
    seen_municipio = defaultdict(list)
    for m in mappings:
        cn = m.get("camara_nif", "")
        mn = m.get("municipio_nif", "")
        if cn:
            seen_camara[cn].append(m.get("location", "?"))
        if mn:
            seen_municipio[mn].append(m.get("location", "?"))

    dup_camara = {nif: locs for nif, locs in seen_camara.items() if len(locs) > 1}
    dup_municipio = {nif: locs for nif, locs in seen_municipio.items() if len(locs) > 1}

    if dup_camara:
        print(f"\n  ⚠️  Duplicate Câmara NIFs:")
        for nif, locs in list(dup_camara.items())[:5]:
            print(f"    [{nif}] used by: {', '.join(locs)}")

    if dup_municipio:
        print(f"\n  ⚠️  Duplicate Município NIFs:")
        for nif, locs in list(dup_municipio.items())[:5]:
            print(f"    [{nif}] used by: {', '.join(locs)}")

    # Check for empty fields
    empty = sum(1 for m in mappings if not m.get("camara_nif") or not m.get("municipio_nif"))
    if empty:
        print(f"\n  ⚠️  Entries with missing NIFs: {empty}")

    print(f"\n  ✅ Valid entries: {len(mappings) - empty}")
    print(f"  📍 Unique Câmara NIFs: {len(seen_camara)}")
    print(f"  📍 Unique Município NIFs: {len(seen_municipio)}")


def export_mapping(data: Dict):
    """Export mapping as JSON."""
    # Convert to clean format
    output = {
        "version": "3.0",
        "description": "Câmara Municipal ↔ Município NIF mapping for Portuguese municipalities",
        "generated_by": "nif_mapper.py",
        "stats": data["stats"],
        "mappings": data["mappings"],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="NIF Mapper — Câmara ↔ Município NIF Cross-Reference",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("build", help="Build mapping from BEP + BASE data")

    show_parser = subparsers.add_parser("show", help="Show mapping table")
    show_parser.add_argument("--top", "-t", type=int, default=50, help="Number of entries to show")

    lookup_parser = subparsers.add_parser("lookup", help="Look up a municipality")
    lookup_parser.add_argument("query", help="Municipality name or NIF")

    subparsers.add_parser("gaps", help="Show unmapped entities")

    subparsers.add_parser("export", help="Export mapping as JSON")

    subparsers.add_parser("validate", help="Validate existing mapping")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "build":
        data = build_mapping()
        # Save to file
        with open(NIF_MAPPING_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {data['stats']['total_mappings']} mappings to {NIF_MAPPING_FILE}", file=sys.stderr)

    elif args.command == "show":
        if not NIF_MAPPING_FILE.exists():
            print("No mapping found. Run 'build' first.", file=sys.stderr)
            return
        with open(NIF_MAPPING_FILE, "r") as f:
            data = json.load(f)
        show_mapping_table(data, args.top)

    elif args.command == "lookup":
        if not NIF_MAPPING_FILE.exists():
            print("No mapping found. Run 'build' first.", file=sys.stderr)
            return
        with open(NIF_MAPPING_FILE, "r") as f:
            data = json.load(f)
        lookup_municipality(args.query, data)

    elif args.command == "gaps":
        data = build_mapping()
        show_gaps(data)

    elif args.command == "export":
        if not NIF_MAPPING_FILE.exists():
            print("No mapping found. Run 'build' first.", file=sys.stderr)
            return
        with open(NIF_MAPPING_FILE, "r") as f:
            data = json.load(f)
        export_mapping(data)

    elif args.command == "validate":
        validate_mapping()


if __name__ == "__main__":
    main()
