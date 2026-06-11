#!/usr/bin/env python3
"""Competitor Data Recovery — Fill missing concorrentes data from BASE.gov.pt.

The BASE.gov.pt API provides competitor (concorrentes) data for public
procurement contracts. Currently 57% of contracts are missing this field.
This tool fetches missing competitor data and updates the procurement database.

BASE.gov.pt API docs:
  https://www.base.gov.pt/Base4/pt/documentacao/formas-de-obter-dados-sobre-os-contratos-publicos/

Usage:
    python competitor_recover.py stats            # Show coverage stats
    python competitor_recover.py fetch --limit 100  # Fetch competitor data
    python competitor_recover.py fetch --nif 501089233  # By entity
    python competitor_recover.py search "hospital"    # Search competitor data
    python competitor_recover.py network --nif 501089233  # Competitor network
"""

import io
import sys

# Fix Windows console encoding for Unicode output (emoji characters)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import sqlite3
import argparse
import time
import re
from pathlib import Path
from collections import defaultdict
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "procurement.db"
CACHE_PATH = DATA_DIR / "competitor_cache.json"

# BASE.gov.pt API endpoints
BASE_API_BASE = "https://www.base.gov.pt/Base4/pt"
BASE_API_SEARCH = f"{BASE_API_BASE}/pesquisa/"
BASE_API_CONTRACT = f"{BASE_API_BASE}/detalhe/"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between requests
MAX_RETRIES = 3


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_cache() -> dict:
    """Load competitor cache from disk."""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def save_cache(cache: dict):
    """Save competitor cache to disk."""
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL with retries and rate limiting."""
    time.sleep(REQUEST_DELAY)
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={
                "User-Agent": "AnalisaPT/1.0 (research project)",
                "Accept": "application/json, text/html, */*",
            })
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return None
    return None


def parse_competitor_field(raw: str) -> list[dict]:
    """Parse the concorrentes field into structured competitor data.

    Format: newline-separated "NIF-Name" or "Name" entries.
    Example: "511005083-Mendes Gomes & Companhia, Lda\\n123456789-Outra Empresa"
    """
    if not raw:
        return []

    competitors = []
    lines = raw.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to extract NIF from start of line
        nif_match = re.match(r'^(\d{9})\s*[-–]\s*(.+)', line)
        if nif_match:
            competitors.append({
                "nif": nif_match.group(1),
                "name": nif_match.group(2).strip(),
            })
        else:
            # No NIF, just a name
            competitors.append({
                "nif": "",
                "name": line.strip(),
            })

    return competitors


def cmd_stats(args):
    """Show competitor data coverage statistics."""
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
    have = conn.execute(
        "SELECT COUNT(*) FROM contratos WHERE concorrentes IS NOT NULL AND concorrentes != '' AND concorrentes != '0'"
    ).fetchone()[0]
    missing = total - have

    print(f"\n{'='*70}")
    print(f"  COMPETITOR DATA — COVERAGE STATISTICS")
    print(f"{'='*70}")
    print(f"  Total contracts:       {total:>10,}")
    print(f"  With competitors:      {have:>10,} ({have*100/total:.1f}%)")
    print(f"  Missing competitors:   {missing:>10,} ({missing*100/total:.1f}%)")

    # By contract type
    print(f"\n  Coverage by contract type:")
    for row in conn.execute("""
        SELECT tipoContrato,
            COUNT(*) as total,
            SUM(CASE WHEN concorrentes IS NOT NULL AND concorrentes != '' AND concorrentes != '0' THEN 1 ELSE 0 END) as have
        FROM contratos
        WHERE tipoContrato IS NOT NULL AND tipoContrato != ''
        GROUP BY tipoContrato
        ORDER BY total DESC
    """).fetchall():
        t, tot, h = row[0], row[1], row[2]
        print(f"    {str(t)[:40]:<40} {h:>6,}/{tot:>6,} ({h*100/tot:.1f}%)")

    # Coverage by year
    print(f"\n  Coverage by year:")
    for row in conn.execute("""
        SELECT Ano,
            COUNT(*) as total,
            SUM(CASE WHEN concorrentes IS NOT NULL AND concorrentes != '' AND concorrentes != '0' THEN 1 ELSE 0 END) as have
        FROM contratos
        WHERE Ano IS NOT NULL
        GROUP BY Ano ORDER BY Ano
    """).fetchall():
        y, tot, h = row[0], row[1], row[2]
        print(f"    {y}: {h:>6,}/{tot:>6,} ({h*100/tot:.1f}%)")

    # Competitor count distribution
    print(f"\n  Competitor count distribution (contracts with data):")
    for row in conn.execute("""
        SELECT
            CASE
                WHEN concorrentes LIKE '%\n%' THEN LENGTH(concorrentes) - LENGTH(REPLACE(concorrentes, '\n', '')) + 1
                ELSE 1
            END as comp_count
        FROM contratos
        WHERE concorrentes IS NOT NULL AND concorrentes != '' AND concorrentes != '0'
    """).fetchall():
        pass  # Just computing

    # Simpler approach — count lines
    have_rows = conn.execute(
        "SELECT concorrentes FROM contratos WHERE concorrentes IS NOT NULL AND concorrentes != '' AND concorrentes != '0' LIMIT 1000"
    ).fetchall()
    count_dist = defaultdict(int)
    for r in have_rows:
        n = len([l for l in str(r[0]).split("\n") if l.strip()])
        count_dist[n] += 1

    for n in sorted(count_dist.keys()):
        print(f"    {n} competitors: {count_dist[n]:,}")

    # Cache stats
    cache = load_cache()
    if cache:
        print(f"\n  Cache: {len(cache):,} entries")

    print(f"{'='*70}\n")
    conn.close()


def cmd_fetch(args):
    """Fetch competitor data for contracts missing it from BASE.gov.pt.

    Note: BASE.gov.pt API requires registration for bulk access.
    This tool works with publicly available contract detail pages.
    """
    conn = get_db()
    cache = load_cache()

    # Build query for contracts missing competitor data
    where = "concorrentes IS NULL OR concorrentes = '' OR concorrentes = '0'"
    params = []

    if args.nif:
        where += " AND adjudicante_nif = ?"
        params.append(args.nif)

    if args.year:
        where += " AND Ano = ?"
        params.append(args.year)

    # Get contracts with linkPecasProc (BASE.gov.pt detail URL)
    query = f"""
        SELECT idcontrato, adjudicante_nome, objectoContrato,
               precoContratual, linkPecasProc, nAnuncio
        FROM contratos
        WHERE {where}
        AND linkPecasProc IS NOT NULL AND linkPecasProc != ''
        ORDER BY precoContratual DESC
        LIMIT ?
    """
    params.append(args.limit)

    rows = conn.execute(query, params).fetchall()
    print(f"\n  Found {len(rows)} contracts to fetch competitor data for")
    print(f"  (limit: {args.limit})\n")

    fetched = 0
    cached_hits = 0
    errors = 0

    for i, row in enumerate(rows):
        cid = str(row["idcontrato"])
        link = row["linkPecasProc"]

        # Check cache first
        if cid in cache:
            cached_hits += 1
            continue

        if not link:
            errors += 1
            continue

        # Build BASE.gov.pt detail URL
        if link.startswith("http"):
            url = link
        else:
            url = f"{BASE_API_CONTRACT}{quote(str(link))}"

        print(f"  [{i+1}/{len(rows)}] Fetching contract {cid}...")
        print(f"    Entity: {str(row['adjudicante_nome'] or '')[:50]}")
        print(f"    URL: {url[:80]}")

        html = fetch_url(url)
        if not html:
            print(f"    ❌ Failed to fetch")
            errors += 1
            continue

        # Parse competitors from HTML
        # Look for concorrentes section in the page
        competitors_found = []

        # Pattern 1: Look for "Concorrentes" or "Outros concorrentes" section
        comp_patterns = [
            r'Concorrentes?[^<]*</[^>]+>\s*(?:<[^>]+>)*\s*([^<]+)',
            r'outros?\s+concorrentes?[^<]*</[^>]+>\s*(?:<[^>]+>)*\s*([^<]+)',
            r'demais\s+concorrentes?[^<]*</[^>]+>\s*(?:<[^>]+>)*\s*([^<]+)',
        ]

        for pattern in comp_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            if matches:
                for m in matches:
                    text = re.sub(r'<[^>]+>', ' ', m).strip()
                    if text and len(text) > 3:
                        competitors_found.append(text)
                break

        if competitors_found:
            comp_str = "\n".join(competitors_found)
            cache[cid] = {"competitors": comp_str, "source": "web"}
            fetched += 1
            print(f"    ✅ Found {len(competitors_found)} competitor entries")
        else:
            cache[cid] = {"competitors": "", "source": "web", "empty": True}
            print(f"    ⚠️  No competitors found on page")

        # Save cache periodically
        if (i + 1) % 20 == 0:
            save_cache(cache)

    save_cache(cache)

    print(f"\n{'='*70}")
    print(f"  FETCH RESULTS")
    print(f"{'='*70}")
    print(f"  Fetched new:     {fetched:>6,}")
    print(f"  Cache hits:      {cached_hits:>6,}")
    print(f"  Errors:          {errors:>6,}")
    print(f"  Cache total:     {len(cache):>6,}")
    print(f"{'='*70}\n")

    conn.close()


def cmd_apply(args):
    """Apply cached competitor data to the procurement database."""
    conn = get_db()
    cache = load_cache()

    if not cache:
        print("  No cache data. Run 'fetch' first.")
        return

    updated = 0
    for cid_str, data in cache.items():
        competitors = data.get("competitors", "")
        if not competitors:
            continue

        # Check if contract still needs data
        row = conn.execute(
            "SELECT concorrentes FROM contratos WHERE idcontrato = ?",
            (int(cid_str),)
        ).fetchone()

        if row and (row["concorrentes"] and row["concorrentes"] not in ("", "0")):
            continue  # Already has data

        conn.execute(
            "UPDATE contratos SET concorrentes = ? WHERE idcontrato = ?",
            (competitors, int(cid_str)),
        )
        updated += 1

    conn.commit()

    # Verify
    total = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
    have = conn.execute(
        "SELECT COUNT(*) FROM contratos WHERE concorrentes IS NOT NULL AND concorrentes != '' AND concorrentes != '0'"
    ).fetchone()[0]

    print(f"\n  Updated {updated:,} contracts with cached competitor data")
    print(f"  New coverage: {have:,} / {total:,} ({have*100/total:.1f}%)")
    conn.close()


def cmd_network(args):
    """Build competitor network for an entity."""
    conn = get_db()

    if not args.nif:
        print("  Error: --nif required")
        return

    # Get all contracts where this entity appears as competitor
    rows = conn.execute("""
        SELECT concorrentes, adjudicante_nome, adjudicante_nif,
               objectoContrato, precoContratual
        FROM contratos
        WHERE concorrentes LIKE ? AND concorrentes IS NOT NULL AND concorrentes != ''
        ORDER BY precoContratual DESC
        LIMIT 100
    """, (f"%{args.nif}%",)).fetchall()

    if not rows:
        print(f"\n  No contracts found where NIF {args.nif} appears as competitor")
        conn.close()
        return

    print(f"\n{'='*70}")
    print(f"  COMPETITOR NETWORK — NIF {args.nif}")
    print(f"{'='*70}")
    print(f"  Found in {len(rows)} contracts as competitor\n")

    # Extract co-competitors
    co_competitors = defaultdict(lambda: {"count": 0, "value": 0})

    for r in rows:
        comps = parse_competitor_field(r["concorrentes"])
        for c in comps:
            if c["nif"] != args.nif:
                key = f"{c['nif']}|{c['name']}" if c["nif"] else c["name"]
                co_competitors[key]["count"] += 1
                co_competitors[key]["value"] += r["precoContratual"] or 0

    print(f"  Co-competitors (also bid on same contracts):")
    print(f"  {'NIF':<12} {'Name':<40} {'Count':>6} {'Value':>15}")
    print(f"  {'-'*12} {'-'*40} {'-'*6} {'-'*15}")

    for key, data in sorted(co_competitors.items(), key=lambda x: -x[1]["value"])[:20]:
        parts = key.split("|", 1)
        nif = parts[0] if len(parts) > 1 else ""
        name = parts[1] if len(parts) > 1 else parts[0]
        val = data["value"]
        val_str = f"€{val:,.0f}" if val >= 1000000 else f"€{val/1000:.0f}K" if val >= 1000 else f"€{val:.0f}"
        print(f"  {nif:<12} {name[:40]:<40} {data['count']:>6} {val_str:>15}")

    print(f"{'='*70}\n")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Recover missing competitor data from BASE.gov.pt",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("stats", help="Show coverage statistics")

    fetch = sub.add_parser("fetch", help="Fetch competitor data from BASE.gov.pt")
    fetch.add_argument("--limit", type=int, default=50, help="Max contracts to fetch")
    fetch.add_argument("--nif", help="Filter by entity NIF")
    fetch.add_argument("--year", type=int, help="Filter by contract year")

    sub.add_parser("apply", help="Apply cached data to database")

    net = sub.add_parser("network", help="Competitor network for an entity")
    net.add_argument("--nif", required=True, help="Entity NIF")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "stats": cmd_stats,
        "fetch": cmd_fetch,
        "apply": cmd_apply,
        "network": cmd_network,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
