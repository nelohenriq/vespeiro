#!/usr/bin/env python3
"""Debt Checker — Cross-reference contract winners with public debt lists.

Checks if companies winning public contracts appear on Portugal's public
debt lists (AT tax debts + Segurança Social debts). Companies with
significant public debt winning public contracts is a red flag for
corruption risk.

Data Sources:
- AT (Autoridade Tributária): Public list of tax debtors
- Segurança Social: Public list of social security debtors
- contract_index.json: Contract winners (adjudicatário)

Usage:
    python debt_checker.py build           # Download and parse debt lists
    python debt_checker.py check           # Cross-reference winners with debts
    python debt_checker.py check --nif 500014872  # Check specific NIF
    python debt_checker.py stats           # Summary statistics
"""

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

SCRIPT_DIR = Path(__file__).parent
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
DEBT_CACHE = SCRIPT_DIR / "data" / "debt_lists.json"
CROSSREF_OUTPUT = SCRIPT_DIR / "data" / "debt_crossref.json"

# Public debt list URLs (these are public government portals)
AT_DEBT_URL = "https://www.portaldasfinancas.gov.pt/pt/contribuintes/declaracoes/Pages/lista-devedores.aspx"
SS_DEBT_URL = "https://www.seg-social.pt/ptss/sef/lista-devedores/consulta-lista-devedores"


# =============================================================================
# DATA LOADING
# =============================================================================

def load_contract_index() -> Dict[str, List[Dict]]:
    """Load contract_index.json."""
    if not CONTRACT_INDEX.exists():
        print(f"Error: {CONTRACT_INDEX} not found", file=sys.stderr)
        return {}
    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        return json.load(f)


