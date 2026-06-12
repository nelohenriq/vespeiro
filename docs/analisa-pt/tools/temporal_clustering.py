#!/usr/bin/env python3
"""Temporal Contract Clustering — Detect suspicious bursts of contract awards.

Analyzes contract award timing to detect patterns like:
- Clusters of contracts awarded in short periods (same day/week)
- Contracts awarded right before elections or fiscal year-end
- Suspicious end-of-year spending surges
- Administration transition timing anomalies

Usage:
    python temporal_clustering.py                        # Full analysis
    python temporal_clustering.py --buyer 500014872      # Analyze specific buyer
    python temporal_clustering.py --municipality Gaia    # Search by municipality name
    python temporal_clustering.py --burst-days 7         # Detect 7-day clusters
    python temporal_clustering.py --top 20               # Top 20 bursts
    python temporal_clustering.py --export bursts.json   # Export to JSON
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import timedelta

from utils import fmt, parse_entity_field, parse_date, days_between

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"

# Portuguese municipal elections (last few cycles)
ELECTION_DATES = [
    "2025-09-28",  # 2025 municipal elections
    "2021-09-26",
    "2017-10-01",
    "2013-09-29",
    "2009-11-11",
]

# Fiscal year-end (Portuguese government fiscal year ends Dec 31)
FISCAL_YEAR_END_MONTH = 12
FISCAL_YEAR_END_DAY = 31


# =============================================================================
# TEMPORAL ANALYZER
# =============================================================================

class TemporalAnalyzer:
    """Detect temporal clustering and suspicious timing patterns."""

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

    def load_contracts(self, buyer_nif=None, municipality=None, year=None):
        """Load contracts with dates."""
        where = "WHERE dataCelebracaoContrato IS NOT NULL AND dataCelebracaoContrato != ''"
        params = []

        if buyer_nif:
            where += " AND adjudicante_nif = ?"
            params.append(buyer_nif)
        if municipality:
            where += " AND adjudicante_nome LIKE ?"
            params.append(f"%{municipality}%")
        if year:
            where += " AND Ano = ?"
            params.append(year)

        rows = self.conn.execute(f"""
            SELECT idcontrato, adjudicante_nif, adjudicante_nome, adjudicatarios,
                   precoContratual, precoBaseProcedimento, tipoprocedimento,
                   tipoContrato, objectoContrato, dataCelebracaoContrato,
                   dataPublicacao, concorrentes, Ano
            FROM contratos
            {where}
            ORDER BY dataCelebracaoContrato ASC
        """, params).fetchall()

        contracts = []
        for r in rows:
            dt = parse_date(r["dataCelebracaoContrato"])
            if not dt:
                continue
            contracts.append({
                "id": r["idcontrato"],
                "buyer_nif": r["adjudicante_nif"],
                "buyer_name": r["adjudicante_nome"],
                "value": r["precoContratual"] or 0,
                "base_price": r["precoBaseProcedimento"] or 0,
                "procedure": r["tipoprocedimento"] or "",
                "type": r["tipoContrato"] or "",
                "object": r["objectoContrato"] or "",
                "date": dt,
                "date_str": r["dataCelebracaoContrato"][:10],
                "year": r["Ano"] or "",
                "competitors": r["concorrentes"] or "",
            })

        return contracts

    def detect_daily_bursts(self, contracts, threshold=3):
        """Find days with an unusual number of contract awards."""
        by_date = defaultdict(list)
        for c in contracts:
            by_date[c["date_str"]].append(c)

        bursts = []
        for date_str, day_contracts in by_date.items():
            if len(day_contracts) >= threshold:
                total_value = sum(c["value"] for c in day_contracts)
                unique_buyers = len(set(c["buyer_nif"] for c in day_contracts))
                unique_types = len(set(c["type"] for c in day_contracts))

                # Check if near election
                dt = parse_date(date_str)
                days_to_election = None
                nearest_election = None
                for eDate in ELECTION_DATES:
                    eDt = parse_date(eDate)
                    if dt and eDt:
                        diff = days_between(dt, eDt)
                        if diff is not None and (days_to_election is None or diff < days_to_election):
                            days_to_election = diff
                            nearest_election = eDate

                # Check if near fiscal year-end
                is_year_end = False
                if dt:
                    if dt.month == 12 and dt.day >= 20:
                        is_year_end = True
                    elif dt.month == 11 and dt.day >= 25:
                        is_year_end = True

                bursts.append({
                    "date": date_str,
                    "contracts": len(day_contracts),
                    "total_value": total_value,
                    "unique_buyers": unique_buyers,
                    "unique_types": unique_types,
                    "is_year_end": is_year_end,
                    "days_to_election": days_to_election,
                    "nearest_election": nearest_election,
                })

        bursts.sort(key=lambda x: -x["total_value"])
        return bursts

    def detect_weekly_bursts(self, contracts, window_days=7, min_contracts=5):
        """Find weekly windows with high contract activity."""
        if not contracts:
            return []

        sorted_contracts = sorted(contracts, key=lambda c: c["date"])
        bursts = []
        seen_windows = set()

        for i, c in enumerate(sorted_contracts):
            window_end = c["date"] + timedelta(days=window_days)
            window_contracts = [
                cc for cc in sorted_contracts
                if cc["date"] >= c["date"] and cc["date"] <= window_end
            ]

            if len(window_contracts) < min_contracts:
                continue

            window_key = (c["date_str"], window_end.strftime("%Y-%m-%d"))
            if window_key in seen_windows:
                continue
            seen_windows.add(window_key)

            total_value = sum(cc["value"] for cc in window_contracts)
            unique_buyers = len(set(cc["buyer_nif"] for cc in window_contracts))

            bursts.append({
                "start_date": c["date_str"],
                "end_date": window_end.strftime("%Y-%m-%d"),
                "window_days": window_days,
                "contracts": len(window_contracts),
                "total_value": total_value,
                "unique_buyers": unique_buyers,
            })

        bursts.sort(key=lambda x: -x["total_value"])
        return bursts

    def detect_year_end_surge(self, contracts, surge_threshold=2.0):
        """Detect if December has significantly more spending than other months."""
        by_month = defaultdict(lambda: {"contracts": 0, "value": 0, "dates": []})
        for c in contracts:
            month = c["date"].month
            by_month[month]["contracts"] += 1
            by_month[month]["value"] += c["value"]
            by_month[month]["dates"].append(c["date_str"])

        if not by_month:
            return None

        # Calculate average monthly value (excluding December)
        other_months = {m: d for m, d in by_month.items() if m != 12}
        if not other_months:
            return None

        avg_other_value = sum(d["value"] for d in other_months.values()) / len(other_months)
        avg_other_contracts = sum(d["contracts"] for d in other_months.values()) / len(other_months)

        december = by_month.get(12, {"contracts": 0, "value": 0})
        dec_value_ratio = december["value"] / avg_other_value if avg_other_value > 0 else 0
        dec_contract_ratio = december["contracts"] / avg_other_contracts if avg_other_contracts > 0 else 0

        # Also check last week of December specifically
        dec_late = [c for c in contracts if c["date"].month == 12 and c["date"].day >= 24]
        dec_late_value = sum(c["value"] for c in dec_late)
        dec_late_count = len(dec_late)

        return {
            "monthly_breakdown": dict(by_month),
            "december_value": december["value"],
            "december_contracts": december["contracts"],
            "avg_other_month_value": avg_other_value,
            "avg_other_month_contracts": avg_other_contracts,
            "dec_value_ratio": dec_value_ratio,
            "dec_contract_ratio": dec_contract_ratio,
            "is_surge": dec_value_ratio >= surge_threshold,
            "dec_late_value": dec_late_value,
            "dec_late_count": dec_late_count,
        }

    def detect_buyer_bursts(self, contracts, min_contracts=3, burst_days=30):
        """Detect per-buyer spending bursts — many contracts in short period."""
        by_buyer = defaultdict(list)
        for c in contracts:
            by_buyer[c["buyer_nif"]].append(c)

        bursts = []
        for buyer_nif, buyer_contracts in by_buyer.items():
            if len(buyer_contracts) < min_contracts:
                continue

            sorted_c = sorted(buyer_contracts, key=lambda x: x["date"])

            # Sliding window
            for i in range(len(sorted_c)):
                window_end = sorted_c[i]["date"] + timedelta(days=burst_days)
                window = [c for c in sorted_c if c["date"] <= window_end and c["date"] >= sorted_c[i]["date"]]

                if len(window) >= min_contracts:
                    total_value = sum(c["value"] for c in window)
                    window_key = (buyer_nif, sorted_c[i]["date_str"])
                    if total_value > 0:
                        bursts.append({
                            "buyer_nif": buyer_nif,
                            "buyer_name": window[0]["buyer_name"],
                            "start_date": sorted_c[i]["date_str"],
                            "end_date": window[-1]["date_str"],
                            "contracts": len(window),
                            "total_value": total_value,
                            "avg_value": total_value / len(window),
                            "window_days": burst_days,
                        })

        # Deduplicate: keep only the highest-value burst per buyer
        best_bursts = {}
        for b in bursts:
            key = b["buyer_nif"]
            if key not in best_bursts or b["total_value"] > best_bursts[key]["total_value"]:
                best_bursts[key] = b

        return sorted(best_bursts.values(), key=lambda x: -x["total_value"])

    def detect_price_pattern(self, contracts):
        """Detect suspicious pricing patterns — same buyer, similar prices, short window."""
        by_buyer = defaultdict(list)
        for c in contracts:
            if c["value"] > 0:
                by_buyer[c["buyer_nif"]].append(c)

        patterns = []
        for buyer_nif, buyer_contracts in by_buyer.items():
            if len(buyer_contracts) < 3:
                continue

            sorted_c = sorted(buyer_contracts, key=lambda x: x["date"])

            # Find clusters of contracts with similar prices
            for i in range(len(sorted_c)):
                base_price = sorted_c[i]["value"]
                if base_price <= 0:
                    continue

                cluster = [sorted_c[i]]
                for j in range(i + 1, len(sorted_c)):
                    other = sorted_c[j]
                    if other["value"] <= 0:
                        continue
                    # Check if price is within 10% and within 90 days
                    price_diff_pct = abs(other["value"] - base_price) / base_price * 100
                    day_diff = days_between(sorted_c[i]["date"], other["date"])
                    if price_diff_pct <= 10 and day_diff is not None and day_diff <= 90:
                        cluster.append(other)

                if len(cluster) >= 3:
                    cluster_key = (buyer_nif, sorted_c[i]["date_str"], round(base_price, -2))
                    total_value = sum(c["value"] for c in cluster)
                    patterns.append({
                        "buyer_nif": buyer_nif,
                        "buyer_name": cluster[0]["buyer_name"],
                        "cluster_size": len(cluster),
                        "price_range": base_price,
                        "total_value": total_value,
                        "start_date": cluster[0]["date_str"],
                        "end_date": cluster[-1]["date_str"],
                        "contracts": cluster,
                    })

        # Deduplicate
        seen = set()
        unique = []
        for p in patterns:
            key = (p["buyer_nif"], p["start_date"], round(p["price_range"], -2))
            if key not in seen:
                seen.add(key)
                unique.append(p)

        unique.sort(key=lambda x: -x["total_value"])
        return unique


# =============================================================================
# OUTPUT
# =============================================================================

def print_report(contracts, bursts, weekly_bursts, year_end, buyer_bursts, price_patterns, top_n=20):
    """Print the temporal analysis report."""
    print(f"\n{'='*110}")
    print(f"  TEMPORAL CONTRACT CLUSTERING ANALYSIS")
    print(f"{'='*110}")
    print(f"\n  📊 Dataset Overview")
    print(f"  {'─'*60}")
    print(f"  Total contracts with dates:  {len(contracts):>8,}")
    total_value = sum(c["value"] for c in contracts)
    print(f"  Total value:                 {fmt(total_value):>8}")
    unique_buyers = len(set(c["buyer_nif"] for c in contracts))
    print(f"  Unique buyers:               {unique_buyers:>8,}")
    date_range = f"{contracts[0]['date_str']} → {contracts[-1]['date_str']}" if contracts else "N/A"
    print(f"  Date range:                  {date_range}")

    # Daily bursts
    print(f"\n  💥 Daily Contract Bursts (≥3 contracts on same day)")
    print(f"  {'─'*105}")
    if bursts:
        print(f"  {'#':<4}{'Date':<12}{'Contracts':>10}{'Value':>14}{'Buyers':>8}{'Year-End':>10}{'Election':>12}")
        print(f"  {'─'*4}{'─'*12}{'─'*10}{'─'*14}{'─'*8}{'─'*10}{'─'*12}")
        for i, b in enumerate(bursts[:top_n], 1):
            yend = "⚠️" if b["is_year_end"] else ""
            election = f"{b['days_to_election']}d" if b["days_to_election"] is not None and b["days_to_election"] <= 30 else ""
            print(f"  {i:<4}{b['date']:<12}{b['contracts']:>10}{fmt(b['total_value']):>14}{b['unique_buyers']:>8}{yend:>10}{election:>12}")
    else:
        print(f"  No significant daily bursts detected.")

    # Weekly bursts
    print(f"\n  📅 Weekly Contract Bursts (7-day windows)")
    print(f"  {'─'*105}")
    if weekly_bursts:
        print(f"  {'#':<4}{'Start':<12}{'End':<12}{'Contracts':>10}{'Value':>14}{'Buyers':>8}")
        print(f"  {'─'*4}{'─'*12}{'─'*12}{'─'*10}{'─'*14}{'─'*8}")
        for i, b in enumerate(weekly_bursts[:top_n], 1):
            print(f"  {i:<4}{b['start_date']:<12}{b['end_date']:<12}{b['contracts']:>10}{fmt(b['total_value']):>14}{b['unique_buyers']:>8}")
    else:
        print(f"  No significant weekly bursts detected.")

    # Year-end surge
    print(f"\n  🗓️  Fiscal Year-End Analysis (December)")
    print(f"  {'─'*60}")
    if year_end:
        ratio_icon = "🚨" if year_end["is_surge"] else "✅"
        print(f"  December value:            {fmt(year_end['december_value']):>10}")
        print(f"  December contracts:        {year_end['december_contracts']:>10,}")
        print(f"  Avg other month value:     {fmt(year_end['avg_other_month_value']):>10}")
        print(f"  December surge ratio:      {year_end['dec_value_ratio']:>9.1f}x {ratio_icon}")
        print(f"  Last week of December:     {year_end['dec_late_count']:>5} contracts ({fmt(year_end['dec_late_value'])})")
        print(f"\n  Monthly breakdown:")
        for month in range(1, 13):
            data = year_end["monthly_breakdown"].get(month, {"contracts": 0, "value": 0})
            bar_len = int(data["value"] / max(d["value"] for d in year_end["monthly_breakdown"].values()) * 30) if year_end["monthly_breakdown"] else 0
            bar = "█" * bar_len
            marker = " ← DEC" if month == 12 else ""
            print(f"    Month {month:>2}: {bar} {data['contracts']:>5} contracts  {fmt(data['value'])}{marker}")
    else:
        print(f"  No date data available.")

    # Per-buyer bursts
    print(f"\n  🏛️  Per-Buyer Spending Bursts (≥3 contracts in 30 days)")
    print(f"  {'─'*105}")
    if buyer_bursts:
        print(f"  {'#':<4}{'Buyer':<35}{'Period':<24}{'Contracts':>10}{'Value':>14}")
        print(f"  {'─'*4}{'─'*35}{'─'*24}{'─'*10}{'─'*14}")
        for i, b in enumerate(buyer_bursts[:top_n], 1):
            period = f"{b['start_date']} → {b['end_date']}"
            print(f"  {i:<4}{b['buyer_name'][:35]:<35}{period:<24}{b['contracts']:>10}{fmt(b['total_value']):>14}")
    else:
        print(f"  No significant buyer bursts detected.")

    # Price pattern anomalies
    print(f"\n  💰 Suspicious Price Patterns (similar prices, short window)")
    print(f"  {'─'*105}")
    if price_patterns:
        print(f"  {'#':<4}{'Buyer':<35}{'Period':<24}{'Count':>8}{'Price':>12}{'Total':>14}")
        print(f"  {'─'*4}{'─'*35}{'─'*24}{'─'*8}{'─'*12}{'─'*14}")
        for i, p in enumerate(price_patterns[:top_n], 1):
            period = f"{p['start_date']} → {p['end_date']}"
            print(f"  {i:<4}{p['buyer_name'][:35]:<35}{period:<24}{p['cluster_size']:>8}{fmt(p['price_range']):>12}{fmt(p['total_value']):>14}")
    else:
        print(f"  No suspicious price patterns detected.")

    print(f"\n{'='*110}\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Temporal Contract Clustering — Detect suspicious bursts",
    )
    parser.add_argument("--buyer", help="Analyze specific buyer by NIF")
    parser.add_argument("--municipality", help="Search by municipality name")
    parser.add_argument("--year", type=int, help="Filter by year")
    parser.add_argument("--burst-days", type=int, default=7, help="Window for weekly burst detection (default 7)")
    parser.add_argument("--top", type=int, default=20, help="Show top N results (default 20)")
    parser.add_argument("--export", help="Export results to JSON")

    args = parser.parse_args()

    analyzer = TemporalAnalyzer()
    analyzer.connect()

    print("Loading contracts...")
    contracts = analyzer.load_contracts(
        buyer_nif=args.buyer,
        municipality=args.municipality,
        year=args.year,
    )

    if not contracts:
        print("No contracts found with valid dates.")
        analyzer.close()
        sys.exit(1)

    print(f"  Loaded {len(contracts):,} contracts")

    print("Detecting daily bursts...")
    bursts = analyzer.detect_daily_bursts(contracts)

    print("Detecting weekly bursts...")
    weekly_bursts = analyzer.detect_weekly_bursts(contracts, window_days=args.burst_days)

    print("Analyzing year-end patterns...")
    year_end = analyzer.detect_year_end_surge(contracts)

    print("Detecting per-buyer bursts...")
    buyer_bursts = analyzer.detect_buyer_bursts(contracts)

    print("Detecting price patterns...")
    price_patterns = analyzer.detect_price_pattern(contracts)

    analyzer.close()

    print_report(contracts, bursts, weekly_bursts, year_end, buyer_bursts, price_patterns, args.top)

    if args.export:
        export_data = {
            "summary": {
                "total_contracts": len(contracts),
                "total_value": sum(c["value"] for c in contracts),
                "unique_buyers": len(set(c["buyer_nif"] for c in contracts)),
            },
            "daily_bursts": [{
                "date": b["date"], "contracts": b["contracts"],
                "total_value": b["total_value"], "is_year_end": b["is_year_end"],
                "days_to_election": b["days_to_election"],
            } for b in bursts],
            "weekly_bursts": [{
                "start_date": b["start_date"], "end_date": b["end_date"],
                "contracts": b["contracts"], "total_value": b["total_value"],
            } for b in weekly_bursts],
            "year_end": year_end,
            "buyer_bursts": [{
                "buyer_nif": b["buyer_nif"], "buyer_name": b["buyer_name"],
                "start_date": b["start_date"], "end_date": b["end_date"],
                "contracts": b["contracts"], "total_value": b["total_value"],
            } for b in buyer_bursts],
            "price_patterns": [{
                "buyer_nif": p["buyer_nif"], "buyer_name": p["buyer_name"],
                "cluster_size": p["cluster_size"], "price_range": p["price_range"],
                "total_value": p["total_value"],
            } for p in price_patterns],
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"Exported to {args.export}")


if __name__ == "__main__":
    main()
