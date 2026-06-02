#!/usr/bin/env python3
"""
Vespeiro — Historical Anomaly Baseline Collector.

Fetches the last N days of GitHub Actions workflow run data via the
GitHub API, computes baseline statistics (run frequency, success rate,
timing) for each monitored workflow, and reads persisted scrape metrics
from ``data/scrape-metrics/`` for per-source-group baselines.

**How scrape metrics are persisted:**
Each ``scrape.yml`` run writes a JSON file to ``data/scrape-metrics/``
with per-group counts (success, failed, articles).  These files are
committed to the repo after each run, giving us a historical record
regardless of GitHub API availability.

Output: ``data/baseline.json`` — consumed by the anomaly detection system.

Usage:
    # Default: fetch last 90 days
    python run_baseline.py

    # Custom days and output path
    python run_baseline.py --days 30 --output ../data/baseline.json

    # With explicit token
    GITHUB_TOKEN=ghp_xxx python run_baseline.py

Environment:
    GITHUB_TOKEN:
        GitHub PAT with ``actions:read`` scope.
        Automatically available inside GHA runners.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

import httpx


# ── Constants ────────────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"

# Workflows to monitor for baseline data
MONITORED_WORKFLOWS = ["scrape.yml", "analyze.yml", "stats.yml"]

# Source groups for scrape.yml (mirrors scrape.yml)
SCRAPE_GROUPS = ["news", "international", "government", "weekly"]

# Path for persisted scrape metrics
SCRAPE_METRICS_DIR = Path(__file__).resolve().parent.parent / "data" / "scrape-metrics"

# Rate limiting
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_repo() -> str:
    """Get the GitHub repository slug (owner/name)."""
    env_repo = os.environ.get("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        match = re.search(r"(?:github\.com[/:])([\w.-]+/[\w.-]+?)(?:\.git)?$", remote)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "vespeiro/vespeiro"


def _parse_iso(date_str: str) -> datetime:
    """Parse an ISO 8601 date string, handling Z suffix."""
    if date_str.endswith("Z"):
        date_str = date_str[:-1] + "+00:00"
    return datetime.fromisoformat(date_str)


def _compute_stats(values: list[float]) -> dict:
    """Compute mean, std, min, max from a list of numbers."""
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance) if n > 1 else None
    return {
        "mean": round(mean, 2),
        "std": round(std, 2) if std is not None else None,
        "min": int(min(values)),
        "max": int(max(values)),
        "n": n,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  GitHub API client
# ═══════════════════════════════════════════════════════════════════════════════


class GHAClient:
    """Minimal GitHub Actions API client with retry/backoff."""

    def __init__(self, token: str, repo: str | None = None):
        self.token = token
        self.repo = repo or _get_repo()
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self, client: httpx.AsyncClient, url: str, params: dict | None = None
    ) -> dict | None:
        """Make a GET request with retry/backoff for rate limits."""
        for attempt in range(MAX_RETRIES):
            resp = await client.get(url, headers=self._headers, params=params)
            if resp.is_success:
                return resp.json()

            if resp.status_code == 404:
                return None
            if resp.status_code == 410:
                return None
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", BASE_BACKOFF_SECONDS))
                wait = retry_after * (attempt + 1)
                print(f"  ⏳ Rate limited — retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
                continue

            if resp.status_code in (500, 502, 503, 504):
                wait = BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"  ⏳ Server error {resp.status_code} — retrying in {wait}s")
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            return None

        return None

    async def list_workflow_runs(
        self,
        client: httpx.AsyncClient,
        workflow: str,
        *,
        days: int = 90,
    ) -> list[dict]:
        """Fetch workflow runs from the last *days* days.

        Handles pagination.  Returns up to 1000 runs.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        url = f"{GITHUB_API}/repos/{self.repo}/actions/workflows/{workflow}/runs"
        params: dict = {
            "created": f">{since}",
            "per_page": 100,
            "page": 1,
        }

        all_runs: list[dict] = []

        while True:
            data = await self._request(client, url, params)
            if data is None:
                print(f"  ⚠️  Could not fetch runs for {workflow}")
                return all_runs

            runs = data.get("workflow_runs", [])
            all_runs.extend(runs)

            link_header = ""  # We'd need to check headers, but _request returns parsed JSON
            # Use a simpler pagination check: if fewer than per_page results, we're done
            if len(runs) < params["per_page"]:
                break

            params["page"] += 1
            if params["page"] > 10:  # Safety: max 1000 runs
                break

        return all_runs


# ═══════════════════════════════════════════════════════════════════════════════
#  Persisted scrape metrics reader
# ═══════════════════════════════════════════════════════════════════════════════


