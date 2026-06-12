#!/usr/bin/env python3
"""run_corruption_scan.py — Automated Corruption Detection Pipeline

Orchestrates all Analisa.pt detection tools in sequence with progress
tracking, error resilience, and consolidated reporting.

Pipeline phases:
  1. PREPARE  — Check data sources & optionally fetch new data
  2. DETECT   — Run all anomaly/pattern detection tools
  3. REPORT   — Save baselines, generate consolidated HTML report

Usage:
    python run_corruption_scan.py                          # Full pipeline
    python run_corruption_scan.py --steps prepare,detect   # Subset
    python run_corruption_scan.py --skip modifications      # Skip a step
    python run_corruption_scan.py --dry-run                 # Preview only
    python run_corruption_scan.py --export summary.json     # Export results
    python run_corruption_scan.py --steps prr              # PRR analysis only
"""

import json
import shutil
import subprocess
import sys
import time
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from utils import fmt
from utils_db import connect as db_connect

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SUMMARY_DIR = DATA_DIR / "summary"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_INDEX = DATA_DIR / "contract_index.json"
ANUNCIOS_DB = DATA_DIR / "anuncios_index.db"
TED_DB = DATA_DIR / "ted_notices.db"
MODIFICACOES_DB = DATA_DIR / "modificacoes_index.db"
TRANSPARENCY_DB = DATA_DIR / "transparency.db"
FINDINGS_MD = SCRIPT_DIR.parent / "FINDINGS.md"

# ── Tool paths ───────────────────────────────────────────────────────────────
TOOLS = {
    "anomaly_scanner": SCRIPT_DIR / "anomaly_scanner.py",
    "bid_pattern": SCRIPT_DIR / "bid_pattern_analyzer.py",
    "temporal": SCRIPT_DIR / "temporal_clustering.py",
    "supplier_profiler": SCRIPT_DIR / "supplier_cross_profiler.py",
    "price_gap": SCRIPT_DIR / "price_gap_analysis.py",
    "entity_network": SCRIPT_DIR / "entity_network.py",
    "municipality_risk": SCRIPT_DIR / "municipality_risk_report.py",
    "competitor_recover": SCRIPT_DIR / "competitor_recover.py",
    "contract_modifications": SCRIPT_DIR / "contract_modifications_analyzer.py",
    "anomaly_diff": SCRIPT_DIR / "anomaly_diff.py",
    "update_findings": SCRIPT_DIR / "update_findings.py",
    "data_quality": SCRIPT_DIR / "data_quality_report.py",
    "generate_dashboard": SCRIPT_DIR / "generate_corruption_dashboard.py",
    "transparency_scraper": SCRIPT_DIR / "transparency_scraper.py",
    "prr_dual_role_tool": SCRIPT_DIR / "prr_procurement_crossref.py",
    "prr_enhanced_tool": SCRIPT_DIR / "prr_base_cdgov_detector.py",
    "money_trail_tool": SCRIPT_DIR / "money_trail_analyzer.py",
    "generate_live_dashboard": SCRIPT_DIR / "generate_live_dashboard.py",
    "freguesia_analyzer": SCRIPT_DIR / "freguesia_contract_analyzer.py",
    "freguesia_downloader": SCRIPT_DIR / "freguesia_downloader.py",
    "freguesia_resolver": SCRIPT_DIR / "freguesia_resolver.py",
    "justice_scraper": SCRIPT_DIR / "justice_scraper.py",
    "ine_stats": SCRIPT_DIR / "ine_stats.py",
}

# ── Step definitions ─────────────────────────────────────────────────────────
PREPARE_STEPS = [
    "competitor",
    "modifications",
    "prr_download",
    "prr_index",
    "freguesia_download",
    "justice_download",
    "ine_download",
]

DETECT_STEPS = [
    "anomaly",
    "bid_pattern",
    "temporal",
    "suppliers",
    "price_gap",
    "entity_network",
    "municipality_risk",
    "modifications_analyze",
    "prr_crossref",
    "prr_dual_role",
    "prr_enhanced",
    "money_trail",
    "freguesia_corruption",
    "justice_crossref",
    "ine_crossref",
]

REPORT_STEPS = [
    "snapshot",
    "data_quality",
    "findings",
    "dashboard",
    "live_dashboard",
    "justice_dashboard",
    "summary",
]

ALL_STEPS = PREPARE_STEPS + DETECT_STEPS + REPORT_STEPS

# Human-readable labels for each step
STEP_LABELS = {
    "competitor": "Competitor Data Recovery",
    "modifications": "Contract Modifications (download & index)",
    "prr_download": "PRR Data (download from dados.gov.pt)",
    "prr_index": "PRR Data (index into SQLite)",
    "anomaly": "Anomaly Scanner",
    "bid_pattern": "Bid Pattern Analyzer",
    "temporal": "Temporal Contract Clustering",
    "suppliers": "Supplier Cross-Buyer Profiler",
    "price_gap": "Price Gap Analysis",
    "entity_network": "Entity Relationship Analysis",
    "municipality_risk": "Municipality Risk Report",
    "modifications_analyze": "Modifications Analysis",
    "prr_crossref": "PRR x Procurement Cross-Reference",
    "prr_dual_role": "PRR Dual-Role Analysis (sectors, trends, competition, mods, geo)",
    "prr_enhanced": "Enhanced PRR x BASE Detector (cd_base_gov, text similarity, Fundao)",
    "money_trail": "Money Trail Analyzer (PRR > Budget > Procurement pipeline)",
    "freguesia_download": "Freguesia Parish NIF Download (dados.gov.pt)",
    "freguesia_corruption": "Freguesia-Level Corruption Analysis",
    "justice_download": "Justice Data Download (dados.justica.gov.pt CKAN)",
    "justice_crossref": "Justice × Procurement Cross-Reference",
    "ine_download": "INE Statistics Download (pension, crime, immigration)",
    "ine_crossref": "INE Statistics × Procurement Cross-Reference",
    "snapshot": "Baseline Snapshot",
    "data_quality": "Data Quality Report",
    "findings": "Update Findings",
    "dashboard": "Consolidated Dashboard",
    "summary": "Export Summary",
    "live_dashboard": "Live Dashboard (reads all databases)",
    "justice_dashboard": "Justice Intelligence Dashboard",
}


