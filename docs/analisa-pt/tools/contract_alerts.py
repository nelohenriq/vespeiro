#!/usr/bin/env python3
"""Contract Alert System — Track new public procurement contracts.

Monitors specified entities (by NIF or name) and alerts when new contracts
appear in the BASE.gov.pt data. Integrates with the existing Telegram bot
for notifications.

Usage:
    # Add an entity to watch list
    python contract_alerts.py add --nif 505335018 --label "Câmara Gaia"
    python contract_alerts.py add --keyword "hospital" --label "Hospitals"

    # List watched entities
    python contract_alerts.py list

    # Check for new contracts (compare against last known state)
    python contract_alerts.py check
    python contract_alerts.py check --notify  # Send Telegram alert if new contracts found

    # Show recent alerts
    python contract_alerts.py history

    # Remove an entity
    python contract_alerts.py remove --id <watch_id>
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"
WATCH_FILE = SCRIPT_DIR / "data" / "contract_watch.json"
ALERT_HISTORY_FILE = SCRIPT_DIR / "data" / "contract_alert_history.json"

BASE_DETAIL_URL = "https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id="


# ═════════════════════════════════════════════════════════════════════════════
#  Watch List Management
# ═════════════════════════════════════════════════════════════════════════════

def load_watch_list() -> list[dict]:
    """Load the watch list from disk."""
    if WATCH_FILE.exists():
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_watch_list(watches: list[dict]) -> None:
    """Save the watch list to disk."""
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCH_FILE, "w", encoding="utf-8") as f:
        json.dump(watches, f, ensure_ascii=False, indent=2)


def add_watch(nif: str = "", keyword: str = "", label: str = "") -> dict:
    """Add an entity to the watch list."""
    watches = load_watch_list()

    # Generate ID
    watch_id = max((w.get("id", 0) for w in watches), default=0) + 1

    watch = {
        "id": watch_id,
        "nif": nif,
        "keyword": keyword,
        "label": label or (nif if nif else keyword),
        "added_at": datetime.now(timezone.utc).isoformat(),
        "last_check": None,
        "last_contract_count": 0,
        "seen_contract_ids": [],
    }

    watches.append(watch)
    save_watch_list(watches)
    return watch


def remove_watch(watch_id: int) -> bool:
    """Remove a watch by ID."""
    watches = load_watch_list()
    before = len(watches)
    watches = [w for w in watches if w.get("id") != watch_id]
    if len(watches) < before:
        save_watch_list(watches)
        return True
    return False


def list_watches() -> list[dict]:
    """List all watched entities."""
    return load_watch_list()


# ═════════════════════════════════════════════════════════════════════════════
#  Contract Matching
# ═════════════════════════════════════════════════════════════════════════════

def load_index() -> dict:
    """Load the contract index."""
    if not CONTRACT_CACHE.exists():
        print(f"Error: Contract index not found at {CONTRACT_CACHE}")
        sys.exit(1)
    with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_contracts_for_watch(index: dict, watch: dict) -> list[dict]:
    """Find all contracts matching a watch entry."""
    results = []
    nif = watch.get("nif", "")
    keyword = watch.get("keyword", "").lower()

    for nif_key, contracts in index.items():
        # NIF match
        if nif and nif not in nif_key:
            continue

        for c in contracts:
            # Keyword match (if specified)
            if keyword:
                searchable = " ".join([
                    c.get("entity_name", ""),
                    c.get("objeto", ""),
                    c.get("tipo", ""),
                ]).lower()
                if keyword not in searchable:
                    continue

            # Enrich with detail URL
            cid = c.get("contract_id")
            c["detail_url"] = f"{BASE_DETAIL_URL}{cid}" if cid else ""

            results.append(c)

    # Sort by date descending
    results.sort(key=lambda x: (x.get("data", ""), x.get("valor", 0)), reverse=True)
    return results


# ═════════════════════════════════════════════════════════════════════════════
#  New Contract Detection
# ═════════════════════════════════════════════════════════════════════════════

def check_for_new_contracts(
    index: dict,
    watch: dict,
) -> tuple[list[dict], dict]:
    """Check for new contracts since last check.

    Returns:
        (new_contracts, updated_watch): List of new contracts and the updated watch entry.
    """
    all_contracts = find_contracts_for_watch(index, watch)
    seen_ids = set(watch.get("seen_contract_ids", []))

    # Find new contracts (not seen before)
    new_contracts = []
    for c in all_contracts:
        cid = c.get("contract_id")
        if cid and cid not in seen_ids:
            new_contracts.append(c)

    # Update watch state
    updated_watch = watch.copy()
    updated_watch["last_check"] = datetime.now(timezone.utc).isoformat()
    updated_watch["last_contract_count"] = len(all_contracts)
    # Keep only last 1000 seen IDs to prevent unbounded growth
    all_ids = list(seen_ids | {c.get("contract_id") for c in all_contracts if c.get("contract_id")})
    updated_watch["seen_contract_ids"] = all_ids[-1000:]

    return new_contracts, updated_watch


# ═════════════════════════════════════════════════════════════════════════════
#  Alert History
# ═════════════════════════════════════════════════════════════════════════════

def load_alert_history() -> list[dict]:
    """Load alert history from disk."""
    if ALERT_HISTORY_FILE.exists():
        with open(ALERT_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_alert_history(history: list[dict]) -> None:
    """Save alert history to disk."""
    ALERT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def record_alert(watch: dict, new_contracts: list[dict]) -> dict:
    """Record an alert in history."""
    history = load_alert_history()

    alert = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "watch_id": watch.get("id"),
        "watch_label": watch.get("label"),
        "new_count": len(new_contracts),
        "total_count": watch.get("last_contract_count", 0),
        "contracts": [
            {
                "contract_id": c.get("contract_id"),
                "date": c.get("data"),
                "value": c.get("valor"),
                "entity": c.get("entity_name"),
                "description": c.get("objeto", "")[:100],
                "detail_url": c.get("detail_url", ""),
            }
            for c in new_contracts[:10]  # Keep only top 10 in history
        ],
    }

    history.insert(0, alert)
    # Keep only last 500 alerts
    history = history[:500]
    save_alert_history(history)
    return alert


# ═════════════════════════════════════════════════════════════════════════════
#  Notification Formatting
# ═════════════════════════════════════════════════════════════════════════════

def format_value(val: float) -> str:
    """Format monetary value."""
    if val >= 1_000_000:
        return f"€{val/1_000_000:.2f}M"
    elif val >= 1_000:
        return f"€{val/1_000:.1f}K"
    return f"€{val:,.2f}"


def format_alert_message(watch: dict, new_contracts: list[dict]) -> str:
    """Format an alert message for Telegram (HTML parse mode)."""
    label = watch.get("label", "Unknown")
    count = len(new_contracts)
    total = watch.get("last_contract_count", 0)

    lines = [
        f"📦 <b>Novos Contratos — {label}</b>",
        "",
        f"Encontrados <b>{count}</b> novos contratos (total: {total})",
        "",
    ]

    # Show top contracts
    for i, c in enumerate(new_contracts[:5], 1):
        valor = format_value(c.get("valor", 0) or 0)
        date = c.get("data", "?")
        entity = (c.get("entity_name") or "?")[:40]
        desc = (c.get("objeto") or "?")[:60]
        url = c.get("detail_url", "")

        lines.append(f"<b>{i}.</b> {valor} — {date}")
        lines.append(f"   {entity}")
        lines.append(f"   <i>{desc}</i>")
        if url:
            lines.append(f"   <a href='{url}'>Ver detalhe</a>")
        lines.append("")

    if count > 5:
        lines.append(f"... e mais {count - 5} contratos")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def format_alert_console(watch: dict, new_contracts: list[dict]) -> str:
    """Format an alert message for console output."""
    label = watch.get("label", "Unknown")
    count = len(new_contracts)
    total = watch.get("last_contract_count", 0)

    lines = [
        f"\n  {'='*70}",
        f"  📦 NEW CONTRACTS ALERT — {label}",
        f"  {'='*70}",
        f"  Found {count} new contracts (total tracked: {total})",
        f"  {'-'*70}",
    ]

    for i, c in enumerate(new_contracts[:10], 1):
        valor = format_value(c.get("valor", 0) or 0)
        date = c.get("data", "?")
        entity = (c.get("entity_name") or "?")[:45]
        desc = (c.get("objeto") or "?")[:50]

        lines.append(f"  {i:2d}. [{date}] {valor:>12}  {entity}")
        lines.append(f"      {desc}")
        if c.get("detail_url"):
            lines.append(f"      📋 {c['detail_url']}")

    if count > 10:
        lines.append(f"  ... and {count - 10} more contracts")

    lines.append(f"  {'='*70}\n")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  CLI Commands
# ═════════════════════════════════════════════════════════════════════════════

def cmd_add(args) -> int:
    """Add an entity to the watch list."""
    if not args.nif and not args.keyword:
        print("Error: Specify --nif or --keyword")
        return 1

    watch = add_watch(nif=args.nif, keyword=args.keyword, label=args.label)
    print(f"\n  ✅ Added watch #{watch['id']}: {watch['label']}")
    if watch["nif"]:
        print(f"     NIF: {watch['nif']}")
    if watch["keyword"]:
        print(f"     Keyword: {watch['keyword']}")
    print()
    return 0


def cmd_remove(args) -> int:
    """Remove a watch by ID."""
    if remove_watch(args.id):
        print(f"\n  ✅ Removed watch #{args.id}\n")
        return 0
    print(f"\n  ❌ Watch #{args.id} not found\n")
    return 1


def cmd_list(args) -> int:
    """List all watched entities."""
    watches = list_watches()

    if not watches:
        print("\n  No watched entities. Use 'add' to start tracking.\n")
        return 0

    print(f"\n  {'='*70}")
    print(f"  👁️  WATCHED ENTITIES ({len(watches)})")
    print(f"  {'='*70}")
    print(f"  {'ID':<5} {'Label':<30} {'NIF':<15} {'Keyword':<15} {'Contracts':>10}")
    print(f"  {'-'*5} {'-'*30} {'-'*15} {'-'*15} {'-'*10}")

    for w in watches:
        print(f"  {w.get('id', '?'):<5} {w.get('label', '?')[:30]:<30} "
              f"{w.get('nif', ''):<15} {w.get('keyword', ''):<15} "
              f"{w.get('last_contract_count', 0):>10}")

    print(f"  {'='*70}\n")
    return 0


def cmd_check(args) -> int:
    """Check for new contracts across all watches."""
    watches = list_watches()
    if not watches:
        print("\n  No watched entities. Use 'add' to start tracking.\n")
        return 0

    print("\n  Checking for new contracts...")
    index = load_index()

    total_new = 0
    alerts_sent = 0

    for watch in watches:
        new_contracts, updated_watch = check_for_new_contracts(index, watch)

        # Update watch state
        idx = next((i for i, w in enumerate(watches) if w.get("id") == watch.get("id")), None)
        if idx is not None:
            watches[idx] = updated_watch

        if new_contracts:
            total_new += len(new_contracts)
            print(f"\n  📦 {watch.get('label')}: {len(new_contracts)} new contracts")

            # Print to console
            print(format_alert_console(watch, new_contracts))

            # Record in history
            record_alert(watch, new_contracts)

            # Send notification if requested
            if args.notify:
                try:
                    from src.alerts.telegram import TelegramBot
                    from src.config.settings import settings

                    token = settings.telegram_bot_token
                    chat_id = settings.telegram_chat_id

                    if token and chat_id:
                        import asyncio

                        async def send_alert():
                            bot = TelegramBot(token, chat_id)
                            message = format_alert_message(watch, new_contracts)
                            return await bot._send(message)

                        ok = asyncio.run(send_alert())
                        if ok:
                            alerts_sent += 1
                            print(f"  ✅ Telegram alert sent for {watch.get('label')}")
                        else:
                            print(f"  ⚠️ Failed to send Telegram alert")
                    else:
                        print(f"  ⚠️ Telegram credentials not configured")
                except ImportError:
                    print(f"  ⚠️ Telegram module not available (run from backend/)")
        else:
            print(f"  ✓ {watch.get('label')}: no new contracts")

    # Save updated watch list
    save_watch_list(watches)

    print(f"\n  {'='*70}")
    print(f"  Summary: {total_new} new contracts across {len(watches)} watches")
    if args.notify:
        print(f"  Telegram alerts sent: {alerts_sent}")
    print(f"  {'='*70}\n")

    return 0


def cmd_history(args) -> int:
    """Show recent alert history."""
    history = load_alert_history()

    if not history:
        print("\n  No alert history yet.\n")
        return 0

    print(f"\n  {'='*70}")
    print(f"  📜 CONTRACT ALERT HISTORY (last {min(args.limit, len(history))} alerts)")
    print(f"  {'='*70}")

    for alert in history[:args.limit]:
        ts = alert.get("timestamp", "?")[:16]
        label = alert.get("watch_label", "?")
        count = alert.get("new_count", 0)
        total = alert.get("total_count", 0)

        print(f"\n  [{ts}] {label}: +{count} contracts (total: {total})")

        for c in alert.get("contracts", [])[:3]:
            valor = format_value(c.get("value", 0) or 0)
            print(f"    • {c.get('date', '?')} {valor:>10} — {(c.get('entity') or '?')[:40]}")

    print(f"\n  {'='*70}\n")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Contract Alert System — Track new public procurement contracts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # add
    add_parser = subparsers.add_parser("add", help="Add entity to watch list")
    add_parser.add_argument("--nif", default="", help="NIF to track")
    add_parser.add_argument("--keyword", default="", help="Keyword to match")
    add_parser.add_argument("--label", default="", help="Human-readable label")

    # remove
    remove_parser = subparsers.add_parser("remove", help="Remove a watch")
    remove_parser.add_argument("--id", type=int, required=True, help="Watch ID to remove")

    # list
    subparsers.add_parser("list", help="List watched entities")

    # check
    check_parser = subparsers.add_parser("check", help="Check for new contracts")
    check_parser.add_argument("--notify", action="store_true", help="Send Telegram notification")

    # history
    history_parser = subparsers.add_parser("history", help="Show alert history")
    history_parser.add_argument("--limit", type=int, default=20, help="Number of alerts to show")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "add": cmd_add,
        "remove": cmd_remove,
        "list": cmd_list,
        "check": cmd_check,
        "history": cmd_history,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
