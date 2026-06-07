#!/usr/bin/env python3
"""Bid Pattern Analyzer — Detect rotating winners, always-same-bidders, and suspicious pricing.

Analyzes bidding patterns across procurement data to detect:
- Rotating winners: Same group of companies taking turns winning
- Always-same-bidders: Small closed group of bidders on every contract
- Suspiciously similar pricing: Contracts with nearly identical final prices
- Bid Suppression: One dominant bidder with others as "decoy" bidders

Usage:
    python bid_pattern_analyzer.py                        # Full analysis
    python bid_pattern_analyzer.py --buyer 500014872      # Analyze specific buyer
    python bid_pattern_analyzer.py --municipality Fundão  # Search by municipality
    python bid_pattern_analyzer.py --top 20               # Top 20 patterns
    python bid_pattern_analyzer.py --export patterns.json # Export to JSON
"""

import sys
import json
import re
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"


# =============================================================================
# PARSING
# =============================================================================

def parse_entity_field(text):
    """Parse 'NIF - Name' or 'NIF1 - Name1; NIF2 - Name2' format."""
    if not text:
        return []
    text = str(text).strip()
    if text in ("-", "- -", "", "None"):
        return []
    entities = []
    for part in text.split(";"):
        part = part.strip()
        match = re.match(r"(\d{9})\s*-\s*(.+)", part)
        if match:
            entities.append({"nif": match.group(1), "name": match.group(2).strip()})
        elif part and part != "-":
            entities.append({"nif": "", "name": part.strip()})
    return entities


