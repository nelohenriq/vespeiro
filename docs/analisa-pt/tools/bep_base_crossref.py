#!/usr/bin/env python3
"""BEP × BASE.gov.pt Cross-Reference Report

Links BEP public sector job entities (via NIF) to their public procurement
contracts from BASE.gov.pt. Identifies entities that are both hiring staff
AND awarding public contracts — a key transparency signal.

Usage:
    python bep_base_crossref.py                      # Full report
    python bep_base_crossref.py --entity "Gaia"      # Filter by entity name
    python bep_base_crossref.py --nif 500014872      # Filter by NIF
    python bep_base_crossref.py --export report.json  # Export to JSON
    python bep_base_crossref.py --stats               # Summary statistics
"""

import sys
import json
import re
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict
from utils_db import connect as db_connect

# Paths
SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "bep_index.db"
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
BASE_DETAIL_URL = "https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id="


def extract_nif_from_adjudicante(text: str) -> tuple[str, str]:
    """Extract NIF and entity name from adjudicante field."""
    if not text:
        return ("", "")
    m = re.match(r'^(\d{9})\s*-\s*(.+)$', text.strip())
    if m:
        return (m.group(1), m.group(2).strip())
    m = re.match(r'^-\s*-\s*(.+)$', text.strip())
    if m:
        return ("", m.group(1).strip())
    return ("", text.strip())


def load_bep_entities_with_nif(db_path: Path) -> list[dict]:
    """Load BEP entities that have NIFs."""
    import sqlite3
    conn = db_connect(str(db_path))
    rows = conn.execute(
        "SELECT id, entidade, organismo, display_name, nif, listing_count "
        "FROM bep_entities WHERE nif IS NOT NULL AND nif != '' "
        "ORDER BY listing_count DESC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "entidade": r[1], "organismo": r[2],
         "display_name": r[3], "nif": r[4], "listing_count": r[5]}
        for r in rows
    ]


def build_contract_index() -> dict[str, list[dict]]:
    """Query procurement.db and build NIF → contracts index. Caches as JSON."""
    cache_path = SCRIPT_DIR / "data" / "contract_index.json"
    if cache_path.exists():
        print(f"  Loading cached index from {cache_path.name}...")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    if not PROCUREMENT_DB.exists():
        print(f"  ERROR: procurement.db not found at {PROCUREMENT_DB}")
        print("  Run: python procurement_db.py build")
        return {}

    print(f"  Querying procurement.db...")
    conn = db_connect(str(PROCUREMENT_DB))
    rows = conn.execute(
        "SELECT adjudicante_nif, adjudicante_nome, idcontrato, objectoContrato, "
        "precoContratual, tipoContrato, linkPecasProc, dataPublicacao, "
        "nAnuncio, CPV, adjudicatarios FROM contratos WHERE adjudicante_nif != ''"
    ).fetchall()
    conn.close()

    nif_contracts: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        nif = r["adjudicante_nif"]
        # Parse adjudicatario from the raw field
        adjt = r["adjudicatarios"] or ""
        adjt_nif, adjt_name = extract_nif_from_adjudicante(adjt)

        nif_contracts[nif].append({
            "nif": nif,
            "entity_name": r["adjudicante_nome"],
            "contract_id": r["idcontrato"],
            "objeto": (r["objectoContrato"] or "")[:200],
            "valor": r["precoContratual"] or 0,
            "tipo": r["tipoContrato"] or "",
            "link_pecas_proc": r["linkPecasProc"] or "",
            "data": (r["dataPublicacao"] or "")[:10],
            "nAnuncio": r["nAnuncio"] or "",
            "cpv": r["CPV"] or "",
            "adjudicatario": adjt_name,
            "adjudicatario_nif": adjt_nif,
        })

    result = dict(nif_contracts)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"  Cached index to {cache_path.name}")
    print(f"  {len(rows):,} contracts → {len(result):,} entities with contracts")
    return result


def cross_reference(
    bep_entities: list[dict],
    contract_index: dict[str, list[dict]],
    entity_filter: str = "",
    nif_filter: str = "",
) -> list[dict]:
    """Cross-reference BEP entities with BASE.gov.pt contracts."""
    results = []

    for entity in bep_entities:
        nif = entity["nif"]
        if not nif:
            continue

        if nif_filter and nif != nif_filter:
            continue

        if entity_filter:
            searchable = f"{entity['display_name']} {entity['entidade']} {entity['organismo']}".lower()
            if entity_filter.lower() not in searchable:
                continue

        contracts = contract_index.get(nif, [])
        total_value = sum(c.get("valor", 0) for c in contracts)

        results.append({
            "bep_entity": entity["display_name"],
            "bep_entidade": entity["entidade"],
            "bep_organismo": entity["organismo"],
            "bep_id": entity["id"],
            "nif": nif,
            "bep_listings": entity["listing_count"],
            "base_contracts": len(contracts),
            "base_total_value": total_value,
            "contracts": sorted(contracts, key=lambda c: c.get("data", ""), reverse=True)[:10],
        })

    results.sort(key=lambda r: r["base_contracts"], reverse=True)
    return results


