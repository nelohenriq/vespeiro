#!/usr/bin/env python3
"""Municipality Risk Report — Combined Concentration + Inflation Analysis

Cross-references supplier concentration, price inflation, direct award rates,
and exclusive company signals to rank municipalities by procurement risk.

Usage:
    python municipality_risk_report.py                  # Top 30 municipalities
    python municipality_risk_report.py --top 50         # Top 50
    python municipality_risk_report.py --export risk.json  # Export to JSON
"""

import sys
import json
import re
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

# Import shared helpers from anomaly_scanner
sys.path.insert(0, str(Path(__file__).parent))
from anomaly_scanner import parse_entity_field, fmt

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
BEP_DB = SCRIPT_DIR / "bep_index.db"


# =============================================================================
# MUNICIPALITY RISK SCANNER
# =============================================================================

# NUTS 3 region code → name mapping
NUTS_REGIONS = {
    "PT110": "Alto Minho", "PT111": "Ave", "PT112": "Cávado",
    "PT119": "Alto Tâmega e Sousa", "PT11A": "Área Metropolitana do Porto",
    "PT11D": "Douro",
    "PT120": "Beira Baixa", "PT126": "Leiria",
    "PT16E": "Região de Coimbra", "PT16D": "Região de Aveiro",
    "PT16B": "Viseu Dão Lafões", "PT16I": "Oeste",
    "PT16J": "Médio Tejo", "PT16K": "Área Metropolitana de Lisboa",
    "PT170": "Área Metropolitana de Lisboa",
    "PT150": "Algarve", "PT180": "Alentejo Central",
    "PT181": "Baixo Alentejo", "PT182": "Alentejo Litoral",
    "PT186": "Alto Alentejo", "PT184": "Lezíria do Tejo",
    "PT200": "R.A. Açores", "PT300": "R.A. Madeira",
    "PTZZZ": "Extra-Regio",
}


def list_regions(conn):
    """Print available NUTS regions."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT NUTs, COUNT(*) as cnt, COUNT(DISTINCT adjudicante_nif) as entities
        FROM contratos WHERE NUTs IS NOT NULL AND NUTs != ''
        GROUP BY NUTs ORDER BY cnt DESC
    """).fetchall()
    print(f"\nAvailable NUTS regions ({len(rows)} total):\n")
    print(f"  {'Code':<10}{'Region':<40}{'Contracts':>10}{'Entities':>10}")
    print(f"  {'─'*10}{'─'*40}{'─'*10}{'─'*10}")
    for r in rows:
        name = NUTS_REGIONS.get(r["NUTs"], r["NUTs"])
        print(f"  {r['NUTs']:<10}{name:<40}{r['cnt']:>10,}{r['entities']:>10,}")
    print()


