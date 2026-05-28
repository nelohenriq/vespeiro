"""Health monitoring for the scrape pipeline.

Runs at the end of each GitHub Actions scrape workflow and outputs a
summary to ``GITHUB_STEP_SUMMARY``.  Designed to replace Grafana — no
server needed.
"""

import os
from datetime import datetime, timedelta, timezone
from src.supabase.client import get_supabase


def get_source_health() -> list[dict]:
    """Query Supabase for per-source health metrics.

    Returns a list of dicts with keys ``source``, ``articles_24h``, and
    ``is_healthy``.  Returns an empty list if Supabase is not configured.
    """
    supabase = get_supabase()
    if supabase is None:
        return []

    # Get all sources from the DB
    sources = supabase.table("sources").select("*").execute()
    if not sources.data:
        return []

    yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    health_report: list[dict] = []

    for source in sources.data:
        slug = source.get("slug", source.get("id", "unknown"))
        result = (
            supabase.table("articles")
            .select("id", count="exact")
            .eq("source_id", slug)
            .gte("collected_at", yesterday)
            .execute()
        )
        article_count = result.count if hasattr(result, "count") else 0
        health_report.append({
            "source": slug,
            "articles_24h": article_count,
            "is_healthy": article_count > 0,
        })

    return health_report


def print_health_summary() -> None:
    """Print health summary to stdout (captured by GHA step summary)."""
    report = get_source_health()
    if not report:
        print("⚠️  Unable to query source health (Supabase not configured or empty)")
        return

    print()
    print("=" * 40)
    print("  📊 SOURCE HEALTH REPORT")
    print("=" * 40)
    for r in report:
        icon = "✅" if r["is_healthy"] else "❌"
        print(f"  {icon} {r['source']}: {r['articles_24h']} articles in 24h")
    print("=" * 40)
    print()


def write_gha_summary() -> None:
    """Write a Markdown summary block to ``GITHUB_STEP_SUMMARY``.

    Only works inside a GitHub Actions runner.
    """
    report = get_source_health()
    if not report:
        return

    lines = ["## 📊 Source Health\n", "| Source | Articles (24h) | Status |\n", "|-------|----------------|--------|\n"]
    for r in report:
        icon = "✅" if r["is_healthy"] else "❌"
        lines.append(f"| {r['source']} | {r['articles_24h']} | {icon} |\n")

    # Write to GHA step summary file if the env var is set
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.writelines(lines)
