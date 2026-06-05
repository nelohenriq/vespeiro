#!/usr/bin/env python3
"""DRE Publication Crawler — Enumerates Diário da República via ELI URIs.

Probes ELI URIs on data.diariodarepublica.pt to discover DRE publications,
follows redirects to get canonical URLs, and stores metadata in SQLite.
Enables cross-referencing with BEP jobs and law projects.

Usage:
    python dre_crawler.py fetch --year 2026 --serie 1       # Fetch serie 1 publications
    python dre_crawler.py fetch --year 2026 --serie 2       # Fetch serie 2 publications
    python dre_crawler.py fetch --year 2026 --all           # Fetch both series
    python dre_crawler.py search "educação"                # Search titles
    python dre_crawler.py stats                             # Index statistics
    python dre_crawler.py crossref                          # Cross-ref with BEP + Laws
"""

import sys
import json
import time
import re
import os
import argparse
import logging
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from pathlib import Path

logger = logging.getLogger("dre_crawler")

ELI_BASE = "https://data.diariodarepublica.pt/eli/diario"
DRE_DETAIL_BASE = "https://diariodarepublica.pt/dr/detalhe/diario-republica"


class DRECrawler:
    """Enumerates DRE publications via ELI URI probing."""

    def __init__(self, delay: float = 0.3):
        self.delay = delay

    def _follow_eli(self, serie: int, numero: int, year: int) -> dict | None:
        """Probe an ELI URI and follow the redirect to get the canonical URL."""
        eli_url = f"{ELI_BASE}/{serie}/{numero}/{year}/0/pt/html"
        req = Request(eli_url, headers={
            "User-Agent": "dre-crawler/1.0 (analisa-pt)",
            "Accept": "text/html",
        })

        try:
            with urlopen(req, timeout=15) as resp:
                final_url = resp.geturl()
                html = resp.read().decode("utf-8", errors="replace")

                # Extract unique ID from redirect URL
                # Pattern: /dr/detalhe/diario-republica/{number}-{year}-{unique_id}
                match = re.search(r'/diario-republica/(\d+)-(\d+)-(\d+)', final_url)
                unique_id = match.group(3) if match else ""

                # Check if redirected to home (invalid publication)
                if "/dr/home" in final_url:
                    return None

                # Try to extract title from HTML
                title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else ""

                return {
                    "eli_url": eli_url,
                    "redirect_url": final_url,
                    "unique_id": unique_id,
                    "title": title,
                }

        except HTTPError as e:
            logger.error(f"HTTP {e.code} for ELI {eli_url}")
            return None
        except URLError as e:
            logger.error(f"Network error for {eli_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error for {eli_url}: {e}")
            return None

    def fetch_series(self, serie: int, year: int, max_number: int = 300) -> list[dict]:
        """Fetch all publications for a series and year.

        Probes ELI URIs from 1 upward until hitting invalid redirects.
        """
        from dre_db import init_db, upsert_publication

        conn = init_db()
        publications = []
        consecutive_misses = 0

        print(f"Fetching DRE Serie {serie}, Year {year}...")

        for numero in range(1, max_number + 1):
            result = self._follow_eli(serie, numero, year)

            if result is None:
                consecutive_misses += 1
                if consecutive_misses >= 10:
                    print(f"  Stopping at #{numero}: 10 consecutive invalid publications")
                    break
                continue

            consecutive_misses = 0
            pub_id = f"{serie}-{numero}-{year}"

            pub = {
                "pub_id": pub_id,
                "serie": serie,
                "numero": numero,
                "year": year,
                **result,
            }

            is_new = upsert_publication(conn, pub)
            publications.append(pub)

            status = "NEW" if is_new else "EXISTS"
            date_str = result.get("publication_date", "?")
            logger.info(f"  [{status}] #{numero}: {result.get('title', '?')[:60]}")

            if numero % 20 == 0:
                print(f"  Progress: {numero} probed, {len(publications)} found")

            time.sleep(self.delay)

        conn.commit()
        conn.close()

        print(f"\n  Serie {serie}: {len(publications)} publications found "
              f"(scanned {numero} numbers)")
        return publications


def _cmd_fetch(client: DRECrawler, args):
    """Fetch DRE publications."""
    series = []
    if args.all or args.serie == 1:
        series.append(1)
    if args.all or args.serie == 2:
        series.append(2)
    if not series:
        series = [1, 2]

    total = 0
    for serie in series:
        pubs = client.fetch_series(serie, args.year, args.max_number)
        total += len(pubs)

    print(f"\n=== Fetch complete ===")
    print(f"Total publications: {total}")


