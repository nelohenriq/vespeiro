#!/usr/bin/env python3
"""Price Gap Analysis — Cross-reference anúncios with signed contracts.

Joins the anúncios index (announced base prices) with procurement.db
(signed contract values) via nAnuncio + entity NIF to find contracts where
the final signed value significantly exceeds the announced base price —
a classic corruption signal.

Usage:
    python price_gap_analysis.py                   # Full analysis
    python price_gap_analysis.py --top 30          # Top 30 by price gap
    python price_gap_analysis.py --min-gap 50      # Only gaps > 50%
    python price_gap_analysis.py --entity "Porto"  # Filter by entity
    python price_gap_analysis.py --stats           # Summary statistics
    python price_gap_analysis.py --export gaps.json  # Export to JSON
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
ANUNCIOS_DB = DATA_DIR / "anuncios_index.db"
PROCUREMENT_DB = DATA_DIR / "procurement.db"


def load_anuncios() -> dict[tuple[str, str], dict]:
    """Load all anúncios keyed by (nAnuncio, nifEntidade).

    The same nAnuncio can appear for different entities (different contracts
    under the same tender announcement). We key on both nAnuncio and NIF
    to ensure correct matching.
    """
    if not ANUNCIOS_DB.exists():
        print(f"  ERROR: Anúncios index not found at {ANUNCIOS_DB}")
        print(f"  Run: python announce_index.py index")
        sys.exit(1)
    conn = sqlite3.connect(str(ANUNCIOS_DB))
    rows = conn.execute(
        "SELECT nAnuncio, nifEntidade, designacaoEntidade, PrecoBase, "
        "tiposContrato, dataPublicacao, CPVs, tipoActo "
        "FROM anuncios WHERE nAnuncio != '' AND PrecoBase > 0"
    ).fetchall()
    conn.close()

    anuncios = {}
    for nA, nif, name, preco, tipo, data, cpvs, acto in rows:
        key = (nA.strip(), str(nif).strip())
        # Keep the entry with the highest base price per (nAnuncio, NIF)
        if key not in anuncios or (preco or 0) > (anuncios[key].get("preco_base") or 0):
            anuncios[key] = {
                "nAnuncio": nA.strip(),
                "nif": str(nif).strip(),
                "entity": name,
                "preco_base": preco,
                "tipo": tipo,
                "date": data,
                "cpvs": cpvs,
                "acto": acto,
            }

    return anuncios


def load_contratos() -> list[dict]:
    """Load contracts from procurement.db."""
    if not PROCUREMENT_DB.exists():
        print(f"  ERROR: procurement.db not found at {PROCUREMENT_DB}")
        print(f"  Run: python procurement_db.py build")
        sys.exit(1)
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    rows = conn.execute(
        "SELECT idcontrato, nAnuncio, precoContratual, adjudicante_nif, adjudicante_nome,"
        " adjudicatarios, objectoContrato, tipoContrato, dataPublicacao, dataCelebracaoContrato"
        " FROM contratos WHERE nAnuncio IS NOT NULL AND nAnuncio != ''"
    ).fetchall()
    conn.close()

    contratos = []
    for (cid, nA, preco, nif, entity, adjt, objeto, tipo, pub, celeb) in rows:
        if not nA or not str(nA).strip():
            continue
        contratos.append({
            "id": cid,
            "nAnuncio": str(nA).strip(),
            "preco_contratual": preco,
            "adjudicante_nif": nif or "",
            "adjudicante": entity or "",
            "adjudicatario": str(adjt or "")[:200],
            "objeto": str(objeto or "")[:200],
            "tipo": str(tipo or ""),
            "data_pub": str(pub or "")[:10],
            "data_celeb": str(celeb or "")[:10],
        })
    return contratos


def cross_reference(anuncios: dict, contratos: list[dict]) -> list[dict]:
    """Join anúncios with contratos via (nAnuncio, NIF) and compute price gaps.

    Strategy:
    1. Primary: match on (nAnuncio, adjudicante_nif) — most precise
    2. Fallback: match on nAnuncio only — when NIF is missing from contract
    """
    matches = []

    # Build a fallback lookup by nAnuncio only (for contracts without NIF)
    by_nAnuncio = defaultdict(list)
    for key, a in anuncios.items():
        by_nAnuncio[a["nAnuncio"]].append(a)

    for c in contratos:
        nA = c["nAnuncio"]
        contract_nif = c["adjudicante_nif"]

        # Primary match: (nAnuncio, NIF)
        matched_announcement = None
        if contract_nif:
            primary_key = (nA, contract_nif)
            if primary_key in anuncios:
                matched_announcement = anuncios[primary_key]

        # Fallback: nAnuncio only (use the entry matching the NIF if available,
        # otherwise the closest entity match)
        if not matched_announcement and nA in by_nAnuncio:
            candidates = by_nAnuncio[nA]
            if contract_nif:
                # Try to find an entry with matching NIF
                for a in candidates:
                    if a["nif"] == contract_nif:
                        matched_announcement = a
                        break
            if not matched_announcement and len(candidates) == 1:
                # Only one announcement for this nAnuncio — safe to use
                matched_announcement = candidates[0]

        if not matched_announcement:
            continue

        base = matched_announcement.get("preco_base")
        signed = c.get("preco_contratual")

        if not base or not signed or base <= 0 or signed <= 0:
            continue

        gap_pct = ((signed - base) / base) * 100
        gap_abs = signed - base

        matches.append({
            "nAnuncio": nA,
            "contract_id": c["id"],
            "entity_adjudicante": c["adjudicante"],
            "nif": c["adjudicante_nif"],
            "entity_anuncio": matched_announcement.get("entity", ""),
            "objeto": c["objeto"],
            "tipo": c["tipo"],
            "preco_base": base,
            "preco_contratual": signed,
            "gap_abs": gap_abs,
            "gap_pct": gap_pct,
            "adjudicatario": c["adjudicatario"],
            "data_publicacao": c.get("data_pub", ""),
            "data_celebracao": c.get("data_celeb", ""),
        })

    matches.sort(key=lambda x: -x["gap_pct"])
    return matches


def cmd_stats(args):
    """Summary statistics of the cross-reference."""
    anuncios = load_anuncios()
    contratos = load_contratos()
    matches = cross_reference(anuncios, contratos)

    print(f"\n{'='*70}")
    print(f"  Price Gap Analysis — Anúncios × Contratos")
    print(f"{'='*70}")
    print(f"\n  Data sources:")
    print(f"    Anúncios: {len(anuncios):,} (nAnuncio, NIF) pairs with base price")
    print(f"    Contratos: {len(contratos):,} contracts with nAnuncio")
    print(f"    Matched: {len(matches):,} contracts with both base price and signed value")

    if not matches:
        print("\n  No matches found.")
        return

    gaps = [m["gap_pct"] for m in matches]
    positive_gaps = [g for g in gaps if g > 0]
    negative_gaps = [g for g in gaps if g < 0]

    print(f"\n  Price Gap Distribution:")
    print(f"    Total matched: {len(matches):,}")
    print(f"    Price INCREASED (final > base): {len(positive_gaps):,} ({len(positive_gaps)*100/len(matches):.1f}%)")
    print(f"    Price DECREASED (final < base): {len(negative_gaps):,} ({len(negative_gaps)*100/len(matches):.1f}%)")
    print(f"    Note: Most contracts come in below the announced base price")
    print(f"    due to competitive bidding. The corruption signal is the")
    print(f"    {len(positive_gaps):,} contracts that exceed the announced ceiling.")

    if positive_gaps:
        print(f"\n  Price Increases:")
        print(f"    Min: {min(positive_gaps):+.1f}%")
        print(f"    Median: {sorted(positive_gaps)[len(positive_gaps)//2]:+.1f}%")
        print(f"    Mean: {sum(positive_gaps)/len(positive_gaps):+.1f}%")
        print(f"    Max: {max(positive_gaps):+.1f}%")

    print(f"\n  🔴 INFLATION THRESHOLDS:")
    for threshold in [10, 25, 50, 100, 200, 500]:
        count = sum(1 for g in gaps if g > threshold)
        total_val = sum(m["gap_abs"] for m in matches if m["gap_pct"] > threshold)
        print(f"    >{threshold:>3}% inflation: {count:>5,} contracts  (total overrun: €{total_val:>14,.0f})")

    print(f"\n  Top 10 Entities by Total Price Inflation:")
    by_entity = defaultdict(lambda: {"count": 0, "total_gap": 0, "total_base": 0})
    for m in matches:
        if m["gap_pct"] > 10:
            e = m["entity_adjudicante"] or m["entity_anuncio"]
            by_entity[e]["count"] += 1
            by_entity[e]["total_gap"] += m["gap_abs"]
            by_entity[e]["total_base"] += m["preco_base"]

    ranked = sorted(by_entity.items(), key=lambda x: -x[1]["total_gap"])
    for entity, stats in ranked[:10]:
        pct = (stats["total_gap"] / stats["total_base"] * 100) if stats["total_base"] else 0
        print(f"    {entity[:45]:45s}  {stats['count']:>4} contracts  "
              f"+€{stats['total_gap']:>12,.0f} ({pct:.0f}%)")

    print(f"\n{'='*70}\n")


def cmd_main(args):
    """Full analysis — show top contracts by price gap."""
    anuncios = load_anuncios()
    contratos = load_contratos()
    matches = cross_reference(anuncios, contratos)

    if args.min_gap:
        matches = [m for m in matches if m["gap_pct"] > args.min_gap]

    if args.entity:
        q = args.entity.lower()
        matches = [m for m in matches if q in (m["entity_adjudicante"] or "").lower()
                   or q in (m["entity_anuncio"] or "").lower()]

    matches = matches[:args.top]

    if not matches:
        print("  No matches found with the given filters.")
        return

    print(f"\n{'='*80}")
    print(f"  Price Gap Analysis — Top {len(matches)} Contracts by Inflation")
    print(f"{'='*80}\n")

    for i, m in enumerate(matches, 1):
        flag = "🔴" if m["gap_pct"] > 100 else "🟡" if m["gap_pct"] > 25 else "⚪"
        print(f"  {flag} #{i:>3} | nAnuncio: {m['nAnuncio']}")
        print(f"       Entity: {(m['entity_adjudicante'] or m['entity_anuncio'] or 'N/A')[:55]}")
        print(f"       Object: {m['objeto'][:60]}")
        print(f"       Base Price:    €{m['preco_base']:>14,.2f}")
        print(f"       Signed Value:  €{m['preco_contratual']:>14,.2f}")
        print(f"       GAP:          +€{m['gap_abs']:>14,.2f}  ({m['gap_pct']:+.1f}%)")
        if m["adjudicatario"]:
            print(f"       Winner:       {m['adjudicatario'][:55]}")
        print(f"       Published: {m['data_publicacao']}  Celebrated: {m['data_celebracao']}")
        print()

    print(f"{'='*80}\n")


def cmd_export(args):
    """Export matched gaps to JSON."""
    anuncios = load_anuncios()
    contratos = load_contratos()
    matches = cross_reference(anuncios, contratos)

    out_path = Path(args.export_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=1, default=str)

    print(f"  Exported {len(matches):,} matches to {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Price Gap Analysis — Anúncios × Contratos cross-reference",
    )
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--min-gap", type=float, default=0, help="Minimum gap %")
    parser.add_argument("--entity", help="Filter by entity name")
    parser.add_argument("--stats", action="store_true", help="Summary statistics only")
    parser.add_argument("--export", metavar="FILE", help="Export matches to JSON file")

    args = parser.parse_args()

    if args.stats:
        cmd_stats(args)
    elif args.export:
        args.export_path = args.export
        cmd_export(args)
    else:
        cmd_main(args)


if __name__ == "__main__":
    main()
