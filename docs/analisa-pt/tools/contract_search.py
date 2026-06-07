#!/usr/bin/env python3
"""Contract Search CLI — Search 245K+ Portuguese public procurement contracts.

Searches across all contracts in contract_index.json by keyword, NIF,
date range, or value range. Replaces the broken search on base.gov.pt.

Usage:
    python contract_search.py "hospital"
    python contract_search.py --nif 505335018
    python contract_search.py --nif 505335018 --keyword "informática"
    python contract_search.py --min-value 100000 --max-value 500000
    python contract_search.py --keyword "reabilitação" --min-date 2025-01-01
    python contract_search.py --tipo "Aquisição de serviços" --top 20
    python contract_search.py --stats  # Show dataset statistics
"""

import sys
import json
import argparse
from pathlib import Path
import re
from collections import defaultdict
from datetime import datetime
from utils import format_currency as format_value

SCRIPT_DIR = Path(__file__).parent
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"

BASE_DETAIL_URL = "https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id="


def load_index() -> dict:
    """Load the contract index into memory."""
    if not CONTRACT_CACHE.exists():
        print(f"Error: Contract index not found at {CONTRACT_CACHE}")
        print("Run merge_nifs.py or bep_base_crossref.py to build it.")
        sys.exit(1)
    with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


def search_contracts(
    index: dict,
    keyword: str = "",
    nif: str = "",
    min_date: str = "",
    max_date: str = "",
    min_value: float = 0,
    max_value: float = float("inf"),
    tipo: str = "",
    limit: int = 50,
) -> list[dict]:
    """Search contracts with multiple filter criteria.

    All filters are AND-combined. Keyword search is case-insensitive
    and matches against entity_name, objeto, and tipo fields.
    """
    results = []
    keyword_lower = keyword.lower() if keyword else ""

    for nif_key, contracts in index.items():
        # NIF filter (exact match or substring)
        if nif and nif not in nif_key:
            continue

        for c in contracts:
            # Keyword filter
            if keyword_lower:
                searchable = " ".join([
                    c.get("entity_name", ""),
                    c.get("objeto", ""),
                    c.get("tipo", ""),
                ]).lower()
                if keyword_lower not in searchable:
                    continue

            # Date filters
            contract_date = c.get("data", "")
            if min_date and contract_date and contract_date < min_date:
                continue
            if max_date and contract_date and contract_date > max_date:
                continue

            # Value filters
            contract_value = c.get("valor", 0) or 0
            if contract_value < min_value:
                continue
            if contract_value > max_value:
                continue

            # Tipo filter
            if tipo:
                contract_tipo = (c.get("tipo") or "").lower()
                if tipo.lower() not in contract_tipo:
                    continue

            # Enrich with detail URL
            cid = c.get("contract_id")
            c["detail_url"] = f"{BASE_DETAIL_URL}{cid}" if cid else ""

            results.append(c)

            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    # Sort by date descending, then value descending
    results.sort(key=lambda x: (x.get("data", ""), x.get("valor", 0)), reverse=True)
    return results


def compute_stats(contracts: list[dict]) -> dict:
    """Compute aggregate statistics for a set of contracts."""
    if not contracts:
        return {}

    total_value = sum(c.get("valor", 0) or 0 for c in contracts)
    values = [c.get("valor", 0) or 0 for c in contracts]
    dates = [c.get("data", "") for c in contracts if c.get("data")]

    # Type breakdown
    type_counts = defaultdict(int)
    type_values = defaultdict(float)
    for c in contracts:
        t = c.get("tipo") or "Desconhecido"
        type_counts[t] += 1
        type_values[t] += c.get("valor", 0) or 0

    # Entity breakdown
    entity_counts = defaultdict(int)
    entity_values = defaultdict(float)
    for c in contracts:
        e = c.get("entity_name") or "Desconhecido"
        entity_counts[e] += 1
        entity_values[e] += c.get("valor", 0) or 0

    return {
        "total_contracts": len(contracts),
        "total_value": total_value,
        "avg_value": total_value / len(contracts) if contracts else 0,
        "min_value": min(values) if values else 0,
        "max_value": max(values) if values else 0,
        "date_range": (min(dates), max(dates)) if dates else ("N/A", "N/A"),
        "type_breakdown": sorted(
            [(t, type_counts[t], type_values[t]) for t in type_counts],
            key=lambda x: -x[2],
        ),
        "top_entities": sorted(
            [(e, entity_counts[e], entity_values[e]) for e in entity_counts],
            key=lambda x: -x[2],
        )[:10],
    }


def format_value(val: float) -> str:
    """Format a monetary value in EUR."""
    if val >= 1_000_000:
        return f"€{val:,.2f} ({val/1_000_000:.1f}M)"
    elif val >= 1_000:
        return f"€{val:,.2f} ({val/1_000:.1f}K)"
    return f"€{val:,.2f}"


