#!/usr/bin/env python3
"""Freguesia Contract Analyzer — Parish-Level Procurement Analysis

Analyzes public procurement contracts at the freguesia (parish) level to
detect spending patterns, seller dominance, and cross-parish anomalies.

Uses procurement.db directly (with ine_* columns from freguesia_resolver.py).

Usage:
    # Top parishes by spending
    python freguesia_contract_analyzer.py spending --top 30

    # Sellers dominating parish procurement
    python freguesia_contract_analyzer.py sellers --min-contracts 5

    # Cross-parish patterns (same seller in multiple parishes)
    python freguesia_contract_analyzer.py cross-parish --min-parishes 3

    # Freguesia entities as buyers (juntas de freguesia)
    python freguesia_contract_analyzer.py entities --top 30

    # Corruption patterns at freguesia level
    python freguesia_contract_analyzer.py corruption

    # Full analysis
    python freguesia_contract_analyzer.py all
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "data" / "procurement.db"
FREGUESIA_MAP = SCRIPT_DIR / "data" / "freguesia_mapping.json"

# Import shared utilities (avoids code duplication)
sys.path.insert(0, str(SCRIPT_DIR))
from utils import fmt as _fmt, parse_entity_field
from utils_db import connect as db_connect


# =============================================================================
# HELPERS
# =============================================================================

def _is_freguesia(name: str) -> bool:
    """Check if an entity name is a freguesia."""
    if not name:
        return False
    nl = name.lower()
    return any(p in nl for p in ["freguesia", "junta de freguesia", "união das freguesias"])


def _extract_parish_name(name: str) -> str:
    """Extract the parish name from a full entity name."""
    for prefix in ["Freguesia de ", "Freguesia do ", "Freguesia da ",
                    "Junta de Freguesia de ", "Junta de Freguesia do ",
                    "Junta de Freguesia da ", "União das Freguesias de ",
                    "União das Freguesias do ", "União das Freguesias da "]:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _parse_adjudicatarios(text: str) -> List[Dict[str, str]]:
    """Parse 'NIF - Name; NIF2 - Name2' format into list of dicts.

    Delegates to utils.parse_entity_field for consistency.
    """
    return parse_entity_field(text)


def _has_ine_columns(conn: sqlite3.Connection) -> bool:
    """Check if ine_* columns exist in contratos table."""
    try:
        conn.execute("SELECT ine_municipality FROM contratos LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


# =============================================================================
# DATA LOADING — from procurement.db
# =============================================================================

def get_db() -> sqlite3.Connection:
    """Open procurement.db."""
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)
    conn = db_connect(str(DB_PATH))
    return conn


def load_contracts_by_municipality(conn: sqlite3.Connection) -> Dict[str, Dict]:
    """Load all contracts grouped by resolved municipality (ine_municipality).

    Returns dict keyed by municipality name with contract data.
    """
    rows = conn.execute("""
        SELECT idcontrato, adjudicante_nif, adjudicante_nome,
               adjudicatarios, precoContratual, precoBaseProcedimento,
               PrecoTotalEfetivo, tipoprocedimento, tipoContrato, CPV,
               ine_district, ine_municipality, ine_freguesia, ine_code
        FROM contratos
        WHERE ine_municipality IS NOT NULL AND ine_municipality != ''
        AND precoContratual > 0
    """).fetchall()

    # Group by municipality
    munis: Dict[str, Dict] = defaultdict(lambda: {
        "code": "", "name": "", "contracts": 0, "total_value": 0.0,
        "sellers": set(), "inflated": 0, "direct_award": 0,
        "freguesias": set(), "buyer_nifs": set(),
    })

    for r in rows:
        muni = r["ine_municipality"]
        code = (r["ine_code"] or "")[:4]
        mu = munis[muni]
        mu["code"] = code
        mu["name"] = muni
        mu["contracts"] += 1
        mu["total_value"] += r["precoContratual"] or 0
        mu["buyer_nifs"].add(r["adjudicante_nif"] or "")

        if r["ine_freguesia"]:
            mu["freguesias"].add(r["ine_freguesia"])

        # Price inflation check
        base = r["precoBaseProcedimento"] or 0
        final = r["precoContratual"] or 0
        if base > 0 and final > base * 1.05:
            mu["inflated"] += 1

        # Direct award check
        proc = (r["tipoprocedimento"] or "").lower()
        if "ajuste direto" in proc or "procedimento direto" in proc:
            mu["direct_award"] += 1

        # Extract sellers
        sellers = _parse_adjudicatarios(r["adjudicatarios"])
        for s in sellers:
            mu["sellers"].add(s["nif"])

    return dict(munis)


def load_contracts_by_freguesia_entity(conn: sqlite3.Connection) -> Dict[str, Dict]:
    """Load contracts WHERE the buyer is a freguesia entity (junta de freguesia).

    Groups by buyer NIF.
    """
    rows = conn.execute("""
        SELECT idcontrato, adjudicante_nif, adjudicante_nome,
               adjudicatarios, precoContratual, precoBaseProcedimento,
               tipoprocedimento, CPV
        FROM contratos
        WHERE adjudicante_nome IS NOT NULL
        AND (adjudicante_nome LIKE '%Freguesia%'
             OR adjudicante_nome LIKE '%Junta de Freguesia%'
             OR adjudicante_nome LIKE '%União das Freguesias%')
        AND precoContratual > 0
    """).fetchall()

    parishes: Dict[str, Dict] = defaultdict(lambda: {
        "nif": "", "name": "", "parish_name": "", "municipality": "",
        "contracts": 0, "total_value": 0.0, "sellers": set(),
        "inflated": 0, "direct_award": 0,
    })

    for r in rows:
        nif = r["adjudicante_nif"]
        name = r["adjudicante_nome"]
        pd = parishes[nif]
        pd["nif"] = nif
        pd["name"] = name
        pd["parish_name"] = _extract_parish_name(name)
        pd["contracts"] += 1
        pd["total_value"] += r["precoContratual"] or 0

        # Price inflation
        base = r["precoBaseProcedimento"] or 0
        final = r["precoContratual"] or 0
        if base > 0 and final > base * 1.05:
            pd["inflated"] += 1

        # Direct award
        proc = (r["tipoprocedimento"] or "").lower()
        if "ajuste direto" in proc:
            pd["direct_award"] += 1

        # Sellers
        sellers = _parse_adjudicatarios(r["adjudicatarios"])
        for s in sellers:
            pd["sellers"].add(s["nif"])

    # Try to resolve municipality from freguesia_mapping
    freg_map = {}
    if FREGUESIA_MAP.exists():
        try:
            with open(FREGUESIA_MAP) as f:
                freg_map = json.load(f)
        except Exception:
            pass

    for nif, pd in parishes.items():
        norm = pd["parish_name"].lower()
        pd["municipality"] = freg_map.get(norm, "")

    return dict(parishes)


def load_seller_parish_network(conn: sqlite3.Connection) -> Dict[str, Dict]:
    """Build seller → parish buyer network from resolved contracts."""
    rows = conn.execute("""
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
               precoContratual, ine_municipality, ine_freguesia
        FROM contratos
        WHERE ine_municipality IS NOT NULL AND ine_municipality != ''
        AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
        AND precoContratual > 0
    """).fetchall()

    network: Dict[str, Dict] = defaultdict(lambda: {
        "name": "", "parishes": set(), "municipalities": set(),
        "contracts": 0, "total_value": 0.0,
        "parish_details": defaultdict(lambda: {"name": "", "contracts": 0, "value": 0.0}),
    })

    for r in rows:
        sellers = _parse_adjudicatarios(r["adjudicatarios"])
        muni = r["ine_municipality"]
        freg = r["ine_freguesia"] or ""
        buyer_nif = r["adjudicante_nif"]
        value = r["precoContratual"] or 0

        for s in sellers:
            nif = s["nif"]
            net = network[nif]
            net["name"] = s["name"]
            net["parishes"].add(buyer_nif)
            net["municipalities"].add(muni)
            net["contracts"] += 1
            net["total_value"] += value
            key = f"{buyer_nif}|{muni}"
            net["parish_details"][key]["name"] = f"{freg} ({muni})" if freg else muni
            net["parish_details"][key]["contracts"] += 1
            net["parish_details"][key]["value"] += value

    return dict(network)


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================

def analyze_spending_by_municipality(conn: sqlite3.Connection, top_n: int = 30):
    """Top municipalities by contract value (resolved via ine_municipality)."""
    # Check columns BEFORE loading data
    if not _has_ine_columns(conn):
        print("\n  ⚠️  ine_* columns not found in contratos table.")
        print("  Run: python freguesia_resolver.py update")
        print("  This resolves LocalExecucao → municipality/freguesia codes.")
        return

    munis = load_contracts_by_municipality(conn)

    if not munis:
        print("\n  No resolved municipality data.")
        return

    sorted_munis = sorted(munis.values(), key=lambda x: -x["total_value"])
    total_value = sum(m["total_value"] for m in sorted_munis)
    total_contracts = sum(m["contracts"] for m in sorted_munis)

    print(f"\n{'='*120}")
    print(f"MUNICIPALITY SPENDING — Top {top_n} by Contract Value (from {len(munis)} resolved)")
    print(f"{'='*120}")
    print(f"  Total value: {_fmt(total_value)}  |  Total contracts: {total_contracts:,}")

    print(f"\n  {'#':<4}{'Municipality':<30}{'Code':<8}{'Contracts':>10}{'Value':>14}{'Sellers':>8}{'Inflated':>9}{'Direct%':>8}")
    print(f"  {'─'*4}{'─'*30}{'─'*8}{'─'*10}{'─'*14}{'─'*8}{'─'*9}{'─'*8}")

    for i, m in enumerate(sorted_munis[:top_n], 1):
        direct_pct = m["direct_award"] * 100 / m["contracts"] if m["contracts"] else 0
        print(f"  {i:<4}{m['name'][:28]:<30}{m['code']:<8}{m['contracts']:>10}{_fmt(m['total_value']):>14}{len(m['sellers']):>8}{m['inflated']:>9}{direct_pct:>7.1f}%")


def analyze_parish_entities(conn: sqlite3.Connection, top_n: int = 30):
    """Analyze freguesia entities as buyers."""
    parishes = load_contracts_by_freguesia_entity(conn)

    if not parishes:
        print("\n  No freguesia entity contracts found.")
        return

    sorted_parishes = sorted(parishes.values(), key=lambda x: -x["total_value"])
    total_value = sum(p["total_value"] for p in sorted_parishes)

    print(f"\n{'='*120}")
    print(f"FREGUESIA ENTITIES — Parish Buyers ({len(parishes)} parishes, {_fmt(total_value)} total)")
    print(f"{'='*120}")

    print(f"\n  {'#':<4}{'Parish':<35}{'Municipality':<20}{'Contracts':>10}{'Value':>14}{'Sellers':>8}{'Inflated':>9}")
    print(f"  {'─'*4}{'─'*35}{'─'*20}{'─'*10}{'─'*14}{'─'*8}{'─'*9}")

    for i, p in enumerate(sorted_parishes[:top_n], 1):
        parish = p["parish_name"][:33]
        muni = p["municipality"][:18] or "(unknown)"
        print(f"  {i:<4}{parish:<35}{muni:<20}{p['contracts']:>10}{_fmt(p['total_value']):>14}{len(p['sellers']):>8}{p['inflated']:>9}")


def analyze_sellers_in_parishes(conn: sqlite3.Connection, min_contracts: int = 5):
    """Sellers dominating freguesia procurement."""
    network = load_seller_parish_network(conn)

    # Filter to only sellers with parish buyers
    sellers = [(nif, d) for nif, d in network.items()
               if d["contracts"] >= min_contracts and len(d["parishes"]) >= 2]
    sellers.sort(key=lambda x: -x[1]["total_value"])

    if not sellers:
        print(f"\n  No sellers with {min_contracts}+ parish contracts found.")
        return

    total_value = sum(d["total_value"] for _, d in sellers)

    print(f"\n{'='*120}")
    print(f"PARISH SELLERS — Companies in {len(sellers)} Multi-Parish Networks ({_fmt(total_value)} total)")
    print(f"{'='*120}")

    print(f"\n  {'#':<4}{'Seller':<35}{'NIF':<12}{'Parishes':>8}{'Munis':>7}{'Contracts':>10}{'Value':>14}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*8}{'─'*7}{'─'*10}{'─'*14}")

    for i, (nif, d) in enumerate(sellers[:25], 1):
        print(f"  {i:<4}{d['name'][:33]:<35}{nif:<12}{len(d['parishes']):>8}{len(d['municipalities']):>7}{d['contracts']:>10}{_fmt(d['total_value']):>14}")

    # Detail top 5
    print(f"\n  🔍 Top 5 Cross-Parish Sellers — Detail")
    for i, (nif, d) in enumerate(sellers[:5], 1):
        print(f"\n  {'─'*110}")
        print(f"  #{i} {d['name'][:60]} (NIF: {nif})")
        print(f"     Parishes: {len(d['parishes'])}  |  Municipalities: {len(d['municipalities'])}  |  Contracts: {d['contracts']:,}  |  Total: {_fmt(d['total_value'])}")
        sorted_pd = sorted(d["parish_details"].items(), key=lambda x: -x[1]["value"])
        for key, pd in sorted_pd[:8]:
            print(f"       {pd['name'][:45]:<45} {pd['contracts']:>5} contracts  {_fmt(pd['value']):>14}")
        if len(sorted_pd) > 8:
            print(f"       ... and {len(sorted_pd) - 8} more")


def analyze_cross_municipality(conn: sqlite3.Connection, min_munis: int = 3):
    """Sellers operating across multiple municipalities."""
    network = load_seller_parish_network(conn)

    multi = [(nif, d) for nif, d in network.items()
             if len(d["municipalities"]) >= min_munis]
    multi.sort(key=lambda x: -x[1]["total_value"])

    if not multi:
        print(f"\n  No sellers found in {min_munis}+ municipalities.")
        return

    total_value = sum(d["total_value"] for _, d in multi)

    print(f"\n{'='*120}")
    print(f"CROSS-MUNICIPALITY — {len(multi)} Sellers in {min_munis}+ Municipalities ({_fmt(total_value)} total)")
    print(f"{'='*120}")

    print(f"\n  {'#':<4}{'Seller':<35}{'NIF':<12}{'Municipalities':>14}{'Contracts':>10}{'Value':>14}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*14}{'─'*10}{'─'*14}")

    for i, (nif, d) in enumerate(multi[:25], 1):
        print(f"  {i:<4}{d['name'][:33]:<35}{nif:<12}{len(d['municipalities']):>14}{d['contracts']:>10}{_fmt(d['total_value']):>14}")


def analyze_corruption_patterns(conn: sqlite3.Connection):
    """Detect corruption patterns at freguesia/parish level.

    Signals:
    - Concentration: >60% top-3 sellers
    - Price inflation: >10% avg overrun
    - Self-referencing: buyer NIF in seller list
    - Direct award excess: >50% ajuste direto
    """
    print(f"\n{'='*120}")
    print(f"CORRUPTION PATTERNS — Freguesia-Level Analysis")
    print(f"{'='*120}")

    # Check columns first
    if not _has_ine_columns(conn):
        print("\n  ⚠️  ine_* columns not found in contratos table.")
        print("  Run: python freguesia_resolver.py update")
        print("  This resolves LocalExecucao → municipality/freguesia codes.")
        return

    # Load all contracts with resolved municipality
    rows = conn.execute("""
        SELECT idcontrato, adjudicante_nif, adjudicante_nome,
               adjudicatarios, precoContratual, precoBaseProcedimento,
               tipoprocedimento, ine_municipality, ine_freguesia
        FROM contratos
        WHERE ine_municipality IS NOT NULL AND ine_municipality != ''
        AND precoContratual > 0
    """).fetchall()

    if not rows:
        print("\n  No contracts with resolved municipality data.")
        return

    # Group by (municipality, freguesia) or just municipality
    groups: Dict[str, Dict] = defaultdict(lambda: {
        "municipality": "", "freguesia": "", "contracts": 0,
        "total_value": 0.0, "sellers": defaultdict(float),
        "inflated": 0, "direct_award": 0, "self_ref": 0,
        "self_ref_set": set(), "buyer_nifs": set(),
    })

    for r in rows:
        muni = r["ine_municipality"]
        freg = r["ine_freguesia"] or ""
        key = f"{muni}|{freg}" if freg else muni

        g = groups[key]
        g["municipality"] = muni
        g["freguesia"] = freg
        g["contracts"] += 1
        g["total_value"] += r["precoContratual"] or 0
        g["buyer_nifs"].add(r["adjudicante_nif"] or "")

        # Price inflation
        base = r["precoBaseProcedimento"] or 0
        final = r["precoContratual"] or 0
        if base > 0 and final > base * 1.10:
            g["inflated"] += 1

        # Direct award
        proc = (r["tipoprocedimento"] or "").lower()
        if "ajuste direto" in proc:
            g["direct_award"] += 1

        # Sellers + self-referencing (track unique NIFs only)
        sellers = _parse_adjudicatarios(r["adjudicatarios"])
        for s in sellers:
            g["sellers"][s["nif"]] += r["precoContratual"] or 0
            if s["nif"] in g["buyer_nifs"] and s["nif"] not in g["self_ref_set"]:
                g["self_ref_set"].add(s["nif"])
                g["self_ref"] += 1

    # Score each group
    flagged = []
    for key, g in groups.items():
        if g["contracts"] < 3:
            continue

        signals = []
        score = 0

        # Concentration: top-3 seller share
        sorted_sellers = sorted(g["sellers"].items(), key=lambda x: -x[1])
        top3_value = sum(v for _, v in sorted_sellers[:3])
        top3_pct = top3_value / g["total_value"] * 100 if g["total_value"] else 0
        if top3_pct >= 60:
            signals.append(f"concentration {top3_pct:.0f}%")
            score += min(35, int(top3_pct / 2))

        # Price inflation
        inflation_rate = g["inflated"] / g["contracts"] * 100 if g["contracts"] else 0
        if inflation_rate >= 10:
            signals.append(f"inflation {inflation_rate:.0f}%")
            score += min(30, int(inflation_rate))

        # Direct award excess
        direct_rate = g["direct_award"] / g["contracts"] * 100 if g["contracts"] else 0
        if direct_rate >= 50:
            signals.append(f"direct {direct_rate:.0f}%")
            score += min(15, int(direct_rate / 5))

        # Self-referencing (unique NIFs)
        if g["self_ref"] > 0:
            signals.append(f"self-ref {g['self_ref']}")
            score += min(25, g["self_ref"] * 10)

        if signals and score >= 20:
            flagged.append({
                **g,
                "score": min(100, score),
                "signals": signals,
                "top3_pct": top3_pct,
                "top_sellers": sorted_sellers[:5],
            })

    flagged.sort(key=lambda x: -x["score"])

    if not flagged:
        print("\n  No freguesia-level corruption patterns detected.")
        print("  (Requires ine_* columns — run 'freguesia_resolver.py update')")
        return

    print(f"\n  🚨 {len(flagged)} freguesias/municipalities flagged")

    print(f"\n  {'#':<4}{'Location':<40}{'Score':>6}{'Contracts':>10}{'Value':>14}{'Signals'}")
    print(f"  {'─'*4}{'─'*40}{'─'*6}{'─'*10}{'─'*14}{'─'*40}")

    for i, f in enumerate(flagged[:30], 1):
        loc = f"{f['freguesia']} ({f['municipality']})" if f["freguesia"] else f["municipality"]
        signals_str = ", ".join(f["signals"])
        print(f"  {i:<4}{loc[:38]:<40}{f['score']:>6}{f['contracts']:>10}{_fmt(f['total_value']):>14}  {signals_str}")

    # Detail top 5
    print(f"\n  🔍 Top 5 Flagged — Detail")
    for i, f in enumerate(flagged[:5], 1):
        print(f"\n  {'─'*110}")
        loc = f"{f['freguesia']}, {f['municipality']}" if f["freguesia"] else f["municipality"]
        print(f"  #{i} {loc} — Risk Score: {f['score']}/100")
        print(f"     Contracts: {f['contracts']:,}  |  Total: {_fmt(f['total_value'])}  |  Top-3 share: {f['top3_pct']:.0f}%")
        print(f"     Signals: {', '.join(f['signals'])}")
        for nif, value in f["top_sellers"]:
            print(f"       Top seller: NIF {nif} — {_fmt(value)}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Freguesia Contract Analyzer — Parish-Level Procurement Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s spending --top 30          # Top municipalities by spending
  %(prog)s entities --top 30          # Freguesia entities as buyers
  %(prog)s sellers --min-contracts 5  # Sellers dominating parishes
  %(prog)s cross-parish --min-parishes 3  # Cross-parish patterns
  %(prog)s corruption                 # Corruption patterns at parish level
  %(prog)s all                        # Full analysis
        """,
    )
    sub = parser.add_subparsers(dest="command")

    spend_p = sub.add_parser("spending", help="Top municipalities by spending (resolved)")
    spend_p.add_argument("--top", "-t", type=int, default=30)

    entity_p = sub.add_parser("entities", help="Freguesia entities as buyers")
    entity_p.add_argument("--top", "-t", type=int, default=30)

    seller_p = sub.add_parser("sellers", help="Sellers dominating parish procurement")
    seller_p.add_argument("--min-contracts", "-m", type=int, default=5)

    cross_p = sub.add_parser("cross-parish", help="Cross-municipality seller patterns")
    cross_p.add_argument("--min-parishes", "-p", type=int, default=3)

    sub.add_parser("corruption", help="Corruption patterns at freguesia level")

    sub.add_parser("all", help="Full analysis")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    conn = get_db()

    # Check ine_* columns once before any mode runs
    if args.command in ("spending", "sellers", "cross-parish", "corruption", "all"):
        if not _has_ine_columns(conn):
            print("\n  ⚠️  ine_* columns not found in contratos table.")
            print("  Run: python freguesia_resolver.py update")
            print("  This resolves LocalExecucao → municipality/freguesia codes.")
            conn.close()
            return

    try:
        if args.command == "spending":
            analyze_spending_by_municipality(conn, top_n=args.top)
        elif args.command == "entities":
            analyze_parish_entities(conn, top_n=args.top)
        elif args.command == "sellers":
            analyze_sellers_in_parishes(conn, min_contracts=args.min_contracts)
        elif args.command == "cross-parish":
            analyze_cross_municipality(conn, min_munis=args.min_parishes)
        elif args.command == "corruption":
            analyze_corruption_patterns(conn)
        elif args.command == "all":
            analyze_spending_by_municipality(conn, top_n=20)
            analyze_parish_entities(conn, top_n=20)
            analyze_sellers_in_parishes(conn, min_contracts=5)
            analyze_cross_municipality(conn, min_munis=3)
            analyze_corruption_patterns(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
