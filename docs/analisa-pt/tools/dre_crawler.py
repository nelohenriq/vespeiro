#!/usr/bin/env python3
"""DRE (Diário da República Eletrónico) Publication Crawler.

Enumerates law publications from the DRE by date range.  Uses two strategies:

1. **PDF enumeration**: Try sequential PDF URLs on `files.dre.pt` for each date.
   PDFs follow a predictable pattern: ``files.dre.pt/{serie}s/{year}/{month}/{day}/{id}.pdf``
2. **OutSystems API** (future): Once the exact request body format is captured
   via browser DevTools, this can be upgraded to use the DRE's internal search API.

Usage:
    python dre_crawler.py crawl --since 2026-06-01 --until 2026-06-05
    python dre_crawler.py crawl --since 2026-06-01 --until 2026-06-05 --serie 1
    python dre_crawler.py list --since 2026-06-01
    python dre_crawler.py stats

API Discovery Notes (from browser network inspection):
    Endpoint: POST /dr/screenservices/dr/Pesquisas/PesquisaResultado/DataActionGetPesquisas
    Headers:  x-csrftoken, Cookie (session), Content-Type: application/json
    Body:     {"versionInfo": {...}, "screenData": "{...}"}
    Status:   CSRF token requires real browser session — curl cannot obtain it.
              Upgrade path: use playwright to automate the search form.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("dre_crawler")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "dre_index.db"

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Serie mapping
SERIE_MAP = {"1": "Série I", "2": "Série II"}
SERIE_PREFIX = {"1": "1s", "2": "2s"}

# ---------------------------------------------------------------------------
# DRE PDF enumeration
# ---------------------------------------------------------------------------

# Try known PDF URL patterns for a given date.
# Pattern 1: files.dre.pt/{serie_prefix}/{year}/{month}/{day}/{id}.pdf
# Pattern 2: files.dre.pt/{serie_prefix}/{year}/{month}/{id}.pdf (older format)

# DRE publishes multiple PDFs per day — each document gets its own PDF.
# IDs are sequential within each day. We try IDs 1 through MAX_ID_PER_DAY.

MAX_ID_PER_MONTH = 500  # DRE IDs are per-month, busy months can have hundreds


def _try_pdf(url: str) -> tuple[bool, str]:
    """Check if a PDF URL exists and return the content type.

    Returns (exists, content_type).
    """
    try:
        result = subprocess.run(
            ["curl", "-s", "-I", "-L", "--max-time", "8",
             "-H", f"User-Agent: {_USER_AGENT}", url],
            capture_output=True, text=True, timeout=12,
        )
        for line in result.stdout.split("\n"):
            if line.lower().startswith("content-type:") and "pdf" in line.lower():
                return True, line.strip()
            if line.lower().startswith("http/") and "404" in line:
                return False, ""
        # Check for redirect to error page
        if "error" in result.stdout.lower():
            return False, ""
    except Exception:
        pass
    return False, ""


def _download_pdf_text(url: str, max_pages: int = 3) -> str | None:
    """Download a PDF and extract text from first N pages."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", "--max-time", "15",
             "-H", f"User-Agent: {_USER_AGENT}", url],
            capture_output=True, timeout=20,
        )
        if result.returncode != 0 or not result.stdout:
            return None

        import pdfplumber
        with pdfplumber.open(io.BytesIO(result.stdout)) as pdf:
            pages = pdf.pages[:max_pages]
            text_parts = []
            for page in pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            full_text = "\n\n".join(text_parts)
            return full_text.strip() if full_text.strip() else None
    except Exception as exc:
        logger.debug("PDF download/extract failed for %s: %s", url, exc)
        return None





# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dre_publications (
    dre_id          TEXT PRIMARY KEY,
    serie           TEXT,
    data_publicacao TEXT,
    pdf_url         TEXT,
    titulo          TEXT,
    content_text    TEXT,
    collected_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dre_pub_date ON dre_publications(data_publicacao);