def print_results(results: list[dict], keyword: str = "", show_urls: bool = False):
    """Print search results in a formatted table."""
    if not results:
        print("\n  No contracts found matching your criteria.\n")
        return

    print(f"\n  Found {len(results)} contracts:\n")
    print(f"  {'Date':<12} {'Value':>15}  {'Type':<30} {'Entity':<35} {'Description'}")
    print(f"  {'-'*12} {'-'*15}  {'-'*30} {'-'*35} {'-'*40}")

    for c in results:
        date = c.get("data", "N/A")
        valor = c.get("valor", 0) or 0
        tipo = (c.get("tipo") or "N/A")[:30]
        entity = (c.get("entity_name") or "N/A")[:35]
        objeto = (c.get("objeto") or "N/A")[:40]

        print(f"  {date:<12} {format_value(valor):>15}  {tipo:<30} {entity:<35} {objeto}")

        if show_urls and c.get("detail_url"):
            print(f"  {'':>12} {'':>15}  📋 {c['detail_url']}")

    print()


def print_stats(stats: dict):
    """Print aggregate statistics."""
    if not stats:
        print("\n  No statistics to display.\n")
        return

    print(f"\n  {'='*70}")
    print(f"  📊 CONTRACT SEARCH STATISTICS")
    print(f"  {'='*70}")
    print(f"  Total contracts: {stats['total_contracts']:,}")
    print(f"  Total value:     {format_value(stats['total_value'])}")
    print(f"  Average value:   {format_value(stats['avg_value'])}")
    print(f"  Min value:       {format_value(stats['min_value'])}")
    print(f"  Max value:       {format_value(stats['max_value'])}")
    print(f"  Date range:      {stats['date_range'][0]} → {stats['date_range'][1]}")

    if stats.get("type_breakdown"):
        print(f"\n  Contract Types:")
        for tipo, count, value in stats["type_breakdown"][:10]:
            print(f"    {count:5d} contracts  {format_value(value):>15}  {tipo}")

    if stats.get("top_entities"):
        print(f"\n  Top Entities by Value:")
        for entity, count, value in stats["top_entities"][:10]:
            print(f"    {count:5d} contracts  {format_value(value):>15}  {entity[:50]}")

    print(f"  {'='*70}\n")


def print_dataset_stats(index: dict):
    """Print overall dataset statistics."""
    total_contracts = sum(len(cs) for cs in index.values())
    total_value = sum(c.get("valor", 0) or 0 for cs in index.values() for c in cs)

    # Type breakdown
    type_counts = defaultdict(int)
    for cs in index.values():
        for c in cs:
            t = c.get("tipo") or "Desconhecido"
            type_counts[t] += 1

    # Date range
    all_dates = []
    for cs in index.values():
        for c in cs:
            d = c.get("data", "")
            if d:
                all_dates.append(d)

    print(f"\n  {'='*70}")
    print(f"  📦 CONTRACT INDEX DATASET STATISTICS")
    print(f"  {'='*70}")
    print(f"  Total NIFs:      {len(index):,}")
    print(f"  Total contracts: {total_contracts:,}")
    print(f"  Total value:     {format_value(total_value)}")
    print(f"  Date range:      {min(all_dates) if all_dates else 'N/A'} → {max(all_dates) if all_dates else 'N/A'}")
    print(f"\n  Contract Types:")
    for tipo, count in sorted(type_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"    {count:6d}  {tipo}")
    print(f"  {'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Search 245K+ Portuguese public procurement contracts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "hospital"                        Search by keyword
  %(prog)s --nif 505335018                   Search by NIF
  %(prog)s --min-value 100000                Contracts over €100K
  %(prog)s --keyword "informática" --min-date 2025-01-01
  %(prog)s --tipo "Aquisição" --top 20       Top 20 by type
  %(prog)s --stats                           Dataset statistics
        """,
    )
    parser.add_argument("keyword", nargs="?", default="", help="Search keyword (matches entity, description, type)")
    parser.add_argument("--nif", default="", help="Filter by NIF (exact or partial match)")
    parser.add_argument("--min-date", default="", help="Minimum date (YYYY-MM-DD)")
    parser.add_argument("--max-date", default="", help="Maximum date (YYYY-MM-DD)")
    parser.add_argument("--min-value", type=float, default=0, help="Minimum contract value (EUR)")
    parser.add_argument("--max-value", type=float, default=float("inf"), help="Maximum contract value (EUR)")
    parser.add_argument("--tipo", default="", help="Filter by contract type (partial match)")
    parser.add_argument("--top", type=int, default=50, help="Maximum results to show (default: 50)")
    parser.add_argument("--urls", action="store_true", help="Show detail URLs for each contract")
    parser.add_argument("--stats", action="store_true", help="Show search result statistics")
    parser.add_argument("--dataset-stats", action="store_true", help="Show overall dataset statistics")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    # Load index
    index = load_index()

    # Dataset stats mode
    if args.dataset_stats:
        print_dataset_stats(index)
        return

    # Search
    results = search_contracts(
        index,
        keyword=args.keyword,
        nif=args.nif,
        min_date=args.min_date,
        max_date=args.max_date,
        min_value=args.min_value,
        max_value=args.max_value,
        tipo=args.tipo,
        limit=args.top,
    )

    # Output
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_results(results, keyword=args.keyword, show_urls=args.urls)

        if args.stats:
            stats = compute_stats(results)
            print_stats(stats)


if __name__ == "__main__":
    main()