# ═════════════════════════════════════════════════════════════════════════════
#  Pipeline Step
# ═════════════════════════════════════════════════════════════════════════════

class PipelineStep:
    """A single step in the corruption scan pipeline."""

    def __init__(
        self,
        step_id: str,
        label: str,
        run_func,
        timeout: int = 600,
        depends_on: Optional[list[str]] = None,
    ):
        self.step_id = step_id
        self.label = label
        self.run_func = run_func
        self.timeout = timeout
        self.depends_on = depends_on or []
        self.status: str = "pending"  # pending | running | passed | skipped | failed
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.result_data: Optional[dict] = None

    def run(self):
        self.status = "running"
        self.started_at = datetime.now(timezone.utc)
        try:
            self.run_func(self)
            self.status = "passed"
        except SkipStep:
            self.status = "skipped"
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
        finally:
            self.finished_at = datetime.now(timezone.utc)

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @property
    def icon(self) -> str:
        return {
            "pending": "[...]", "running": "[..]", "passed": "[OK]",
            "skipped": "[--]", "failed": "[!!]",
        }.get(self.status, "[??]")


class SkipStep(Exception):
    """Raised when a step should be skipped (e.g., missing dependency)."""
    pass


# ═════════════════════════════════════════════════════════════════════════════
#  Utilities
# ═════════════════════════════════════════════════════════════════════════════

def run_tool(step: PipelineStep, args: list[str], timeout: int = 300) -> str:
    """Run a tool as a subprocess and return stdout."""
    tool_key = args[0]
    tool_path = TOOLS.get(tool_key)
    if tool_path is None:
        raise FileNotFoundError(f"Unknown tool key: {tool_key} (not in TOOLS registry)")
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool script not found: {tool_path}")

    cmd = [sys.executable, str(tool_path)] + args[1:]
    print(f"  Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SCRIPT_DIR),
    )

    # Print stdout (progress + results from the tool)
    for line in result.stdout.split("\n"):
        if line.strip():
            print(f"    {line}")

    # Also print stderr lines (some tools write progress there)
    for line in result.stderr.split("\n"):
        stripped = line.strip()
        if stripped and stripped not in result.stdout:
            print(f"    {stripped}")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
        raise RuntimeError(f"Tool failed: {error_msg}")

    return result.stdout


def check_db(db_path: Path) -> bool:
    """Check if a database file exists and has content."""
    return db_path.exists() and db_path.stat().st_size > 1000