def print_report(results: list[dict], verbose: bool = False):
    """Print the cross-reference report."""
    if not results:
        print("No cross-reference matches found.")
        print("Note: NIF enrichment may still be running (merge_nifs.py)")
        return

    total_contracts = sum(r["base_contracts"] for r in results)
    total_value = sum(r["base_total_value"] for r in results)
    matched = sum(1 for r in results if r["base_contracts"] > 0)

    print(f"\n{'='*80}")
    print(f"  BEP × BASE.gov.pt Cross-Reference Report")
    print(f"{'='*80}")
    print(f"  BEP entities with NIF:     {len(results)}")
    print(f"  Matched to contracts:      {matched}")
    print(f"  Total contracts found:     {total_contracts}")
    print(f"  Total contract value:      €{total_value:,.2f}")
    print(f"{'='*80}\n")

    for r in results:
        marker = "🔗" if r["base_contracts"] > 0 else "  "
        print(f"{marker} {r['bep_entity']}")
        print(f"   NIF: {r['nif']}  |  BEP listings: {r['bep_listings']}  |  "
              f"BASE contracts: {r['base_contracts']}  |  "
              f"Value: €{r['base_total_value']:,.2f}")

        if r["base_contracts"] > 0 and verbose:
            print(f"   Recent contracts:")
            for c in r["contracts"][:5]:
                valor = f"€{c.get('valor', 0):,.2f}" if c.get("valor") else "?"
                cid = c.get("contract_id")
                detail_url = f"{BASE_DETAIL_URL}{cid}" if cid else ""
                link_proc = c.get("link_pecas_proc", "")
                print(f"     [{c.get('data', '?')}] {valor}  {c.get('tipo', '')}  "
                      f"{c.get('objeto', '')[:60]}")
                if detail_url:
                    print(f"       📋 {detail_url}")
                if link_proc:
                    print(f"       📎 {link_proc[:100]}")
        print()


def print_stats(results: list[dict]):
    """Print summary statistics."""
    matched = [r for r in results if r["base_contracts"] > 0]
    unmatched = [r for r in results if r["base_contracts"] == 0]

    print(f"\n=== Cross-Reference Statistics ===")
    print(f"  Total BEP entities with NIF: {len(results)}")
    print(f"  Matched to BASE contracts:   {len(matched)}")
    print(f"  No contracts found:          {len(unmatched)}")

    if matched:
        top = sorted(matched, key=lambda r: r["base_contracts"], reverse=True)[:10]
        print(f"\n  Top entities by contract count:")
        for r in top:
            print(f"    {r['base_contracts']:4d} contracts  €{r['base_total_value']:>14,.2f}  "
                  f"{r['bep_entity'][:50]}")

        total_value = sum(r["base_total_value"] for r in matched)
        print(f"\n  Total contract value: €{total_value:,.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="BEP × BASE.gov.pt Cross-Reference Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--entity", default="", help="Filter by entity name")
    parser.add_argument("--nif", default="", help="Filter by NIF number")
    parser.add_argument("--export", help="Export to JSON file")
    parser.add_argument("--stats", action="store_true", help="Show summary stats only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show contract details")

    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: BEP database not found at {DB_PATH}")
        print("Run `bep_scraper.py collect` first.")
        sys.exit(1)

    if not PROCUREMENT_DB.exists():
        print(f"ERROR: procurement.db not found at {PROCUREMENT_DB}")
        print("Run: python procurement_db.py build")
        sys.exit(1)

    print("Loading BEP entities with NIFs...")
    bep_entities = load_bep_entities_with_nif(DB_PATH)
    print(f"  Found {len(bep_entities)} entities with NIFs")

    print("Building contract index from procurement.db...")
    contract_index = build_contract_index()

    print("Cross-referencing...")
    results = cross_reference(
        bep_entities, contract_index,
        entity_filter=args.entity,
        nif_filter=args.nif,
    )

    if args.stats:
        print_stats(results)
    else:
        print_report(results, verbose=args.verbose)

    if args.export:
        output = {
            "summary": {
                "bep_entities_with_nif": len(results),
                "matched_to_contracts": sum(1 for r in results if r["base_contracts"] > 0),
                "total_contracts": sum(r["base_contracts"] for r in results),
                "total_value": sum(r["base_total_value"] for r in results),
            },
            "results": results,
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nExported to {args.export}")


if __name__ == "__main__":
    main()
