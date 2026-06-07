#!/usr/bin/env python3
"""Anomaly Scan Diff Tracker — Compare Results Over Time

Saves scan snapshots with timestamps and compares new results against
baselines to detect emerging patterns, new flags, and score changes.

Usage:
    python anomaly_diff.py save                # Save current scan as baseline
    python anomaly_diff.py diff                # Compare current vs last baseline
    python anomaly_diff.py diff --baseline baseline_20260601.json
    python anomaly_diff.py history             # Show all saved snapshots
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
BEP_DB = SCRIPT_DIR / "bep_index.db"
SNAPSHOTS_DIR = SCRIPT_DIR / "data" / "snapshots"

# Import scanner
sys.path.insert(0, str(SCRIPT_DIR))
from anomaly_scanner import AnomalyScanner, fmt
from municipality_risk_report import scan_municipalities


def ensure_snapshots_dir():
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def get_snapshot_path(name=None):
    if name:
        return SNAPSHOTS_DIR / name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return SNAPSHOTS_DIR / f"scan_{ts}.json"


def load_snapshot(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_snapshot(scan_results, name=None):
    """Save scan results as a timestamped snapshot."""
    ensure_snapshots_dir()
    path = get_snapshot_path(name)

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "total_entities": len(scan_results),
        "critical": sum(1 for d in scan_results.values() if d.get("critical_count", 0) > 0),
        "warning": sum(1 for d in scan_results.values() if d.get("signal_count", 0) >= 2),
        "signals_by_type": {},
        "entities": {},
    }

    for nif, data in scan_results.items():
        snapshot["entities"][nif] = {
            "name": data.get("name", ""),
            "score": round(data.get("total_score", 0), 1),
            "signals": data.get("signal_count", 0),
            "critical": data.get("critical_count", 0),
            "signal_types": [s["type"] for s in data.get("signals", [])],
        }
        for s in data.get("signals", []):
            stype = s["type"]
            snapshot["signals_by_type"][stype] = snapshot["signals_by_type"].get(stype, 0) + 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)

    print(f"Snapshot saved: {path}")
    print(f"  Entities: {snapshot['total_entities']}")
    print(f"  Critical: {snapshot['critical']}")
    print(f"  Warning:  {snapshot['warning']}")
    return path


def diff_snapshots(old, new):
    """Compare two snapshots and return changes."""
    old_entities = old.get("entities", {})
    new_entities = new.get("entities", {})

    old_nifs = set(old_entities.keys())
    new_nifs = set(new_entities.keys())

    # New entities flagged
    added = [{"nif": nif, "name": new_entities.get(nif, {}).get("name", "")} for nif in sorted(new_nifs - old_nifs)]
    # Entities no longer flagged
    removed = [{"nif": nif, "name": old_entities.get(nif, {}).get("name", "")} for nif in sorted(old_nifs - new_nifs)]
    # Entities in both
    common = old_nifs & new_nifs

    # Score changes
    score_up = []
    score_down = []
    new_critical = []
    new_signals = []

    for nif in common:
        old_score = old_entities[nif].get("score", 0)
        new_score = new_entities[nif].get("score", 0)
        old_name = old_entities[nif].get("name", "")
        new_name = new_entities[nif].get("name", "")

        delta = new_score - old_score
        if abs(delta) >= 1:
            entry = {
                "nif": nif, "name": new_name or old_name,
                "old_score": old_score, "new_score": new_score,
                "delta": round(delta, 1),
            }
            if delta > 0:
                score_up.append(entry)
            else:
                score_down.append(entry)

        # New critical signal
        old_critical = old_entities[nif].get("critical", 0)
        new_critical_count = new_entities[nif].get("critical", 0)
        if new_critical_count > old_critical:
            new_critical.append({
                "nif": nif, "name": new_name or old_name,
                "old_critical": old_critical, "new_critical": new_critical_count,
            })

        # New signal type
        old_types = set(old_entities[nif].get("signal_types", []))
        new_types = set(new_entities[nif].get("signal_types", []))
        added_types = new_types - old_types
        if added_types:
            new_signals.append({
                "nif": nif, "name": new_name or old_name,
                "new_signals": list(added_types),
            })

    # Signal count changes
    old_signals = old.get("signals_by_type", {})
    new_signals_by_type = new.get("signals_by_type", {})
    signal_changes = {}
    all_types = set(list(old_signals.keys()) + list(new_signals_by_type.keys()))
    for stype in all_types:
        old_count = old_signals.get(stype, 0)
        new_count = new_signals_by_type.get(stype, 0)
        if old_count != new_count:
            signal_changes[stype] = {"old": old_count, "new": new_count, "delta": new_count - old_count}

    return {
        "old_timestamp": old.get("timestamp", "unknown"),
        "new_timestamp": new.get("timestamp", "unknown"),
        "added": added,
        "removed": removed,
        "score_up": sorted(score_up, key=lambda x: -x["delta"]),
        "score_down": sorted(score_down, key=lambda x: x["delta"]),
        "new_critical": new_critical,
        "new_signals": new_signals,
        "signal_changes": signal_changes,
        "old_total": old.get("total_entities", 0),
        "new_total": new.get("total_entities", 0),
    }


def print_diff(diff):
    """Print the diff report."""
    print(f"\n{'='*100}")
    print(f"  ANOMALY SCAN DIFF — Emerging Patterns Detection")
    print(f"{'='*100}")
    print(f"\n  Old scan: {diff['old_timestamp']}")
    print(f"  New scan: {diff['new_timestamp']}")
    print(f"  Entities: {diff['old_total']} → {diff['new_total']} ({diff['new_total'] - diff['old_total']:+d})")

    # New entities
    if diff["added"]:
        print(f"\n  🆕 NEW ENTITIES FLAGGED ({len(diff['added'])})")
        print(f"  {'─'*60}")
        for e in diff["added"][:20]:
            print(f"    {e['nif']}  {e['name'][:50]}")
        if len(diff["added"]) > 20:
            print(f"    ... and {len(diff['added']) - 20} more")

    # Removed entities
    if diff["removed"]:
        print(f"\n  ✅ ENTITIES NO LONGER FLAGGED ({len(diff['removed'])})")
        print(f"  {'─'*60}")
        for e in diff["removed"][:20]:
            print(f"    {e['nif']}  {e['name'][:50]}")
        if len(diff["removed"]) > 20:
            print(f"    ... and {len(diff['removed']) - 20} more")

    # Score increases (getting worse)
    if diff["score_up"]:
        print(f"\n  🔴 SCORE INCREASES — Getting Worse ({len(diff['score_up'])})")
        print(f"  {'─'*60}")
        print(f"  {'NIF':<12}{'Entity':<35}{'Old':>6}{'New':>6}{'Delta':>8}")
        for e in diff["score_up"][:15]:
            print(f"  {e['nif']:<12}{e['name'][:35]:<35}{e['old_score']:>5.0f} {e['new_score']:>5.0f} {e['delta']:>+7.1f}")

    # Score decreases (improving)
    if diff["score_down"]:
        print(f"\n  🟢 SCORE DECREASES — Improving ({len(diff['score_down'])})")
        print(f"  {'─'*60}")
        for e in diff["score_down"][:10]:
            print(f"  {e['nif']:<12}{e['name'][:35]:<35}{e['old_score']:>5.0f} {e['new_score']:>5.0f} {e['delta']:>+7.1f}")

    # New critical signals
    if diff["new_critical"]:
        print(f"\n  🔴 NEW CRITICAL SIGNALS ({len(diff['new_critical'])})")
        print(f"  {'─'*60}")
        for e in diff["new_critical"]:
            print(f"  {e['nif']:<12}{e['name'][:45]:<45} {e['old_critical']} → {e['new_critical']} critical")

    # New signal types
    if diff["new_signals"]:
        print(f"\n  ⚠️  NEW SIGNAL TYPES DETECTED ({len(diff['new_signals'])})")
        print(f"  {'─'*60}")
        for e in diff["new_signals"]:
            print(f"  {e['nif']:<12}{e['name'][:45]:<45} +{', '.join(e['new_signals'])}")

    # Signal count changes
    if diff["signal_changes"]:
        print(f"\n  📊 SIGNAL COUNT CHANGES")
        print(f"  {'─'*60}")
        for stype, change in sorted(diff["signal_changes"].items(), key=lambda x: abs(x[1]["delta"]), reverse=True):
            arrow = "↑" if change["delta"] > 0 else "↓"
            print(f"    {stype:<25} {change['old']:>5} → {change['new']:>5} ({arrow}{abs(change['delta']):>3})")

    # Summary
    print(f"\n{'='*100}")
    total_changes = len(diff["added"]) + len(diff["removed"]) + len(diff["score_up"]) + len(diff["score_down"])
    if total_changes == 0:
        print(f"  No significant changes detected between scans.")
    else:
        print(f"  Total changes: {total_changes}")
        print(f"  New entities:  {len(diff['added'])}")
        print(f"  Removed:       {len(diff['removed'])}")
        print(f"  Score changes: {len(diff['score_up']) + len(diff['score_down'])}")
    print(f"{'='*100}\n")


def list_snapshots():
    """List all saved snapshots."""
    ensure_snapshots_dir()
    files = sorted(SNAPSHOTS_DIR.glob("scan_*.json"), reverse=True)
    if not files:
        print("No snapshots found. Run 'anomaly_diff.py save' first.")
        return

    print(f"\n{'='*80}")
    print(f"  SAVED SNAPSHOTS ({len(files)} total)")
    print(f"{'='*80}")
    print(f"\n  {'File':<35}{'Timestamp':<22}{'Entities':>10}{'Critical':>10}{'Warning':>10}")
    print(f"  {'─'*35}{'─'*22}{'─'*10}{'─'*10}{'─'*10}")

    for f in files[:20]:
        try:
            data = load_snapshot(f)
            ts = data.get("timestamp", "?")[:19]
            print(f"  {f.name:<35}{ts:<22}{data.get('total_entities', 0):>10,}{data.get('critical', 0):>10,}{data.get('warning', 0):>10,}")
        except Exception:
            print(f"  {f.name:<35} (corrupt)")
    print()


# =============================================================================
# MUNICIPALITY RISK DIFF
# =============================================================================

def get_muni_snapshot_path(name=None):
    if name:
        return SNAPSHOTS_DIR / name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return SNAPSHOTS_DIR / f"muni_{ts}.json"


def save_muni_snapshot(results, name=None):
    """Save municipality risk results as a timestamped snapshot."""
    ensure_snapshots_dir()
    path = get_muni_snapshot_path(name)

    high = sum(1 for r in results if r["risk"] > 60)
    medium = sum(1 for r in results if 40 < r["risk"] <= 60)
    dual = [r for r in results if r["top3_share"] >= 60 and r["inflated"] > 0]

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "total_municipalities": len(results),
        "high_risk": high,
        "medium_risk": medium,
        "low_risk": len(results) - high - medium,
        "dual_anomaly_count": len(dual),
        "total_overrun": sum(r["overrun"] for r in results),
        "municipalities": {},
    }

    for r in results:
        snapshot["municipalities"][r["nif"]] = {
            "name": r["name"],
            "risk": r["risk"],
            "top3_share": r["top3_share"],
            "inflation_rate": r["inflation_rate"],
            "inflated": r["inflated"],
            "overrun": r["overrun"],
            "direct_rate": r["direct_rate"],
            "exclusive_count": r["exclusive_count"],
            "num_winners": r["num_winners"],
        }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)

    print(f"Municipality snapshot saved: {path}")
    print(f"  Municipalities: {len(results)}")
    print(f"  High risk: {high}")
    print(f"  Dual-anomaly: {len(dual)}")
    print(f"  Total overrun: {fmt(snapshot['total_overrun'])}")
    return path


def diff_municipalities(old, new):
    """Compare two municipality snapshots and return changes."""
    old_munis = old.get("municipalities", {})
    new_munis = new.get("municipalities", {})

    old_nifs = set(old_munis.keys())
    new_nifs = set(new_munis.keys())

    added = [{"nif": nif, "name": new_munis.get(nif, {}).get("name", ""), "risk": new_munis.get(nif, {}).get("risk", 0)} for nif in sorted(new_nifs - old_nifs)]
    removed = [{"nif": nif, "name": old_munis.get(nif, {}).get("name", ""), "risk": old_munis.get(nif, {}).get("risk", 0)} for nif in sorted(old_nifs - new_nifs)]
    common = old_nifs & new_nifs

    risk_up = []
    risk_down = []
    new_high_risk = []
    new_inflation = []

    for nif in common:
        old_risk = old_munis[nif].get("risk", 0)
        new_risk = new_munis[nif].get("risk", 0)
        name = new_munis[nif].get("name", "") or old_munis[nif].get("name", "")

        delta = new_risk - old_risk
        if abs(delta) >= 5:
            entry = {"nif": nif, "name": name, "old_risk": old_risk, "new_risk": new_risk, "delta": round(delta, 1)}
            if delta > 0:
                risk_up.append(entry)
            else:
                risk_down.append(entry)

        if old_risk <= 60 and new_risk > 60:
            new_high_risk.append({"nif": nif, "name": name, "old_risk": old_risk, "new_risk": new_risk})

        old_inflated = old_munis[nif].get("inflated", 0)
        new_inflated = new_munis[nif].get("inflated", 0)
        if old_inflated == 0 and new_inflated > 0:
            new_inflation.append({"nif": nif, "name": name, "inflated": new_inflated, "overrun": new_munis[nif].get("overrun", 0)})

    return {
        "old_timestamp": old.get("timestamp", "unknown"),
        "new_timestamp": new.get("timestamp", "unknown"),
        "old_total": old.get("total_municipalities", 0),
        "new_total": new.get("total_municipalities", 0),
        "added": added,
        "removed": removed,
        "risk_up": sorted(risk_up, key=lambda x: -x["delta"]),
        "risk_down": sorted(risk_down, key=lambda x: x["delta"]),
        "new_high_risk": new_high_risk,
        "new_inflation": new_inflation,
        "old_dual": old.get("dual_anomaly_count", 0),
        "new_dual": new.get("dual_anomaly_count", 0),
        "old_overrun": old.get("total_overrun", 0),
        "new_overrun": new.get("total_overrun", 0),
    }


def print_muni_diff(diff):
    """Print municipality diff report."""
    print(f"\n{'='*100}")
    print(f"  MUNICIPALITY RISK DIFF")
    print(f"{'='*100}")
    print(f"\n  Old scan: {diff['old_timestamp']}")
    print(f"  New scan: {diff['new_timestamp']}")
    print(f"  Municipalities: {diff['old_total']} → {diff['new_total']}")
    print(f"  Dual-anomaly: {diff['old_dual']} → {diff['new_dual']}")
    print(f"  Total overrun: {fmt(diff['old_overrun'])} → {fmt(diff['new_overrun'])}")

    if diff["new_high_risk"]:
        print(f"\n  🔴 NEW HIGH-RISK MUNICIPALITIES ({len(diff['new_high_risk'])})")
        print(f"  {'─'*60}")
        for e in diff["new_high_risk"]:
            print(f"    {e['name'][:45]:<45} risk {e['old_risk']:.0f} → {e['new_risk']:.0f}")

    if diff["new_inflation"]:
        print(f"\n  ⚠️  NEW INFLATION DETECTED ({len(diff['new_inflation'])})")
        print(f"  {'─'*60}")
        for e in diff["new_inflation"]:
            print(f"    {e['name'][:45]:<45} {e['inflated']} contracts, overrun {fmt(e['overrun'])}")

    if diff["risk_up"]:
        print(f"\n  🔴 RISK INCREASING ({len(diff['risk_up'])})")
        print(f"  {'─'*60}")
        print(f"  {'NIF':<12}{'Municipality':<35}{'Old':>6}{'New':>6}{'Delta':>8}")
        for e in diff["risk_up"][:15]:
            print(f"  {e['nif']:<12}{e['name'][:35]:<35}{e['old_risk']:>5.0f} {e['new_risk']:>5.0f} {e['delta']:>+7.1f}")

    if diff["risk_down"]:
        print(f"\n  🟢 RISK DECREASING ({len(diff['risk_down'])})")
        print(f"  {'─'*60}")
        for e in diff["risk_down"][:10]:
            print(f"  {e['nif']:<12}{e['name'][:35]:<35}{e['old_risk']:>5.0f} {e['new_risk']:>5.0f} {e['delta']:>+7.1f}")

    if diff["added"]:
        print(f"\n  🆕 NEW MUNICIPALITIES ({len(diff['added'])})")
        for e in diff["added"][:10]:
            print(f"    {e['nif']}  {e['name'][:50]}  risk {e['risk']:.0f}")

    if diff["removed"]:
        print(f"\n  ✅ REMOVED MUNICIPALITIES ({len(diff['removed'])})")
        for e in diff["removed"][:10]:
            print(f"    {e['nif']}  {e['name'][:50]}  risk {e['risk']:.0f}")

    print(f"\n{'='*100}\n")


def run_municipality(args):
    """Run municipality scan/diff."""
    print("Running municipality risk scan...", file=sys.stderr)
    results = scan_municipalities()

    if args.command == "save-muni":
        save_muni_snapshot(results)
        return

    if args.command == "diff-muni":
        files = sorted(SNAPSHOTS_DIR.glob("muni_*.json"), reverse=True)
        if len(files) < 1:
            print("No baseline found. Run 'anomaly_diff.py save-muni' first.")
            return
        baseline_path = files[0]
        print(f"Comparing against: {baseline_path.name}", file=sys.stderr)
        old = load_snapshot(baseline_path)
        new_path = save_muni_snapshot(results)
        new = load_snapshot(new_path)
        diff = diff_municipalities(old, new)
        print_muni_diff(diff)
        diff_path = SNAPSHOTS_DIR / f"muni_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diff, f, ensure_ascii=False, indent=2, default=str)
        print(f"Diff report saved: {diff_path}")


def main():
    parser = argparse.ArgumentParser(description="Anomaly Scan Diff Tracker")
    sub = parser.add_subparsers(dest="command")

    save_p = sub.add_parser("save", help="Save current scan as baseline")
    save_p.add_argument("--name", help="Custom snapshot name")

    diff_p = sub.add_parser("diff", help="Compare current vs last baseline")
    diff_p.add_argument("--baseline", help="Specific baseline file to compare against")

    sub.add_parser("history", help="Show all saved snapshots")

    sub.add_parser("save-muni", help="Save municipality risk scan as baseline")
    sub.add_parser("diff-muni", help="Compare municipality risk vs last baseline")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "history":
        list_snapshots()
        return

    if args.command in ("save-muni", "diff-muni"):
        run_municipality(args)
        return

    # Run current scan
    print("Running anomaly scan...", file=sys.stderr)
    scanner = AnomalyScanner()
    results = scanner.run_scan()

    # Convert to dict format for snapshot
    scan_data = {}
    for nif, data in results.items():
        scan_data[nif] = {
            "name": data.get("name", ""),
            "total_score": data.get("total_score", 0),
            "signal_count": data.get("signal_count", 0),
            "critical_count": data.get("critical_count", 0),
            "signals": data.get("signals", []),
        }

    if args.command == "save":
        path = save_snapshot(scan_data, args.name)
        return

    if args.command == "diff":
        # Find baseline
        if args.baseline:
            baseline_path = Path(args.baseline)
            if not baseline_path.exists():
                baseline_path = SNAPSHOTS_DIR / args.baseline
        else:
            files = sorted(SNAPSHOTS_DIR.glob("scan_*.json"), reverse=True)
            if len(files) < 1:
                print("No baseline found. Run 'anomaly_diff.py save' first.")
                return
            baseline_path = files[0]

        print(f"Comparing against: {baseline_path.name}", file=sys.stderr)
        old = load_snapshot(baseline_path)

        # Save new snapshot
        new_path = save_snapshot(scan_data)

        # Compute diff
        new_snapshot = load_snapshot(new_path)
        diff = diff_snapshots(old, new_snapshot)
        print_diff(diff)

        # Save diff report
        diff_path = SNAPSHOTS_DIR / f"diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diff, f, ensure_ascii=False, indent=2, default=str)
        print(f"Diff report saved: {diff_path}")


if __name__ == "__main__":
    main()