def json_safe(val):
    """Safely convert a value for JSON serialization."""
    if isinstance(val, set):
        return list(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


# ═════════════════════════════════════════════════════════════════════════════
#  Phase: PREPARE
# ═════════════════════════════════════════════════════════════════════════════

def step_competitor(step: PipelineStep):
    """Fetch missing competitor data from BASE.gov.pt and apply to DB."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    stats = run_tool(step, ["competitor_recover", "stats"])
    step.result_data = {"stats_output": stats}

    print("  Fetching competitor data (limit=100)...")
    run_tool(step, ["competitor_recover", "fetch", "--limit", "100"])

    print("  Applying cached data to DB...")
    run_tool(step, ["competitor_recover", "apply"])

    print("  Verifying coverage improvement...")
    stats2 = run_tool(step, ["competitor_recover", "stats"])
    step.result_data["after_fetch"] = stats2


def step_modifications(step: PipelineStep):
    """Download and index contract modifications data."""
    print("  Downloading modifications XLSX from dados.gov.pt...")
    try:
        run_tool(step, ["contract_modifications", "download"], timeout=120)
    except RuntimeError as e:
        raise SkipStep(f"Download failed: {e}")

    print("  Indexing modifications into SQLite...")
    run_tool(step, ["contract_modifications", "index"], timeout=300)


def step_prr_download(step: PipelineStep):
    """Download PRR datasets from dados.gov.pt."""
    print("  Downloading PRR datasets (8 files) from dados.gov.pt...")
    try:
        run_tool(step, ["transparency_scraper", "download", "--type", "prr"], timeout=120)
    except RuntimeError as e:
        raise SkipStep(f"PRR download failed: {e}")

    print("  Downloading budget datasets (4 files) from dados.gov.pt...")
    try:
        run_tool(step, ["transparency_scraper", "download", "--type", "budget"], timeout=120)
    except RuntimeError as e:
        print(f"    Budget download failed (non-fatal): {e}")


def step_prr_index(step: PipelineStep):
    """Index PRR XLSX files into SQLite."""
    print("  Indexing PRR + budget data into transparency.db...")
    try:
        run_tool(step, ["transparency_scraper", "index"], timeout=300)
    except RuntimeError as e:
        raise SkipStep(f"PRR index failed: {e}")

    # Show stats
    print("  PRR database statistics...")
    run_tool(step, ["transparency_scraper", "stats"])


# ═════════════════════════════════════════════════════════════════════════════
#  Phase: DETECT
# ═════════════════════════════════════════════════════════════════════════════

def step_anomaly(step: PipelineStep):
    """Run multi-signal anomaly scanner and export results."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "anomalies.json"
    export_path.parent.mkdir(parents=True, exist_ok=True)

    run_tool(step, ["anomaly_scanner", "--export", str(export_path)])

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = data.get("summary", {})


def step_bid_pattern(step: PipelineStep):
    """Detect rotating winners, bid suppression, closed bidder groups."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "bid_patterns.json"
    run_tool(step, ["bid_pattern", "--export", str(export_path)])

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = data.get("summary", {})


def step_temporal(step: PipelineStep):
    """Detect temporal clustering and suspicious timing patterns."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "temporal_bursts.json"
    run_tool(step, ["temporal", "--export", str(export_path)])

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = data.get("summary", {})


def step_suppliers(step: PipelineStep):
    """Profile top suppliers by cross-buyer reach."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "top_suppliers.json"
    output = run_tool(step, ["supplier_profiler", "--top", "30"])
    step.result_data = {"output": output}


def step_price_gap(step: PipelineStep):
    """Cross-reference anúncios with signed contracts for price gaps."""
    if not check_db(ANUNCIOS_DB):
        raise SkipStep("anuncios_index.db not found")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "price_gaps.json"
    run_tool(step, ["price_gap", "--export", str(export_path)], timeout=120)
    run_tool(step, ["price_gap", "--stats"])

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        thresholds = {10: 0, 25: 0, 50: 0, 100: 0}
        for m in data:
            gpct = m.get("gap_pct", 0)
            for t in thresholds:
                if gpct > t:
                    thresholds[t] += 1
        step.result_data = {
            "total_matches": len(data),
            "thresholds": thresholds,
        }


def step_entity_network(step: PipelineStep):
    """Analyze buyer-seller relationships, self-referencing, and cross-municipality."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "entity_network.json"
    run_tool(step, ["entity_network", "export", "--output", str(export_path)])
    run_tool(step, ["entity_network", "analyze"])
    run_tool(step, ["entity_network", "self-ref"])
    run_tool(step, ["entity_network", "cross-municipality", "--top", "20"])

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = data.get("stats", {})


def step_municipality_risk(step: PipelineStep):
    """Run municipality-level combined risk scoring."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "municipality_risk.json"
    run_tool(step, ["municipality_risk", "--export", str(export_path)])

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = data.get("summary", {})


def step_modifications_analyze(step: PipelineStep):
    """Analyze contract modifications for suspicious patterns."""
    if not check_db(MODIFICACOES_DB):
        raise SkipStep("modificacoes_index.db not found — run 'prepare' first")

    run_tool(step, ["contract_modifications", "stats"])
    run_tool(step, ["contract_modifications", "suspicious"])
    run_tool(step, ["contract_modifications", "inflation"])

    step.result_data = {"analyzed": True}


def step_prr_crossref(step: PipelineStep):
    """Run PRR x Procurement basic cross-reference."""
    if not check_db(TRANSPARENCY_DB):
        raise SkipStep("transparency.db not found — run 'prr_index' first")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "prr_crossref.json"
    run_tool(step, ["transparency_scraper", "crossref"])
    run_tool(step, ["transparency_scraper", "prr"])

    # Also export PRR data
    run_tool(step, ["transparency_scraper", "export", "--out", str(export_path)])


def step_prr_dual_role(step: PipelineStep):
    """Run full PRR dual-role analysis with all 5 extended analyses."""
    if not check_db(TRANSPARENCY_DB):
        raise SkipStep("transparency.db not found — run 'prr_index' first")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "prr_dual_role_scan.json"
    run_tool(step, [
        "prr_dual_role_tool", "all",
        "--export", str(export_path),
    ], timeout=600)

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = {
            "total_dual_role_entities": data.get("total_dual_role_entities", 0),
            "high_risk": data.get("summary", {}).get("high_risk", 0),
        }


def step_prr_enhanced(step: PipelineStep):
    """Run enhanced PRR x BASE corruption pattern detector.

    Adds 3 extra match dimensions beyond NIF-level matching:
      1. cd_base_gov -> nAnuncio contract-level matching
      2. Object-of-contract text similarity
      3. Composite risk (all dimensions combined)
      4. Fundao deep-dive
    """
    if not check_db(TRANSPARENCY_DB):
        raise SkipStep("transparency.db not found — run 'prr_index' first")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "prr_enhanced_scan.json"
    run_tool(step, [
        "prr_enhanced_tool", "all",
        "--top", "50",
        "--export", str(export_path),
    ], timeout=600)

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        step.result_data = {
            "cdbg_matches": data.get("cd_base_gov", {}).get("total_matched", 0),
            "text_matches": data.get("text_similarity", {}).get("unique_prr_matched", 0),
            "composite_high_risk": data.get("composite_risk", {}).get("high_risk_count", 0),
        }


def step_money_trail(step: PipelineStep):
    """Run the money trail analyzer -- traces PRR -> Budget -> Procurement pipeline.

    For each concelho with PRR data, measures:
      - Phase 1: PRR allocated vs paid
      - Phase 2: Budget previsto vs realizado
      - Phase 3: Procurement contracts, inflation, concentration
      - Chain: ratios between phases, anomaly detection
    """
    if not check_db(TRANSPARENCY_DB):
        raise SkipStep("transparency.db not found — run 'prr_index' first")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    export_path = SUMMARY_DIR / "money_trail.json"
    run_tool(step, [
        "money_trail_tool", "--concelho", "Fundão",
        "--verbose",
        "--export", str(export_path),
    ], timeout=600)

    if export_path.exists():
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        chain = data.get("chain", {})
        phase1 = data.get("phase1_prr", {})
        phase3 = data.get("phase3_procurement", {})
        step.result_data = {
            "prr_aprovado": phase1.get("total_aprovado", 0),
            "prr_pago": phase1.get("total_pago", 0),
            "prr_execution_pct": phase1.get("execution_rate_pct", 0),
            "proc_contracts": phase3.get("total_contracts", 0),
            "proc_value": phase3.get("total_value", 0),
            "inflated_count": phase3.get("inflated_count", 0),
            "top3_share": phase3.get("top3_share", 0),
            "anomalies": chain.get("total_anomalies", 0),
            "critical_anomalies": chain.get("critical_anomalies", 0),
        }


def step_freguesia_download(step: PipelineStep):
    """Download official freguesia parish NIF database from dados.gov.pt.

    Downloads the Freguesiasdadosgerais.xlsx dataset containing ~3,000 parishes
    with their NIFs, INE codes, municipality names, and district names.
    This data is used by freguesia_resolver.py for parish-level resolution.
    """
    nif_db = DATA_DIR / "freguesia_nif_database.json"
    if nif_db.exists():
        # Check if data is recent (within 7 days)
        age_days = (time.time() - nif_db.stat().st_mtime) / 86400
        if age_days < 7:
            print(f"  NIF database is {age_days:.1f} days old — skipping download")
            step.result_data = {"skipped": True, "age_days": round(age_days, 1)}
            return
        print(f"  NIF database is {age_days:.0f} days old — refreshing...")

    print("  Downloading freguesia parish NIF database from dados.gov.pt...")
    try:
        run_tool(step, ["freguesia_downloader", "download"], timeout=120)
    except RuntimeError as e:
        raise SkipStep(f"Freguesia download failed: {e}")

    # Show stats
    print("  Freguesia NIF database statistics...")
    run_tool(step, ["freguesia_downloader", "stats"])

    step.result_data = {"downloaded": True}


def step_justice_download(step: PipelineStep):
    """Download justice datasets from dados.justica.gov.pt CKAN API."""
    justice_db = DATA_DIR / "justice.db"
    if justice_db.exists():
        age_days = (time.time() - justice_db.stat().st_mtime) / 86400
        if age_days < 7:
            print(f"  justice.db is {age_days:.1f} days old — skipping download")
            step.result_data = {"skipped": True, "age_days": round(age_days, 1)}
            return
        print(f"  justice.db is {age_days:.0f} days old — refreshing...")

    print("  Downloading justice datasets from dados.justica.gov.pt...")
    try:
        run_tool(step, ["justice_scraper", "download"], timeout=300)
    except RuntimeError as e:
        raise SkipStep(f"Justice download failed: {e}")

    print("  Indexing justice data into SQLite...")
    try:
        run_tool(step, ["justice_scraper", "index"], timeout=300)
    except RuntimeError as e:
        raise SkipStep(f"Justice index failed: {e}")

    step.result_data = {"downloaded": True}


def step_justice_crossref(step: PipelineStep):
    """Cross-reference justice corruption data with procurement anomalies.

    Produces risk signals by comparing:
    - Corruption/money-laundering case trends from justice.db
    - Court backlog and pending-case trends from justice.db
    - Price inflation, direct awards, and seller concentration from procurement.db

    Results exported to summary/justice_crossref.json.
    """
    justice_db = DATA_DIR / "justice.db"
    if not check_db(justice_db):
        raise SkipStep("justice.db not found — run justice_download first")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    # ── Deep cross-reference via SQL ──────────────────────────────────────
    risk_signals = []
    result = {}

    import sqlite3 as _sqlite3

    # Helper: 3-year trend direction
    def _trend_direction(trend):
        if len(trend) < 4:
            return "insufficient_data", 0.0
        recent = [t["cases"] for t in trend[-3:]]
        earlier = [t["cases"] for t in trend[-6:-3]]
        if not earlier or sum(earlier) == 0:
            return "insufficient_data", 0.0
        recent_avg = sum(recent) / len(recent)
        earlier_avg = sum(earlier) / len(earlier)
        pct_change = ((recent_avg - earlier_avg) / earlier_avg) * 100
        if pct_change > 20:
            return "rising", pct_change
        elif pct_change < -20:
            return "falling", pct_change
        return "stable", pct_change

    # ══════════════════════════════════════════════════════════════════════
    # SECTION A: Justice data (justice.db) — small, fast, reliable
    # ══════════════════════════════════════════════════════════════════════
    jconn = None
    try:
        jconn = db_connect(str(justice_db), timeout=30)
        jconn.row_factory = _sqlite3.Row

        # ── 1. Corruption case trends ────────────────────────────────────
        corruption_trend = []
        for row in jconn.execute("""
            SELECT year, SUM(value) as total
            FROM corruption_cases
            WHERE dataset = 'corrupcaopj' AND year IS NOT NULL AND value IS NOT NULL
            GROUP BY year ORDER BY year
        """).fetchall():
            corruption_trend.append({"year": row["year"], "cases": row["total"]})

        laundering_trend = []
        for row in jconn.execute("""
            SELECT year, SUM(value) as total
            FROM corruption_cases
            WHERE dataset = 'branqueamentopj' AND year IS NOT NULL AND value IS NOT NULL
            GROUP BY year ORDER BY year
        """).fetchall():
            laundering_trend.append({"year": row["year"], "cases": row["total"]})

        cor_dir, cor_pct = _trend_direction(corruption_trend)
        lau_dir, lau_pct = _trend_direction(laundering_trend)

        if cor_dir == "rising":
            risk_signals.append({
                "signal": "corruption_cases_rising",
                "severity": "high" if cor_pct > 50 else "medium",
                "detail": f"Corruption cases {cor_pct:+.0f}% over 3-year trend",
                "trend": corruption_trend,
            })

        if lau_dir == "rising":
            risk_signals.append({
                "signal": "money_laundering_rising",
                "severity": "high" if lau_pct > 50 else "medium",
                "detail": f"Money laundering cases {lau_pct:+.0f}% over 3-year trend",
                "trend": laundering_trend,
            })

        result["corruption_trend"] = corruption_trend
        result["laundering_trend"] = laundering_trend
        result["corruption_direction"] = cor_dir
        result["laundering_direction"] = lau_dir

        # ── 2. Court backlog trends ──────────────────────────────────────
        court_trend = []
        for row in jconn.execute("""
            SELECT year, SUM(entered) as entered, SUM(finalized) as finalized,
                   SUM(pending) as pending
            FROM court_movements WHERE year IS NOT NULL
            GROUP BY year ORDER BY year
        """).fetchall():
            court_trend.append({
                "year": row["year"],
                "entered": row["entered"] or 0,
                "finalized": row["finalized"] or 0,
                "pending": row["pending"] or 0,
            })

        if court_trend:
            latest = court_trend[-1]
            if latest["entered"] > 0:
                backlog_ratio = latest["pending"] / latest["entered"]
                if backlog_ratio > 0.5:
                    risk_signals.append({
                        "signal": "court_backlog_high",
                        "severity": "high" if backlog_ratio > 1.0 else "medium",
                        "detail": f"Court backlog ratio {backlog_ratio:.2f} ({latest['pending']:,} pending / {latest['entered']:,} entered in {latest['year']})",
                    })

        result["court_trend"] = court_trend

        # ── 3. Prison population trend ───────────────────────────────────
        prison_trend = []
        for row in jconn.execute("""
            SELECT year, SUM(count) as total
            FROM prison_population WHERE year IS NOT NULL
            GROUP BY year ORDER BY year
        """).fetchall():
            prison_trend.append({"year": row["year"], "total": row["total"] or 0})

        result["prison_trend"] = prison_trend
        print(f"  Justice data loaded: {len(corruption_trend)} corruption years, {len(court_trend)} court years")

    except Exception as e:
        print(f"    Justice data error (non-fatal, will still export): {e}")
        result["justice_error"] = str(e)
    finally:
        if jconn:
            jconn.close()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION B: Procurement data (procurement.db) — 1.9GB, may fail
    # ══════════════════════════════════════════════════════════════════════
    pconn = None
    try:
        pconn = db_connect(str(PROCUREMENT_DB), timeout=60)
        pconn.row_factory = _sqlite3.Row

        # Create indexes in separate connection to avoid locking
        print("  Ensuring procurement indexes...")
        try:
            idx_conn = db_connect(str(PROCUREMENT_DB), timeout=30)
            idx_conn.execute("CREATE INDEX IF NOT EXISTS idx_proc_price ON contratos(precoContratual)")
            idx_conn.execute("CREATE INDEX IF NOT EXISTS idx_proc_base ON contratos(precoBaseProcedimento)")
            idx_conn.execute("CREATE INDEX IF NOT EXISTS idx_proc_ano ON contratos(Ano)")
            idx_conn.commit()
            idx_conn.close()
        except Exception as e:
            print(f"    Index creation skipped ({e}) — queries may be slower")

        # Scope to last 5 years for speed on 1.9GB database
        latest_ano = pconn.execute(
            "SELECT MAX(Ano) FROM contratos WHERE Ano IS NOT NULL"
        ).fetchone()[0]
        min_ano = (latest_ano or 2024) - 5 if latest_ano else 2019

        # Price inflation
        inflated = pconn.execute("""
            SELECT COUNT(*) as n FROM contratos
            WHERE Ano >= ? AND precoBaseProcedimento > 0
            AND precoContratual > precoBaseProcedimento * 1.05
        """, (min_ano,)).fetchone()["n"]

        total_priced = pconn.execute("""
            SELECT COUNT(*) as n FROM contratos
            WHERE Ano >= ? AND precoBaseProcedimento > 0 AND precoContratual > 0
        """, (min_ano,)).fetchone()["n"]

        inflation_rate = (inflated / total_priced * 100) if total_priced > 0 else 0

        if inflation_rate > 15:
            risk_signals.append({
                "signal": "procurement_price_inflation",
                "severity": "high" if inflation_rate > 30 else "medium",
                "detail": f"{inflation_rate:.1f}% of contracts show >5% price inflation ({inflated:,}/{total_priced:,}) since {min_ano}",
            })

        # Direct awards
        direct = pconn.execute("""
            SELECT COUNT(*) as n FROM contratos
            WHERE Ano >= ? AND tipoprocedimento LIKE '%ajuste direto%'
        """, (min_ano,)).fetchone()["n"]

        total_contracts = pconn.execute(
            "SELECT COUNT(*) as n FROM contratos WHERE Ano >= ?", (min_ano,)
        ).fetchone()["n"]

        direct_rate = (direct / total_contracts * 100) if total_contracts > 0 else 0

        if direct_rate > 40:
            risk_signals.append({
                "signal": "procurement_direct_awards_high",
                "severity": "high" if direct_rate > 60 else "medium",
                "detail": f"{direct_rate:.1f}% direct awards ({direct:,}/{total_contracts:,}) since {min_ano}",
            })

        # Seller concentration: top-3 sellers by total value share
        top3 = pconn.execute("""
            SELECT SUM(v) as v FROM (
                SELECT adjudicatarios, SUM(precoContratual) as v
                FROM contratos
                WHERE Ano >= ? AND adjudicatarios != '' AND precoContratual > 0
                GROUP BY adjudicatarios
                ORDER BY v DESC
                LIMIT 3
            )
        """, (min_ano,)).fetchone()["v"] or 0

        total_proc_value = pconn.execute("""
            SELECT SUM(precoContratual) as v FROM contratos
            WHERE Ano >= ? AND precoContratual > 0
        """, (min_ano,)).fetchone()["v"] or 0

        top3_share = (top3 / total_proc_value * 100) if total_proc_value > 0 else 0

        if top3_share > 30:
            risk_signals.append({
                "signal": "procurement_seller_concentration",
                "severity": "high" if top3_share > 50 else "medium",
                "detail": f"Top 3 sellers hold {top3_share:.1f}% of procurement value",
            })

        result["procurement"] = {
            "total_contracts": total_contracts,
            "inflated_count": inflated,
            "inflation_rate_pct": round(inflation_rate, 1),
            "direct_awards": direct,
            "direct_rate_pct": round(direct_rate, 1),
            "top3_share_pct": round(top3_share, 1),
            "total_value": total_proc_value,
        }
        print(f"  Procurement data loaded: {total_contracts:,} contracts since {min_ano}")

    except Exception as e:
        print(f"    Procurement data error (non-fatal, justice data preserved): {e}")
        result["procurement_error"] = str(e)
    finally:
        if pconn:
            pconn.close()

    # ══════════════════════════════════════════════════════════════════════
    # SECTION C: Composite risk score (uses whatever data succeeded)
    # ══════════════════════════════════════════════════════════════════════
    severity_weights = {"high": 3, "medium": 2, "low": 1}
    composite_score = sum(
        severity_weights.get(s["severity"], 1) for s in risk_signals
    )

    if len(risk_signals) >= 4 or composite_score >= 8:
        risk_level = "critical"
    elif len(risk_signals) >= 2 or composite_score >= 4:
        risk_level = "elevated"
    else:
        risk_level = "normal"

    result["risk_signals"] = risk_signals
    result["composite_score"] = composite_score
    result["risk_level"] = risk_level

    # ── Print summary ────────────────────────────────────────────────────
    cor_dir = result.get("corruption_direction", "?")
    lau_dir = result.get("laundering_direction", "?")
    cor_pct = 0
    lau_pct = 0
    proc = result.get("procurement", {})
    total_contracts = proc.get("total_contracts", 0)
    inflation_rate = proc.get("inflation_rate_pct", 0)
    direct_rate = proc.get("direct_rate_pct", 0)

    print(f"\n  ── Justice × Procurement Cross-Reference ──")
    print(f"  Corruption cases:   {len(result.get('corruption_trend', []))} years, trend={cor_dir}")
    print(f"  Money laundering:   {len(result.get('laundering_trend', []))} years, trend={lau_dir}")
    print(f"  Court backlog:      {len(result.get('court_trend', []))} years")
    print(f"  Procurement:        {total_contracts:,} contracts, inflation={inflation_rate}%, direct={direct_rate}%")
    print(f"  Risk signals:       {len(risk_signals)} (composite={composite_score}, level={risk_level})")
    for sig in risk_signals:
        print(f"    ⚠️  [{sig['severity'].upper()}] {sig['detail']}")
    if result.get("justice_error"):
        print(f"  ⚠️  Justice data error: {result['justice_error']}")
    if result.get("procurement_error"):
        print(f"  ⚠️  Procurement data error: {result['procurement_error']}")

    # Export cross-reference results
    export_path = SUMMARY_DIR / "justice_crossref.json"
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=json_safe)
    print(f"  Exported: {export_path}")

    step.result_data = result


def step_ine_download(step: PipelineStep):
    """Download INE statistics (pension, crime, immigration)."""
    ine_db = DATA_DIR / "ine_stats.db"
    if ine_db.exists():
        age_days = (time.time() - ine_db.stat().st_mtime) / 86400
        if age_days < 7:
            print(f"  ine_stats.db is {age_days:.1f} days old — skipping download")
            step.result_data = {"skipped": True, "age_days": round(age_days, 1)}
            return
        print(f"  ine_stats.db is {age_days:.0f} days old — refreshing...")

    print("  Downloading INE indicators (pension, crime, immigration)...")
    try:
        run_tool(step, ["ine_stats", "download"], timeout=300)
    except RuntimeError as e:
        raise SkipStep(f"INE download failed: {e}")

    print("  Indexing INE data into SQLite...")
    try:
        run_tool(step, ["ine_stats", "index"], timeout=300)
    except RuntimeError as e:
        raise SkipStep(f"INE index failed: {e}")

    step.result_data = {"downloaded": True}


def step_ine_crossref(step: PipelineStep):
    """Cross-reference INE social indicators with procurement patterns."""
    ine_db = DATA_DIR / "ine_stats.db"
    if not check_db(ine_db):
        raise SkipStep("ine_stats.db not found — run ine_download first")
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    print("  INE statistics overview...")
    run_tool(step, ["ine_stats", "stats"])

    # Cross-reference summary
    try:
        import sqlite3 as _sqlite3
        iconn = db_connect(str(ine_db))
        pconn = db_connect(str(PROCUREMENT_DB))

        ine_total = iconn.execute("SELECT COUNT(*) FROM ine_observations").fetchone()[0]
        ine_indicators = iconn.execute(
            "SELECT COUNT(DISTINCT indicator_code) FROM ine_observations"
        ).fetchone()[0]

        proc_count = pconn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]

        step.result_data = {
            "ine_observations": ine_total,
            "ine_indicators": ine_indicators,
            "procurement_contracts": proc_count,
            "crossref": True,
        }

        iconn.close()
        pconn.close()
    except Exception as e:
        print(f"    Cross-ref summary error (non-fatal): {e}")
        step.result_data = {"crossref": True, "error": str(e)}


def step_freguesia_corruption(step: PipelineStep):
    """Run parish-level corruption pattern detection.

    First ensures ine_* columns are populated in contratos table
    (via freguesia_resolver.py update), then runs all 5 analysis modes:
      - spending: top municipalities by resolved location
      - entities: freguesia entities as buyers (juntas de freguesia)
      - sellers: companies dominating parish procurement
      - cross-parish: sellers operating across multiple municipalities
      - corruption: concentration, inflation, self-ref, direct award excess
    """
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    # Check if ine_* columns exist — if not, run resolver update first
    try:
        import sqlite3 as _sqlite3
        _conn = db_connect(str(PROCUREMENT_DB))
        _conn.execute("SELECT ine_municipality FROM contratos LIMIT 1")
        _conn.close()
    except Exception:
        print("  ine_* columns not found — running freguesia_resolver.py update...")
        try:
            run_tool(step, ["freguesia_resolver", "update"], timeout=600)
        except RuntimeError as e:
            raise SkipStep(f"Freguesia resolver update failed: {e}")

    # Run all 5 analysis modes
    print("  Running parish-level spending analysis...")
    run_tool(step, ["freguesia_analyzer", "spending", "--top", "20"])

    print("  Running freguesia entity analysis...")
    run_tool(step, ["freguesia_analyzer", "entities", "--top", "20"])

    print("  Running cross-parish seller analysis...")
    run_tool(step, ["freguesia_analyzer", "sellers", "--min-contracts", "5"])

    print("  Running cross-municipality analysis...")
    run_tool(step, ["freguesia_analyzer", "cross-parish", "--min-parishes", "3"])

    print("  Running freguesia corruption pattern detection...")
    run_tool(step, ["freguesia_analyzer", "corruption"])

    step.result_data = {"analyzed": True, "mode": "freguesia_corruption"}


# ═════════════════════════════════════════════════════════════════════════════
#  Phase: REPORT
# ═════════════════════════════════════════════════════════════════════════════

def step_snapshot(step: PipelineStep):
    """Save baseline snapshot for future diff comparison."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    run_tool(step, ["anomaly_diff", "save"])
    run_tool(step, ["anomaly_diff", "save-muni"])
    run_tool(step, ["anomaly_diff", "history"])


def step_data_quality(step: PipelineStep):
    """Generate data quality report."""
    try:
        run_tool(step, ["data_quality"])
    except (FileNotFoundError, RuntimeError) as e:
        raise SkipStep(f"Data quality report failed: {e}")


def step_findings(step: PipelineStep):
    """Check for new data inconsistencies and update findings."""
    if not FINDINGS_MD.exists():
        raise SkipStep("FINDINGS.md not found")
    run_tool(step, ["update_findings", "--check"])


def step_dashboard(step: PipelineStep):
    """Generate the comprehensive consolidated corruption dashboard."""
    if not check_db(PROCUREMENT_DB):
        raise SkipStep("procurement.db not found")

    dashboard_path = SUMMARY_DIR / "corruption_dashboard.html"
    run_tool(step, [
        "generate_dashboard",
        "--top", "50",
        "--output", str(dashboard_path),
    ], timeout=600)

    step.result_data = {"dashboard_path": str(dashboard_path)}


def step_live_dashboard(step: PipelineStep):
    """Generate the live dashboard by querying all SQLite databases directly."""
    run_tool(step, [
        "generate_live_dashboard",
        "-o", str(SUMMARY_DIR / "live_dashboard.html"),
    ])

    step.result_data = {"dashboard_path": str(SUMMARY_DIR / "live_dashboard.html")}


def step_justice_dashboard(step: PipelineStep):
    """Generate the justice × procurement intelligence dashboard."""
    dashboard_path = SUMMARY_DIR / "justice_intelligence.html"
    run_tool(step, [
        "generate_justice_dashboard",
        "-o", str(dashboard_path),
    ])
    step.result_data = {"dashboard_path": str(dashboard_path)}


def step_summary(step: PipelineStep):
    """Export consolidated summary as JSON."""
    context = getattr(step, "context", None)
    all_steps = context.steps if context else [step]

    summary = {
        "pipeline_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "summary": {},
    }

    n_passed = 0
    n_failed = 0
    n_skipped = 0
    for s in all_steps:
        summary["steps"][s.step_id] = {
            "label": s.label,
            "status": s.status,
            "duration": s.duration,
            "error": s.error,
        }
        if s.status == "passed":
            n_passed += 1
        elif s.status == "failed":
            n_failed += 1
        elif s.status == "skipped":
            n_skipped += 1

    summary["summary"] = {
        "total_steps": len(all_steps),
        "passed": n_passed,
        "failed": n_failed,
        "skipped": n_skipped,
    }

    key_findings: list[dict] = []
    for s in all_steps:
        if s.status == "passed" and s.result_data:
            key_findings.append({
                "step": s.step_id,
                "label": s.label,
                "data": json_safe(s.result_data),
            })
    summary["key_findings"] = key_findings

    export_path = SUMMARY_DIR / "scan_summary.json"
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"  Summary exported to {export_path}")

    print(f"\n  {'=' * 60}")
    print(f"  Pipeline Summary: {n_passed} passed, {n_failed} failed, {n_skipped} skipped")
    print(f"  {'=' * 60}")
    for s in all_steps:
        print(f"  {s.icon} {s.label:<35} {s.status:>8}"
              + (f"  ({s.duration:.1f}s)" if s.duration else "")
              + (f"  [ERR] {s.error[:60]}" if s.error else ""))
    print(f"\n  All exports saved to: {SUMMARY_DIR.resolve()}")

    step.result_data = summary["summary"]