def fmt(val):
    """Format currency value."""
    if val is None or val == 0:
        return "€0"
    if val >= 1_000_000_000:
        return f"€{val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"€{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"€{val / 1_000:.0f}K"
    return f"€{val:.0f}"


def parse_competitor_count(text):
    """Extract number of competitors from concorrentes field."""
    if not text or text in ("-", ""):
        return None
    text = str(text).strip()
    # Try to extract a number
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    # Count NIF patterns (NIF - Name)
    nifs = re.findall(r"\d{9}\s*-", text)
    if nifs:
        return len(nifs)
    return None


def parse_competitor_nifs(text):
    """Extract competitor NIFs from concorrentes field."""
    if not text or text in ("-", ""):
        return []
    text = str(text).strip()
    nifs = re.findall(r"(\d{9})\s*-", text)
    return nifs


# =============================================================================
# BID PATTERN ANALYZER
# =============================================================================

class BidPatternAnalyzer:
    """Detect suspicious bidding patterns."""

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

    def load_contracts(self, buyer_nif=None, municipality=None):
        """Load contracts with competitor data."""
        where = "WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' AND adjudicatarios != '-'"
        params = []

        if buyer_nif:
            where += " AND adjudicante_nif = ?"
            params.append(buyer_nif)
        if municipality:
            where += " AND adjudicante_nome LIKE ?"
            params.append(f"%{municipality}%")

        rows = self.conn.execute(f"""
            SELECT idcontrato, adjudicante_nif, adjudicante_nome, adjudicatarios,
                   precoContratual, precoBaseProcedimento, tipoprocedimento,
                   tipoContrato, objectoContrato, dataCelebracaoContrato,
                   dataPublicacao, concorrentes, CPV, Ano
            FROM contratos
            {where}
            ORDER BY dataCelebracaoContrato ASC
        """, params).fetchall()

        contracts = []
        for r in rows:
            winners = parse_entity_field(r["adjudicatarios"])
            if not winners:
                continue

            contracts.append({
                "id": r["idcontrato"],
                "buyer_nif": r["adjudicante_nif"],
                "buyer_name": r["adjudicante_nome"],
                "winners": [w for w in winners if w["nif"]],
                "value": r["precoContratual"] or 0,
                "base_price": r["precoBaseProcedimento"] or 0,
                "procedure": r["tipoprocedimento"] or "",
                "type": r["tipoContrato"] or "",
                "object": r["objectoContrato"] or "",
                "date": r["dataCelebracaoContrato"] or "",
                "pub_date": r["dataPublicacao"] or "",
                "competitor_text": r["concorrentes"] or "",
                "competitor_count": parse_competitor_count(r["concorrentes"]),
                "competitor_nifs": parse_competitor_nifs(r["concorrentes"]),
                "cpv": r["CPV"] or "",
                "year": r["Ano"] or "",
            })

        return contracts

    def detect_rotating_winners(self, contracts, min_contracts=5, min_winners=3):
        """Detect groups of companies that take turns winning from the same buyer."""
        # Group by buyer
        by_buyer = defaultdict(list)
        for c in contracts:
            by_buyer[c["buyer_nif"]].append(c)

        rotations = []
        for buyer_nif, buyer_contracts in by_buyer.items():
            if len(buyer_contracts) < min_contracts:
                continue

            # Get unique winners
            winner_counts = Counter()
            for c in buyer_contracts:
                for w in c["winners"]:
                    winner_counts[w["nif"]] += 1

            if len(winner_counts) < min_winners:
                continue

            # Check if winners appear with similar frequency (rotation pattern)
            counts = list(winner_counts.values())
            avg_count = sum(counts) / len(counts)
            if avg_count < 2:
                continue

            # Calculate rotation score: how evenly distributed are wins
            max_count = max(counts)
            min_count = min(counts)
            rotation_ratio = min_count / max_count if max_count > 0 else 0

            if rotation_ratio >= 0.3:  # At least 30% as many wins as the leader
                # Get winner details
                winner_details = []
                for nif, count in winner_counts.most_common():
                    name = ""
                    for c in buyer_contracts:
                        for w in c["winners"]:
                            if w["nif"] == nif:
                                name = w["name"]
                                break
                        if name:
                            break
                    total_value = sum(c["value"] for c in buyer_contracts if any(w["nif"] == nif for w in c["winners"]))
                    winner_details.append({
                        "nif": nif, "name": name, "wins": count, "value": total_value,
                    })

                total_value = sum(c["value"] for c in buyer_contracts)
                rotations.append({
                    "buyer_nif": buyer_nif,
                    "buyer_name": buyer_contracts[0]["buyer_name"],
                    "total_contracts": len(buyer_contracts),
                    "total_value": total_value,
                    "unique_winners": len(winner_counts),
                    "rotation_ratio": rotation_ratio,
                    "winners": winner_details,
                })

        rotations.sort(key=lambda x: (-x["rotation_ratio"], -x["total_value"]))
        return rotations

    def detect_closed_bidder_groups(self, contracts, min_contracts=5, min_bidder_set=3):
        """Detect groups of bidders that always appear together."""
        # Group by buyer
        by_buyer = defaultdict(list)
        for c in contracts:
            by_buyer[c["buyer_nif"]].append(c)

        closed_groups = []
        for buyer_nif, buyer_contracts in by_buyer.items():
            if len(buyer_contracts) < min_contracts:
                continue

            # Build bidder sets per contract
            bidder_sets = []
            for c in buyer_contracts:
                bidder_nifs = set(w["nif"] for w in c["winners"])
                bidder_nifs.update(c["competitor_nifs"])
                if bidder_nifs:
                    bidder_sets.append(frozenset(bidder_nifs))

            if not bidder_sets:
                continue

            # Find bidder groups that co-occur frequently
            bidder_freq = Counter()
            for bs in bidder_sets:
                for nif in bs:
                    bidder_freq[nif] += 1

            # Find bidders that appear in >50% of contracts
            total = len(bidder_sets)
            frequent_bidders = {nif for nif, count in bidder_freq.items() if count >= total * 0.5}

            if len(frequent_bidders) >= min_bidder_set:
                # Get names for frequent bidders
                bidder_names = {}
                for c in buyer_contracts:
                    winner_map = {w["nif"]: w["name"] for w in c["winners"]}
                    for nif in frequent_bidders:
                        if nif not in bidder_names and nif in winner_map:
                            bidder_names[nif] = winner_map[nif]

                # Calculate how often this exact group appears together
                group_cooccurrence = 0
                for bs in bidder_sets:
                    if frequent_bidders.issubset(bs):
                        group_cooccurrence += 1

                cooccurrence_rate = group_cooccurrence / total * 100

                if cooccurrence_rate >= 30:  # Group appears together in 30%+ of contracts
                    closed_groups.append({
                        "buyer_nif": buyer_nif,
                        "buyer_name": buyer_contracts[0]["buyer_name"],
                        "total_contracts": total,
                        "group_size": len(frequent_bidders),
                        "cooccurrence_rate": cooccurrence_rate,
                        "bidders": [
                            {"nif": nif, "name": bidder_names.get(nif, nif), "frequency": bidder_freq[nif] * 100 / total}
                            for nif in frequent_bidders
                        ],
                    })

        closed_groups.sort(key=lambda x: (-x["cooccurrence_rate"], -x["group_size"]))
        return closed_groups

    def detect_price_suppression(self, contracts, min_contracts=3, suppression_ratio=0.7):
        """Detect bid suppression — one dominant bidder with decoy bidders.

        Pattern: One company wins most contracts while others consistently
        lose despite always bidding.
        """
        # Group by buyer
        by_buyer = defaultdict(list)
        for c in contracts:
            if c["competitor_count"] and c["competitor_count"] >= 2:
                by_buyer[c["buyer_nif"]].append(c)

        suppressions = []
        for buyer_nif, buyer_contracts in by_buyer.items():
            if len(buyer_contracts) < min_contracts:
                continue

            # Count wins per winner
            winner_wins = Counter()
            for c in buyer_contracts:
                for w in c["winners"]:
                    winner_wins[w["nif"]] += 1

            if not winner_wins:
                continue

            # Check if one winner dominates
            top_winner, top_wins = winner_wins.most_common(1)[0]
            total = len(buyer_contracts)
            win_rate = top_wins / total

            if win_rate >= suppression_ratio:
                # Find the decoy bidders (always bid, never win)
                loser_counts = Counter()
                for c in buyer_contracts:
                    for nif in c["competitor_nifs"]:
                        if nif != top_winner and nif not in c["winner_nifs"]:
                            loser_counts[nif] += 1

                # Decoys: appeared in ≥50% of contracts but never won
                decoys = [
                    {"nif": nif, "appearances": count, "appear_rate": count * 100 / total}
                    for nif, count in loser_counts.items()
                    if count >= total * 0.4 and nif not in winner_wins
                ]

                if decoys:
                    top_name = ""
                    for c in buyer_contracts:
                        for w in c["winners"]:
                            if w["nif"] == top_winner:
                                top_name = w["name"]
                                break
                        if top_name:
                            break

                    suppressions.append({
                        "buyer_nif": buyer_nif,
                        "buyer_name": buyer_contracts[0]["buyer_name"],
                        "total_contracts": total,
                        "dominant_winner_nif": top_winner,
                        "dominant_winner_name": top_name,
                        "win_rate": win_rate,
                        "wins": top_wins,
                        "decoys": decoys,
                    })

        suppressions.sort(key=lambda x: (-x["win_rate"], -x["total_contracts"]))
        return suppressions

    def detect_similar_pricing(self, contracts, similarity_pct=5, min_cluster=3):
        """Detect contracts with suspiciously similar pricing from the same buyer."""
        # Group by buyer
        by_buyer = defaultdict(list)
        for c in contracts:
            if c["value"] > 0:
                by_buyer[c["buyer_nif"]].append(c)

        similar = []
        for buyer_nif, buyer_contracts in by_buyer.items():
            if len(buyer_contracts) < min_cluster:
                continue

            # Find price clusters
            sorted_c = sorted(buyer_contracts, key=lambda x: x["value"])
            visited = set()

            for i, c in enumerate(sorted_c):
                if i in visited:
                    continue

                cluster = [c]
                for j in range(i + 1, len(sorted_c)):
                    if j in visited:
                        continue
                    other = sorted_c[j]
                    if c["value"] > 0:
                        diff_pct = abs(other["value"] - c["value"]) / c["value"] * 100
                        if diff_pct <= similarity_pct:
                            cluster.append(other)
                            visited.add(j)

                if len(cluster) >= min_cluster:
                    visited.add(i)
                    total_value = sum(cc["value"] for cc in cluster)
                    similar.append({
                        "buyer_nif": buyer_nif,
                        "buyer_name": buyer_contracts[0]["buyer_name"],
                        "cluster_size": len(cluster),
                        "price": c["value"],
                        "total_value": total_value,
                        "contracts": cluster,
                    })

        similar.sort(key=lambda x: -x["total_value"])
        return similar

    def detect_winner_concentration(self, contracts, min_concentration=0.6):
        """Detect buyers where one winner takes >60% of contracts."""
        by_buyer = defaultdict(lambda: {"total": 0, "value": 0, "name": "", "winners": Counter()})
        for c in contracts:
            b = by_buyer[c["buyer_nif"]]
            b["total"] += 1
            b["value"] += c["value"]
            b["name"] = c["buyer_name"]
            for w in c["winners"]:
                b["winners"][w["nif"]] += 1

        concentrated = []
        for buyer_nif, data in by_buyer.items():
            if data["total"] < 5:
                continue

            for winner_nif, wins in data["winners"].most_common(3):
                win_rate = wins / data["total"]
                if win_rate >= min_concentration:
                    # Get winner name
                    name = ""
                    for c in contracts:
                        if c["buyer_nif"] == buyer_nif:
                            for w in c["winners"]:
                                if w["nif"] == winner_nif:
                                    name = w["name"]
                                    break
                            if name:
                                break

                    concentrated.append({
                        "buyer_nif": buyer_nif,
                        "buyer_name": data["name"],
                        "winner_nif": winner_nif,
                        "winner_name": name,
                        "win_rate": win_rate,
                        "wins": wins,
                        "total": data["total"],
                        "value": data["value"],
                    })

        concentrated.sort(key=lambda x: (-x["win_rate"], -x["value"]))
        return concentrated


# =============================================================================
# OUTPUT
# =============================================================================

def print_report(contracts, rotations, closed_groups, suppressions, similar_pricing, concentrated, top_n=20):
    """Print the bid pattern analysis report."""
    print(f"\n{'='*110}")
    print(f"  BID PATTERN ANALYSIS")
    print(f"{'='*110}")
    print(f"\n  📊 Dataset Overview")
    print(f"  {'─'*60}")
    print(f"  Total contracts:         {len(contracts):>8,}")
    total_value = sum(c["value"] for c in contracts)
    print(f"  Total value:             {fmt(total_value):>8}")
    with_competitors = sum(1 for c in contracts if c["competitor_count"] is not None)
    print(f"  With competitor data:    {with_competitors:>8,} ({with_competitors*100/max(len(contracts),1):.1f}%)")
    unique_buyers = len(set(c["buyer_nif"] for c in contracts))
    print(f"  Unique buyers:           {unique_buyers:>8,}")

    # Rotating winners
    print(f"\n  🔄 Rotating Winners (same group, taking turns)")
    print(f"  {'─'*105}")
    if rotations:
        print(f"  {'#':<4}{'Buyer':<30}{'Winners':>8}{'Contracts':>10}{'Value':>14}{'Rotation':>10}")
        print(f"  {'─'*4}{'─'*30}{'─'*8}{'─'*10}{'─'*14}{'─'*10}")
        for i, r in enumerate(rotations[:top_n], 1):
            print(f"  {i:<4}{r['buyer_name'][:30]:<30}{r['unique_winners']:>8}{r['total_contracts']:>10}{fmt(r['total_value']):>14}{r['rotation_ratio']:>9.0%}")
            for w in r["winners"][:5]:
                print(f"      └─ {w['name'][:40]:<40} {w['wins']:>3} wins  {fmt(w['value'])}")
    else:
        print(f"  No rotating winner patterns detected.")

    # Closed bidder groups
    print(f"\n  🚫 Closed Bidder Groups (same bidders always appear together)")
    print(f"  {'─'*105}")
    if closed_groups:
        print(f"  {'#':<4}{'Buyer':<30}{'Group':>8}{'Contracts':>10}{'Co-occurrence':>14}")
        print(f"  {'─'*4}{'─'*30}{'─'*8}{'─'*10}{'─'*14}")
        for i, g in enumerate(closed_groups[:top_n], 1):
            print(f"  {i:<4}{g['buyer_name'][:30]:<30}{g['group_size']:>8}{g['total_contracts']:>10}{g['cooccurrence_rate']:>13.1f}%")
            for b in g["bidders"]:
                print(f"      └─ {b['name'][:40]:<40} appears in {b['frequency']:.0f}% of contracts")
    else:
        print(f"  No closed bidder groups detected.")

    # Bid suppression
    print(f"\n  🎭 Bid Suppression (dominant winner with decoy bidders)")
    print(f"  {'─'*105}")
    if suppressions:
        print(f"  {'#':<4}{'Buyer':<30}{'Winner':<30}{'Win Rate':>10}{'Contracts':>10}{'Decoys':>8}")
        print(f"  {'─'*4}{'─'*30}{'─'*30}{'─'*10}{'─'*10}{'─'*8}")
        for i, s in enumerate(suppressions[:top_n], 1):
            print(f"  {i:<4}{s['buyer_name'][:30]:<30}{s['dominant_winner_name'][:30]:<30}{s['win_rate']:>9.0%}{s['total_contracts']:>10}{len(s['decoys']):>8}")
            for d in s["decoys"][:3]:
                print(f"      └─ Decoy: appears {d['appear_rate']:.0f}% but never wins")
    else:
        print(f"  No bid suppression patterns detected.")

    # Similar pricing
    print(f"\n  💰 Suspiciously Similar Pricing")
    print(f"  {'─'*105}")
    if similar_pricing:
        print(f"  {'#':<4}{'Buyer':<30}{'Count':>8}{'Price':>14}{'Total':>14}")
        print(f"  {'─'*4}{'─'*30}{'─'*8}{'─'*14}{'─'*14}")
        for i, sp in enumerate(similar_pricing[:top_n], 1):
            print(f"  {i:<4}{sp['buyer_name'][:30]:<30}{sp['cluster_size']:>8}{fmt(sp['price']):>14}{fmt(sp['total_value']):>14}")
    else:
        print(f"  No suspicious pricing patterns detected.")

    # Winner concentration
    print(f"\n  🎯 Winner Concentration (≥60% win rate)")
    print(f"  {'─'*105}")
    if concentrated:
        print(f"  {'#':<4}{'Buyer':<30}{'Winner':<30}{'Win Rate':>10}{'Wins':>8}{'Total':>8}{'Value':>14}")
        print(f"  {'─'*4}{'─'*30}{'─'*30}{'─'*10}{'─'*8}{'─'*8}{'─'*14}")
        for i, c in enumerate(concentrated[:top_n], 1):
            print(f"  {i:<4}{c['buyer_name'][:30]:<30}{c['winner_name'][:30]:<30}{c['win_rate']:>9.0%}{c['wins']:>8}{c['total']:>8}{fmt(c['value']):>14}")
    else:
        print(f"  No high concentration detected.")

    print(f"\n{'='*110}\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Bid Pattern Analyzer — Detect rotating winners and suspicious patterns",
    )
    parser.add_argument("--buyer", help="Analyze specific buyer by NIF")
    parser.add_argument("--municipality", help="Search by municipality name")
    parser.add_argument("--top", type=int, default=20, help="Show top N results (default 20)")
    parser.add_argument("--export", help="Export results to JSON")

    args = parser.parse_args()

    analyzer = BidPatternAnalyzer()
    analyzer.connect()

    print("Loading contracts...")
    contracts = analyzer.load_contracts(
        buyer_nif=args.buyer,
        municipality=args.municipality,
    )

    if not contracts:
        print("No contracts found with competitor data.")
        analyzer.close()
        sys.exit(1)

    print(f"  Loaded {len(contracts):,} contracts")

    print("Detecting rotating winners...")
    rotations = analyzer.detect_rotating_winners(contracts)

    print("Detecting closed bidder groups...")
    closed_groups = analyzer.detect_closed_bidder_groups(contracts)

    print("Detecting bid suppression...")
    suppressions = analyzer.detect_price_suppression(contracts)

    print("Detecting similar pricing...")
    similar_pricing = analyzer.detect_similar_pricing(contracts)

    print("Detecting winner concentration...")
    concentrated = analyzer.detect_winner_concentration(contracts)

    analyzer.close()

    print_report(contracts, rotations, closed_groups, suppressions, similar_pricing, concentrated, args.top)

    if args.export:
        export_data = {
            "summary": {
                "total_contracts": len(contracts),
                "total_value": sum(c["value"] for c in contracts),
            },
            "rotating_winners": [{
                "buyer_nif": r["buyer_nif"], "buyer_name": r["buyer_name"],
                "unique_winners": r["unique_winners"], "total_contracts": r["total_contracts"],
                "rotation_ratio": r["rotation_ratio"],
                "winners": r["winners"],
            } for r in rotations],
            "closed_bidder_groups": [{
                "buyer_nif": g["buyer_nif"], "buyer_name": g["buyer_name"],
                "group_size": g["group_size"], "cooccurrence_rate": g["cooccurrence_rate"],
                "bidders": g["bidders"],
            } for g in closed_groups],
            "bid_suppression": [{
                "buyer_nif": s["buyer_nif"], "buyer_name": s["buyer_name"],
                "dominant_winner_nif": s["dominant_winner_nif"],
                "dominant_winner_name": s["dominant_winner_name"],
                "win_rate": s["win_rate"], "decoys": s["decoys"],
            } for s in suppressions],
            "similar_pricing": [{
                "buyer_nif": sp["buyer_nif"], "buyer_name": sp["buyer_name"],
                "cluster_size": sp["cluster_size"], "price": sp["price"],
            } for sp in similar_pricing],
            "winner_concentration": [{
                "buyer_nif": c["buyer_nif"], "buyer_name": c["buyer_name"],
                "winner_nif": c["winner_nif"], "winner_name": c["winner_name"],
                "win_rate": c["win_rate"], "wins": c["wins"],
            } for c in concentrated],
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"Exported to {args.export}")


if __name__ == "__main__":
    main()