def load_debt_cache() -> Dict:
    """Load cached debt lists."""
    if not DEBT_CACHE.exists():
        return {"at_debts": {}, "ss_debts": {}, "last_updated": None}
    with open(DEBT_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_debt_cache(data: Dict):
    """Save debt lists to cache."""
    DEBT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(DEBT_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================================================================
# DEBT LIST PARSING
# =============================================================================

def try_download_at_debts() -> Dict[str, Dict]:
    """Try to download AT tax debt list.

    The AT portal publishes a public list of significant tax debtors.
    This function attempts to fetch and parse it.
    """
    print("  Attempting to fetch AT tax debt list...", file=sys.stderr)

    try:
        req = urllib.request.Request(AT_DEBT_URL, headers={
            "User-Agent": "Mozilla/5.0 (compatible; analisa-pt/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Try to find NIF patterns in the HTML
        nif_pattern = re.compile(r'\b(\d{9})\b')
        nifs_found = set(nif_pattern.findall(html))

        # Try to extract structured data (NIF + Name pairs)
        # The AT list typically has: NIF | Name | Debt Amount | Municipality
        debt_entries = {}
        # Look for table rows with NIF patterns
        row_pattern = re.compile(
            r'(\d{9})\s*[|\-]\s*([A-ZÁÉÍÓÚÃÕÊÔ][\w\s,\.]+?)(?:\s*[|\-]\s*([\d\.,]+))?',
            re.IGNORECASE
        )
        for match in row_pattern.finditer(html):
            nif = match.group(1)
            name = match.group(2).strip()
            amount_str = match.group(3) or "0"
            # Parse amount
            amount = 0
            if amount_str:
                amount_str = amount_str.replace(".", "").replace(",", ".")
                try:
                    amount = float(amount_str)
                except ValueError:
                    pass
            debt_entries[nif] = {
                "nif": nif,
                "name": name,
                "amount": amount,
                "source": "AT",
            }

        if debt_entries:
            print(f"  Found {len(debt_entries)} AT debt entries", file=sys.stderr)
        else:
            print(f"  AT portal returned HTML but no structured debt data parsed", file=sys.stderr)
            print(f"  (The list may require JavaScript rendering or manual download)", file=sys.stderr)

        return debt_entries

    except Exception as e:
        print(f"  AT download failed: {e}", file=sys.stderr)
        return {}


def try_download_ss_debts() -> Dict[str, Dict]:
    """Try to download Segurança Social debt list.

    The SS portal publishes a public list of social security debtors.
    """
    print("  Attempting to fetch SS debt list...", file=sys.stderr)

    try:
        req = urllib.request.Request(SS_DEBT_URL, headers={
            "User-Agent": "Mozilla/5.0 (compatible; analisa-pt/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Try to extract debt entries
        nif_pattern = re.compile(r'\b(\d{9})\b')
        nifs_found = set(nif_pattern.findall(html))

        debt_entries = {}
        row_pattern = re.compile(
            r'(\d{9})\s*[|\-]\s*([A-ZÁÉÍÓÚÃÕÊÔ][\w\s,\.]+?)(?:\s*[|\-]\s*([\d\.,]+))?',
            re.IGNORECASE
        )
        for match in row_pattern.finditer(html):
            nif = match.group(1)
            name = match.group(2).strip()
            amount_str = match.group(3) or "0"
            amount = 0
            if amount_str:
                amount_str = amount_str.replace(".", "").replace(",", ".")
                try:
                    amount = float(amount_str)
                except ValueError:
                    pass
            debt_entries[nif] = {
                "nif": nif,
                "name": name,
                "amount": amount,
                "source": "SS",
            }

        if debt_entries:
            print(f"  Found {len(debt_entries)} SS debt entries", file=sys.stderr)
        else:
            print(f"  SS portal returned HTML but no structured debt data parsed", file=sys.stderr)

        return debt_entries

    except Exception as e:
        print(f"  SS download failed: {e}", file=sys.stderr)
        return {}


def build_debt_lists() -> Dict:
    """Download and cache debt lists from AT and SS."""
    print("Building debt lists...", file=sys.stderr)

    at_debts = try_download_at_debts()
    ss_debts = try_download_ss_debts()

    # If downloads failed, create empty lists with instructions
    if not at_debts and not ss_debts:
        print("\n  ⚠️  Automatic download failed for both sources.", file=sys.stderr)
        print("  The debt lists require JavaScript rendering or manual download.", file=sys.stderr)
        print("  To use this tool manually:", file=sys.stderr)
        print(f"    1. Download AT list from: {AT_DEBT_URL}", file=sys.stderr)
        print(f"    2. Download SS list from: {SS_DEBT_URL}", file=sys.stderr)
        print("    3. Place them as data/at_debts.json and data/ss_debts.json", file=sys.stderr)
        print("    4. Run: python debt_checker.py check", file=sys.stderr)

        # Check for manual downloads
        manual_at = SCRIPT_DIR / "data" / "at_debts.json"
        manual_ss = SCRIPT_DIR / "data" / "ss_debts.json"

        if manual_at.exists():
            print(f"  Found manual AT debt list: {manual_at}", file=sys.stderr)
            with open(manual_at, "r", encoding="utf-8") as f:
                at_debts = json.load(f)

        if manual_ss.exists():
            print(f"  Found manual SS debt list: {manual_ss}", file=sys.stderr)
            with open(manual_ss, "r", encoding="utf-8") as f:
                ss_debts = json.load(f)

    result = {
        "at_debts": at_debts,
        "ss_debts": ss_debts,
        "stats": {
            "at_count": len(at_debts),
            "ss_count": len(ss_debts),
        }
    }

    save_debt_cache(result)
    print(f"\n  AT debt entries: {len(at_debts)}", file=sys.stderr)
    print(f"  SS debt entries: {len(ss_debts)}", file=sys.stderr)

    return result


# =============================================================================
# CROSS-REFERENCE
# =============================================================================

def cross_reference(debt_data: Dict, contract_index: Dict, nif_filter: str = "") -> List[Dict]:
    """Cross-reference contract winners with debt lists."""
    at_debts = debt_data.get("at_debts", {})
    ss_debts = debt_data.get("ss_debts", {})

    # Collect all unique winner NIFs from contracts
    winner_nifs: Dict[str, Dict] = defaultdict(lambda: {
        "name": "", "contracts": 0, "total_value": 0.0,
        "buyers": set(), "at_debt": None, "ss_debt": None,
    })

    for buyer_nif, contracts in contract_index.items():
        for c in contracts:
            winner_nif = c.get("adjudicatario_nif", "")
            winner_name = c.get("adjudicatario", "")
            if not winner_nif:
                continue
            valor = c.get("valor", 0) or 0

            wd = winner_nifs[winner_nif]
            wd["name"] = winner_name
            wd["contracts"] += 1
            wd["total_value"] += valor
            wd["buyers"].add(buyer_nif)

    # Cross-reference with debt lists
    matches = []
    for nif, wd in winner_nifs.items():
        if nif_filter and nif != nif_filter:
            continue

        at_match = at_debts.get(nif)
        ss_match = ss_debts.get(nif)

        if at_match or ss_match:
            wd["at_debt"] = at_match
            wd["ss_debt"] = ss_match
            wd["debt_count"] = (1 if at_match else 0) + (1 if ss_match else 0)
            wd["total_debt"] = (
                (at_match.get("amount", 0) if at_match else 0) +
                (ss_match.get("amount", 0) if ss_match else 0)
            )
            matches.append({
                "nif": nif,
                "name": wd["name"],
                "contracts": wd["contracts"],
                "total_value": wd["total_value"],
                "buyer_count": len(wd["buyers"]),
                "at_debt": at_match,
                "ss_debt": ss_match,
                "debt_count": wd["debt_count"],
                "total_debt": wd["total_debt"],
            })

    matches.sort(key=lambda x: -x["total_value"])
    return matches


# =============================================================================
# DISPLAY
# =============================================================================

def show_crossref(matches: List[Dict], debt_data: Dict):
    """Display cross-reference results."""
    at_count = debt_data.get("stats", {}).get("at_count", 0)
    ss_count = debt_data.get("stats", {}).get("ss_count", 0)

    print(f"\n{'='*110}")
    print(f"DEBT × CONTRACTS CROSS-REFERENCE")
    print(f"{'='*110}")
    print(f"  AT debt list: {at_count} entries")
    print(f"  SS debt list: {ss_count} entries")

    if not matches:
        print(f"\n  No contract winners found on debt lists.")
        if at_count == 0 and ss_count == 0:
            print(f"  (Debt lists are empty — run 'build' first or download manually)")
        return

    total_value = sum(m["total_value"] for m in matches)
    total_debt = sum(m["total_debt"] for m in matches)

    print(f"\n  🚨 {len(matches)} contract winners found on debt lists")
    print(f"  Total contract value: €{total_value:,.2f}")
    print(f"  Total debt amount:    €{total_debt:,.2f}")

    print(f"\n  {'#':<4}{'Company':<35}{'NIF':<12}{'Contracts':>10}{'Contract €':>16}{'Debt €':>16}{'Flags'}")
    print(f"  {'─'*4}{'─'*35}{'─'*12}{'─'*10}{'─'*16}{'─'*16}{'─'*20}")

    for i, m in enumerate(matches[:30], 1):
        flags = []
        if m["at_debt"]:
            flags.append("AT")
        if m["ss_debt"]:
            flags.append("SS")
        flag_str = " ".join(flags)

        debt_str = f"€{m['total_debt']:>14,.0f}" if m["total_debt"] > 0 else "      (listed)"

        print(f"  {i:<4}{m['name'][:35]:<35}{m['nif']:<12}{m['contracts']:>10}€{m['total_value']:>14,.0f}{debt_str} {flag_str}")

    # Detail top 5
    print(f"\n  🔍 Detailed View — Top 5")
    for i, m in enumerate(matches[:5], 1):
        print(f"\n  {'─'*100}")
        print(f"  #{i} {m['name'][:60]} (NIF: {m['nif']})")
        print(f"     Contracts: {m['contracts']}  |  Value: €{m['total_value']:,.2f}  |  Buyers: {m['buyer_count']}")
        if m["at_debt"]:
            print(f"     🚨 AT Tax Debt: €{m['at_debt'].get('amount', 0):,.2f} — {m['at_debt'].get('name', '')}")
        if m["ss_debt"]:
            print(f"     🚨 SS Debt: €{m['ss_debt'].get('amount', 0):,.2f} — {m['ss_debt'].get('name', '')}")


def show_stats(debt_data: Dict, contract_index: Dict):
    """Show summary statistics."""
    at_count = debt_data.get("stats", {}).get("at_count", 0)
    ss_count = debt_data.get("stats", {}).get("ss_count", 0)

    # Count unique winners
    winners = set()
    for contracts in contract_index.values():
        for c in contracts:
            wn = c.get("adjudicatario_nif", "")
            if wn:
                winners.add(wn)

    print(f"\n=== Debt Checker Statistics ===")
    print(f"  AT debt entries:     {at_count}")
    print(f"  SS debt entries:     {ss_count}")
    print(f"  Total debt NIFs:     {at_count + ss_count}")
    print(f"  Unique winners:      {len(winners)}")
    print(f"  Last updated:        {debt_data.get('last_updated', 'never')}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Debt Checker — Cross-reference contract winners with public debt lists",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("build", help="Download and parse debt lists")

    check_p = sub.add_parser("check", help="Cross-reference winners with debts")
    check_p.add_argument("--nif", help="Check specific winner NIF")

    sub.add_parser("stats", help="Summary statistics")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if args.command == "build":
        debt_data = build_debt_lists()
        contract_index = load_contract_index()
        if contract_index:
            matches = cross_reference(debt_data, contract_index)
            show_crossref(matches, debt_data)

    elif args.command == "check":
        debt_data = load_debt_cache()
        if not debt_data.get("at_debts") and not debt_data.get("ss_debts"):
            print("No debt data found. Run 'build' first.", file=sys.stderr)
            return
        contract_index = load_contract_index()
        if not contract_index:
            return
        matches = cross_reference(debt_data, contract_index, nif_filter=args.nif or "")
        show_crossref(matches, debt_data)

    elif args.command == "stats":
        debt_data = load_debt_cache()
        contract_index = load_contract_index()
        show_stats(debt_data, contract_index)


if __name__ == "__main__":
    main()