# ═════════════════════════════════════════════════════════════════════════════
#  Step Registry
# ═════════════════════════════════════════════════════════════════════════════

STEP_REGISTRY = {
    # PREPARE
    "competitor": PipelineStep("competitor", "Competitor Data Recovery", step_competitor, timeout=600),
    "modifications": PipelineStep("modifications", "Contract Modifications", step_modifications, timeout=600),
    "prr_download": PipelineStep("prr_download", "PRR Download", step_prr_download, timeout=300),
    "prr_index": PipelineStep("prr_index", "PRR Index", step_prr_index, timeout=300),
    # DETECT
    "anomaly": PipelineStep("anomaly", "Anomaly Scanner", step_anomaly, timeout=300),
    "bid_pattern": PipelineStep("bid_pattern", "Bid Pattern Analyzer", step_bid_pattern, timeout=300),
    "temporal": PipelineStep("temporal", "Temporal Clustering", step_temporal, timeout=300),
    "suppliers": PipelineStep("suppliers", "Supplier Cross-Profiler", step_suppliers, timeout=300),
    "price_gap": PipelineStep("price_gap", "Price Gap Analysis", step_price_gap, timeout=300),
    "entity_network": PipelineStep("entity_network", "Entity Network Analysis", step_entity_network, timeout=300),
    "municipality_risk": PipelineStep("municipality_risk", "Municipality Risk Report", step_municipality_risk, timeout=300),
    "modifications_analyze": PipelineStep("modifications_analyze", "Modifications Analysis", step_modifications_analyze, timeout=300),
    "prr_crossref": PipelineStep("prr_crossref", "PRR Cross-Reference", step_prr_crossref, timeout=300),
    "prr_dual_role": PipelineStep("prr_dual_role", "PRR Dual-Role Analysis", step_prr_dual_role, timeout=600),
    "prr_enhanced": PipelineStep("prr_enhanced", "Enhanced PRR x BASE Detector", step_prr_enhanced, timeout=600),
    "money_trail": PipelineStep("money_trail", "Money Trail Analyzer", step_money_trail, timeout=600),
    "freguesia_download": PipelineStep("freguesia_download", "Freguesia NIF Download", step_freguesia_download, timeout=120),
    "freguesia_corruption": PipelineStep("freguesia_corruption", "Freguesia Corruption Analysis", step_freguesia_corruption, timeout=600),
    "justice_download": PipelineStep("justice_download", "Justice Data Download", step_justice_download, timeout=300),
    "justice_crossref": PipelineStep("justice_crossref", "Justice x Procurement Cross-Reference", step_justice_crossref, timeout=600),
    "ine_download": PipelineStep("ine_download", "INE Statistics Download", step_ine_download, timeout=300),
    "ine_crossref": PipelineStep("ine_crossref", "INE Statistics x Procurement Cross-Reference", step_ine_crossref, timeout=300),
    # REPORT
    "snapshot": PipelineStep("snapshot", "Baseline Snapshot", step_snapshot, timeout=120),
    "data_quality": PipelineStep("data_quality", "Data Quality Report", step_data_quality, timeout=120),
    "findings": PipelineStep("findings", "Update Findings", step_findings, timeout=120),
    "dashboard": PipelineStep("dashboard", "Consolidated Dashboard", step_dashboard, timeout=300),
    "live_dashboard": PipelineStep("live_dashboard", "Live Dashboard", step_live_dashboard, timeout=600),
    "justice_dashboard": PipelineStep("justice_dashboard", "Justice Intelligence Dashboard", step_justice_dashboard, timeout=600),
    "summary": PipelineStep("summary", "Export Summary", step_summary, timeout=60),
}


