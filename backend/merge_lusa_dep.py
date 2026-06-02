#!/usr/bin/env python3
"""Merge Lusa dependency analysis results into stats.json.

Reads the temp file written by run_lusa_dep_background.py and updates
the lusa_dependency and timelines.lusa_dependency_7d fields.

Usage:
    python merge_lusa_dep.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

RESULT_PATH = Path(__file__).parent / "data" / "lusa_dep_result.json"
STATS_PATH = Path(__file__).parent.parent / "frontend" / "public" / "stats.json"


def main() -> int:
    if not RESULT_PATH.exists():
        print(f"❌ Result file not found: {RESULT_PATH}")
        print("   Run run_lusa_dep_background.py first (takes 10+ min)")
        return 1

    if not STATS_PATH.exists():
        print(f"❌ Stats file not found: {STATS_PATH}")
        print("   Run run_stats_fast.py first")
        return 1

    # Load both files
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))

    # Update lusa_dependency
    stats["lusa_dependency"] = {
        "global_pct": result["global_pct"],
        "per_outlet": result["per_outlet"],
        "per_topic": result["per_topic"],
    }

    # Update timeline
    if "daily_timeline_7d" in result:
        stats["timelines"]["lusa_dependency_7d"] = result["daily_timeline_7d"]

    # Write updated stats
    STATS_PATH.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    size_kb = len(json.dumps(stats)) / 1024
    print(f"✅ stats.json updated ({size_kb:.1f} KB)")
    print(f"   global_pct: {result['global_pct']}")
    print(f"   outlets: {len(result['per_outlet'])}")
    print(f"   timeline: {result.get('daily_timeline_7d', 'N/A')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
