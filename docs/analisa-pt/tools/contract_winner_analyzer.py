#!/usr/bin/env python3
"""Contract Winner Analyzer — Corruption Pattern Detection

Analyzes public procurement contracts to detect suspicious patterns:
- Spending concentration: one company dominating a municipality's contracts
- Self-referencing: buyer NIF = seller NIF (same entity on both sides)
- Cross-municipality dominance: same company winning across many municipalities
- Price clustering: suspiciously similar contract values from same seller

Usage:
    # Full analysis (all patterns)
    python contract_winner_analyzer.py

    # Concentration: find municipalities where one winner dominates
    python contract_winner_analyzer.py concentration --threshold 40

    # Self-referencing: find entities buying from themselves
    python contract_winner_analyzer.py self-ref

    # Cross-municipality: find companies winning in many municipalities
    python contract_winner_analyzer.py cross-municipality --min 3

    # Suspicious patterns: combined risk score
    python contract_winner_analyzer.py suspicious --top 20
"""

import argparse
import html as html_mod
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).parent
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
NIF_MAPPING_FILE = SCRIPT_DIR / "data" / "nif_mapping.json"
FREGUESIA_MAPPING_FILE = SCRIPT_DIR / "data" / "freguesia_mapping.json"
HTML_OUTPUT = SCRIPT_DIR / "corruption_report.html"


# =============================================================================
# DATA LOADING
# =============================================================================