def _load_scrape_metrics() -> dict[str, list[dict]]:
    """Load all persisted scrape metric files from ``data/scrape-metrics/``.

    Returns a dict mapping group name → list of metric dicts (each with
    timestamp, success, failed, articles).
    """
    per_group: dict[str, list[dict]] = {g: [] for g in SCRAPE_GROUPS}

    if not SCRAPE_METRICS_DIR.is_dir():
        return per_group

    for path in sorted(SCRAPE_METRICS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            group = data.get("group", "")
            if group in per_group:
                per_group[group].append({
                    "timestamp": data.get("timestamp", ""),
                    "success": data.get("success", 0),
                    "failed": data.get("failed", 0),
                    "articles": data.get("articles", 0),
                })
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  ⚠️  Skipping malformed metrics file {path.name}: {exc}")

    return per_group


# ═══════════════════════════════════════════════════════════════════════════════
#  Baseline computation
# ═══════════════════════════════════════════════════════════════════════════════


async def collect_baseline(
    client: GHAClient,
    days: int = 90,
) -> dict:
    """Collect GHA run data and persisted metrics, compute baseline statistics.

    Sources:
    1. GitHub API: workflow run conclusions, timing, cadence
    2. Persisted ``data/scrape-metrics/*.json``: per-group scrape metrics
    """
    baseline: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "days_analyzed": days,
        "repo": client.repo,
        "workflows": {},
        "scrape_groups": {},
    }

    async with httpx.AsyncClient() as http_client:
        for workflow in MONITORED_WORKFLOWS:
            print(f"\n📡 Fetching runs for {workflow}…")
            runs = await client.list_workflow_runs(http_client, workflow, days=days)
            print(f"   Found {len(runs)} runs in the last {days} days")

            if not runs:
                baseline["workflows"][workflow] = {"n_runs": 0}
                continue

            # ── Compute per-run timing ──
            durations: list[float] = []
            intervals: list[float] = []
            prev_time: datetime | None = None
            conclusions: dict[str, int] = {}
            scheduled_runs = 0
            manual_runs = 0

            for run in runs:
                created = _parse_iso(run.get("created_at", ""))
                conclusion = run.get("conclusion", "unknown")
                conclusions[conclusion] = conclusions.get(conclusion, 0) + 1

                event = run.get("event", "")
                if event == "schedule":
                    scheduled_runs += 1
                elif event == "workflow_dispatch":
                    manual_runs += 1

                # Duration
                updated = run.get("updated_at")
                if updated:
                    dur = (_parse_iso(updated) - created).total_seconds()
                    if dur > 0:
                        durations.append(dur)

                # Interval between consecutive runs
                if prev_time is not None:
                    interval = (created - prev_time).total_seconds()
                    if 0 < interval < 86400:  # Sanity: max 24h between runs
                        intervals.append(interval)
                prev_time = created

            # ── Build workflow baseline ──
            wf_data: dict = {
                "n_runs": len(runs),
                "conclusions": conclusions,
                "scheduled_runs": scheduled_runs,
                "manual_runs": manual_runs,
                "success_rate": round(
                    conclusions.get("success", 0) / len(runs) * 100, 1
                ),
                "duration_seconds": _compute_stats(durations),
                "interval_seconds": _compute_stats(intervals),
            }

            baseline["workflows"][workflow] = wf_data

    # ── Scrape group metrics (from persisted files) ──
    print(f"\n📁 Loading persisted scrape metrics from {SCRAPE_METRICS_DIR}…")
    scrape_metrics = _load_scrape_metrics()

    for group in SCRAPE_GROUPS:
        metrics = scrape_metrics.get(group, [])
        if not metrics:
            baseline["scrape_groups"][group] = {"n_runs": 0}
            continue

        success_vals = [m["success"] for m in metrics]
        failed_vals = [m["failed"] for m in metrics]
        articles_vals = [m["articles"] for m in metrics]

        baseline["scrape_groups"][group] = {
            "n_runs": len(metrics),
            "success": _compute_stats([float(v) for v in success_vals]),
            "failed": _compute_stats([float(v) for v in failed_vals]),
            "articles": _compute_stats([float(v) for v in articles_vals]),
        }
        print(f"   • {group}: {len(metrics)} metric files, "
              f"avg {_compute_stats([float(v) for v in articles_vals])['mean']:.0f} articles/run")

    return baseline


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vespeiro — Historical Anomaly Baseline Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of history to fetch (default: 90)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for baseline.json (default: data/baseline.json)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="GitHub token (default: GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repository slug (default: auto-detect from git remote)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print collected data without writing to disk",
    )
    return parser


async def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "❌ GITHUB_TOKEN is required.\n"
            "   Set it via --token, GITHUB_TOKEN env var, or run inside GHA.\n"
        )
        return 1

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        script_dir = Path(__file__).resolve().parent
        output_path = script_dir.parent / "data" / "baseline.json"

    print(f"🐝 Vespeiro — Historical Baseline Collector")
    print(f"   Repo: {args.repo or _get_repo()}")
    print(f"   Days: {args.days}")
    print(f"   Output: {output_path}")
    print()

    client = GHAClient(token=token, repo=args.repo)
    baseline = await collect_baseline(client, days=args.days)

    if args.dry_run:
        print("\n📋 Dry-run output:")
        print(json.dumps(baseline, indent=2, default=str)[:4000])
        if len(json.dumps(baseline, indent=2, default=str)) > 4000:
            print("… (truncated)")
        return 0

    # Write to disk
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(baseline, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n✅ Baseline saved to: {output_path.resolve()}")
    print(f"   Workflows analyzed:")
    for wf_name, wf_data in baseline.get("workflows", {}).items():
        n = wf_data.get("n_runs", 0)
        rate = wf_data.get("success_rate", "N/A")
        print(f"   • {wf_name}: {n} runs, success rate {rate}%")

    groups_with_data = [
        g for g, d in baseline.get("scrape_groups", {}).items()
        if d.get("n_runs", 0) > 0
    ]
    if groups_with_data:
        print(f"   Scrape groups with persisted metrics: {len(groups_with_data)}")
        for g in groups_with_data:
            print(f"     • {g}: {baseline['scrape_groups'][g]['n_runs']} files")

    return 0


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
