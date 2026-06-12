#!/usr/bin/env python3
"""BEP × Procurement Cross-Reference

Finds entities that appear in both BEP (public employment/job listings)
and procurement (contracts) data — revealing which public entities are
both hiring and buying, and their relative activity levels.

Usage:
    python bep_procurement_crossref.py                  # Full overview
    python bep_procurement_crossref.py --top 30         # Top 30 by procurement value
    python bep_procurement_crossref.py --by-jobs        # Sort by BEP job listings
    python bep_procurement_crossref.py --nif 500014872  # Single entity profile
    python bep_procurement_crossref.py --detail         # Full history for all overlaps
    python bep_procurement_crossref.py --detail --top 10  # Full history for top 10
    python bep_procurement_crossref.py --export cross.json  # Export to JSON
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

# Import shared functions from entity_profile.py
from entity_profile import (
    get_entity_listings,
    get_entity_dre,
    get_entity_laws,
    compute_contract_trends,
    compute_hiring_trends,
    render_ascii_chart,
    camara_to_municipio,
    municipio_to_camara,
)

from utils import fmt, parse_entity_field
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"


# =============================================================================
# DATA LOADING
# =============================================================================

def load_bep_entities():
    """Load BEP entities keyed by NIF."""
    if not BEP_DB.exists():
        print(f"ERROR: BEP database not found at {BEP_DB}")
        sys.exit(1)
    conn = db_connect(str(BEP_DB))
    entities = {}
    for r in conn.execute(
        "SELECT nif, display_name, listing_count, id FROM bep_entities "
        "WHERE nif IS NOT NULL AND nif != ''"
    ).fetchall():
        entities[r["nif"]] = {
            "name": r["display_name"],
            "listings": r["listing_count"],
            "entity_id": r["id"],
        }
    conn.close()
    return entities


def load_procurement_stats():
    """Load procurement stats per buyer NIF."""
    if not PROCUREMENT_DB.exists():
        print(f"ERROR: procurement.db not found at {PROCUREMENT_DB}")
        sys.exit(1)
    conn = db_connect(str(PROCUREMENT_DB))
    stats = {}
    for r in conn.execute(
        """SELECT adjudicante_nif, adjudicante_nome,
                  COUNT(*) as contracts, SUM(precoContratual) as total_value,
                  AVG(precoContratual) as avg_value
           FROM contratos
           WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
           GROUP BY adjudicante_nif"""
    ).fetchall():
        stats[r["adjudicante_nif"]] = {
            "name": r["adjudicante_nome"],
            "contracts": r["contracts"],
            "value": r["total_value"] or 0,
            "avg_value": r["avg_value"] or 0,
        }
    conn.close()
    return stats


def cross_reference(bep, proc):
    """Find entities appearing in both databases."""
    matches = []
    for nif, bep_data in bep.items():
        if nif in proc:
            proc_data = proc[nif]
            matches.append({
                "nif": nif,
                "bep_name": bep_data["name"],
                "proc_name": proc_data["name"],
                "bep_listings": bep_data["listings"],
                "entity_id": bep_data.get("entity_id", ""),
                "proc_contracts": proc_data["contracts"],
                "proc_value": proc_data["value"],
                "proc_avg": proc_data["avg_value"],
            })
    return matches


def get_entity_contracts_from_db(nif):
    """Get procurement contracts directly from procurement.db by buyer NIF."""
    if not PROCUREMENT_DB.exists():
        return []
    conn = db_connect(str(PROCUREMENT_DB))
    rows = conn.execute(
        """SELECT idcontrato, adjudicante_nif, adjudicante_nome, objectoContrato,
                  adjudicatarios, precoContratual, precoBaseProcedimento,
                  tipoContrato, tipoprocedimento, dataCelebracaoContrato,
                  dataPublicacao, CPV
           FROM contratos
           WHERE adjudicante_nif = ?
           ORDER BY precoContratual DESC""",
        (nif,),
    ).fetchall()
    conn.close()
    return [
        {"idcontrato": r[0], "adjudicante_nif": r[1], "adjudicante_nome": r[2],
         "objecto": r[3], "adjudicatarios": r[4], "valor": r[5],
         "preco_base": r[6], "tipo": r[7], "procedimento": r[8],
         "data": r[9], "data_publicacao": r[10], "cpv": r[11]}
        for r in rows
    ]


# =============================================================================
# COMMANDS
# =============================================================================

def cmd_overview(args):
    """Full overview of BEP × Procurement overlap."""
    bep = load_bep_entities()
    proc = load_procurement_stats()
    matches = cross_reference(bep, proc)

    total_bep_value = sum(m["proc_value"] for m in matches)
    total_bep_contracts = sum(m["proc_contracts"] for m in matches)
    total_bep_listings = sum(m["bep_listings"] for m in matches)

    print(f"\n{'='*80}")
    print(f"  BEP × Procurement Cross-Reference")
    print(f"{'='*80}")
    print(f"\n  📊 Overview")
    print(f"  {'─'*60}")
    print(f"  BEP entities (with NIF):     {len(bep):>8,}")
    print(f"  Procurement NIFs:            {len(proc):>8,}")
    print(f"  Overlapping entities:        {len(matches):>8,}")
    print(f"  Overlap rate (of BEP):       {len(matches)*100/max(len(bep),1):>7.1f}%")
    print(f"  Overlap rate (of Proc):      {len(matches)*100/max(len(proc),1):>7.1f}%")

    if matches:
        print(f"\n  💰 Procurement Activity (overlapping entities)")
        print(f"  {'─'*60}")
        print(f"  Total contracts:             {total_bep_contracts:>8,}")
        print(f"  Total value:                 {fmt(total_bep_value):>8}")
        print(f"  Total job listings:          {total_bep_listings:>8,}")

    # Top by procurement value
    print(f"\n  🏛️  Top 20 by Procurement Value")
    print(f"  {'─'*95}")
    print(f"  {'#':<4}{'NIF':<12}{'Entity':<40}{'Contracts':>10}{'Value':>14}{'Jobs':>6}")
    print(f"  {'─'*4}{'─'*12}{'─'*40}{'─'*10}{'─'*14}{'─'*6}")
    for i, m in enumerate(sorted(matches, key=lambda x: -x["proc_value"])[:20], 1):
        name = (m["bep_name"] or m["proc_name"] or "N/A")[:38]
        print(f"  {i:<4}{m['nif']:<12}{name:<40}{m['proc_contracts']:>10,}{fmt(m['proc_value']):>14}{m['bep_listings']:>6}")

    # Top by BEP activity
    print(f"\n  👥 Top 20 by Job Listings")
    print(f"  {'─'*95}")
    print(f"  {'#':<4}{'NIF':<12}{'Entity':<40}{'Jobs':>6}{'Contracts':>10}{'Value':>14}")
    print(f"  {'─'*4}{'─'*12}{'─'*40}{'─'*6}{'─'*10}{'─'*14}")
    for i, m in enumerate(sorted(matches, key=lambda x: -x["bep_listings"])[:20], 1):
        name = (m["bep_name"] or m["proc_name"] or "N/A")[:38]
        print(f"  {i:<4}{m['nif']:<12}{name:<40}{m['bep_listings']:>6}{m['proc_contracts']:>10,}{fmt(m['proc_value']):>14}")

    # Anomaly signals
    print(f"\n  🔍 Anomaly Signals")
    print(f"  {'─'*60}")
    high_proc_low_hire = [m for m in matches if m["proc_contracts"] >= 50 and m["bep_listings"] <= 2]
    if high_proc_low_hire:
        print(f"\n  High procurement (50+ contracts) but minimal hiring (≤2 listings):")
        for m in sorted(high_proc_low_hire, key=lambda x: -x["proc_contracts"])[:10]:
            name = (m["proc_name"] or "N/A")[:45]
            print(f"    [{m['nif']}] {name} — {m['proc_contracts']} contracts ({fmt(m['proc_value'])}), {m['bep_listings']} jobs")

    print(f"\n{'='*80}\n")


def cmd_detail(args):
    """Show full procurement history for overlapping entities."""
    bep = load_bep_entities()
    proc = load_procurement_stats()
    matches = cross_reference(bep, proc)
    top_n = args.top or 20

    # Sort by procurement value
    matches.sort(key=lambda x: -x["proc_value"])
    detail_matches = matches[:top_n]

    print(f"\n{'='*80}")
    print(f"  BEP × Procurement — Full Entity History (Top {top_n})")
    print(f"{'='*80}")

    for idx, m in enumerate(detail_matches, 1):
        nif = m["nif"]
        name = m["bep_name"] or m["proc_name"] or "N/A"
        entity_id = m.get("entity_id", "")

        print(f"\n{'─'*80}")
        print(f"  [{idx}/{len(detail_matches)}] {name}")
        print(f"  NIF: {nif} | BEP: {m['bep_listings']} listings | Procurement: {m['proc_contracts']:,} contracts ({fmt(m['proc_value'])})")
        print(f"{'─'*80}")

        # --- BEP Job Listings ---
        if entity_id:
            listings = get_entity_listings(entity_id)
            if listings:
                print(f"\n  📋 BEP JOB LISTINGS ({len(listings)})")
                for l in listings[:8]:
                    status = "🟢" if "aberta" in (l["estado"] or "").lower() else "⚪"
                    print(f"  {status} {l['titulo'][:65]}")
                    details = []
                    if l["categoria"]:
                        details.append(l["categoria"])
                    if l["remuneracao"]:
                        details.append(f"€{l['remuneracao']}")
                    if l["total_postos"] and l["total_postos"] != "1":
                        details.append(f"{l['total_postos']} positions")
                    if details:
                        print(f"     {' | '.join(details)}")
                if len(listings) > 8:
                    print(f"  ... and {len(listings) - 8} more listings")

                # Hiring trends
                hiring_trends = compute_hiring_trends(listings)
                if hiring_trends:
                    total_months = len(hiring_trends)
                    total_listings = sum(d["count"] for d in hiring_trends.values())
                    avg_monthly = total_listings / total_months if total_months else 0
                    print(f"\n  📈 Hiring Timeline ({total_listings} listings, avg {avg_monthly:.1f}/month):")
                    chart = render_ascii_chart(hiring_trends, "count", currency=False)
                    if chart:
                        print(chart)

        # --- Procurement Contracts (from procurement.db) ---
        contracts = get_entity_contracts_from_db(nif)
        if contracts:
            total_value = sum(c.get("valor", 0) or 0 for c in contracts)
            print(f"\n  📦 PROCUREMENT CONTRACTS ({len(contracts)}, {fmt(total_value)} total)")

            # Procedure breakdown
            proc_types = defaultdict(lambda: {"count": 0, "value": 0})
            for c in contracts:
                pt = c.get("procedimento") or "N/A"
                proc_types[pt]["count"] += 1
                proc_types[pt]["value"] += c.get("valor", 0) or 0
            print(f"\n  Procedure breakdown:")
            for pt, d in sorted(proc_types.items(), key=lambda x: -x[1]["value"])[:5]:
                share = d["count"] * 100 / len(contracts) if contracts else 0
                print(f"    {str(pt)[:40]:40s} {d['count']:>5} ({share:>5.1f}%) {fmt(d['value']):>10}")

            # Winner concentration
            winners = defaultdict(lambda: {"count": 0, "value": 0})
            for c in contracts:
                for entity in parse_entity_field(c.get("adjudicatarios", "")):
                    key = entity["nif"] or entity["name"]
                    winners[key]["count"] += 1
                    winners[key]["value"] += c.get("valor", 0) or 0
                    if not winners[key].get("name"):
                        winners[key]["name"] = entity["name"]
            if winners:
                print(f"\n  Top winners:")
                for wk, wd in sorted(winners.items(), key=lambda x: -x[1]["value"])[:5]:
                    share = wd["value"] * 100 / total_value if total_value > 0 else 0
                    wname = wd.get("name", wk)[:40]
                    print(f"    {wname:40s} {wd['count']:>5} contracts {fmt(wd['value']):>10} ({share:.0f}%)")

            # Inflated contracts
            inflated = [c for c in contracts
                       if (c.get("preco_base") or 0) > 0 and (c.get("valor") or 0) > (c.get("preco_base") or 0)]
            if inflated:
                inf_overrun = sum((c.get("valor", 0) or 0) - (c.get("preco_base", 0) or 0) for c in inflated)
                print(f"\n  ⚠️  Price inflation: {len(inflated)} contracts, overrun: {fmt(inf_overrun)}")
                for c in inflated[:3]:
                    overrun = (c.get("valor", 0) or 0) - (c.get("preco_base", 0) or 0)
                    pct = overrun * 100 / (c.get("preco_base") or 1)
                    obj = str(c.get("objecto") or "")[:50]
                    print(f"    +{pct:.0f}% {fmt(overrun)} overrun — {obj}")

            # Top 5 contracts by value
            print(f"\n  Top contracts:")
            for c in contracts[:5]:
                valor = fmt(c.get("valor", 0))
                date = c.get("data") or c.get("dataPublicacao") or "?"
                obj = str(c.get("objecto") or "")[:55]
                winner = str(c.get("adjudicatarios") or "")[:35]
                print(f"    [{date}] {valor:>10}  {obj}")
                if winner and winner != "-":
                    print(f"                  Winner: {winner}")

            # Contract timeline
            trends = compute_contract_trends(contracts)
            if trends and len(trends) > 2:
                total_months = len(trends)
                tv = sum(d["value"] for d in trends.values())
                tc = sum(d["count"] for d in trends.values())
                avg_m = tv / total_months if total_months else 0
                print(f"\n  📈 Contract Timeline ({tc} contracts, {fmt(tv)} total, avg {fmt(avg_m)}/month):")
                chart = render_ascii_chart(trends, "value")
                if chart:
                    print(chart)

        # --- DRE Publications ---
        dre = get_entity_dre(name)
        if dre:
            print(f"\n  📰 DRE Publications ({len(dre)})")
            for d in dre[:3]:
                print(f"    Serie {d['serie']} #{d['numero']}/{d['year']}: {str(d.get('title', ''))[:60]}")

        # --- Law Projects ---
        laws = get_entity_laws(name)
        if laws:
            print(f"\n  ⚖️  Law Projects ({len(laws)})")
            for l in laws[:3]:
                print(f"    [{l.get('ini_desc_tipo', '?')}] {str(l.get('ini_titulo', ''))[:55]}")
                print(f"      Phase: {l.get('latest_fase', '?')} ({l.get('latest_fase_date', '?')})")

    print(f"\n{'='*80}\n")


def cmd_profile(args):
    """Show detailed profile for a single entity."""
    bep = load_bep_entities()
    proc = load_procurement_stats()
    matches = cross_reference(bep, proc)

    nif = args.nif
    match = next((m for m in matches if m["nif"] == nif), None)

    if not match:
        print(f"NIF {nif} not found in both databases.")
        if nif in bep:
            print(f"  Found in BEP only: {bep[nif]['name']}")
        if nif in proc:
            print(f"  Found in procurement only: {proc[nif]['name']}")
        return

    name = match["bep_name"] or match["proc_name"]
    entity_id = match.get("entity_id", "")

    print(f"\n{'='*80}")
    print(f"  🔍 FULL ENTITY PROFILE: {name}")
    print(f"  NIF: {nif}")
    print(f"{'='*80}")

    # BEP listings
    if entity_id:
        listings = get_entity_listings(entity_id)
        if listings:
            print(f"\n  📋 BEP JOB LISTINGS ({len(listings)})")
            for l in listings[:15]:
                status = "🟢" if "aberta" in (l["estado"] or "").lower() else "⚪"
                print(f"  {status} {l['titulo'][:65]}")
                details = []
                if l["categoria"]:
                    details.append(l["categoria"])
                if l["remuneracao"]:
                    details.append(f"€{l['remuneracao']}")
                if l["total_postos"] and l["total_postos"] != "1":
                    details.append(f"{l['total_postos']} positions")
                if l["data_limite"]:
                    details.append(f"deadline: {l['data_limite'][:10]}")
                if details:
                    print(f"     {' | '.join(details)}")
                if l["url"]:
                    print(f"     🔗 {l['url']}")

            hiring_trends = compute_hiring_trends(listings)
            if hiring_trends:
                total_listings = sum(d["count"] for d in hiring_trends.values())
                total_positions = sum(d["positions"] for d in hiring_trends.values())
                total_months = len(hiring_trends)
                avg = total_listings / total_months if total_months else 0
                print(f"\n  📈 Hiring Timeline ({total_listings} listings, {total_positions} positions, avg {avg:.1f}/month):")
                chart = render_ascii_chart(hiring_trends, "count", currency=False)
                if chart:
                    print(chart)

    # Procurement contracts
    contracts = get_entity_contracts_from_db(nif)
    if contracts:
        total_value = sum(c.get("valor", 0) or 0 for c in contracts)
        print(f"\n  📦 PROCUREMENT CONTRACTS ({len(contracts)}, {fmt(total_value)} total)")

        # Procedure breakdown
        proc_types = defaultdict(lambda: {"count": 0, "value": 0})
        for c in contracts:
            pt = c.get("procedimento") or "N/A"
            proc_types[pt]["count"] += 1
            proc_types[pt]["value"] += c.get("valor", 0) or 0
        print(f"\n  Procedure breakdown:")
        for pt, d in sorted(proc_types.items(), key=lambda x: -x[1]["value"]):
            share = d["count"] * 100 / len(contracts)
            print(f"    {str(pt)[:40]:40s} {d['count']:>5} ({share:>5.1f}%) {fmt(d['value']):>10}")

        # Winner concentration
        winners = defaultdict(lambda: {"count": 0, "value": 0})
        for c in contracts:
            for entity in parse_entity_field(c.get("adjudicatarios", "")):
                key = entity["nif"] or entity["name"]
                winners[key]["count"] += 1
                winners[key]["value"] += c.get("valor", 0) or 0
                if not winners[key].get("name"):
                    winners[key]["name"] = entity["name"]
        if winners:
            print(f"\n  Top winners:")
            for wk, wd in sorted(winners.items(), key=lambda x: -x[1]["value"])[:10]:
                share = wd["value"] * 100 / total_value if total_value > 0 else 0
                wname = wd.get("name", wk)[:45]
                print(f"    {wname:45s} {wd['count']:>5} contracts {fmt(wd['value']):>10} ({share:.0f}%)")

        # Inflated contracts
        inflated = [c for c in contracts
                   if (c.get("preco_base") or 0) > 0 and (c.get("valor") or 0) > (c.get("preco_base") or 0)]
        if inflated:
            inf_overrun = sum((c.get("valor", 0) or 0) - (c.get("preco_base", 0) or 0) for c in inflated)
            print(f"\n  ⚠️  Price inflation: {len(inflated)} contracts, overrun: {fmt(inf_overrun)}")
            for c in inflated[:5]:
                overrun = (c.get("valor", 0) or 0) - (c.get("preco_base", 0) or 0)
                pct = overrun * 100 / (c.get("preco_base") or 1)
                obj = str(c.get("objecto") or "")[:55]
                print(f"    +{pct:.0f}% {fmt(overrun)} — {obj}")

        # Top contracts
        print(f"\n  Top contracts by value:")
        for c in contracts[:10]:
            valor = fmt(c.get("valor", 0))
            date = c.get("data") or c.get("dataPublicacao") or "?"
            obj = str(c.get("objecto") or "")[:55]
            winner = str(c.get("adjudicatarios") or "")[:40]
            print(f"    [{date}] {valor:>10}  {obj}")
            if winner and winner != "-":
                print(f"                  Winner: {winner}")

        # Timeline
        trends = compute_contract_trends(contracts)
        if trends:
            total_months = len(trends)
            tv = sum(d["value"] for d in trends.values())
            tc = sum(d["count"] for d in trends.values())
            avg_m = tv / total_months if total_months else 0
            print(f"\n  📈 Contract Timeline ({tc} contracts, {fmt(tv)} total, avg {fmt(avg_m)}/month):")
            chart = render_ascii_chart(trends, "value")
            if chart:
                print(chart)

    # DRE
    dre = get_entity_dre(name)
    if dre:
        print(f"\n  📰 DRE Publications ({len(dre)})")
        for d in dre[:5]:
            print(f"    Serie {d['serie']} #{d['numero']}/{d['year']}: {str(d.get('title', ''))[:60]}")
            if d.get("redirect_url"):
                print(f"      🔗 {d['redirect_url']}")

    # Laws
    laws = get_entity_laws(name)
    if laws:
        print(f"\n  ⚖️  Law Projects ({len(laws)})")
        for l in laws[:5]:
            print(f"    [{l.get('ini_desc_tipo', '?')}] {str(l.get('ini_titulo', ''))[:60]}")
            print(f"      Phase: {l.get('latest_fase', '?')} ({l.get('latest_fase_date', '?')})")
            if l.get("vote_result"):
                print(f"      Vote: {l['vote_result']}")

    print(f"\n{'='*80}\n")


def cmd_export(args):
    """Export cross-reference data to JSON."""
    bep = load_bep_entities()
    proc = load_procurement_stats()
    matches = cross_reference(bep, proc)

    out_path = Path(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=1, default=str)

    print(f"Exported {len(matches):,} overlapping entities to {out_path}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="BEP × Procurement Cross-Reference",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("overview", help="Full cross-reference overview")

    detail_p = sub.add_parser("detail", help="Full history for overlapping entities")
    detail_p.add_argument("--top", type=int, default=20, help="Show top N entities (default 20)")

    profile_p = sub.add_parser("profile", help="Single entity profile")
    profile_p.add_argument("--nif", required=True)

    export_p = sub.add_parser("export", help="Export to JSON")
    export_p.add_argument("--output", "-o", default="data/bep_procurement_crossref.json")

    args = parser.parse_args()

    if not args.command:
        cmd_overview(args)
        return

    if args.command == "overview":
        cmd_overview(args)
    elif args.command == "detail":
        cmd_detail(args)
    elif args.command == "profile":
        cmd_profile(args)
    elif args.command == "export":
        cmd_export(args)


if __name__ == "__main__":
    main()