def _cmd_search(args):
    """Search stored publications."""
    from dre_db import init_db, get_publications

    conn = init_db(args.db)
    pubs = get_publications(conn, limit=args.limit, search=args.query)
    conn.close()

    if not pubs:
        print("No publications found.")
        return

    print(f"Found {len(pubs)} publications:\n")
    for p in pubs:
        print(f"  {p['pub_id']}  Serie {p['serie']}  #{p['numero']}  "
              f"{p.get('publication_date', '?')[:10]}")
        if p.get("title"):
            print(f"    {p['title'][:70]}")
        if p.get("redirect_url"):
            print(f"    {p['redirect_url']}")
        print()


def _cmd_stats(args):
    """Show index statistics."""
    from dre_db import init_db, get_stats

    conn = init_db(args.db)
    stats = get_stats(conn)
    conn.close()

    print(f"\n=== DRE Publication Crawler — Index Stats ===")
    print(f"  Publications:  {stats['publications']}")
    print(f"  Documents:     {stats['documents']}")
    print(f"  Serie 1:       {stats['serie_1']}")
    print(f"  Serie 2:       {stats['serie_2']}")
    if stats["date_range"][0]:
        print(f"  Date range:    {stats['date_range'][0]} → {stats['date_range'][1]}")
    print()


def _cmd_crossref(args):
    """Cross-reference DRE publications with BEP and Law projects."""
    import sqlite3
    from dre_db import init_db, get_publications

    # Load DRE publications
    conn = init_db(args.db)
    pubs = get_publications(conn, limit=500)
    conn.close()

    # Load BEP and Law counts
    bep_path = Path(__file__).parent / "bep_index.db"
    law_path = Path(__file__).parent / "law_index.db"
    bep_count = 0
    law_count = 0

    if bep_path.exists():
        bep_conn = sqlite3.connect(str(bep_path))
        bep_count = bep_conn.execute("SELECT COUNT(*) FROM bep_listings").fetchone()[0]
        bep_conn.close()

    if law_path.exists():
        law_conn = sqlite3.connect(str(law_path))
        law_count = law_conn.execute("SELECT COUNT(*) FROM law_projects").fetchone()[0]
        law_conn.close()

    print(f"\n{'='*80}")
    print(f"  DRE × BEP × Laws Cross-Reference")
    print(f"{'='*80}")
    print(f"  DRE publications:  {len(pubs)}")
    print(f"  BEP listings:      {bep_count}")
    print(f"  Law projects:      {law_count}")
    print(f"{'='*80}\n")

    # Group DRE pubs by serie
    s1 = [p for p in pubs if p["serie"] == 1]
    s2 = [p for p in pubs if p["serie"] == 2]

    print(f"  Serie 1 (Laws): {len(s1)} publications")
    for p in s1[:5]:
        print(f"    #{p['numero']:3d}  {p.get('publication_date', '?')[:10]}  "
              f"{(p.get('title') or '?')[:50]}")

    print(f"\n  Serie 2 (Other): {len(s2)} publications")
    for p in s2[:5]:
        print(f"    #{p['numero']:3d}  {p.get('publication_date', '?')[:10]}  "
              f"{(p.get('title') or '?')[:50]}")

    print(f"\n  Cross-reference opportunities:")
    print(f"    • BEP job → DRE appointment publication (série 2)")
    print(f"    • Law project → DRE law publication (série 1)")
    print(f"    • Entity NIF → contracts + hiring + DRE publications")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="DRE Publication Crawler — Diário da República via ELI URIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s fetch --year 2026 --serie 1
  %(prog)s fetch --year 2026 --all
  %(prog)s search "educação"
  %(prog)s stats
  %(prog)s crossref
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests")

    sub = parser.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch", help="Fetch DRE publications via ELI enumeration")
    p_fetch.add_argument("--year", type=int, default=2026, help="Year to fetch")
    p_fetch.add_argument("--serie", type=int, default=0, help="Series (1 or 2)")
    p_fetch.add_argument("--all", action="store_true", help="Fetch both series")
    p_fetch.add_argument("--max-number", type=int, default=300, help="Max publication number to probe")
    p_fetch.add_argument("--db", default=None, help="DB path")

    p_search = sub.add_parser("search", help="Search publications")
    p_search.add_argument("query", nargs="?", default="", help="Search keyword")
    p_search.add_argument("-n", "--limit", type=int, default=50, help="Max results")
    p_search.add_argument("--db", default=None, help="DB path")

    p_stats = sub.add_parser("stats", help="Show index statistics")
    p_stats.add_argument("--db", default=None, help="DB path")

    p_crossref = sub.add_parser("crossref", help="Cross-reference with BEP and Laws")
    p_crossref.add_argument("--db", default=None, help="DB path")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.command == "fetch":
        client = DRECrawler(delay=args.delay)
        _cmd_fetch(client, args)
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "stats":
        _cmd_stats(args)
    elif args.command == "crossref":
        _cmd_crossref(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
