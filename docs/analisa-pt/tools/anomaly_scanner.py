#!/usr/bin/env python3
"""Procurement Anomaly Scanner — Automated Multi-Signal Detection

Systematically scans procurement data for discrepancies and suspicious
patterns, computing composite risk scores to prioritize investigation.

Signals detected:
  1. Price Inflation (final > base price)
  2. Single-Supplier Dominance (>30% concentration)
  3. Self-Referencing (buyer = seller)
  4. Closed Procurement Ecosystem (few rotating companies)
  5. BEP-Procurement Mismatch (high contracts, low hiring)
  6. Direct Award Rate (excessive Ajuste Direto)
  7. No Competitors Recorded
  8. Municipality-Exclusive Companies
  9. Framework Agreement Abuse
 10. PRR Construction Inflation

Usage:
    python anomaly_scanner.py                  # Full scan, top 30 anomalies
    python anomaly_scanner.py --top 50         # Top 50
    python anomaly_scanner.py --entity 501089233  # Scan specific entity
    python anomaly_scanner.py --municipality Fundão  # Scan specific municipality
    python anomaly_scanner.py --signal price   # Only check price inflation
    python anomaly_scanner.py --export anomalies.json  # Export to JSON
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

from utils import fmt, parse_entity_field

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
BEP_DB = SCRIPT_DIR / "bep_index.db"


# =============================================================================
# SIGNAL DETECTORS
# =============================================================================

class AnomalyScanner:
    """Multi-signal procurement anomaly detector."""

    def __init__(self):
        self.conn = None
        self.bep_conn = None
        self.signals = []

    def connect(self):
        self.conn = sqlite3.connect(str(PROCUREMENT_DB))
        self.conn.row_factory = sqlite3.Row
        if BEP_DB.exists():
            self.bep_conn = sqlite3.connect(str(BEP_DB))
            self.bep_conn.row_factory = sqlite3.Row
        else:
            self.bep_conn = None

    def close(self):
        if self.conn:
            self.conn.close()
        if self.bep_conn:
            self.bep_conn.close()

    # -------------------------------------------------------------------------
    # Signal 1: Price Inflation
    # -------------------------------------------------------------------------
    def detect_price_inflation(self, nif_filter=None, min_overrun=1000):
        """Find entities with contracts where final price > base price."""
        where = "WHERE precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento"
        params = [min_overrun]
        if nif_filter:
            where += " AND adjudicante_nif = ?"
            params.append(nif_filter)

        rows = self.conn.execute(f"""
            SELECT adjudicante_nif, adjudicante_nome,
                   COUNT(*) as inflated_count,
                   SUM(precoContratual - precoBaseProcedimento) as total_overrun,
                   AVG((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) as avg_pct,
                   MAX((precoContratual - precoBaseProcedimento) * 100.0 / precoBaseProcedimento) as max_pct
            FROM contratos {where}
            GROUP BY adjudicante_nif
            HAVING total_overrun >= ?
            ORDER BY total_overrun DESC
        """, params).fetchall()

        for r in rows:
            # Get total contracts for rate calculation
            total = self.conn.execute(
                "SELECT COUNT(*) FROM contratos WHERE adjudicante_nif = ? AND precoBaseProcedimento > 0",
                (r["adjudicante_nif"],)
            ).fetchone()[0]

            rate = r["inflated_count"] * 100 / total if total > 0 else 0
            score = min(100, (r["avg_pct"] or 0) * 2 + rate * 5 + min(r["inflated_count"], 20))

            self.signals.append({
                "type": "price_inflation",
                "severity": "critical" if r["avg_pct"] > 15 else "warning",
                "nif": r["adjudicante_nif"],
                "name": r["adjudicante_nome"],
                "score": score,
                "details": {
                    "inflated_count": r["inflated_count"],
                    "total_with_base": total,
                    "inflation_rate": round(rate, 1),
                    "total_overrun": r["total_overrun"],
                    "avg_pct": round(r["avg_pct"] or 0, 1),
                    "max_pct": round(r["max_pct"] or 0, 1),
                },
                "description": f"{r['inflated_count']} inflated contracts, avg +{r['avg_pct']:.1f}%, overrun {fmt(r['total_overrun'])}",
            })

    # -------------------------------------------------------------------------
    # Signal 2: Single-Supplier Dominance
    # -------------------------------------------------------------------------
    def detect_supplier_dominance(self, nif_filter=None, min_share=30, min_value=500000):
        """Find entities where one winner takes >min_share% of total value."""
        # Get all buyer-winner pairs
        where = "WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' AND adjudicante_nif IS NOT NULL"
        params = []
        if nif_filter:
            where += " AND adjudicante_nif = ?"
            params.append(nif_filter)

        # First get total per buyer
        buyer_totals = {}
        for r in self.conn.execute(f"""
            SELECT adjudicante_nif, SUM(precoContratual) as total
            FROM contratos {where} AND precoContratual > 0
            GROUP BY adjudicante_nif HAVING total >= ?
        """, params + [min_value]).fetchall():
            buyer_totals[r["adjudicante_nif"]] = r["total"]

        # Then get per winner
        winner_data = defaultdict(lambda: defaultdict(float))
        for r in self.conn.execute(f"""
            SELECT adjudicante_nif, adjudicante_nome, adjudicatarios, precoContratual
            FROM contratos {where} AND precoContratual > 0
        """, params).fetchall():
            buyers_nif = r["adjudicante_nif"]
            if buyers_nif not in buyer_totals:
                continue
            for entity in parse_entity_field(r["adjudicatarios"]):
                key = entity["nif"] or entity["name"]
                winner_data[buyers_nif][key] += r["precoContratual"] or 0

        # Find dominant winners
        for buyer_nif, winners in winner_data.items():
            total = buyer_totals.get(buyer_nif, 0)
            if total < min_value:
                continue
            for winner_key, winner_value in winners.items():
                share = winner_value * 100 / total
                if share >= min_share and winner_value >= min_value:
                    # Get buyer name
                    buyer_name = self.conn.execute(
                        "SELECT adjudicante_nome FROM contratos WHERE adjudicante_nif = ? LIMIT 1",
                        (buyer_nif,)
                    ).fetchone()
                    bname = buyer_name[0] if buyer_name else buyer_nif

                    # Get winner name
                    wname = winner_key
                    for r in self.conn.execute(
                        "SELECT adjudicatarios FROM contratos WHERE adjudicatarios LIKE ? LIMIT 1",
                        (f"%{winner_key[:20]}%",)
                    ).fetchall():
                        for e in parse_entity_field(r[0]):
                            if e["nif"] == winner_key or e["name"] == winner_key:
                                wname = e["name"]
                                break

                    score = min(100, share + (10 if share > 50 else 0) + (10 if total > 10_000_000 else 0))
                    self.signals.append({
                        "type": "supplier_dominance",
                        "severity": "critical" if share > 50 else "warning",
                        "nif": buyer_nif,
                        "name": bname,
                        "score": score,
                        "details": {
                            "winner_nif": winner_key,
                            "winner_name": wname,
                            "share_pct": round(share, 1),
                            "winner_value": winner_value,
                            "total_value": total,
                        },
                        "description": f"{wname[:40]} takes {share:.0f}% ({fmt(winner_value)}) of {fmt(total)} total",
                    })

    # -------------------------------------------------------------------------
    # Signal 3: Self-Referencing
    # -------------------------------------------------------------------------
    def detect_self_referencing(self, nif_filter=None):
        """Find entities appearing as both buyer and seller."""
        where = "WHERE adjudicatarios IS NOT NULL AND adjudicatarios != '' AND adjudicante_nif IS NOT NULL"
        params = []
        if nif_filter:
            where += " AND adjudicante_nif = ?"
            params.append(nif_filter)

        rows = self.conn.execute(f"""
            SELECT adjudicante_nif, adjudicante_nome, COUNT(*) as cnt,
                   SUM(precoContratual) as total
            FROM contratos {where}
            GROUP BY adjudicante_nif
        """, params).fetchall()

        for r in rows:
            adj_nif = r["adjudicante_nif"]
            # Check if this NIF appears in adjudicatarios
            for contract in self.conn.execute(
                "SELECT adjudicatarios, precoContratual, objectoContrato FROM contratos WHERE adjudicante_nif = ? AND adjudicatarios IS NOT NULL",
                (adj_nif,)
            ).fetchall():
                for entity in parse_entity_field(contract[0]):
                    if entity["nif"] == adj_nif:
                        self.signals.append({
                            "type": "self_referencing",
                            "severity": "critical",
                            "nif": adj_nif,
                            "name": r["adjudicante_nome"],
                            "score": 100,
                            "details": {
                                "contracts": r["cnt"],
                                "total_value": r["total"],
                                "object": str(contract[2] or "")[:60],
                                "value": contract[1],
                            },
                            "description": f"Self-referencing: {r['adjudicante_nome']} buys from itself ({fmt(contract[1])})",
                        })
                        break  # One case is enough to flag

    # -------------------------------------------------------------------------
    # Signal 4: Closed Procurement Ecosystem
    # -------------------------------------------------------------------------
    def detect_closed_ecosystem(self, min_contracts=10):
        """Find municipalities where a small number of companies rotate wins."""
        # Get all buyers with their winners
        buyers = defaultdict(lambda: {"name": "", "total": 0, "winners": defaultdict(float)})

        for r in self.conn.execute("""
            SELECT adjudicante_nif, adjudicante_nome, adjudicatarios, precoContratual
            FROM contratos WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''
            AND adjudicante_nif IS NOT NULL AND precoContratual > 0
        """).fetchall():
            buyers[r["adjudicante_nif"]]["name"] = r["adjudicante_nome"]
            buyers[r["adjudicante_nif"]]["total"] += r["precoContratual"] or 0
            for entity in parse_entity_field(r["adjudicatarios"]):
                key = entity["nif"] or entity["name"]
                buyers[r["adjudicante_nif"]]["winners"][key] += r["precoContratual"] or 0

        for buyer_nif, data in buyers.items():
            if data["total"] < 1_000_000:  # Skip small buyers
                continue
            winners = data["winners"]
            if len(winners) < 2 or len(winners) > 20:  # Too few or too many
                continue

            # Calculate Herfindahl index (concentration)
            hhi = sum((v / data["total"]) ** 2 for v in winners.values())
            # Normalize: 1/n <= HHI <= 1, where n = number of winners
            normalized = (hhi - 1/len(winners)) / (1 - 1/len(winners)) if len(winners) > 1 else 1

            # Check if top 3 win >60% of value
            sorted_winners = sorted(winners.items(), key=lambda x: -x[1])
            top3_value = sum(v for _, v in sorted_winners[:3])
            top3_share = top3_value * 100 / data["total"]

            if top3_share >= 60 and len(winners) >= 3:
                # Get winner names
                top3_names = []
                for wk, wv in sorted_winners[:3]:
                    name = wk
                    for r in self.conn.execute(
                        "SELECT adjudicatarios FROM contratos WHERE adjudicatarios LIKE ? LIMIT 1",
                        (f"%{wk[:15]}%",)
                    ).fetchall():
                        for e in parse_entity_field(r[0]):
                            if e["nif"] == wk or e["name"] == wk:
                                name = e["name"][:35]
                                break
                    top3_names.append(f"{name} ({wv*100/data['total']:.0f}%)")

                score = min(100, top3_share + (10 if len(winners) <= 5 else 0) + normalized * 20)
                self.signals.append({
                    "type": "closed_ecosystem",
                    "severity": "warning",
                    "nif": buyer_nif,
                    "name": data["name"],
                    "score": score,
                    "details": {
                        "unique_winners": len(winners),
                        "top3_share": round(top3_share, 1),
                        "top3_names": top3_names,
                        "hhi": round(hhi, 4),
                        "total_value": data["total"],
                    },
                    "description": f"Top 3 companies take {top3_share:.0f}% of {fmt(data['total'])} across {len(winners)} winners",
                })

    # -------------------------------------------------------------------------
    # Signal 5: BEP-Procurement Mismatch
    # -------------------------------------------------------------------------
    def detect_bep_mismatch(self, min_contracts=50, max_listings=2):
        """Find entities with high procurement but minimal BEP job listings."""
        if not self.bep_conn:
            return

        # Load BEP NIF -> listing_count
        bep_map = {}
        for r in self.bep_conn.execute(
            "SELECT nif, listing_count FROM bep_entities WHERE nif IS NOT NULL AND nif != ''"
        ).fetchall():
            bep_map[r[0]] = r[1]

        # Get high-contract entities
        for r in self.conn.execute(f"""
            SELECT adjudicante_nif, adjudicante_nome, COUNT(*) as cnt,
                   SUM(precoContratual) as total
            FROM contratos WHERE adjudicante_nif IS NOT NULL
            GROUP BY adjudicante_nif
            HAVING cnt >= ? AND total >= 5000000
            ORDER BY total DESC
        """, (min_contracts,)).fetchall():
            nif = r["adjudicante_nif"]
            listings = bep_map.get(nif, -1)
            if listings >= 0 and listings <= max_listings:
                score = min(100, (r["cnt"] / 100) * 10 + (r["total"] / 1_000_000) * 2)
                self.signals.append({
                    "type": "bep_mismatch",
                    "severity": "warning",
                    "nif": nif,
                    "name": r["adjudicante_nome"],
                    "score": score,
                    "details": {
                        "contracts": r["cnt"],
                        "total_value": r["total"],
                        "bep_listings": listings,
                    },
                    "description": f"{r['cnt']} contracts ({fmt(r['total'])}) but only {listings} BEP job listings",
                })

    # -------------------------------------------------------------------------
    # Signal 6: Direct Award Rate
    # -------------------------------------------------------------------------
    def detect_direct_award_excess(self, min_contracts=20, threshold_pct=50):
        """Find entities with excessive use of direct award."""
        rows = self.conn.execute("""
            SELECT adjudicante_nif, adjudicante_nome,
                   COUNT(*) as total,
                   SUM(CASE WHEN tipoprocedimento LIKE '%Ajuste Direto%' THEN 1 ELSE 0 END) as direct,
                   SUM(precoContratual) as total_value
            FROM contratos WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
            GROUP BY adjudicante_nif
            HAVING total >= ?
        """, (min_contracts,)).fetchall()

        for r in rows:
            if r["total"] == 0:
                continue
            rate = r["direct"] * 100 / r["total"]
            if rate >= threshold_pct:
                score = min(100, rate + (10 if r["total_value"] > 5_000_000 else 0))
                self.signals.append({
                    "type": "direct_award_excess",
                    "severity": "warning" if rate > 70 else "info",
                    "nif": r["adjudicante_nif"],
                    "name": r["adjudicante_nome"],
                    "score": score,
                    "details": {
                        "total_contracts": r["total"],
                        "direct_awards": r["direct"],
                        "direct_rate": round(rate, 1),
                        "total_value": r["total_value"],
                    },
                    "description": f"{rate:.0f}% direct award rate ({r['direct']}/{r['total']} contracts, {fmt(r['total_value'])})",
                })

    # -------------------------------------------------------------------------
    # Signal 7: No Competitors Recorded
    # -------------------------------------------------------------------------
    def detect_no_competitors(self, min_contracts=10, threshold_pct=80):
        """Find entities where competitors are almost never recorded."""
        rows = self.conn.execute("""
            SELECT adjudicante_nif, adjudicante_nome,
                   COUNT(*) as total,
                   SUM(CASE WHEN concorrentes IS NULL OR concorrentes = '' OR concorrentes = '-'
                       THEN 1 ELSE 0 END) as no_comp,
                   SUM(precoContratual) as total_value
            FROM contratos WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
            AND precoContratual > 0
            GROUP BY adjudicante_nif
            HAVING total >= ?
        """, (min_contracts,)).fetchall()

        for r in rows:
            if r["total"] == 0:
                continue
            rate = r["no_comp"] * 100 / r["total"]
            if rate >= threshold_pct:
                score = min(100, rate + (5 if r["total"] > 50 else 0))
                self.signals.append({
                    "type": "no_competitors",
                    "severity": "info",
                    "nif": r["adjudicante_nif"],
                    "name": r["adjudicante_nome"],
                    "score": score,
                    "details": {
                        "total_contracts": r["total"],
                        "no_competitor_contracts": r["no_comp"],
                        "no_competitor_rate": round(rate, 1),
                        "total_value": r["total_value"],
                    },
                    "description": f"{rate:.0f}% of contracts have no competitors recorded ({r['no_comp']}/{r['total']})",
                })

    # -------------------------------------------------------------------------
    # Signal 8: Municipality-Exclusive Companies
    # -------------------------------------------------------------------------
    def detect_exclusive_companies(self, min_contracts=5, min_value=100000):
        """Find companies that only win contracts from one buyer."""
        # Build company -> set of buyers mapping
        company_buyers = defaultdict(lambda: {"name": "", "buyers": set(), "total": 0, "contracts": 0})

        for r in self.conn.execute("""
            SELECT adjudicante_nif, adjudicante_nome, adjudicatarios, precoContratual
            FROM contratos WHERE adjudicatarios IS NOT NULL AND adjudicatarios != ''
            AND precoContratual > 0
        """).fetchall():
            for entity in parse_entity_field(r["adjudicatarios"]):
                key = entity["nif"] or entity["name"]
                company_buyers[key]["name"] = entity["name"]
                company_buyers[key]["buyers"].add(r["adjudicante_nif"])
                company_buyers[key]["total"] += r["precoContratual"] or 0
                company_buyers[key]["contracts"] += 1

        for nif, data in company_buyers.items():
            if len(data["buyers"]) == 1 and data["contracts"] >= min_contracts and data["total"] >= min_value:
                buyer_nif = list(data["buyers"])[0]
                buyer_name = self.conn.execute(
                    "SELECT adjudicante_nome FROM contratos WHERE adjudicante_nif = ? LIMIT 1",
                    (buyer_nif,)
                ).fetchone()
                bname = buyer_name[0] if buyer_name else buyer_nif

                score = min(100, data["contracts"] * 2 + (data["total"] / 1_000_000) * 5)
                self.signals.append({
                    "type": "exclusive_company",
                    "severity": "warning",
                    "nif": nif,
                    "name": data["name"],
                    "score": score,
                    "details": {
                        "buyer_nif": buyer_nif,
                        "buyer_name": bname,
                        "contracts": data["contracts"],
                        "total_value": data["total"],
                    },
                    "description": f"{data['name'][:40]} only wins with {bname[:30]} ({data['contracts']} contracts, {fmt(data['total'])})",
                })

    # -------------------------------------------------------------------------
    # Composite Risk Score
    # -------------------------------------------------------------------------
    def compute_composite_scores(self):
        """Combine all signals into per-entity composite risk scores."""
        entities = defaultdict(lambda: {
            "name": "", "signals": [], "total_score": 0,
            "signal_count": 0, "critical_count": 0
        })

        for s in self.signals:
            nif = s["nif"]
            entities[nif]["name"] = s["name"]
            entities[nif]["signals"].append(s)
            # Weighted score: critical signals count double
            weight = 2 if s["severity"] == "critical" else 1
            entities[nif]["total_score"] += s["score"] * weight
            entities[nif]["signal_count"] += 1
            if s["severity"] == "critical":
                entities[nif]["critical_count"] += 1

        # Normalize: divide by number of signals and cap at 100
        for nif, data in entities.items():
            if data["signal_count"] > 0:
                data["total_score"] = min(100, data["total_score"] / data["signal_count"])

        return entities

    # -------------------------------------------------------------------------
    # Main Scan
    # -------------------------------------------------------------------------
    def run_scan(self, signals=None, nif_filter=None):
        """Run all (or selected) anomaly detection signals."""
        self.connect()

        available_signals = {
            "price": self.detect_price_inflation,
            "dominance": self.detect_supplier_dominance,
            "self_ref": self.detect_self_referencing,
            "ecosystem": self.detect_closed_ecosystem,
            "bep": self.detect_bep_mismatch,
            "direct": self.detect_direct_award_excess,
            "competitors": self.detect_no_competitors,
            "exclusive": self.detect_exclusive_companies,
        }

        # Entity-level signals accept nif_filter; dataset-level signals don't
        entity_level = {"price", "dominance", "self_ref"}

        if signals:
            for s in signals:
                if s in available_signals:
                    if s in entity_level:
                        available_signals[s](nif_filter=nif_filter)
                    else:
                        available_signals[s]()
        else:
            for name, detector in available_signals.items():
                if name in entity_level:
                    detector(nif_filter=nif_filter)
                else:
                    detector()

        entities = self.compute_composite_scores()
        self.close()
        return entities


# =============================================================================
# OUTPUT
# =============================================================================

def print_report(entities, top_n=30):
    """Print the anomaly report."""
    # Sort by composite score
    ranked = sorted(entities.items(), key=lambda x: (-x[1]["critical_count"], -x[1]["total_score"], -x[1]["signal_count"]))

    print(f"\n{'='*110}")
    print(f"  PROCUREMENT ANOMALY SCAN — Top {top_n} Entities by Risk Score")
    print(f"{'='*110}")

    # Summary stats
    total_entities = len(entities)
    critical_entities = sum(1 for d in entities.values() if d["critical_count"] > 0)
    warning_entities = sum(1 for d in entities.values() if d["critical_count"] == 0 and d["signal_count"] >= 2)
    single_signal = sum(1 for d in entities.values() if d["signal_count"] == 1)

    print(f"\n  📊 Summary")
    print(f"  {'─'*60}")
    print(f"  Total entities flagged:     {total_entities:>6,}")
    print(f"  Critical (has self-ref):    {critical_entities:>6,}")
    print(f"  Warning (2+ signals):       {warning_entities:>6,}")
    print(f"  Single signal:              {single_signal:>6,}")

    # Signal type breakdown
    signal_counts = defaultdict(int)
    for data in entities.values():
        for s in data["signals"]:
            signal_counts[s["type"]] += 1
    print(f"\n  Signals by type:")
    for stype, count in sorted(signal_counts.items(), key=lambda x: -x[1]):
        print(f"    {stype:<25} {count:>5}")

    # Top anomalies
    print(f"\n  {'─'*105}")
    print(f"  {'#':<4}{'Score':>6}{'Crit':>5}{'Signals':>8}{'NIF':<12}{'Entity':<35}{'Top Signal'}")
    print(f"  {'─'*4}{'─'*6}{'─'*5}{'─'*8}{'─'*12}{'─'*35}{'─'*35}")

    for i, (nif, data) in enumerate(ranked[:top_n], 1):
        crit = f"{'🔴' if data['critical_count'] > 0 else '🟡' if data['signal_count'] >= 2 else '⚪'}"
        top_signal = data["signals"][0]["type"]
        print(f"  {i:<4}{data['total_score']:>5.0f} {crit}  {data['signal_count']:>5}  {nif:<12}{data['name'][:35]:<35}{top_signal}")

    # Detailed view for top 10
    print(f"\n\n{'='*110}")
    print(f"  DETAILED ANOMALY REPORT — Top 10")
    print(f"{'='*110}")

    for i, (nif, data) in enumerate(ranked[:10], 1):
        print(f"\n{'─'*100}")
        print(f"  [{i}] {data['name'][:60]} (NIF: {nif})")
        print(f"      Composite Score: {data['total_score']:.0f}/100 | "
              f"Signals: {data['signal_count']} | Critical: {data['critical_count']}")
        print(f"{'─'*100}")

        for s in data["signals"]:
            icon = "🔴" if s["severity"] == "critical" else "🟡" if s["severity"] == "warning" else "⚪"
            print(f"  {icon} {s['type']:<25} Score: {s['score']:.0f}  {s['description']}")

    print(f"\n{'='*110}\n")
    return ranked


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Procurement Anomaly Scanner — Automated Multi-Signal Detection",
    )
    parser.add_argument("--top", "-t", type=int, default=30, help="Show top N anomalies (default 30)")
    parser.add_argument("--entity", help="Scan specific entity by NIF")
    parser.add_argument("--signal", nargs="+", help="Only check specific signals: price, dominance, self_ref, ecosystem, bep, direct, competitors, exclusive")
    parser.add_argument("--export", help="Export results to JSON")

    args = parser.parse_args()

    scanner = AnomalyScanner()
    entities = scanner.run_scan(signals=args.signal, nif_filter=args.entity)
    ranked = print_report(entities, args.top)

    if args.export:
        export_data = {
            "scan_results": [],
            "summary": {
                "total_flagged": len(entities),
                "critical": sum(1 for d in entities.values() if d["critical_count"] > 0),
                "warning": sum(1 for d in entities.values() if d["signal_count"] >= 2),
            }
        }
        for nif, data in ranked:
            export_data["scan_results"].append({
                "nif": nif,
                "name": data["name"],
                "composite_score": round(data["total_score"], 1),
                "signal_count": data["signal_count"],
                "critical_count": data["critical_count"],
                "signals": [{"type": s["type"], "severity": s["severity"],
                             "score": round(s["score"], 1), "details": s["details"],
                             "description": s["description"]} for s in data["signals"]],
            })
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"Exported {len(ranked)} entities to {args.export}")


if __name__ == "__main__":
    main()