"""


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _upsert(conn: sqlite3.Connection, pub: dict) -> bool:
    """Insert a publication. Returns True if new."""
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT dre_id FROM dre_publications WHERE dre_id = ?",
        (pub["dre_id"],),
    ).fetchone()
    if existing:
        return False
    conn.execute(
        """INSERT INTO dre_publications
        (dre_id, serie, data_publicacao, pdf_url, titulo, content_text, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (pub["dre_id"], pub["serie"], pub["data_publicacao"],
         pub["pdf_url"], pub["titulo"], pub["content_text"], now),
    )
    return True


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_crawl(args):
    """Crawl DRE publications for a date range via PDF enumeration."""
    since = datetime.strptime(args.since, "%Y-%m-%d")
    until = datetime.strptime(args.until, "%Y-%m-%d")

    conn = init_db(args.db)
    series = [args.serie] if args.serie != "all" else ["1", "2"]

    total_new = 0
    total_checked = 0
    current = since

    while current <= until:
        date_str = current.strftime("%Y-%m-%d")
        current += timedelta(days=1)

        for serie in series:
            serie_name = SERIE_MAP.get(serie, f"Série {serie}")
            print(f"\n[{date_str}] {serie_name} — scanning PDFs...")

            consecutive_misses = 0
            found_this_day = 0

            for doc_id in range(1, MAX_ID_PER_MONTH + 1):
                # DRE PDF pattern: files.dre.pt/{1s|2s}/{year}/{month}/{id}.pdf
                # Note: no day component in the URL path
                url = f"https://files.dre.pt/{SERIE_PREFIX[serie]}/{current.year}/{current.month:02d}/{doc_id}.pdf"
                total_checked += 1

                exists, _ = _try_pdf(url)
                if exists:
                    consecutive_misses = 0
                    found_this_day += 1

                    # Extract text (first 3 pages for speed)
                    text = _download_pdf_text(url, max_pages=3)
                    title = (text[:120].replace("\n", " ").strip() if text else f"DRE {serie_name} N.º {doc_id}")

                    pub = {
                        "dre_id": f"{date_str}-s{serie}-{doc_id:04d}",
                        "serie": serie,
                        "data_publicacao": date_str,
                        "pdf_url": url,
                        "titulo": title,
                        "content_text": text,
                    }
                    is_new = _upsert(conn, pub)
                    if is_new:
                        total_new += 1
                        print(f"  NEW  N.º {doc_id:3d} — {title[:70]}")
                    conn.commit()
                else:
                    consecutive_misses += 1

                    # If we found some PDFs and now hit 10 consecutive misses,
                    # we've probably reached the end for this day
                    if found_this_day > 0 and consecutive_misses >= 10:
                        break

            if found_this_day > 0:
                print(f"  → {found_this_day} publications found")
            else:
                print(f"  → no publications")

    conn.close()

    print(f"\n=== Crawl complete ===")
    print(f"New publications: {total_new}")
    print(f"URLs checked:     {total_checked}")


def cmd_list(args):
    """List publications from the database."""
    conn = init_db(args.db)
    query = "SELECT dre_id, serie, data_publicacao, titulo FROM dre_publications"
    params: list = []
    conditions: list = []

    if args.since:
        conditions.append("data_publicacao >= ?")
        params.append(args.since)
    if args.until:
        conditions.append("data_publicacao <= ?")
        params.append(args.until)
    if args.serie:
        conditions.append("serie = ?")
        params.append(args.serie)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY data_publicacao DESC"
    if args.num:
        query += f" LIMIT {args.num}"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print("No publications found")
        return

    print(f"Found {len(rows)} publications:\n")
    for row in rows:
        dre_id, serie, pub_date, titulo = row
        serie_label = f"S{serie}"
        title_text = (titulo or "")[:70]
        print(f"  [{pub_date}] {serie_label} — {title_text}")


def cmd_stats(args):
    """Show database statistics."""
    if not DB_PATH.exists():
        print("No database found. Run `dre_crawler.py crawl` first.")
        return

    conn = init_db(args.db)
    total = conn.execute("SELECT count(*) FROM dre_publications").fetchone()[0]
    if total == 0:
        print("Database is empty. Run `dre_crawler.py crawl` first.")
        conn.close()
        return

    print(f"Total:     {total} publications")
    row = conn.execute(
        "SELECT min(data_publicacao), max(data_publicacao) FROM dre_publications"
    ).fetchone()
    if row[0]:
        print(f"Date range: {row[0]} → {row[1]}")

    print(f"\nBy serie:")
    for row in conn.execute(
        "SELECT serie, count(*) FROM dre_publications GROUP BY serie"
    ).fetchall():
        print(f"  Série {row[0]}: {row[1]}")

    with_content = conn.execute(
        "SELECT count(*) FROM dre_publications WHERE content_text IS NOT NULL"
    ).fetchone()[0]
    print(f"\nWith text: {with_content}/{total}")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="DRE Publication Crawler — enumerate law publications by date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s crawl --since 2026-06-01 --until 2026-06-05
  %(prog)s crawl --since 2026-06-01 --until 2026-06-05 --serie 1
  %(prog)s list --since 2026-06-01 -n 20
  %(prog)s stats
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p_crawl = sub.add_parser("crawl", help="Crawl DRE by date range")
    p_crawl.add_argument("--since", required=True, help="Start date YYYY-MM-DD")
    p_crawl.add_argument("--until", required=True, help="End date YYYY-MM-DD")
    p_crawl.add_argument("--serie", default="all", help="1, 2, or all")
    p_crawl.add_argument("--db", default=None, help="DB path")

    p_list = sub.add_parser("list", help="List publications")
    p_list.add_argument("--since", help="Filter by start date")
    p_list.add_argument("--until", help="Filter by end date")
    p_list.add_argument("--serie", help="Filter by serie")
    p_list.add_argument("-n", "--num", type=int, help="Max results")
    p_list.add_argument("--db", default=None, help="DB path")

    p_stats = sub.add_parser("stats", help="Show statistics")
    p_stats.add_argument("--db", default=None, help="DB path")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    commands = {"crawl": cmd_crawl, "list": cmd_list, "stats": cmd_stats}
    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
