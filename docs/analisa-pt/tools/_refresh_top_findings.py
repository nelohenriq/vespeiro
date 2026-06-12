#!/usr/bin/env python3
"""_refresh_top_findings.py — Background job for the Top Findings panel.

Runs the per-analyzer scripts (anomaly, bid_pattern, temporal, suppliers,
price_gap, municipality_risk) as subprocesses with a hard per-step timeout,
then consolidates their JSON outputs into data/summary/top_findings.json
so the Overview tab's Top Findings panel stays fresh without timing out
the way the full run_corruption_scan.py does.

Two modes:
  --once       Run once and exit. Suitable for cron / Windows Task Scheduler.
  --watch      Loop forever, sleeping --interval-hours between runs.

Concurrency:
  Uses an atomic lockfile (data/summary/.scheduler.lock) so two scheduled
  invocations never overlap. The lockfile contains the run id + start
  timestamp so a stale lock can be detected.

Error handling:
  Per-step timeouts kill the subprocess + log + continue. Missing analyzer
  scripts are logged and skipped. The job is designed to never crash the
  scheduler.

CLI:
  python _refresh_top_findings.py --once
  python _refresh_top_findings.py --watch --interval-hours 6
  python _refresh_top_findings.py --once --step-timeout 30 --dry-run

Dependencies: Python stdlib only.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
SUMMARY_DIR = SCRIPT_DIR / "data" / "summary"
LOG_FILE = SUMMARY_DIR / ".scheduler.log"
LOCK_FILE = SUMMARY_DIR / ".scheduler.lock"
TOP_FINDINGS = SUMMARY_DIR / "top_findings.json"
TOP_RISK_MUNICIPALITIES = SUMMARY_DIR / "top_risk_municipalities.json"


# ── Per-analyzer definitions ────────────────────────────────────────────────
# (id, script_name, extra_args). Each step runs in its own subprocess with
# --step-timeout seconds. The per-step results are materialised as JSON files
# in data/summary/ which the consolidator reads at the end.
#
# Order: fast -> slow. Each step is independent \u2014 a failure in one step
# doesn't block the others.

ANALYZERS = [
    {
        "id": "anomaly",
        "script": "anomaly_scanner.py",
        "args": ["--export", str(SUMMARY_DIR / "anomalies.json"), "--top", "30"],
    },
    {
        "id": "bid_pattern",
        "script": "bid_pattern_analyzer.py",
        "args": ["--export", str(SUMMARY_DIR / "bid_patterns.json"), "--top", "20"],
    },
    {
        "id": "temporal",
        "script": "temporal_clustering.py",
        "args": ["--export", str(SUMMARY_DIR / "temporal_bursts.json"), "--top", "20"],
    },
    {
        "id": "suppliers",
        "script": "supplier_cross_profiler.py",
        "args": ["--top", "20", "--export", str(SUMMARY_DIR / "top_suppliers.json")],
    },
    {
        "id": "price_gap",
        "script": "price_gap_analysis.py",
        "args": ["--export", str(SUMMARY_DIR / "price_gaps.json"), "--top", "30"],
    },
    {
        "id": "municipality_risk",
        "script": "municipality_risk_report.py",
        "args": ["--export", str(SUMMARY_DIR / "municipality_risk.json"), "--top", "30"],
    },
]


# ── Logging ─────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool) -> logging.Logger:
    """Configure file + console logging. Idempotent (safe to call repeatedly)."""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("refresh_top_findings")
    if logger.handlers:  # already configured
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # File handler \u2014 rotated manually on size, but the log is small (~1KB/run)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


# ── Lockfile ────────────────────────────────────────────────────────────────

def _acquire_lock() -> tuple[int, str] | None:
    """Atomic lockfile via O_CREAT|O_EXCL.

    Returns (fd, run_id) on success, None if another run holds the lock.
    The fd stays open for the lifetime of the run \u2014 closing it releases
    the lock on POSIX; on Windows we delete the file explicitly in release.
    Stale locks (>2h old) are stolen at most once per call to avoid
    pathological recursion.
    """
    import socket
    run_id = f"{socket.gethostname()}-{os.getpid()}-{int(time.time())}"
    payload = f"{run_id}\nstarted_at={datetime.now(timezone.utc).isoformat()}\n"
    for _attempt in range(2):  # first try + one stale-steal retry
        try:
            fd = os.open(
                str(LOCK_FILE),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
            return fd, run_id
        except FileExistsError:
            # Check for stale lock (>2h old). If so, steal it.
            try:
                st = LOCK_FILE.stat()
                age_s = time.time() - st.st_mtime
                if age_s > 2 * 3600:
                    LOCK_FILE.unlink()
                    continue  # retry once
            except Exception:
                pass
            return None
    return None


def _release_lock(fd: int) -> None:
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


# ── Per-analyzer runner ─────────────────────────────────────────────────────

def _run_step(analyzer: dict, timeout_s: int, dry_run: bool, log: logging.Logger) -> dict:
    """Run one analyzer as a subprocess with a hard timeout.

    Returns a result dict: {id, status, duration_s, error}.
    status in {"passed", "timeout", "failed", "skipped", "dry-run"}.
    """
    script_path = SCRIPT_DIR / analyzer["script"]
    result = {
        "id": analyzer["id"],
        "status": "skipped",
        "duration_s": 0.0,
        "error": None,
    }

    if dry_run:
        result["status"] = "dry-run"
        log.info(f"  [DRY-RUN] would run: {analyzer['script']} {' '.join(analyzer['args'])}")
        return result

    if not script_path.exists():
        result["error"] = f"script not found: {script_path.name}"
        log.warning(f"  [SKIP] {analyzer['id']}: {result['error']}")
        return result

    cmd = [sys.executable, str(script_path)] + analyzer["args"]
    log.info(f"  [RUN] {analyzer['id']} (timeout={timeout_s}s)")
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        result["duration_s"] = round(time.time() - t0, 1)
        if proc.returncode == 0:
            result["status"] = "passed"
            log.info(f"  [OK] {analyzer['id']} in {result['duration_s']}s")
        else:
            result["status"] = "failed"
            stderr_tail = (proc.stderr or "").strip().splitlines()[-5:]
            result["error"] = f"exit={proc.returncode}: " + " | ".join(stderr_tail)
            log.warning(f"  [FAIL] {analyzer['id']} in {result['duration_s']}s: {result['error']}")
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["duration_s"] = round(time.time() - t0, 1)
        result["error"] = f"timed out after {timeout_s}s"
        log.warning(f"  [TIMEOUT] {analyzer['id']} after {result['duration_s']}s")
    except Exception as e:
        result["status"] = "failed"
        result["duration_s"] = round(time.time() - t0, 1)
        result["error"] = f"{type(e).__name__}: {e}"
        log.error(f"  [ERROR] {analyzer['id']}: {result['error']}")
    return result


# ── Top findings consolidator ───────────────────────────────────────────────

# Severity inference for ad-hoc numbers extracted from analyzer summaries.
# The thresholds are deliberately conservative so a "high" really means
# something actionable; medium is the default for unknown signals.
def _severity_for(value, high_thr: float, med_thr: float) -> str:
    if value is None:
        return "info"
    if value >= high_thr:
        return "high"
    if value >= med_thr:
        return "medium"
    return "low"


def _consolidate_top_findings(step_results: list[dict], log: logging.Logger) -> dict:
    """Read the analyzer JSON outputs and consolidate them into top_findings.json.

    Pulls from the materialised JSON files in data/summary/ + the existing
    justice_crossref.json (the strongest cross-domain signal we already have).
    Skips steps that didn't produce a parseable JSON file.
    """
    findings: list[dict] = []

    # 1) justice_crossref.json: the richest source (3 high-severity signals)
    jc_path = SUMMARY_DIR / "justice_crossref.json"
    if jc_path.exists():
        try:
            jc = json.loads(jc_path.read_text(encoding="utf-8"))
            for sig in jc.get("risk_signals", []):
                findings.append({
                    "source": "justice_xref",
                    "severity": sig.get("severity", "info"),
                    "category": "crossref",
                    "signal": sig.get("signal"),
                    "detail": sig.get("detail"),
                })
            findings.append({
                "source": "justice_xref",
                "severity": "critical" if jc.get("risk_level") == "critical" else "high",
                "category": "composite",
                "signal": "composite_risk",
                "detail": f"Composite risk score {jc.get('composite_score')} / "
                          f"level={jc.get('risk_level')} "
                          f"({len(jc.get('risk_signals', []))} signals)",
            })
            proc = jc.get("procurement", {})
            if proc:
                findings.append({
                    "source": "justice_xref",
                    "severity": "high",
                    "category": "procurement",
                    "signal": "direct_awards_dominate",
                    "detail": f"{proc.get('direct_rate_pct')}% of "
                              f"{proc.get('total_contracts'):,} contracts are direct awards",
                })
        except Exception as e:
            log.warning(f"  [consolidate] justice_crossref.json unreadable: {e}")

    # 2) Per-analyzer JSONs (if the step passed)
    passed_ids = {r["id"] for r in step_results if r["status"] == "passed"}
    step_id_map = {
        "bid_patterns.json": "bid_pattern",
        "anomalies.json": "anomaly",
        "temporal_bursts.json": "temporal",
        "municipality_risk.json": "municipality_risk",
        "price_gaps.json": "price_gap",
        "top_suppliers.json": "suppliers",
    }
    for src_id, src_name, category in [
        ("bid_patterns.json", "bid_pattern", "bidding"),
        ("anomalies.json", "anomaly_scanner", "anomaly"),
        ("temporal_bursts.json", "temporal", "temporal"),
        ("municipality_risk.json", "municipality_risk", "geographic"),
        ("price_gaps.json", "price_gap", "price"),
        ("top_suppliers.json", "supplier_profiler", "supplier"),
    ]:
        step_id = step_id_map[src_id]
        if step_id not in passed_ids:
            log.debug(f"  [consolidate] skip {src_id} (step did not pass)")
            continue
        p = SUMMARY_DIR / src_id
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"  [consolidate] {src_id} unreadable: {e}")
            continue
        summary_block = d.get("summary") if isinstance(d, dict) else None
        if not isinstance(summary_block, dict):
            continue
        for k, v in list(summary_block.items())[:3]:
            if not isinstance(v, (int, float)):
                continue
            if "pct" in k.lower() or "rate" in k.lower():
                sev = _severity_for(v, 50, 25)
            elif "count" in k.lower() or "total" in k.lower():
                sev = _severity_for(v, 100, 10)
            else:
                sev = "info"
            findings.append({
                "source": src_name,
                "severity": sev,
                "category": category,
                "signal": k,
                "detail": f"{k}: {v}",
            })

    # Dedupe (signal, detail-prefix) keeping the highest severity
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    seen: dict[tuple, dict] = {}
    for f in findings:
        key = (f.get("signal"), (f.get("detail") or "")[:60])
        if key in seen:
            if sev_order.get(f.get("severity"), 5) < sev_order.get(seen[key].get("severity"), 5):
                seen[key] = f
        else:
            seen[key] = f
    findings = list(seen.values())
    findings.sort(key=lambda f: (sev_order.get(f.get("severity"), 5), f.get("source", "")))

    by_severity = {s: sum(1 for f in findings if f.get("severity") == s)
                   for s in sev_order}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_findings": len(findings),
        "by_severity": by_severity,
        "findings": findings[:20],
    }


def _refresh_top_risk_municipalities(log: logging.Logger) -> bool:
    """Run the existing _build_top_risk_municipalities.py to refresh
    the top_risk_municipalities.json cache. Returns True on success."""
    build_script = SCRIPT_DIR / "_build_top_risk_municipalities.py"
    if not build_script.exists():
        log.warning("  [muni] _build_top_risk_municipalities.py not found, skipping")
        return False
    try:
        log.info("  [muni] running _build_top_risk_municipalities.py (timeout=120s)")
        proc = subprocess.run(
            [sys.executable, str(build_script)],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            log.info("  [muni] OK")
            return True
        log.warning(f"  [muni] failed: exit={proc.returncode} "
                    f"stderr={(proc.stderr or '').strip().splitlines()[-3:]}")
    except subprocess.TimeoutExpired:
        log.warning("  [muni] timed out after 120s")
    except Exception as e:
        log.warning(f"  [muni] {type(e).__name__}: {e}")
    return False


# ── Main loop ──────────────────────────────────────────────────────────────

def run_once(args: argparse.Namespace, log: logging.Logger) -> int:
    """Run the full refresh cycle once. Returns 0 on success, 1 on no-op."""
    lock = _acquire_lock()
    if lock is None:
        log.warning("[lock] another run is in progress, exiting")
        return 1
    fd, run_id = lock
    log.info(f"[start] run_id={run_id} mode=once step_timeout={args.step_timeout}s")
    try:
        # 1) Run the per-analyzer steps
        step_results = []
        for analyzer in ANALYZERS:
            r = _run_step(analyzer, args.step_timeout, args.dry_run, log)
            step_results.append(r)

        # 2) Always run the top risk municipalities build (it's the
        #    narrowest, fastest aggregation, and the panel ships as a
        #    stub if this never runs)
        _refresh_top_risk_municipalities(log)

        # 3) Consolidate the top findings from the per-analyzer outputs
        consolidated = _consolidate_top_findings(step_results, log)
        with open(TOP_FINDINGS, "w", encoding="utf-8") as f:
            json.dump(consolidated, f, indent=2, ensure_ascii=False)
        log.info(f"[consolidate] wrote {TOP_FINDINGS} "
                 f"({consolidated['total_findings']} findings, "
                 f"critical={consolidated['by_severity'].get('critical', 0)} "
                 f"high={consolidated['by_severity'].get('high', 0)})")

        # 4) Write a heartbeat file so the dashboard / health endpoint
        #    can show the last refresh time without hitting the API
        heartbeat = {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "step_results": step_results,
        }
        (SUMMARY_DIR / ".scheduler_heartbeat.json").write_text(
            json.dumps(heartbeat, indent=2), encoding="utf-8"
        )

        # 5) Summary
        n_passed = sum(1 for r in step_results if r["status"] == "passed")
        n_failed = sum(1 for r in step_results if r["status"] in ("failed", "timeout"))
        n_skipped = sum(1 for r in step_results if r["status"] == "skipped")
        log.info(f"[done] {n_passed} passed, {n_failed} failed, {n_skipped} skipped")
        return 0
    except Exception as e:
        log.error(f"[crash] {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
        return 1
    finally:
        _release_lock(fd)


def run_watch(args: argparse.Namespace, log: logging.Logger) -> int:
    """Loop forever, sleeping --interval-hours between runs."""
    interval_s = max(60, int(args.interval_hours * 3600))
    log.info(f"[watch] starting loop, interval={interval_s}s "
             f"({args.interval_hours}h), step_timeout={args.step_timeout}s")
    while True:
        try:
            run_once(args, log)
        except KeyboardInterrupt:
            log.info("[watch] interrupted, exiting")
            return 0
        except Exception as e:
            log.error(f"[watch] {type(e).__name__}: {e}")
        log.info(f"[watch] sleeping {interval_s}s until next run "
                 f"(next at ~{datetime.now().strftime('%H:%M:%S')} +{interval_s}s)")
        try:
            time.sleep(interval_s)
        except KeyboardInterrupt:
            log.info("[watch] interrupted, exiting")
            return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Background job that refreshes the Top Findings panel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python _refresh_top_findings.py --once\n"
            "  python _refresh_top_findings.py --watch --interval-hours 6\n"
            "  python _refresh_top_findings.py --once --step-timeout 30 --dry-run\n"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", default=True,
                      help="Run once and exit (default). Suitable for cron/Task Scheduler.")
    mode.add_argument("--watch", action="store_true",
                      help="Loop forever, refreshing every --interval-hours.")
    parser.add_argument("--interval-hours", type=float, default=6.0,
                        help="Hours between refreshes in --watch mode (default: 6).")
    parser.add_argument("--step-timeout", type=int, default=90,
                        help="Hard timeout per analyzer in seconds (default: 90).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run without executing anything.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging (DEBUG level).")
    args = parser.parse_args()

    log = _setup_logging(args.verbose)
    log.info(f"[boot] pid={os.getpid()} cwd={os.getcwd()} args={vars(args)}")

    if args.watch:
        return run_watch(args, log)
    return run_once(args, log)


if __name__ == "__main__":
    sys.exit(main())