def load_contract_index() -> Dict[str, List[Dict]]:
    """Load contract_index.json (includes adjudicatário data)."""
    if not CONTRACT_INDEX.exists():
        print(f"Error: {CONTRACT_INDEX} not found", file=sys.stderr)
        print("Run `bep_base_crossref.py` first to build the index.", file=sys.stderr)
        return {}
    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def load_nif_mapping() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load Câmara↔Município NIF mapping."""
    if not NIF_MAPPING_FILE.exists():
        return {}, {}
    with open(NIF_MAPPING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    mappings = data.get("mappings", []) if isinstance(data, dict) else data
    camara_to_municipio = {m["camara_nif"]: m["municipio_nif"] for m in mappings}
    municipio_to_camara = {m["municipio_nif"]: m["camara_nif"] for m in mappings}
    return camara_to_municipio, municipio_to_camara


# =============================================================================
# CONCENTRATION ANALYSIS
# =============================================================================

def analyze_concentration(contract_index: Dict, threshold: float = 40.0):
    """Find municipalities where one winner dominates spending.

    A concentration above `threshold`% means one company receives more
    than that share of a municipality's total contract value.
    """
    print(f"\n{'='*110}")
    print(f"SPENDING CONCENTRATION — Single Winner Dominating Municipalities (>{threshold}%)")
    print(f"{'='*110}")

    # Group by buyer NIF → seller NIF
    buyer_seller: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(lambda: {
        "name": "", "contracts": 0, "value": 0.0
    }))
    buyer_totals: Dict[str, Dict] = defaultdict(lambda: {"name": "", "contracts": 0, "value": 0.0})

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            winner_name = c.get("adjudicatario", "")
            valor = c.get("valor", 0) or 0
            if not winner_nif or not winner_name:
                continue

            buyer_seller[buyer_nif][winner_nif]["name"] = winner_name
            buyer_seller[buyer_nif][winner_nif]["contracts"] += 1
            buyer_seller[buyer_nif][winner_nif]["value"] += valor

            buyer_totals[buyer_nif]["contracts"] += 1
            buyer_totals[buyer_nif]["value"] += valor
            if not buyer_totals[buyer_nif]["name"]:
                buyer_totals[buyer_nif]["name"] = contracts[0].get("entity_name", buyer_nif)

    # Find concentration cases
    alerts = []
    for buyer_nif, sellers in buyer_seller.items():
        total_value = buyer_totals[buyer_nif]["value"]
        if total_value <= 0:
            continue
        for seller_nif, sd in sellers.items():
            share = (sd["value"] / total_value) * 100
            if share >= threshold:
                alerts.append({
                    "buyer_nif": buyer_nif,
                    "buyer_name": buyer_totals[buyer_nif]["name"],
                    "seller_nif": seller_nif,
                    "seller_name": sd["name"],
                    "contracts": sd["contracts"],
                    "value": sd["value"],
                    "total_value": total_value,
                    "share": share,
                })

    alerts.sort(key=lambda x: -x["value"])

    if not alerts:
        print(f"\n  No concentration cases above {threshold}% found.")
        return

    total_value = sum(a["value"] for a in alerts)
    print(f"\n  ⚠️  {len(alerts)} concentration alerts found")
    print(f"  Total concentrated value: €{total_value:,.2f}")

    print(f"\n  {'#':<4}{'Buyer (Municipality)':<35}{'Winner':<30}{'Share':>7}{'Contracts':>10}{'Value':>16}")
    print(f"  {'─'*4}{'─'*35}{'─'*30}{'─'*7}{'─'*10}{'─'*16}")

    for i, a in enumerate(alerts[:30], 1):
        buyer = a["buyer_name"][:33]
        seller = a["seller_name"][:28]
        print(f"  {i:<4}{buyer:<35}{seller:<30}{a['share']:>6.1f}%{a['contracts']:>10}€{a['value']:>14,.2f}")

    if len(alerts) > 30:
        print(f"\n  ... and {len(alerts) - 30} more alerts")


# =============================================================================
# SELF-REFERENCING DETECTION
# =============================================================================

def analyze_self_referencing(contract_index: Dict):
    """Find entities where buyer NIF = seller NIF (same entity on both sides)."""
    print(f"\n{'='*110}")
    print(f"SELF-REFERENCING — Entities Buying From Themselves")
    print(f"{'='*110}")

    cases = []
    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            if winner_nif and winner_nif == buyer_nif:
                cases.append({
                    "nif": buyer_nif,
                    "name": c.get("entity_name", buyer_nif),
                    "winner_name": c.get("adjudicatario", ""),
                    "valor": c.get("valor", 0) or 0,
                    "tipo": c.get("tipo", ""),
                    "objeto": c.get("objeto", ""),
                    "data": c.get("data", ""),
                    "contract_id": c.get("contract_id"),
                })

    if not cases:
        print("\n  No self-referencing cases found.")
        return

    # Group by NIF
    by_nif: Dict[str, List[Dict]] = defaultdict(list)
    for c in cases:
        by_nif[c["nif"]].append(c)

    total_value = sum(c["valor"] for c in cases)
    print(f"\n  🚨 {len(cases)} self-referencing contracts found")
    print(f"  Unique entities: {len(by_nif)}")
    print(f"  Total value: €{total_value:,.2f}")

    print(f"\n  ⚠️  Self-Referencing Entities (by total value)")
    print(f"  {'─'*100}")

    for nif, entity_cases in sorted(by_nif.items(), key=lambda x: -sum(c["valor"] for c in x[1]))[:15]:
        total = sum(c["valor"] for c in entity_cases)
        print(f"\n  [{nif}] {entity_cases[0]['name'][:60]}")
        print(f"    Cases: {len(entity_cases)}, Total: €{total:,.2f}")
        for c in entity_cases[:3]:
            print(f"    • €{c['valor']:,.2f} ({c['tipo'][:40]}) [{c['data']}]")
            if c["objeto"]:
                print(f"      {c['objeto'][:70]}")
        if len(entity_cases) > 3:
            print(f"    ... and {len(entity_cases) - 3} more")


# =============================================================================
# CROSS-MUNICIPALITY DOMINANCE
# =============================================================================

def analyze_cross_municipality(contract_index: Dict, min_municipalities: int = 3):
    """Find companies winning contracts in many municipalities."""
    print(f"\n{'='*110}")
    print(f"CROSS-MUNICIPALITY DOMINANCE — Companies Winning in {min_municipalities}+ Municipalities")
    print(f"{'='*110}")

    # Group by seller NIF
    seller_data: Dict[str, Dict] = defaultdict(lambda: {
        "name": "",
        "municipalities": set(),
        "contracts": 0,
        "total_value": 0.0,
        "buyers": defaultdict(lambda: {"name": "", "contracts": 0, "value": 0.0}),
    })

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            winner_name = c.get("adjudicatario", "")
            if not winner_nif or not winner_name:
                continue
            valor = c.get("valor", 0) or 0
            buyer_name = c.get("entity_name", buyer_nif)

            sd = seller_data[winner_nif]
            sd["name"] = winner_name
            sd["municipalities"].add(buyer_nif)
            sd["contracts"] += 1
            sd["total_value"] += valor
            sd["buyers"][buyer_nif]["name"] = buyer_name
            sd["buyers"][buyer_nif]["contracts"] += 1
            sd["buyers"][buyer_nif]["value"] += valor

    # Filter and sort
    multi = [
        (nif, d) for nif, d in seller_data.items()
        if len(d["municipalities"]) >= min_municipalities
    ]
    multi.sort(key=lambda x: -x[1]["total_value"])

    if not multi:
        print(f"\n  No companies found winning in {min_municipalities}+ municipalities.")
        return

    total_value = sum(d["total_value"] for _, d in multi)
    print(f"\n  📊 {len(multi)} companies winning in {min_municipalities}+ municipalities")
    print(f"  Total multi-municipality value: €{total_value:,.2f}")

    print(f"\n  {'#':<4}{'Company':<35}{'NIF':<12}{'Municipalities':>14}{'Contracts':>12}{'Value':>18}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*14}{'─'*12}{'─'*18}")

    for i, (nif, d) in enumerate(multi[:25], 1):
        mc = len(d["municipalities"])
        print(f"  {i:<4}{d['name'][:35]:<35}{nif:<12}{mc:>14}{d['contracts']:>12,}€{d['total_value']:>16,.2f}")

    # Detail top 3
    print(f"\n  🔍 Detailed View — Top 3")
    for i, (nif, d) in enumerate(multi[:3], 1):
        mc = len(d["municipalities"])
        print(f"\n  {'─'*100}")
        print(f"  #{i} {d['name'][:60]}")
        print(f"     NIF: {nif}  |  Municipalities: {mc}  |  Contracts: {d['contracts']:,}  |  Total: €{d['total_value']:,.2f}")
        sorted_buyers = sorted(d["buyers"].items(), key=lambda x: -x[1]["value"])
        for buyer_nif, bd in sorted_buyers[:8]:
            print(f"       [{buyer_nif}] {bd['name'][:45]:<45} {bd['contracts']:>5} contracts  €{bd['value']:>14,.2f}")
        if len(sorted_buyers) > 8:
            print(f"       ... and {len(sorted_buyers) - 8} more")


# =============================================================================
# SUSPICIOUS PATTERNS (COMBINED RISK)
# =============================================================================

def analyze_suspicious(contract_index: Dict, top_n: int = 20):
    """Combined risk scoring: concentration + self-ref + cross-municipality."""
    print(f"\n{'='*110}")
    print(f"SUSPICIOUS PATTERNS — Combined Risk Scoring")
    print(f"{'='*110}")

    # Build seller profiles
    seller_risk: Dict[str, Dict] = defaultdict(lambda: {
        "name": "",
        "contracts": 0,
        "total_value": 0.0,
        "municipalities": set(),
        "self_ref_count": 0,
        "self_ref_value": 0.0,
        "concentration_max": 0.0,
        "concentration_buyer": "",
        "risk_score": 0.0,
    })

    # Track buyer totals for concentration calc
    buyer_totals: Dict[str, float] = defaultdict(float)
    buyer_seller_value: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            if not winner_nif:
                continue
            valor = c.get("valor", 0) or 0
            buyer_totals[buyer_nif] += valor
            buyer_seller_value[buyer_nif][winner_nif] += valor

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            winner_name = c.get("adjudicatario", "")
            if not winner_nif or not winner_name:
                continue
            valor = c.get("valor", 0) or 0

            sr = seller_risk[winner_nif]
            sr["name"] = winner_name
            sr["contracts"] += 1
            sr["total_value"] += valor
            sr["municipalities"].add(buyer_nif)

            # Self-referencing
            if winner_nif == buyer_nif:
                sr["self_ref_count"] += 1
                sr["self_ref_value"] += valor

    # Calculate concentration for each seller
    for buyer_nif, sellers in buyer_seller_value.items():
        total = buyer_totals[buyer_nif]
        if total <= 0:
            continue
        for seller_nif, val in sellers.items():
            share = (val / total) * 100
            if share > seller_risk[seller_nif]["concentration_max"]:
                seller_risk[seller_nif]["concentration_max"] = share
                seller_risk[seller_nif]["concentration_buyer"] = buyer_nif

    # Risk scoring
    for nif, sr in seller_risk.items():
        score = 0.0
        # Cross-municipality breadth (log scale)
        mc = len(sr["municipalities"])
        if mc >= 10:
            score += 30
        elif mc >= 5:
            score += 20
        elif mc >= 3:
            score += 10
        # Total value
        if sr["total_value"] > 10_000_000:
            score += 25
        elif sr["total_value"] > 1_000_000:
            score += 15
        elif sr["total_value"] > 100_000:
            score += 5
        # Self-referencing (very suspicious)
        if sr["self_ref_count"] > 0:
            score += 40
        # Concentration
        if sr["concentration_max"] > 80:
            score += 20
        elif sr["concentration_max"] > 50:
            score += 10
        sr["risk_score"] = score

    # Sort by risk score
    ranked = sorted(seller_risk.items(), key=lambda x: -x[1]["risk_score"])

    if not ranked:
        print("\n  No data to analyze.")
        return

    print(f"\n  🎯 Risk Scoring Methodology:")
    print(f"     +30 pts: 10+ municipalities  |  +20: 5+  |  +10: 3+")
    print(f"     +25 pts: >€10M total  |  +15: >€1M  |  +5: >€100K")
    print(f"     +40 pts: self-referencing contracts")
    print(f"     +20 pts: >80% concentration  |  +10: >50%")

    print(f"\n  {'#':<4}{'Score':>6}{'Company':<35}{'NIF':<12}{'Municipalities':>14}{'Contracts':>10}{'Value':>16}{'Flags'}")
    print(f"  {'─'*4}{'─'*6}{'─'*35}{'─'*12}{'─'*14}{'─'*10}{'─'*16}{'─'*20}")

    for i, (nif, sr) in enumerate(ranked[:top_n], 1):
        mc = len(sr["municipalities"])
        flags = []
        if sr["self_ref_count"] > 0:
            flags.append("SELF-REF")
        if sr["concentration_max"] > 50:
            flags.append(f"CONC {sr['concentration_max']:.0f}%")
        flag_str = " ".join(flags)
        print(f"  {i:<4}{sr['risk_score']:>5.0f} {sr['name'][:35]:<35}{nif:<12}{mc:>14}{sr['contracts']:>10,}€{sr['total_value']:>14,.2f} {flag_str}")

    # Detail top 5
    print(f"\n  🔍 Detailed Risk Profiles — Top 5")
    for i, (nif, sr) in enumerate(ranked[:5], 1):
        mc = len(sr["municipalities"])
        print(f"\n  {'─'*100}")
        print(f"  #{i} [Score: {sr['risk_score']:.0f}] {sr['name'][:60]}")
        print(f"     NIF: {nif}  |  Municipalities: {mc}  |  Contracts: {sr['contracts']:,}  |  Total: €{sr['total_value']:,.2f}")
        if sr["self_ref_count"] > 0:
            print(f"     🚨 SELF-REFERENCING: {sr['self_ref_count']} contracts worth €{sr['self_ref_value']:,.2f}")
        if sr["concentration_max"] > 50:
            conc_buyer = sr["concentration_buyer"]
            print(f"     ⚠️  CONCENTRATION: {sr['concentration_max']:.1f}% of [{conc_buyer}] spending")


# =============================================================================
# CLI
# =============================================================================

# =============================================================================
# TEMPORAL CLUSTERING
# =============================================================================

def analyze_temporal(contract_index: Dict, window_days: int = 7):
    """Detect contracts clustered around the same date from the same seller.

    When many contracts from the same seller land on the same day or within
    a short window, it may indicate batch-awarding to favor a specific company.
    """
    print(f"\n{'='*110}")
    print(f"TEMPORAL CLUSTERING — Contracts Clustered Within {window_days} Days (Same Seller)")
    print(f"{'='*110}")

    # Group by seller NIF → date
    seller_dates: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    seller_names: Dict[str, str] = {}

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            winner_name = c.get("adjudicatario", "")
            data = c.get("data", "")
            if not winner_nif or not data:
                continue
            seller_dates[winner_nif][data[:10]].append({
                "buyer_nif": buyer_nif,
                "buyer_name": c.get("entity_name", buyer_nif),
                "valor": c.get("valor", 0) or 0,
                "tipo": c.get("tipo", ""),
                "objeto": c.get("objeto", ""),
                "date": data[:10],
            })
            seller_names[winner_nif] = winner_name

    # Find clusters: for each seller, find dates where many contracts land
    clusters = []
    for seller_nif, date_groups in seller_dates.items():
        sorted_dates = sorted(date_groups.keys())
        if len(sorted_dates) < 3:
            continue

        # Sliding window
        for i, start_date in enumerate(sorted_dates):
            window_contracts = []
            for j in range(i, len(sorted_dates)):
                # Simple day diff (works for YYYY-MM-DD)
                try:
                    d1 = datetime.strptime(start_date, "%Y-%m-%d")
                    d2 = datetime.strptime(sorted_dates[j], "%Y-%m-%d")
                    if (d2 - d1).days <= window_days:
                        window_contracts.extend(date_groups[sorted_dates[j]])
                    else:
                        break
                except ValueError:
                    # Fallback: just check same month
                    if sorted_dates[j][:7] == start_date[:7]:
                        window_contracts.extend(date_groups[sorted_dates[j]])
                    else:
                        break

            if len(window_contracts) >= 3:
                total_value = sum(c["valor"] for c in window_contracts)
                unique_buyers = len(set(c["buyer_nif"] for c in window_contracts))
                clusters.append({
                    "seller_nif": seller_nif,
                    "seller_name": seller_names[seller_nif],
                    "start_date": start_date,
                    "contracts": len(window_contracts),
                    "total_value": total_value,
                    "unique_buyers": unique_buyers,
                    "details": window_contracts[:5],
                })

    # Deduplicate: keep only the best window per seller
    best_per_seller: Dict[str, Dict] = {}
    for cl in clusters:
        sn = cl["seller_nif"]
        if sn not in best_per_seller or cl["contracts"] > best_per_seller[sn]["contracts"]:
            best_per_seller[sn] = cl

    sorted_clusters = sorted(best_per_seller.values(), key=lambda x: -x["contracts"])

    if not sorted_clusters:
        print("\n  No temporal clusters found.")
        return

    print(f"\n  ⏰ {len(sorted_clusters)} sellers with clustered contracts found")

    print(f"\n  {'#':<4}{'Seller':<35}{'Contracts':>10}{'Buyers':>8}{'Window Start':>14}{'Value':>16}")
    print(f"  {'─'*4}{'─'*35}{'─'*10}{'─'*8}{'─'*14}{'─'*16}")

    for i, cl in enumerate(sorted_clusters[:20], 1):
        print(f"  {i:<4}{cl['seller_name'][:35]:<35}{cl['contracts']:>10}{cl['unique_buyers']:>8}{cl['start_date']:>14}€{cl['total_value']:>14,.2f}")

    # Detail top 5
    print(f"\n  🔍 Detailed View — Top 5 Clusters")
    for i, cl in enumerate(sorted_clusters[:5], 1):
        print(f"\n  {'─'*100}")
        print(f"  #{i} {cl['seller_name'][:60]} (NIF: {cl['seller_nif']})")
        print(f"     {cl['contracts']} contracts in ≤{window_days} days starting {cl['start_date']}  |  €{cl['total_value']:,.2f}")
        for c in cl["details"]:
            print(f"    • [{c['date']}] €{c['valor']:,.2f} → {c['buyer_name'][:45]}")


# =============================================================================
# PRICE ANOMALY DETECTION
# =============================================================================

def analyze_price_anomaly(contract_index: Dict):
    """Detect suspicious pricing patterns.

    Flags:
    - Round-number contracts (exactly €10,000, €50,000, etc.)
    - Suspiciously similar values from same seller to same buyer
    - Contracts with zero or near-zero value
    """
    print(f"\n{'='*110}")
    print(f"PRICE ANOMALY DETECTION — Suspicious Pricing Patterns")
    print(f"{'='*110}")

    # 1. Round numbers
    round_contracts = []
    # 2. Similar values (same seller, same buyer, within 1%)
    similar_pairs: Dict[str, List[Dict]] = defaultdict(list)
    # 3. Zero-value
    zero_contracts = []

    for buyer_nif, contracts in contract_index.items():
        buyer_name = contracts[0].get("entity_name", buyer_nif) if contracts else buyer_nif
        for c in contracts:
            valor = c.get("valor", 0) or 0
            seller_nif = c.get("adjudicatario_nif", "")
            seller_name = c.get("adjudicatario", "")

            # Round number check (exact match only, avoid false positives)
            if valor > 0:
                is_round = False
                for base in [1000, 5000, 10000, 50000, 100000, 500000, 1000000]:
                    if abs(valor - base) < 0.01:
                        is_round = True
                        break
                if is_round:
                    round_contracts.append({
                        "buyer_nif": buyer_nif, "buyer_name": buyer_name,
                        "seller_nif": seller_nif, "seller_name": seller_name,
                        "valor": valor, "tipo": c.get("tipo", ""),
                        "objeto": c.get("objeto", ""), "data": c.get("data", ""),
                    })

            # Zero value
            if valor == 0 and seller_nif:
                zero_contracts.append({
                    "buyer_nif": buyer_nif, "buyer_name": buyer_name,
                    "seller_nif": seller_nif, "seller_name": seller_name,
                    "tipo": c.get("tipo", ""), "objeto": c.get("objeto", ""),
                    "data": c.get("data", ""),
                })

            # Similar values (group by seller+buyer)
            if valor > 0 and seller_nif:
                key = f"{buyer_nif}:{seller_nif}"
                similar_pairs[key].append({
                    "valor": valor, "buyer_name": buyer_name,
                    "seller_name": seller_name, "objeto": c.get("objeto", ""),
                    "data": c.get("data", ""),
                })

    # Find suspiciously similar values
    similar_alerts = []
    for key, pair_list in similar_pairs.items():
        if len(pair_list) < 2:
            continue
        # Check if any values are within 1% of each other
        for i in range(len(pair_list)):
            for j in range(i + 1, len(pair_list)):
                v1, v2 = pair_list[i]["valor"], pair_list[j]["valor"]
                if v1 > 0 and abs(v1 - v2) / max(v1, v2) < 0.01:
                    similar_alerts.append({
                        "buyer_name": pair_list[i]["buyer_name"],
                        "seller_name": pair_list[i]["seller_name"],
                        "v1": v1, "v2": v2,
                        "objeto1": pair_list[i]["objeto"],
                        "objeto2": pair_list[j]["objeto"],
                        "date1": pair_list[i]["data"],
                        "date2": pair_list[j]["data"],
                    })

    # Print results
    print(f"\n  🔢 Round-Number Contracts: {len(round_contracts)}")
    if round_contracts:
        round_value = sum(c["valor"] for c in round_contracts)
        print(f"  Total value: €{round_value:,.2f}")
        print(f"\n  {'#':<4}{'Buyer':<25}{'Seller':<25}{'Value':>14}{'Type'}")
        print(f"  {'─'*4}{'─'*25}{'─'*25}{'─'*14}{'─'*30}")
        # Sort by value desc, show top 15
        round_contracts.sort(key=lambda x: -x["valor"])
        for i, c in enumerate(round_contracts[:15], 1):
            print(f"  {i:<4}{c['buyer_name'][:25]:<25}{c['seller_name'][:25]:<25}€{c['valor']:>12,.2f}{c['tipo'][:30]}")

    print(f"\n  ⚪ Zero-Value Contracts: {len(zero_contracts)}")
    if zero_contracts:
        print(f"  (Contracts awarded at €0 — may indicate in-kind or undeclared value)")
        for i, c in enumerate(zero_contracts[:10], 1):
            print(f"  {i:<4}{c['buyer_name'][:30]:<30}{c['seller_name'][:30]:<30}[{c['data']}]")
            if c["objeto"]:
                print(f"       {c['objeto'][:70]}")

    # Deduplicate similar alerts
    seen = set()
    unique_similar = []
    for sa in similar_alerts:
        pair_key = (sa["buyer_name"], round(min(sa["v1"], sa["v2"]), 2))
        if pair_key not in seen:
            seen.add(pair_key)
            unique_similar.append(sa)

    print(f"\n  🔗 Suspiciously Similar Values (same buyer+seller, <1% diff): {len(unique_similar)}")
    if unique_similar:
        print(f"\n  {'#':<4}{'Buyer':<22}{'Seller':<22}{'Value 1':>14}{'Value 2':>14}{'Diff':>8}")
        print(f"  {'─'*4}{'─'*22}{'─'*22}{'─'*14}{'─'*14}{'─'*8}")
        for i, sa in enumerate(sorted(unique_similar, key=lambda x: -x["v1"])[:15], 1):
            diff = abs(sa["v1"] - sa["v2"])
            print(f"  {i:<4}{sa['buyer_name'][:22]:<22}{sa['seller_name'][:22]:<22}€{sa['v1']:>12,.2f}€{sa['v2']:>12,.2f}€{diff:>6,.0f}")


# =============================================================================
# FREGUESIA EXTRACTION
# =============================================================================

def load_freguesia_mapping() -> Dict[str, str]:
    """Load freguesia→municipality mapping."""
    if not FREGUESIA_MAPPING_FILE.exists():
        return {}
    with open(FREGUESIA_MAPPING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Remove metadata keys
    return {k: v for k, v in data.items() if not k.startswith("_")}


def analyze_freguesia(contract_index: Dict):
    """Extract freguesia names from contract descriptions and map to municipalities.

    Detects which municipalities are spending on specific parishes,
    which can reveal geographic spending patterns.
    """
    print(f"\n{'='*110}")
    print(f"FREGUESIA ATTRIBUTION — Contracts Linked to Parishes")
    print(f"{'='*110}")

    freguesia_map = load_freguesia_mapping()
    if not freguesia_map:
        print(f"\n  Error: freguesia_mapping.json not found at {FREGUESIA_MAPPING_FILE}")
        return

    print(f"  Loaded {len(freguesia_map)} freguesia→municipality mappings")

    # Parse freguesia mentions from contract objeto text
    freg_pattern = re.compile(
        r"(?:junta de freguesia|freguesia)\s+(?:de|do|da)\s+([\w\s-]{2,30}?)(?:\s*[,\.\-]|\s*$)",
        re.IGNORECASE
    )

    # Results: freguesia → {contracts, value, buyers, sellers}
    freg_data: Dict[str, Dict] = defaultdict(lambda: {
        "contracts": 0, "value": 0.0,
        "buyers": set(), "sellers": set(),
        "municipality": "", "examples": [],
    })

    total_parsed = 0
    for buyer_nif, contracts in contract_index.items():
        buyer_name = contracts[0].get("entity_name", buyer_nif) if contracts else buyer_nif
        for c in contracts:
            objeto = c.get("objeto", "") or ""
            valor = c.get("valor", 0) or 0
            seller_nif = c.get("adjudicatario_nif", "")
            seller_name = c.get("adjudicatario", "")

            matches = freg_pattern.findall(objeto)
            for match in matches:
                freg_name = match.strip().lower().rstrip(".")
                if len(freg_name) < 3:
                    continue
                total_parsed += 1
                fd = freg_data[freg_name]
                fd["contracts"] += 1
                fd["value"] += valor
                fd["buyers"].add(buyer_nif)
                if seller_nif:
                    fd["sellers"].add(seller_nif)
                fd["municipality"] = freguesia_map.get(freg_name, "")
                if len(fd["examples"]) < 3:
                    fd["examples"].append({
                        "buyer": buyer_name[:40],
                        "seller": seller_name[:30],
                        "valor": valor,
                        "objeto": objeto[:80],
                    })

    if not freg_data:
        print("\n  No freguesia mentions found in contract descriptions.")
        return

    print(f"  Found {total_parsed} freguesia mentions across {len(freg_data)} unique parishes")

    # Sort by value
    sorted_fregs = sorted(freg_data.items(), key=lambda x: -x[1]["value"])

    print(f"\n  {'#':<4}{'Freguesia':<25}{'Municipality':<20}{'Contracts':>10}{'Value':>16}{'Buyers':>8}")
    print(f"  {'─'*4}{'─'*25}{'─'*20}{'─'*10}{'─'*16}{'─'*8}")

    for i, (freg, fd) in enumerate(sorted_fregs[:25], 1):
        muni = fd["municipality"][:18] if fd["municipality"] else "(unknown)"
        print(f"  {i:<4}{freg:<25}{muni:<20}{fd['contracts']:>10}€{fd['value']:>14,.2f}{len(fd['buyers']):>8}")

    # Detail top 5
    print(f"\n  🔍 Detailed View — Top 5 Freguesias")
    for i, (freg, fd) in enumerate(sorted_fregs[:5], 1):
        muni = fd["municipality"] or "(unknown)"
        print(f"\n  {'─'*100}")
        print(f"  #{i} Freguesia de {freg.title()} → {muni}")
        print(f"     Contracts: {fd['contracts']}  |  Value: €{fd['value']:,.2f}  |  Unique buyers: {len(fd['buyers'])}")
        for ex in fd["examples"]:
            print(f"    • €{ex['valor']:,.2f}  {ex['buyer']} → {ex['seller']}")
            if ex["objeto"]:
                print(f"      {ex['objeto'][:70]}")


# =============================================================================
# HTML DASHBOARD GENERATOR
# =============================================================================

def generate_html(contract_index: Dict, output_path: str = ""):
    """Generate a self-contained HTML corruption detection report."""
    if not output_path:
        output_path = str(HTML_OUTPUT)

    # Collect all analysis results
    concentration_data = _collect_concentration(contract_index)
    self_ref_data = _collect_self_ref(contract_index)
    cross_muni_data = _collect_cross_municipality(contract_index)
    risk_data = _collect_risk(contract_index)

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Corruption Detection Report — Analisa.pt</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; line-height: 1.6; }}
  .header {{ background: linear-gradient(135deg, #1e293b, #334155); padding: 2rem; border-bottom: 2px solid #f59e0b; }}
  .header h1 {{ font-size: 1.8rem; color: #f59e0b; }}
  .header p {{ color: #94a3b8; margin-top: 0.5rem; }}
  .stats-bar {{ display: flex; gap: 1rem; padding: 1rem 2rem; background: #1e293b; flex-wrap: wrap; }}
  .stat {{ background: #334155; padding: 1rem 1.5rem; border-radius: 8px; min-width: 180px; }}
  .stat .value {{ font-size: 1.5rem; font-weight: 700; color: #f59e0b; }}
  .stat .label {{ font-size: 0.85rem; color: #94a3b8; }}
  .section {{ padding: 2rem; }}
  .section h2 {{ font-size: 1.3rem; color: #f59e0b; margin-bottom: 1rem; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th {{ background: #334155; padding: 0.75rem; text-align: left; color: #f59e0b; position: sticky; top: 0; }}
  td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid #1e293b; }}
  tr:hover {{ background: #1e293b; }}
  .flag {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
  .flag-critical {{ background: #dc2626; color: white; }}
  .flag-warning {{ background: #f59e0b; color: #0f172a; }}
  .flag-info {{ background: #3b82f6; color: white; }}
  .value {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .risk-bar {{ height: 8px; border-radius: 4px; background: #334155; display: inline-block; width: 100px; }}
  .risk-fill {{ height: 100%; border-radius: 4px; }}
  .footer {{ padding: 1rem 2rem; text-align: center; color: #64748b; font-size: 0.8rem; border-top: 1px solid #334155; }}
</style>
</head>
<body>
<div class="header">
  <h1>🛡️ Corruption Detection Report</h1>
  <p>Procurement anomaly analysis — {len(contract_index)} entities, {sum(len(v) for v in contract_index.values()):,} contracts</p>
</div>
<div class="stats-bar">
  <div class="stat"><div class="value">{concentration_data['count']}</div><div class="label">Concentration Alerts</div></div>
  <div class="stat"><div class="value">{self_ref_data['count']}</div><div class="label">Self-Referencing</div></div>
  <div class="stat"><div class="value">{cross_muni_data['count']}</div><div class="label">Cross-Municipality (3+)</div></div>
  <div class="stat"><div class="value">€{risk_data['total_value']/1e9:.1f}B</div><div class="label">Flagged Value</div></div>
</div>

<div class="section">
<h2>🚨 Self-Referencing Entities</h2>
<table>
<tr><th>#</th><th>Entity</th><th>NIF</th><th>Contracts</th><th class="value">Total Value</th><th>Flag</th></tr>
"""

    for i, sr in enumerate(self_ref_data["items"][:20], 1):
        html += f'<tr><td>{i}</td><td>{sr["name"][:50]}</td><td>{sr["nif"]}</td><td>{sr["count"]}</td><td class="value">€{sr["value"]:,.0f}</td><td><span class="flag flag-critical">SELF-REF</span></td></tr>\n'

    html += """</table>
</div>

<div class="section">
<h2>⚠️ Spending Concentration (>40%)</h2>
<table>
<tr><th>#</th><th>Buyer</th><th>Winner</th><th>Share</th><th>Contracts</th><th class="value">Value</th></tr>
"""

    for i, ca in enumerate(concentration_data["items"][:20], 1):
        flag_class = "flag-critical" if ca["share"] > 80 else "flag-warning"
        html += f'<tr><td>{i}</td><td>{ca["buyer"][:40]}</td><td>{ca["seller"][:35]}</td><td>{ca["share"]:.1f}%</td><td>{ca["contracts"]}</td><td class="value">€{ca["value"]:,.0f}</td><td><span class="flag {flag_class}">{ca["share"]:.0f}%</span></td></tr>\n'

    html += """</table>
</div>

<div class="section">
<h2>🌐 Cross-Municipality Dominance</h2>
<table>
<tr><th>#</th><th>Company</th><th>NIF</th><th>Municipalities</th><th>Contracts</th><th class="value">Total Value</th></tr>
"""

    for i, cm in enumerate(cross_muni_data["items"][:20], 1):
        html += f'<tr><td>{i}</td><td>{cm["name"][:45]}</td><td>{cm["nif"]}</td><td>{cm["municipalities"]}</td><td>{cm["contracts"]}</td><td class="value">€{cm["value"]:,.0f}</td></tr>\n'

    html += """</table>
</div>

<div class="section">
<h2>🎯 Risk Scoring</h2>
<table>
<tr><th>#</th><th>Score</th><th>Company</th><th>NIF</th><th>Municipalities</th><th class="value">Value</th><th>Flags</th></tr>
"""

    for i, rd in enumerate(risk_data["items"][:20], 1):
        score_pct = min(rd["score"] / 100 * 100, 100)
        color = "#dc2626" if rd["score"] >= 70 else "#f59e0b" if rd["score"] >= 40 else "#22c55e"
        flags = []
        if rd.get("self_ref", 0) > 0:
            flags.append('<span class="flag flag-critical">SELF-REF</span>')
        if rd.get("conc", 0) > 50:
            flags.append(f'<span class="flag flag-warning">{rd["conc"]:.0f}%</span>')
        html += f'<tr><td>{i}</td><td><div class="risk-bar"><div class="risk-fill" style="width:{score_pct}%;background:{color}"></div></div> {rd["score"]:.0f}</td><td>{rd["name"][:40]}</td><td>{rd["nif"]}</td><td>{rd["municipalities"]}</td><td class="value">€{rd["value"]:,.0f}</td><td>{" ".join(flags)}</td></tr>\n'

    html += f"""</table>
</div>

<div class="footer">
  Generated by contract_winner_analyzer.py — Analisa.pt Corruption Detection<br>
  Data: contratos2025.xlsx ({sum(len(v) for v in contract_index.values()):,} contracts)
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📄 HTML report generated: {output_path}")
    print(f"     File size: {len(html):,} bytes")


def _collect_concentration(contract_index: Dict) -> Dict:
    """Collect concentration data for HTML generation."""
    buyer_seller = defaultdict(lambda: defaultdict(lambda: {"name": "", "contracts": 0, "value": 0.0}))
    buyer_totals = defaultdict(lambda: {"name": "", "value": 0.0})
    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            if not wn: continue
            v = c.get("valor", 0) or 0
            buyer_seller[buyer_nif][wn]["name"] = c.get("adjudicatario", "")
            buyer_seller[buyer_nif][wn]["contracts"] += 1
            buyer_seller[buyer_nif][wn]["value"] += v
            buyer_totals[buyer_nif]["value"] += v
            if not buyer_totals[buyer_nif]["name"]:
                buyer_totals[buyer_nif]["name"] = c.get("entity_name", buyer_nif)
    items = []
    for bn, sellers in buyer_seller.items():
        tv = buyer_totals[bn]["value"]
        if tv <= 0: continue
        for sn, sd in sellers.items():
            share = (sd["value"] / tv) * 100
            if share >= 40:
                items.append({"buyer": buyer_totals[bn]["name"], "seller": sd["name"],
                             "share": share, "contracts": sd["contracts"], "value": sd["value"]})
    items.sort(key=lambda x: -x["value"])
    return {"count": len(items), "items": items}


def _collect_self_ref(contract_index: Dict) -> Dict:
    """Collect self-referencing data for HTML generation."""
    by_nif = defaultdict(lambda: {"name": "", "count": 0, "value": 0.0})
    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            if wn and wn == buyer_nif:
                by_nif[wn]["name"] = c.get("entity_name", buyer_nif)
                by_nif[wn]["count"] += 1
                by_nif[wn]["value"] += (c.get("valor", 0) or 0)
    items = [{"nif": nif, **d} for nif, d in sorted(by_nif.items(), key=lambda x: -x[1]["value"])]
    return {"count": len(items), "items": items}


def _collect_cross_municipality(contract_index: Dict) -> Dict:
    """Collect cross-municipality data for HTML generation."""
    sellers = defaultdict(lambda: {"name": "", "municipalities": set(), "contracts": 0, "value": 0.0})
    for bn, contracts in contract_index.items():
        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            if not wn: continue
            s = sellers[wn]
            s["name"] = c.get("adjudicatario", "")
            s["municipalities"].add(bn)
            s["contracts"] += 1
            s["value"] += (c.get("valor", 0) or 0)
    items = [{"nif": n, "name": d["name"], "municipalities": len(d["municipalities"]),
              "contracts": d["contracts"], "value": d["value"]}
             for n, d in sellers.items() if len(d["municipalities"]) >= 3]
    items.sort(key=lambda x: -x["value"])
    return {"count": len(items), "items": items}


def _collect_risk(contract_index: Dict) -> Dict:
    """Collect risk scoring data for HTML generation."""
    sellers = defaultdict(lambda: {"name": "", "municipalities": set(), "contracts": 0,
                                   "value": 0.0, "self_ref": 0, "conc": 0.0})
    buyer_totals = defaultdict(float)
    buyer_seller_v = defaultdict(lambda: defaultdict(float))
    for bn, contracts in contract_index.items():
        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            if not wn: continue
            v = c.get("valor", 0) or 0
            buyer_totals[bn] += v
            buyer_seller_v[bn][wn] += v
            s = sellers[wn]
            s["name"] = c.get("adjudicatario", "")
            s["municipalities"].add(bn)
            s["contracts"] += 1
            s["value"] += v
            if wn == bn: s["self_ref"] += 1
    for bn, sv in buyer_seller_v.items():
        t = buyer_totals[bn]
        if t <= 0: continue
        for sn, val in sv.items():
            share = (val / t) * 100
            if share > sellers[sn]["conc"]: sellers[sn]["conc"] = share
    items = []
    for n, s in sellers.items():
        score = 0.0
        mc = len(s["municipalities"])
        if mc >= 10: score += 30
        elif mc >= 5: score += 20
        elif mc >= 3: score += 10
        if s["value"] > 10_000_000: score += 25
        elif s["value"] > 1_000_000: score += 15
        elif s["value"] > 100_000: score += 5
        if s["self_ref"] > 0: score += 40
        if s["conc"] > 80: score += 20
        elif s["conc"] > 50: score += 10
        if score > 0:
            items.append({"nif": n, "name": s["name"], "score": score,
                         "municipalities": mc, "contracts": s["contracts"],
                         "value": s["value"], "self_ref": s["self_ref"], "conc": s["conc"]})
    items.sort(key=lambda x: -x["score"])
    total = sum(i["value"] for i in items)
    return {"count": len(items), "total_value": total, "items": items}


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Contract Winner Analyzer — Corruption Pattern Detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Full analysis (all patterns)
  %(prog)s concentration --threshold 30 # Find concentration >30%%
  %(prog)s self-ref                     # Self-referencing entities
  %(prog)s cross-municipality --min 5   # Companies in 5+ municipalities
  %(prog)s suspicious --top 10          # Combined risk scoring
  %(prog)s temporal --window 7          # Temporal clustering (7-day window)
  %(prog)s price-anomaly               # Price anomaly detection
  %(prog)s freguesia                   # Freguesia attribution
  %(prog)s html                        # Generate HTML dashboard
        """,
    )
    sub = parser.add_subparsers(dest="command")

    conc_p = sub.add_parser("concentration", help="Spending concentration analysis")
    conc_p.add_argument("--threshold", "-t", type=float, default=40.0,
                        help="Minimum concentration %% (default 40)")

    sub.add_parser("self-ref", help="Self-referencing entity detection")

    cross_p = sub.add_parser("cross-municipality", help="Cross-municipality dominance")
    cross_p.add_argument("--min", "-m", type=int, default=3,
                         help="Minimum municipalities (default 3)")

    susp_p = sub.add_parser("suspicious", help="Combined risk scoring")
    susp_p.add_argument("--top", "-n", type=int, default=20,
                        help="Show top N results (default 20)")

    temp_p = sub.add_parser("temporal", help="Temporal clustering detection")
    temp_p.add_argument("--window", "-w", type=int, default=7,
                        help="Window size in days (default 7)")

    sub.add_parser("price-anomaly", help="Price anomaly detection")
    sub.add_parser("freguesia", help="Freguesia attribution from contracts")

    html_p = sub.add_parser("html", help="Generate HTML dashboard report")
    html_p.add_argument("--output", "-o", default="", help="Output HTML path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    contract_index = load_contract_index()
    if not contract_index:
        return

    if args.command == "concentration":
        analyze_concentration(contract_index, threshold=args.threshold)
    elif args.command == "self-ref":
        analyze_self_referencing(contract_index)
    elif args.command == "cross-municipality":
        analyze_cross_municipality(contract_index, min_municipalities=args.min)
    elif args.command == "suspicious":
        analyze_suspicious(contract_index, top_n=args.top)
    elif args.command == "temporal":
        analyze_temporal(contract_index, window_days=args.window)
    elif args.command == "price-anomaly":
        analyze_price_anomaly(contract_index)
    elif args.command == "freguesia":
        analyze_freguesia(contract_index)
    elif args.command == "html":
        generate_html(contract_index, output_path=args.output)


if __name__ == "__main__":
    main()