# ═════════════════════════════════════════════════════════════════════════════
#  Pipeline Runner
# ═════════════════════════════════════════════════════════════════════════════

class PipelineContext:
    """Shared context passed through pipeline steps."""
    def __init__(self, steps: list):
        self.steps = steps
        self.data: dict[str, Any] = {}


class PipelineRunner:
    """Orchestrate execution of pipeline steps."""

    def __init__(self, steps_to_run: list[str], dry_run: bool = False):
        self.steps_to_run = steps_to_run
        self.dry_run = dry_run
        self.steps: list[PipelineStep] = []
        self._build_steps()

    def _build_steps(self):
        for step_id in self.steps_to_run:
            if step_id in STEP_REGISTRY:
                self.steps.append(STEP_REGISTRY[step_id])
            else:
                print(f"  [WARN] Unknown step: {step_id}", file=sys.stderr)

    def run(self):
        """Execute all steps in order."""
        if not self.steps:
            print("No steps to run.")
            return

        print(f"\n{'=' * 80}")
        print(f"  == ANALISA.PT -- CORRUPTION DETECTION PIPELINE")
        print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"  Steps: {len(self.steps)}")
        if self.dry_run:
            print(f"  [WARN] DRY RUN -- no commands will execute")
        print(f"{'=' * 80}\n")

        context = PipelineContext(self.steps)
        for step in self.steps:
            step.context = context

        for i, step in enumerate(self.steps, 1):
            print(f"\n{'-' * 70}")
            print(f"  [{i}/{len(self.steps)}] {step.icon} {step.label}")
            print(f"{'-' * 70}")

            if self.dry_run:
                step.status = "skipped"
                continue

            step.run()

            if step.status == "passed":
                print(f"  [OK] {step.label} -- completed in {step.duration:.1f}s")
            elif step.status == "skipped":
                print(f"  [--] {step.label} -- skipped")
            elif step.status == "failed":
                print(f"  [!!] {step.label} -- FAILED: {step.error[:80]}")
                if step.error:
                    print(f"     {step.error}")

        n_passed = sum(1 for s in self.steps if s.status == "passed")
        n_failed = sum(1 for s in self.steps if s.status == "failed")

        print(f"\n{'=' * 80}")
        if n_failed == 0:
            print(f"  [OK] PIPELINE COMPLETE -- {n_passed}/{len(self.steps)} steps passed")
        else:
            print(f"  [WARN] PIPELINE FINISHED -- {n_passed} passed, {n_failed} failed,"
                  f" {len(self.steps) - n_passed - n_failed} skipped")
        print(f"{'=' * 80}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def resolve_steps(args) -> list[str]:
    """Resolve which steps to run based on CLI args."""
    if args.steps:
        selected = []
        for chunk in args.steps.split(","):
            chunk = chunk.strip()
            if chunk == "all":
                selected = ALL_STEPS[:]
                break
            elif chunk == "prepare":
                selected.extend(PREPARE_STEPS)
            elif chunk == "detect":
                selected.extend(DETECT_STEPS)
            elif chunk == "report":
                selected.extend(REPORT_STEPS)
            elif chunk == "prr":
                selected.extend(["prr_download", "prr_index", "prr_crossref", "prr_dual_role", "prr_enhanced"])
            elif chunk == "money":
                selected.extend(["money_trail"])
            elif chunk == "justice":
                selected.extend(["justice_download", "justice_crossref"])
            elif chunk == "ine":
                selected.extend(["ine_download", "ine_crossref"])
            elif chunk in STEP_REGISTRY:
                selected.append(chunk)
            else:
                print(f"  [WARN] Unknown step group: {chunk}", file=sys.stderr)
        return _dedup_ordered(selected)
    else:
        return ALL_STEPS[:]


def _dedup_ordered(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def main():
    import argparse

    # Fix Windows console encoding for Unicode output
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Automated Corruption Detection Pipeline — Analisa.pt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python run_corruption_scan.py                               # Full pipeline
              python run_corruption_scan.py --steps detect                # Detection only
              python run_corruption_scan.py --steps prepare,detect        # Prepare + detect
              python run_corruption_scan.py --steps prr                   # PRR analysis only
              python run_corruption_scan.py --skip competitor             # Skip competitor step
              python run_corruption_scan.py --dry-run                     # Preview only
        """),
    )
    parser.add_argument(
        "--steps", "-s",
        default="",
        help="Comma-separated: all, prepare, detect, report, prr, or specific step IDs",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        default=[],
        help="Step ID(s) to skip",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing",
    )
    parser.add_argument(
        "--export",
        metavar="FILE",
        default="",
        help="Export consolidated results to JSON (also saved to data/summary/)",
    )

    args = parser.parse_args()

    # Resolve steps and apply exclusions
    steps = resolve_steps(args)
    for skip_id in args.skip:
        if skip_id in steps:
            steps.remove(skip_id)

    if not steps:
        print("No steps to run. Use --steps or --help to see available steps.")
        sys.exit(1)

    # Display plan
    print(f"\n  Pipeline plan ({len(steps)} steps):")
    for i, sid in enumerate(steps, 1):
        labels = STEP_LABELS.get(sid, sid)
        print(f"    {i:>2}. {labels}")

    if args.dry_run:
        print("\n  [WARN] Dry run -- use --dry-run to preview (remove to execute)")
        return

    # Create summary directory
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    # Run pipeline
    runner = PipelineRunner(steps, dry_run=args.dry_run)
    runner.run()

    # Export consolidated results if requested
    if args.export:
        summary_path = SUMMARY_DIR / "scan_summary.json"
        if summary_path.exists():
            shutil.copy(summary_path, args.export)
            print(f"Exported summary to {args.export}")


if __name__ == "__main__":
    main()
