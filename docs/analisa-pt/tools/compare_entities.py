#!/usr/bin/env python3
"""Cross-Entity Comparison Tool

Compares two Portuguese public entities side by side across all
transparency dimensions: BEP jobs, BASE contracts, DRE publications,
and law projects.

Usage:
    python compare_entities.py "Gaia" "Lisboa"
    python compare_entities.py --nif 500014872 500000105
    python compare_entities.py "Saúde" "Educação" --export comparison.json
"""

import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict


# Import shared functions from entity_profile
from entity_profile import (
    search_entities, get_entity_listings, get_entity_contracts,
    get_entity_dre, get_entity_laws, compute_contract_trends,
    compute_hiring_trends,
)

SCRIPT_DIR = Path(__file__).parent


def _safe_int(val, default=1):
    """Safely convert a value to int."""
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


def compare_side_by_side(a: dict, b: dict) -> dict:
    """Compute comparison metrics between two entities."""
    def avg(values):
        return sum(values) / len(values) if values else 0

    def salary_stats(listings):
        salaries = []
        for l in listings:
            try:
                s = float(l.get("remuneracao", 0) or 0)
                if s > 0:
                    salaries.append(s)
            except (ValueError, TypeError):
                pass
        return {
            "count": len(salaries),
            "avg": avg(salaries),
            "min": min(salaries) if salaries else 0,
            "max": max(salaries) if salaries else 0,
        }

    def contract_type_breakdown(contracts):
        types = defaultdict(int)
        for c in contracts:
            tipo = c.get("tipo") or "Unknown"
            types[tipo] += 1
        return dict(sorted(types.items(), key=lambda x: -x[1]))

    def hiring_type_breakdown(listings):
        types = defaultdict(int)
        for l in listings:
            tipo = l.get("tipo_oferta") or l.get("categoria") or "Unknown"
            types[tipo] += 1
        return dict(sorted(types.items(), key=lambda x: -x[1]))

    total_a = sum(c.get("valor", 0) for c in a["contracts"])
    total_b = sum(c.get("valor", 0) for c in b["contracts"])

    return {
        "bep": {
            "listings": {"a": len(a["listings"]), "b": len(b["listings"])},
            "positions": {
                "a": sum(_safe_int(l.get("total_postos")) for l in a["listings"]),
                "b": sum(_safe_int(l.get("total_postos")) for l in b["listings"]),
            },
            "salary": {"a": salary_stats(a["listings"]), "b": salary_stats(b["listings"])},
            "types": {"a": hiring_type_breakdown(a["listings"]), "b": hiring_type_breakdown(b["listings"])},
        },
        "contracts": {
            "count": {"a": len(a["contracts"]), "b": len(b["contracts"])},
            "total_value": {"a": total_a, "b": total_b},
            "avg_value": {
                "a": total_a / len(a["contracts"]) if a["contracts"] else 0,
                "b": total_b / len(b["contracts"]) if b["contracts"] else 0,
            },
            "types": {"a": contract_type_breakdown(a["contracts"]), "b": contract_type_breakdown(b["contracts"])},
        },
        "dre": {
            "publications": {"a": len(a["dre"]), "b": len(b["dre"])},
        },
        "laws": {
            "projects": {"a": len(a["laws"]), "b": len(b["laws"])},
        },
    }


def _winner_symbol(a, b):
    """Return comparison symbol between two numeric values."""
    if a > b:
        return "◀"
    elif b > a:
        return "▶"
    return "═"


