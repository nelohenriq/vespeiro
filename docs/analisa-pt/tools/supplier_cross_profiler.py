#!/usr/bin/env python3
"""Supplier Cross-Buyer Profiler — Profile a single supplier across ALL buyers.

Given a supplier NIF or name, shows every entity they win contracts with,
concentration per buyer, whether they're dominant in multiple places,
temporal patterns, and connection to risk signals (price inflation,
self-referencing, direct award excess).

Usage:
    python supplier_cross_profiler.py --nif 501089233           # Profile by NIF
    python supplier_cross_profiler.py --name Constrobi          # Search by name
    python supplier_cross_profiler.py --nif 514288256 --export profile.json
    python supplier_cross_profiler.py --top 20                  # Top 20 suppliers by reach
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from utils import fmt, parse_entity_field

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"


# =============================================================================
# PARSING
# =============================================================================


# =============================================================================
# SUPPLIER PROFILER
# =============================================================================

class SupplierProfiler:
    """Profile a single supplier across all buyers in procurement data."""

    def __init__(self):
        self.conn = None

    def connect(self):
        if not PROCUREMENT_DB.exists():
            print(f"ERROR: procurement.db not found at {PROCUREMENT_DB}")
            sys.exit(1)
        self.conn = sqlite3.connect(str(PROCUREMENT_DB))
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def find_supplier(self, nif=None, name=None):
        """Find supplier NIF by NIF or name search."""
        if nif:
            row = self.conn.execute(
                "SELECT nifEntidade, desigEntidade FROM entidades WHERE nifEntidade = ?",
                (nif,),
            ).fetchone()
            if row:
                return {"nif": row["nifEntidade"], "name": row["desigEntidade"]}
            return None

        if name:
            rows = self.conn.execute(
                "SELECT nifEntidade, desigEntidade FROM entidades "
                "WHERE desigEntidade LIKE ? ORDER BY totValorContratIni DESC LIMIT 5",
                (f"%{name}%",),
            ).fetchall()
            if rows:
                if len(rows) > 1:
                    print(f"\n  Found {len(rows)} matching suppliers:")
                    for i, r in enumerate(rows):
                        print(f"    [{i+1}] {r['desigEntidade']} (NIF: {r['nifEntidade']})")
                    print(f"\n  Showing first match. Use --nif for exact match.\n")
                return {"nif": rows[0]["nifEntidade"], "name": rows[0]["desigEntidade"]}
            return None

        return None

    def profile_supplier(self, supplier_nif):
        """Build complete supplier profile across all buyers."""
        # Get all contracts where this supplier won
        rows = self.conn.execute("""
            SELECT idcontrato, adjudicante_nif, adjudicante_nome, adjudicatarios,
                   precoContratual, precoBaseProcedimento, tipoprocedimento,
                   tipoContrato, objectoContrato, dataCelebracaoContrato,
                   dataPublicacao, concorrentes, CPV, NUTs, Ano
            FROM contratos
            WHERE adjudicatarios LIKE ?
            ORDER BY dataCelebracaoContrato DESC
        """, (f"%{supplier_nif}%",)).fetchall()

        if not rows:
            return None

        # Parse contracts — extract those where this supplier is the winner
        contracts = []
        for r in rows:
            winners = parse_entity_field(r["adjudicatarios"])
            is_winner = any(w["nif"] == supplier_nif for w in winners)
            if not is_winner:
                continue

            winner_name = ""
            for w in winners:
                if w["nif"] == supplier_nif:
                    winner_name = w["name"]
                    break

            # Parse competitors
            competitors = []
            if r["concorrentes"] and r["concorrentes"] not in ("-", ""):
                for part in str(r["concorrentes"]).replace("\n", ";").split(";"):
                    part = part.strip()
                    if part and part != "-":
                        competitors.append(part)

            contracts.append({
                "id": r["idcontrato"],
                "buyer_nif": r["adjudicante_nif"],
                "buyer_name": r["adjudicante_nome"],
                "winner_name": winner_name,
                "value": r["precoContratual"] or 0,
                "base_price": r["precoBaseProcedimento"] or 0,
                "procedure": r["tipoprocedimento"] or "",
                "type": r["tipoContrato"] or "",
                "object": r["objectoContrato"] or "",
                "date": r["dataCelebracaoContrato"] or "",
                "pub_date": r["dataPublicacao"] or "",
                "competitors": competitors,
                "cpv": r["CPV"] or "",
                "nuts": r["NUTs"] or "",
                "year": r["Ano"] or "",
            })

        if not contracts:
            return None

        return self._build_profile(supplier_nif, contracts)

    def _build_profile(self, supplier_nif, contracts):
        """Build the structured profile from contract list."""
        total_value = sum(c["value"] for c in contracts)
        total_contracts = len(contracts)

        # Group by buyer
        by_buyer = defaultdict(lambda: {
            "name": "", "contracts": 0, "value": 0,
            "inflated": 0, "direct_award": 0, "years": set(),
            "competitor_sets": [], "objects": [],
        })

        for c in contracts:
            b = by_buyer[c["buyer_nif"]]
            b["name"] = c["buyer_name"]
            b["contracts"] += 1
            b["value"] += c["value"]
            if c["year"]:
                b["years"].add(str(c["year"]))
            if c["base_price"] > 0 and c["value"] > c["base_price"]:
                b["inflated"] += 1
            if "direto" in c["procedure"].lower() or "ajuste" in c["procedure"].lower():
                b["direct_award"] += 1
            if c["competitors"]:
                b["competitor_sets"].append(c["competitors"])
            if c["object"]:
                b["objects"].append(c["object"][:80])

        # Group by year
        by_year = defaultdict(lambda: {"contracts": 0, "value": 0})
        for c in contracts:
            y = str(c["year"]) if c["year"] else "unknown"
            by_year[y]["contracts"] += 1
            by_year[y]["value"] += c["value"]

        # Group by procedure type
        by_procedure = defaultdict(lambda: {"contracts": 0, "value": 0})
        for c in contracts:
            p = c["procedure"] or "unknown"
            by_procedure[p]["contracts"] += 1
            by_procedure[p]["value"] += c["value"]

        # Group by contract type
        by_type = defaultdict(lambda: {"contracts": 0, "value": 0})
        for c in contracts:
            t = c["type"] or "unknown"
            by_type[t]["contracts"] += 1
            by_type[t]["value"] += c["value"]

        # Detect risk signals
        risk_signals = []

        # Signal: Exclusive supplier (only works with one buyer)
        unique_buyers = len(by_buyer)
        if unique_buyers == 1 and total_contracts >= 5:
            risk_signals.append({
                "type": "exclusive_supplier",
                "severity": "warning",
                "description": f"Only wins contracts with {list(by_buyer.values())[0]['name'][:40]}",
            })

        # Signal: Dominant supplier (>30% of any buyer's total)
        for buyer_nif, data in by_buyer.items():
            buyer_total = self._get_buyer_total(buyer_nif)
            if buyer_total > 0:
                share = data["value"] * 100 / buyer_total
                if share >= 50:
                    risk_signals.append({
                        "type": "dominant_supplier",
                        "severity": "critical",
                        "description": f"Takes {share:.0f}% of {data['name'][:40]}'s total procurement ({fmt(data['value'])} of {fmt(buyer_total)})",
                    })
                elif share >= 30:
                    risk_signals.append({
                        "type": "dominant_supplier",
                        "severity": "warning",
                        "description": f"Takes {share:.0f}% of {data['name'][:40]}'s total procurement ({fmt(data['value'])} of {fmt(buyer_total)})",
                    })

        # Signal: Price inflation
        inflated_count = sum(1 for c in contracts if c["base_price"] > 0 and c["value"] > c["base_price"])
        if inflated_count > 0:
            total_overrun = sum(c["value"] - c["base_price"] for c in contracts if c["base_price"] > 0 and c["value"] > c["base_price"])
            risk_signals.append({
                "type": "price_inflation",
                "severity": "critical" if inflated_count >= 3 else "warning",
                "description": f"{inflated_count}/{total_contracts} contracts inflated, total overrun: {fmt(total_overrun)}",
            })

        # Signal: Direct award excess
        direct_count = sum(1 for c in contracts if "direto" in c["procedure"].lower() or "ajuste" in c["procedure"].lower())
        if total_contracts >= 5:
            direct_rate = direct_count * 100 / total_contracts
            if direct_rate >= 50:
                risk_signals.append({
                    "type": "direct_award_excess",
                    "severity": "warning",
                    "description": f"{direct_rate:.0f}% of contracts via direct award ({direct_count}/{total_contracts})",
                })

        # Signal: Multi-municipality dominance
        dominant_buyers = []
        for bn, bd in by_buyer.items():
            bt = self._get_buyer_total(bn)
            if bt > 0 and bd["value"] * 100 / bt >= 30:
                dominant_buyers.append(bd)
        if len(dominant_buyers) >= 3:
            risk_signals.append({
                "type": "multi_municipality_dominance",
                "severity": "critical",
                "description": f"Dominant (≥30%) in {len(dominant_buyers)} different buyers",
            })

        # Signal: Narrow competitor field
        contracts_with_competitors = [c for c in contracts if c["competitors"]]
        if contracts_with_competitors:
            avg_competitors = sum(len(c["competitors"]) for c in contracts_with_competitors) / len(contracts_with_competitors)
            if avg_competitors <= 2 and len(contracts_with_competitors) >= 5:
                risk_signals.append({
                    "type": "narrow_competition",
                    "severity": "warning",
                    "description": f"Avg {avg_competitors:.1f} competitors across {len(contracts_with_competitors)} contracts with data",
                })

        return {
            "supplier_nif": supplier_nif,
            "supplier_name": contracts[0]["winner_name"] if contracts else "",
            "total_contracts": total_contracts,
            "total_value": total_value,
            "unique_buyers": unique_buyers,
            "by_buyer": dict(by_buyer),
            "by_year": dict(by_year),
            "by_procedure": dict(by_procedure),
            "by_type": dict(by_type),
            "risk_signals": risk_signals,
            "contracts": contracts,
        }

    def _get_buyer_total(self, buyer_nif, cache=None):
        """Get total procurement value for a buyer (with optional cache)."""
        if cache is not None and buyer_nif in cache:
            return cache[buyer_nif]
        row = self.conn.execute(
            "SELECT SUM(precoContratual) as total FROM contratos "
            "WHERE adjudicante_nif = ? AND precoContratual > 0",
            (buyer_nif,),
        ).fetchone()
        total = row["total"] if row and row["total"] else 0
        if cache is not None:
            cache[buyer_nif] = total
        return total

    def top_suppliers(self, top_n=20, min_contracts=5):
        """List top suppliers by number of distinct buyers."""
        rows = self.conn.execute("""
            SELECT adjudicatarios, COUNT(DISTINCT adjudicante_nif) as buyer_count,
                   COUNT(*) as contract_count, SUM(precoContratual) as total_value
            FROM contratos
            WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''
            AND adjudicatarios != '-'
            GROUP BY adjudicatarios
            HAVING buyer_count >= ? AND contract_count >= ?
            ORDER BY buyer_count DESC, total_value DESC
            LIMIT ?
        """, (3, min_contracts, top_n)).fetchall()

        results = []
        for r in rows:
            winners = parse_entity_field(r["adjudicatarios"])
            if winners:
                nif = winners[0]["nif"]
                name = winners[0]["name"]
            else:
                nif = ""
                name = r["adjudicatarios"][:50]
            results.append({
                "nif": nif,
                "name": name,
                "buyer_count": r["buyer_count"],
                "contracts": r["contract_count"],
                "value": r["total_value"] or 0,
            })
        return results


# =============================================================================
# OUTPUT
# =============================================================================

def print_profile(profile):
    """Print the supplier profile."""
    print(f"\n{'='*100}")
    print(f"  SUPPLIER CROSS-BUYER PROFILE: {profile['supplier_name']}")
    print(f"  NIF: {profile['supplier_nif']}")
    print(f"{'='*100}")

    # Summary
    print(f"\n  📊 Summary")
    print(f"  {'─'*60}")
    print(f"  Total contracts:     {profile['total_contracts']:>8,}")
    print(f"  Total value:         {fmt(profile['total_value']):>8}")
    print(f"  Unique buyers:       {profile['unique_buyers']:>8,}")

    # Risk signals
    if profile["risk_signals"]:
        print(f"\n  🚨 Risk Signals ({len(profile['risk_signals'])})")
        print(f"  {'─'*60}")
        for s in profile["risk_signals"]:
            icon = "🔴" if s["severity"] == "critical" else "🟡" if s["severity"] == "warning" else "⚪"
            print(f"  {icon} [{s['type']}] {s['description']}")

    # Buyer breakdown
    print(f"\n  🏛️  Buyers ({profile['unique_buyers']})")
    print(f"  {'─'*95}")
    print(f"  {'#':<4}{'Buyer':<35}{'Contracts':>10}{'Value':>14}{'Share':>8}{'Inflated':>10}{'Direct':>8}")
    print(f"  {'─'*4}{'─'*35}{'─'*10}{'─'*14}{'─'*8}{'─'*10}{'─'*8}")

    sorted_buyers = sorted(profile["by_buyer"].items(), key=lambda x: -x[1]["value"])
    for i, (buyer_nif, data) in enumerate(sorted_buyers, 1):
        share = data["value"] * 100 / profile["total_value"] if profile["total_value"] > 0 else 0
        inflated = f"{data['inflated']}/{data['contracts']}" if data["inflated"] > 0 else "-"
        direct = f"{data['direct_award']}/{data['contracts']}" if data["direct_award"] > 0 else "-"
        print(f"  {i:<4}{data['name'][:35]:<35}{data['contracts']:>10}{fmt(data['value']):>14}{share:>7.1f}%{inflated:>10}{direct:>8}")

    # Year breakdown
    print(f"\n  📅 Timeline")
    print(f"  {'─'*60}")
    sorted_years = sorted(profile["by_year"].items())
    for year, data in sorted_years:
        bar_len = int(data["value"] / max(d["value"] for d in profile["by_year"].values()) * 30) if profile["by_year"] else 0
        bar = "█" * bar_len
        print(f"  {year:<8} {bar} {data['contracts']:>4} contracts  {fmt(data['value'])}")

    # Procedure breakdown
    print(f"\n  ⚙️  Procedure Types")
    print(f"  {'─'*60}")
    sorted_procs = sorted(profile["by_procedure"].items(), key=lambda x: -x[1]["value"])
    for proc, data in sorted_procs:
        share = data["value"] * 100 / profile["total_value"] if profile["total_value"] > 0 else 0
        print(f"  {proc[:45]:<45} {data['contracts']:>5} ({share:>5.1f}%) {fmt(data['value'])}")

    # Contract type breakdown
    print(f"\n  📦 Contract Types")
    print(f"  {'─'*60}")
    sorted_types = sorted(profile["by_type"].items(), key=lambda x: -x[1]["value"])
    for t, data in sorted_types:
        share = data["value"] * 100 / profile["total_value"] if profile["total_value"] > 0 else 0
        print(f"  {t[:45]:<45} {data['contracts']:>5} ({share:>5.1f}%) {fmt(data['value'])}")

    # Top contracts
    print(f"\n  📋 Top 10 Contracts by Value")
    print(f"  {'─'*95}")
    top_contracts = sorted(profile["contracts"], key=lambda x: -x["value"])[:10]
    for i, c in enumerate(top_contracts, 1):
        date = c["date"][:10] if c["date"] else "?"
        obj = c["object"][:55] if c["object"] else "?"
        print(f"  {i:>2}. [{date}] {fmt(c['value']):>10}  {c['buyer_name'][:35]}")
        print(f"      {obj}")
        if c["competitors"]:
            print(f"      Competitors: {', '.join(c['competitors'][:3])}")

    print(f"\n{'='*100}\n")


def print_top_suppliers(suppliers):
    """Print top suppliers list."""
    print(f"\n{'='*100}")
    print(f"  TOP SUPPLIERS BY CROSS-BUYER REACH")
    print(f"{'='*100}")
    print(f"\n  {'#':<4}{'Supplier':<35}{'NIF':<12}{'Buyers':>8}{'Contracts':>12}{'Value':>16}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*8}{'─'*12}{'─'*16}")

    for i, s in enumerate(suppliers, 1):
        print(f"  {i:<4}{s['name'][:35]:<35}{s['nif']:<12}{s['buyer_count']:>8}{s['contracts']:>12,}{fmt(s['value']):>16}")

    print(f"\n{'='*100}\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Supplier Cross-Buyer Profiler — Profile a supplier across all buyers",
    )
    parser.add_argument("--nif", help="Supplier NIF")
    parser.add_argument("--name", help="Supplier name (fuzzy search)")
    parser.add_argument("--top", type=int, default=20, help="Show top N suppliers by reach (default 20)")
    parser.add_argument("--min-contracts", type=int, default=5, help="Min contracts for top list (default 5)")
    parser.add_argument("--export", help="Export profile to JSON")

    args = parser.parse_args()

    profiler = SupplierProfiler()
    profiler.connect()

    if not args.nif and not args.name:
        # Show top suppliers by cross-buyer reach
        suppliers = profiler.top_suppliers(args.top, args.min_contracts)
        print_top_suppliers(suppliers)
        profiler.close()
        return

    # Find supplier
    supplier = profiler.find_supplier(nif=args.nif, name=args.name)
    if not supplier:
        print(f"Supplier not found: {args.nif or args.name}")
        profiler.close()
        sys.exit(1)

    # Build profile
    profile = profiler.profile_supplier(supplier["nif"])
    profiler.close()

    if not profile:
        print(f"No contracts found for supplier {supplier['name']} ({supplier['nif']})")
        sys.exit(1)

    print_profile(profile)

    if args.export:
        # Convert sets to lists for JSON serialization
        export_data = {
            "supplier_nif": profile["supplier_nif"],
            "supplier_name": profile["supplier_name"],
            "total_contracts": profile["total_contracts"],
            "total_value": profile["total_value"],
            "unique_buyers": profile["unique_buyers"],
            "risk_signals": profile["risk_signals"],
            "by_buyer": {
                k: {kk: (list(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()}
                for k, v in profile["by_buyer"].items()
            },
            "by_year": {k: dict(v) for k, v in profile["by_year"].items()},
            "by_procedure": {k: dict(v) for k, v in profile["by_procedure"].items()},
            "by_type": {k: dict(v) for k, v in profile["by_type"].items()},
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"Exported to {args.export}")


if __name__ == "__main__":
    main()
