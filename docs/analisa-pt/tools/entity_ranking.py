#!/usr/bin/env python3
"""Entity Ranking — Rank public entities by procurement activity.

Queries procurement.db to rank entities by contract value, distinguishing
buyers (adjudicantes) from winners (adjudicatários). Uses the 209K entity
dataset from Portal BASE / IMPIC.

Usage:
    python entity_ranking.py ranking --top 30       # Top 30 buyers + winners
    python entity_ranking.py ranking --country PT   # Portuguese only
    python entity_ranking.py ranking --min-contracts 10  # Min contract count
    python entity_ranking.py ranking --nif 500014872 # Specific entity
    python entity_ranking.py ranking --export ranking.json
    python entity_ranking.py search "EDP"           # Search by name
    python entity_ranking.py stats                  # Summary statistics
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "procurement.db"


def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print("ERROR: procurement.db not found. Run: python procurement_db.py build")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_overall(args):
    """Top entities by overall procurement activity."""
    conn = get_conn()

    where_parts = []
    params = []
    if args.country:
        where_parts.append("AliasPais = ?")
        params.append(args.country.upper())
    if args.min_contracts:
        where_parts.append("numContratos >= ?")
        params.append(args.min_contracts)
    if args.nif:
        where_parts.append("nifEntidade = ?")
        params.append(args.nif)

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    rows = conn.execute(f"""
        SELECT nifEntidade, desigEntidade, numContratos,
               totAdjudicatario, totValorContratIni,
               totAdjudicante, totAdjudicanteValorContratIni,
               descPais, AliasPais
        FROM entidades
        {where}
        ORDER BY totAdjudicanteValorContratIni DESC
        LIMIT ?
    """, params + [args.top]).fetchall()

    print(f"\n{'='*90}")
    print(f"  Entity Ranking — Top {len(rows)} by Buyer Value (Adjudicante)")
    print(f"{'='*90}")
    print(f"\n  {'#':>4}  {'NIF':>11}  {'Entity':<40}  {'Contracts':>9}  {'Buyer Value':>15}")
    print(f"  {'─'*4}  {'─'*11}  {'─'*40}  {'─'*9}  {'─'*15}")

    for i, r in enumerate(rows, 1):
        val = r["totAdjudicanteValorContratIni"] or 0
        print(f"  {i:>4}  {r['nifEntidade']:>11}  {r['desigEntidade'][:40]:<40}  "
              f"{r['totAdjudicante']:>9,}  €{val:>14,.0f}")

    # Also show top winners
    rows_w = conn.execute(f"""
        SELECT nifEntidade, desigEntidade, numContratos,
               totAdjudicatario, totValorContratIni, AliasPais
        FROM entidades
        {where}
        ORDER BY totValorContratIni DESC
        LIMIT ?
    """, params + [args.top]).fetchall()

    print(f"\n{'='*90}")
    print(f"  Entity Ranking — Top {len(rows_w)} by Winner Value (Adjudicatário)")
    print(f"{'='*90}")
    print(f"\n  {'#':>4}  {'NIF':>11}  {'Entity':<40}  {'Contracts':>9}  {'Winner Value':>15}")
    print(f"  {'─'*4}  {'─'*11}  {'─'*40}  {'─'*9}  {'─'*15}")

    for i, r in enumerate(rows_w, 1):
        val = r["totValorContratIni"] or 0
        print(f"  {i:>4}  {r['nifEntidade']:>11}  {r['desigEntidade'][:40]:<40}  "
              f"{r['totAdjudicatario']:>9,}  €{val:>14,.0f}")

    # Summary stats
    total_entities = conn.execute("SELECT COUNT(*) FROM entidades").fetchone()[0]
    total_value = conn.execute("SELECT SUM(totAdjudicanteValorContratIni) FROM entidades").fetchone()[0] or 0
    total_winner = conn.execute("SELECT SUM(totValorContratIni) FROM entidades").fetchone()[0] or 0

    print(f"\n{'='*90}")
    print(f"  Summary")
    print(f"{'='*90}")
    print(f"  Total entities: {total_entities:,}")
    print(f"  Total buyer value: €{total_value:,.0f}")
    print(f"  Total winner value: €{total_winner:,.0f}")
    print(f"{'='*90}\n")

    conn.close()


def cmd_search(args):
    """Search entities by name."""
    conn = get_conn()
    q = f"%{args.search}%"
    rows = conn.execute("""
        SELECT nifEntidade, desigEntidade, numContratos,
               totAdjudicatario, totValorContratIni,
               totAdjudicante, totAdjudicanteValorContratIni,
               descPais
        FROM entidades
        WHERE desigEntidade LIKE ?
        ORDER BY totAdjudicanteValorContratIni DESC
        LIMIT ?
    """, (q, args.top)).fetchall()

    if not rows:
        print(f"  No entities matching '{args.search}'")
        conn.close()
        return

    print(f"\n  Search results for '{args.search}' ({len(rows)} found):\n")
    for r in rows:
        buyer_val = r["totAdjudicanteValorContratIni"] or 0
        winner_val = r["totValorContratIni"] or 0
        print(f"  NIF: {r['nifEntidade']}  {r['desigEntidade']}")
        print(f"    Country: {r['descPais']}  Contracts: {r['numContratos']:,}")
        print(f"    As buyer: {r['totAdjudicante'] or 0:,} contracts, €{buyer_val:,.0f}")
        print(f"    As winner: {r['totAdjudicatario'] or 0:,} contracts, €{winner_val:,.0f}")
        print()

    conn.close()


def cmd_stats(args):
    """Overall statistics."""
    conn = get_conn()

    total = conn.execute("SELECT COUNT(*) FROM entidades").fetchone()[0]
    pt = conn.execute("SELECT COUNT(*) FROM entidades WHERE AliasPais = 'PT'").fetchone()[0]
    with_buyer = conn.execute("SELECT COUNT(*) FROM entidades WHERE totAdjudicante > 0").fetchone()[0]
    with_winner = conn.execute("SELECT COUNT(*) FROM entidades WHERE totAdjudicatario > 0").fetchone()[0]

    total_buyer_val = conn.execute("SELECT SUM(totAdjudicanteValorContratIni) FROM entidades").fetchone()[0] or 0
    total_winner_val = conn.execute("SELECT SUM(totValorContratIni) FROM entidades").fetchone()[0] or 0

    print(f"\n{'='*60}")
    print(f"  Entity Ranking — Statistics")
    print(f"{'='*60}")
    print(f"\n  Total entities: {total:,}")
    print(f"    Portuguese: {pt:,} ({pt*100/total:.1f}%)")
    print(f"    With buyer activity: {with_buyer:,}")
    print(f"    With winner activity: {with_winner:,}")
    print(f"\n  Total buyer value: €{total_buyer_val:,.0f}")
    print(f"  Total winner value: €{total_winner_val:,.0f}")

    # Country breakdown
    print(f"\n  Top 10 Countries by Entity Count:")
    for country, count in conn.execute(
        "SELECT descPais, COUNT(*) FROM entidades WHERE descPais != '' "
        "GROUP BY descPais ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall():
        print(f"    {country[:30]:30s} {count:>7,}")

    print(f"\n{'='*60}\n")

    # Export if requested
    if getattr(args, 'export', None):
        export_data = {
            "buyers": [{
                "nif": r["nifEntidade"], "name": r["desigEntidade"],
                "contracts": r["totAdjudicante"],
                "value": r["totAdjudicanteValorContratIni"] or 0,
            } for r in rows],
            "winners": [{
                "nif": r["nifEntidade"], "name": r["desigEntidade"],
                "contracts": r["totAdjudicatario"],
                "value": r["totValorContratIni"] or 0,
            } for r in rows_w],
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=1)
        print(f"Exported to {args.export}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Entity Ranking — Portuguese procurement entity analysis",
    )
    sub = parser.add_subparsers(dest="command")

    # Overall
    overall = sub.add_parser("ranking", help="Top entities ranking")
    overall.add_argument("--top", type=int, default=30, help="Show top N")
    overall.add_argument("--country", help="Filter by country code (PT, etc.)")
    overall.add_argument("--min-contracts", type=int, default=0, help="Min contract count")
    overall.add_argument("--nif", help="Show specific entity by NIF")
    overall.add_argument("--export", metavar="FILE", help="Export to JSON")

    # Search
    search = sub.add_parser("search", help="Search entities by name")
    search.add_argument("search", help="Search query")
    search.add_argument("--top", type=int, default=20, help="Max results")

    # Stats
    sub.add_parser("stats", help="Overall statistics")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "ranking": cmd_overall,
        "search": cmd_search,
        "stats": cmd_stats,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
