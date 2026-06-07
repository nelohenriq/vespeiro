#!/usr/bin/env python3
"""Scan a specific BEP ID range and persist to the local SQLite index."""
import sys
import time
sys.path.insert(0, ".")
from bep_scraper import BEPScraper
from bep_db import init_db, upsert_entity, upsert_listing, refresh_entity_count

def scan_range(start_id: int, end_id: int, delay: float = 0.1):
    scraper = BEPScraper(delay=delay)
    conn = init_db()

    new_count = 0
    updated_count = 0
    empty_streak = 0
    total = 0

    print(f"Scanning IDs {start_id}-{end_id}...")

    for cod in range(end_id, start_id - 1, -1):
        listing = scraper.fetch_listing(cod)
        if not listing:
            empty_streak += 1
            if empty_streak > 30:
                print(f"Stopping at {cod}: 30 consecutive empty IDs")
                break
            continue

        empty_streak = 0
        eid = upsert_entity(conn, listing.entidade, listing.organismo)
        is_new = upsert_listing(conn, listing.to_dict(), eid)
        refresh_entity_count(conn, eid)

        if is_new:
            new_count += 1
        else:
            updated_count += 1
        total += 1

        if total % 50 == 0:
            print(f"  Progress: {total} processed ({new_count} new, {updated_count} updated)")

    conn.commit()
    conn.close()
    print(f"\nDone: {total} total, {new_count} new, {updated_count} updated")


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 140000
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 147000
    scan_range(start, end)