def scan_municipalities(min_contracts=5, region=None):
    """Scan all municipalities for combined procurement risk signals."""
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    conn.row_factory = sqlite3.Row

    bep_map = {}
    if BEP_DB.exists():
        bep_conn = sqlite3.connect(str(BEP_DB))
        for r in bep_conn.execute(
            "SELECT nif, listing_count FROM bep_entities WHERE nif IS NOT NULL AND nif != ''"
        ).fetchall():
            bep_map[r[0]] = r[1]
        bep_conn.close()

    # Pre-compute exclusive company map: company_name -> number of distinct buyers
    print("  Pre-computing exclusive company map...", file=sys.stderr)
    exclusive_map = defaultdict(int)  # name -> set of buyer NIFs (count via len)
    exclusive_buyers = defaultdict(set)  # name -> set of buyer NIFs
    for r in conn.execute("""
        SELECT adjudicante_nif, adjudicatarios, precoContratual
        FROM contratos
        WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''
        AND adjudicatarios LIKE '% - %' AND precoContratual > 0
    """).fetchall():
        for entity in parse_entity_field(r["adjudicatarios"]):
            if entity["name"]:
                exclusive_buyers[entity["name"]].add(r["adjudicante_nif"])
    exclusive_map = {name: len(buyers) for name, buyers in exclusive_buyers.items()}
    print(f"  Loaded {len(exclusive_map):,} company-to-buyer mappings", file=sys.stderr)

    # Get all entities with construction contracts (CPV 45%)
    nuts_filter = ""
    nuts_params = []
    if region:
        nuts_filter = "AND NUTs LIKE ?"
        nuts_params = [f"{region}%"]

    entities = conn.execute(f"""
        SELECT adjudicante_nif, adjudicante_nome,
               COUNT(*) as total_contracts,
               SUM(precoContratual) as total_value
        FROM contratos
        WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
        AND CPV LIKE '45%' AND precoContratual > 0
        {nuts_filter}
        GROUP BY adjudicante_nif
        HAVING total_contracts >= ?
        ORDER BY total_value DESC
    """, nuts_params + [min_contracts]).fetchall()

    results = []

    for ent in entities:
        nif = ent["adjudicante_nif"]
        name = ent["adjudicante_nome"]
        total_contracts = ent["total_contracts"]
        total_value = ent["total_value"] or 0

        if total_value < 100_000:
            continue

        # --- Signal 1: Supplier Concentration ---
        winners = defaultdict(lambda: {"count": 0, "value": 0})
        for w in conn.execute("""
            SELECT adjudicatarios, precoContratual
            FROM contratos
            WHERE adjudicante_nif = ? AND CPV LIKE '45%'
            AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
            AND precoContratual > 0
        """, (nif,)).fetchall():
            adj = str(w["adjudicatarios"] or "")
            m = re.match(r"(\d{9})\s*-\s*(.+)", adj)
            wname = m.group(2).strip()[:45] if m else adj[:45]
            winners[wname]["count"] += 1
            winners[wname]["value"] += w["precoContratual"] or 0

        num_winners = len(winners)
        sorted_winners = sorted(winners.items(), key=lambda x: -x[1]["value"])
        top3_value = sum(w["value"] for _, w in sorted_winners[:3])
        top3_share = top3_value * 100 / total_value if total_value > 0 else 0

        # HHI
        hhi = sum((w["value"] / total_value) ** 2 for _, w in winners.items()) if total_value > 0 else 0

        # --- Signal 2: Price Inflation ---
        inf = conn.execute("""
            SELECT COUNT(*) as inflated,
                   SUM(precoContratual - precoBaseProcedimento) as overrun,
                   AVG((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) as avg_pct,
                   SUM(CASE WHEN precoBaseProcedimento > 0 THEN 1 ELSE 0 END) as with_base
            FROM contratos WHERE adjudicante_nif = ? AND CPV LIKE '45%'
            AND precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento
        """, (nif,)).fetchone()

        inflated = inf["inflated"] or 0
        overrun = inf["overrun"] or 0
        avg_pct = inf["avg_pct"] or 0
        with_base = max(inf["with_base"] or 1, 1)
        inflation_rate = inflated * 100 / with_base

        # --- Signal 3: Direct Award Rate ---
        direct = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN tipoprocedimento LIKE '%Ajuste Direto%' THEN 1 ELSE 0 END) as direct_count
            FROM contratos WHERE adjudicante_nif = ? AND CPV LIKE '45%'
        """, (nif,)).fetchone()
        direct_rate = (direct["direct_count"] or 0) * 100 / max(direct["total"] or 1, 1)

        # --- Signal 4: Exclusive Companies ---
        exclusive_count = 0
        exclusive_names = []
        for wk, wv in sorted_winners[:10]:
            buyer_count = exclusive_map.get(wk, 99)
            if buyer_count == 1:  # Only works with 1 buyer
                exclusive_count += 1
                exclusive_names.append(f"{wk} ({fmt(wv['value'])})")

        # --- Signal 5: BEP Mismatch ---
        bep_listings = bep_map.get(nif, -1)

        # --- Composite Risk Score ---
        risk = 0

        # Concentration component (0-35)
        risk += min(35, top3_share * 0.35)

        # Inflation component (0-30)
        risk += min(30, inflation_rate * 3 + inflated * 2)

        # Direct award component (0-15)
        risk += min(15, direct_rate * 0.15)

        # Exclusive companies component (0-10)
        risk += min(10, exclusive_count * 3)

        # BEP mismatch component (0-5)
        if bep_listings >= 0 and bep_listings <= 2 and total_contracts >= 20:
            risk += 5

        risk = min(100, risk)

        results.append({
            "nif": nif,
            "name": name,
            "total_contracts": total_contracts,
            "total_value": total_value,
            "num_winners": num_winners,
            "top3_share": round(top3_share, 1),
            "hhi": round(hhi, 4),
            "top3_names": [f"{wn} ({wv['value']*100/total_value:.0f}%)" for wn, wv in sorted_winners[:3]],
            "inflated": inflated,
            "inflation_rate": round(inflation_rate, 1),
            "overrun": overrun,
            "avg_pct": round(avg_pct, 1),
            "direct_rate": round(direct_rate, 1),
            "exclusive_count": exclusive_count,
            "exclusive_names": exclusive_names[:3],
            "bep_listings": bep_listings,
            "risk": round(risk, 1),
        })

    conn.close()

    results.sort(key=lambda x: -x["risk"])
    return results


# =============================================================================
# OUTPUT
# =============================================================================

def print_report(results, top_n=30):
    """Print the municipality risk report."""
    print(f"\n{'='*130}")
    print(f"  MUNICIPALITY PROCUREMENT RISK REPORT — Top {top_n}")
    print(f"  Concentration + Inflation + Direct Award + Exclusive Companies + BEP Mismatch")
    print(f"{'='*130}")

    # Summary
    high = sum(1 for r in results if r["risk"] > 60)
    medium = sum(1 for r in results if 40 < r["risk"] <= 60)
    low = sum(1 for r in results if r["risk"] <= 40)

    print(f"\n  📊 Summary")
    print(f"  {'─'*60}")
    print(f"  Total municipalities scanned:  {len(results):>6}")
    print(f"  High risk (>60):               {high:>6}")
    print(f"  Medium risk (40-60):           {medium:>6}")
    print(f"  Low risk (<40):                {low:>6}")

    # Top table
    print(f"\n  {'─'*125}")
    print(f"  {'#':<4}{'Risk':>5}{'Conc%':>7}{'Infl%':>7}{'Infl':>5}{'Overrun':>12}{'Direct%':>8}{'Excl':>5}  {'Municipality':<35}{'Top 3 Winners'}")
    print(f"  {'─'*4}{'─'*5}{'─'*7}{'─'*7}{'─'*5}{'─'*12}{'─'*8}{'─'*5}  {'─'*35}{'─'*50}")

    for idx, r in enumerate(results[:top_n], 1):
        marker = "🔴" if r["risk"] > 60 else "🟡" if r["risk"] > 40 else "🟢"
        print(f"  {idx:<4}{marker}{r['risk']:>4.0f} {r['top3_share']:>5.1f}% {r['inflation_rate']:>5.1f}% {r['inflated']:>4} {fmt(r['overrun']):>12} {r['direct_rate']:>6.1f}% {r['exclusive_count']:>4}  {r['name'][:35]:<35}{'; '.join(r['top3_names'][:3])}")

    # Detailed top 10
    print(f"\n\n{'='*130}")
    print(f"  DETAILED RISK BREAKDOWN — Top 10")
    print(f"{'='*130}")

    for idx, r in enumerate(results[:10], 1):
        print(f"\n{'─'*120}")
        print(f"  [{idx}] {r['name'][:60]} (NIF: {r['nif']})")
        print(f"      Risk Score: {r['risk']}/100 | Contracts: {r['total_contracts']} | Value: {fmt(r['total_value'])} | Winners: {r['num_winners']}")
        print(f"{'─'*120}")

        # Concentration
        conc_icon = "🔴" if r["top3_share"] > 80 else "🟡" if r["top3_share"] > 60 else "🟢"
        print(f"  {conc_icon} Concentration:  Top 3 take {r['top3_share']:.1f}% (HHI: {r['hhi']:.4f})")
        print(f"     Winners: {'; '.join(r['top3_names'][:3])}")

        # Inflation
        if r["inflated"] > 0:
            inf_icon = "🔴" if r["inflation_rate"] > 15 else "🟡" if r["inflation_rate"] > 5 else "🟢"
            print(f"  {inf_icon} Price Inflation: {r['inflated']} contracts ({r['inflation_rate']:.1f}% rate), overrun {fmt(r['overrun'])}, avg +{r['avg_pct']:.1f}%")
        else:
            print(f"  ⚪ Price Inflation: None")

        # Direct award
        dir_icon = "🔴" if r["direct_rate"] > 70 else "🟡" if r["direct_rate"] > 50 else "🟢"
        print(f"  {dir_icon} Direct Award:   {r['direct_rate']:.1f}%")

        # Exclusive companies
        if r["exclusive_count"] > 0:
            print(f"  🟡 Exclusive:     {r['exclusive_count']} companies only work with this municipality")
            for en in r["exclusive_names"][:3]:
                print(f"     • {en}")

        # BEP
        if r["bep_listings"] >= 0:
            bep_icon = "🟡" if r["bep_listings"] <= 2 and r["total_contracts"] >= 20 else "🟢"
            print(f"  {bep_icon} BEP Mismatch:   {r['bep_listings']} job listings")

    print(f"\n{'='*130}\n")
    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Municipality Risk Report — Combined Concentration + Inflation Analysis",
    )
    parser.add_argument("--top", "-t", type=int, default=30, help="Show top N (default 30)")
    parser.add_argument("--min-contracts", type=int, default=5, help="Min contracts per municipality (default 5)")
    parser.add_argument("--export", help="Export to JSON")
    parser.add_argument("--region", help="Filter by NUTS region code (e.g. PT16E for Coimbra)")
    parser.add_argument("--list-regions", action="store_true", help="List available NUTS regions")

    args = parser.parse_args()

    if args.list_regions:
        conn = sqlite3.connect(str(PROCUREMENT_DB))
        conn.row_factory = sqlite3.Row
        list_regions(conn)
        conn.close()
        return

    if args.region:
        args.region = args.region.upper()
        print(f"  Filtering by region: {args.region} ({NUTS_REGIONS.get(args.region, 'unknown')})", file=sys.stderr)

    results = scan_municipalities(min_contracts=args.min_contracts, region=args.region)
    print_report(results, args.top)

    if args.export:
        export_data = {
            "scan_results": results,
            "summary": {
                "total_municipalities": len(results),
                "high_risk": sum(1 for r in results if r["risk"] > 60),
                "medium_risk": sum(1 for r in results if 40 < r["risk"] <= 60),
                "low_risk": sum(1 for r in results if r["risk"] <= 40),
            }
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"Exported {len(results)} municipalities to {args.export}")


if __name__ == "__main__":
    main()