def print_comparison(name_a: str, name_b: str, data_a: dict, data_b: dict,
                     comparison: dict):
    """Print the side-by-side comparison."""
    short_a = name_a[:30]
    short_b = name_b[:30]
    col_w = 30

    def row(label, val_a, val_b, fmt="s"):
        if fmt == "money":
            a_str = f"€{val_a:,.0f}" if val_a else "—"
            b_str = f"€{val_b:,.0f}" if val_b else "—"
        elif fmt == "money2":
            a_str = f"€{val_a:,.2f}" if val_a else "—"
            b_str = f"€{val_b:,.2f}" if val_b else "—"
        elif fmt == "num":
            a_str = f"{val_a:,}" if val_a else "—"
            b_str = f"{val_b:,}" if val_b else "—"
        else:
            a_str = str(val_a) if val_a else "—"
            b_str = str(val_b) if val_b else "—"
        print(f"  {label:28s} {a_str:>{col_w}s}  │  {b_str:<{col_w}s}")

    print(f"\n{'='*95}")
    print(f"  ⚖️  ENTITY COMPARISON")
    print(f"{'='*95}")

    # Header
    print(f"  {'':28s} {short_a:>{col_w}s}  │  {short_b:<{col_w}s}")
    print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")

    # --- BEP Jobs ---
    bep = comparison["bep"]
    row("BEP Listings", bep["listings"]["a"], bep["listings"]["b"], "num")
    row("Total Positions", bep["positions"]["a"], bep["positions"]["b"], "num")
    sa = bep["salary"]["a"]
    sb = bep["salary"]["b"]
    row("Avg Salary", sa["avg"], sb["avg"], "money2")
    row("Salary Range", f"{sa['min']:,.0f}-{sa['max']:,.0f}" if sa["min"] else None,
        f"{sb['min']:,.0f}-{sb['max']:,.0f}" if sb["min"] else None)
    print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")

    # --- BASE Contracts ---
    ct = comparison["contracts"]
    row("Contract Count", ct["count"]["a"], ct["count"]["b"], "num")
    row("Total Contract Value", ct["total_value"]["a"], ct["total_value"]["b"], "money")
    row("Avg Contract Value", ct["avg_value"]["a"], ct["avg_value"]["b"], "money")
    print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")

    # --- DRE & Laws ---
    row("DRE Publications", comparison["dre"]["publications"]["a"],
        comparison["dre"]["publications"]["b"], "num")
    row("Law Projects", comparison["laws"]["projects"]["a"],
        comparison["laws"]["projects"]["b"], "num")
    print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")

    # --- Contract Type Breakdown ---
    all_types = set(comparison["contracts"]["types"]["a"]) | set(comparison["contracts"]["types"]["b"])
    if all_types:
        print(f"  {'Contract Types':28s} {'─'*col_w}──┼──{'─'*col_w}")
        for tipo in sorted(all_types, key=lambda t: -(comparison["contracts"]["types"]["a"].get(t, 0) +
                                                       comparison["contracts"]["types"]["b"].get(t, 0))):
            cnt_a = comparison["contracts"]["types"]["a"].get(tipo, 0)
            cnt_b = comparison["contracts"]["types"]["b"].get(tipo, 0)
            if cnt_a or cnt_b:
                w = _winner_symbol(cnt_a, cnt_b)
                row(f"  {tipo[:25]}", f"{cnt_a} {w}", f"{cnt_b} {w}", "s")
        print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")

    # --- Hiring Type Breakdown ---
    all_h_types = set(comparison["bep"]["types"]["a"]) | set(comparison["bep"]["types"]["b"])
    if all_h_types:
        print(f"  {'Hiring Categories':28s} {'─'*col_w}──┼──{'─'*col_w}")
        for tipo in sorted(all_h_types, key=lambda t: -(comparison["bep"]["types"]["a"].get(t, 0) +
                                                         comparison["bep"]["types"]["b"].get(t, 0)))[:8]:
            cnt_a = comparison["bep"]["types"]["a"].get(tipo, 0)
            cnt_b = comparison["bep"]["types"]["b"].get(tipo, 0)
            if cnt_a or cnt_b:
                w = _winner_symbol(cnt_a, cnt_b)
                row(f"  {tipo[:25]}", f"{cnt_a} {w}", f"{cnt_b} {w}", "s")
        print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")

    # --- Winner Summary ---
    print(f"\n  {'SUMMARY':28s}")
    print(f"  {'─'*28} {'─'*col_w}──┼──{'─'*col_w}")
    scores = {"a": 0, "b": 0}
    metrics = [
        ("More listings", bep["listings"]["a"], bep["listings"]["b"]),
        ("Higher salaries", sa["avg"], sb["avg"]),
        ("More contracts", ct["count"]["a"], ct["count"]["b"]),
        ("Higher contract value", ct["total_value"]["a"], ct["total_value"]["b"]),
        ("More DRE publications", comparison["dre"]["publications"]["a"], comparison["dre"]["publications"]["b"]),
        ("More law projects", comparison["laws"]["projects"]["a"], comparison["laws"]["projects"]["b"]),
    ]
    for label, va, vb in metrics:
        if va > vb:
            w = f"◀ {short_a[:20]}"
            scores["a"] += 1
        elif vb > va:
            w = f"{short_b[:20]} ▶"
            scores["b"] += 1
        else:
            w = "═ Tied"
        row(label, w, w, "s")

    print(f"\n  SCORE: {short_a[:20]} {scores['a']} — {scores['b']} {short_b[:20]}")
    if scores["a"] > scores["b"]:
        print(f"  🏆 {short_a[:20]} leads in {scores['a']}/{len(metrics)} categories")
    elif scores["b"] > scores["a"]:
        print(f"  🏆 {short_b[:20]} leads in {scores['b']}/{len(metrics)} categories")
    else:
        print(f"  🤝 Tie — both entities are comparable")
    print(f"{'='*95}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Cross-Entity Comparison Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("entity_a", nargs="?", default="", help="First entity name")
    parser.add_argument("entity_b", nargs="?", default="", help="Second entity name")
    parser.add_argument("--nif", nargs=2, default=[], help="Compare by NIF (two NIFs)")
    parser.add_argument("--export", help="Export comparison to JSON")

    args = parser.parse_args()

    # Resolve entities
    if args.nif and len(args.nif) == 2:
        entities_a = search_entities(nif=args.nif[0], limit=1)
        entities_b = search_entities(nif=args.nif[1], limit=1)
    elif args.entity_a and args.entity_b:
        entities_a = search_entities(query=args.entity_a, limit=1)
        entities_b = search_entities(query=args.entity_b, limit=1)
    else:
        parser.print_help()
        sys.exit(1)

    if not entities_a:
        print(f"No entity found matching '{args.entity_a or (args.nif[0] if args.nif else '')}'")
        sys.exit(1)
    if not entities_b:
        print(f"No entity found matching '{args.entity_b or (args.nif[1] if len(args.nif) > 1 else '')}'")
        sys.exit(1)

    ea = entities_a[0]
    eb = entities_b[0]

    print(f"\nLoading data for comparison...")

    listings_a = get_entity_listings(ea["id"])
    listings_b = get_entity_listings(eb["id"])
    contracts_a = get_entity_contracts(ea.get("nif", ""), entity_name=ea.get("display_name", ""), entidade=ea.get("entidade", ""))
    contracts_b = get_entity_contracts(eb.get("nif", ""), entity_name=eb.get("display_name", ""), entidade=eb.get("entidade", ""))
    dre_a = get_entity_dre(ea["display_name"])
    dre_b = get_entity_dre(eb["display_name"])
    laws_a = get_entity_laws(ea["display_name"])
    laws_b = get_entity_laws(eb["display_name"])

    data_a = {"listings": listings_a, "contracts": contracts_a, "dre": dre_a, "laws": laws_a}
    data_b = {"listings": listings_b, "contracts": contracts_b, "dre": dre_b, "laws": laws_b}

    comparison = compare_side_by_side(data_a, data_b)
    print_comparison(ea["display_name"], eb["display_name"], data_a, data_b, comparison)

    if args.export:
        output = {
            "entity_a": ea, "entity_b": eb,
            "comparison": comparison,
            "data_a": data_a, "data_b": data_b,
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"Exported to {args.export}")


if __name__ == "__main__":
    main()
