#!/usr/bin/env python3
"""Merge NIFs from dados.gov.pt contratos datasets into bep_entities index.

Extracts NIF + entity name pairs from procurement.db (which consolidates
the IMPIC public procurement dataset) and matches them against our
bep_entities by fuzzy name matching.

Usage:
    python merge_nifs.py                  # Run merge with defaults
    python merge_nifs.py --dry-run        # Preview matches without writing
    python merge_nifs.py --threshold 80   # Lower fuzzy match threshold (default 75)
"""

import sqlite3
import re
import sys
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

# Paths
SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "bep_index.db"
DATA_DIR = SCRIPT_DIR / "data"
PROCUREMENT_DB = DATA_DIR / "procurement.db"


def normalize_name(name: str) -> str:
    """Normalize entity name for fuzzy matching."""
    name = name.lower().strip()
    # Remove accents
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    # Remove common suffixes
    for suffix in [', i.p.', ', ip', ', i. p.', ', p.u.', ', p. u.', ', s.a.', ' - sede', ' (sede)']:
        name = name.replace(suffix, '')
    # Normalize whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_nif_from_adjudicante(text: str) -> tuple[str, str]:
    """Extract NIF and entity name from adjudicante field.
    
    Format: 'NIF - Entity Name' or '- - Entity Name' (no NIF)
    Returns: (nif, entity_name)
    """
    if not text:
        return ("", "")
    
    # Pattern: "123456789 - Entity Name"  
    m = re.match(r'^(\d{9})\s*-\s*(.+)$', text.strip())
    if m:
        return (m.group(1), m.group(2).strip())
    
    # Pattern: "- - Entity Name" (no NIF)
    m = re.match(r'^-\s*-\s*(.+)$', text.strip())
    if m:
        return ("", m.group(1).strip())
    
    return ("", text.strip())


def build_nif_lookup_from_db() -> dict[str, str]:
    """Query procurement.db and build a lookup: normalized_entity_name -> nif.
    
    Only includes entities with valid NIFs (9-digit numbers).
    """
    if not PROCUREMENT_DB.exists():
        print(f"  ERROR: procurement.db not found at {PROCUREMENT_DB}")
        print(f"  Run: python procurement_db.py build")
        return {}
    
    print(f"  Loading from procurement.db...")
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    rows = conn.execute(
        "SELECT adjudicante_nif, adjudicante_nome FROM contratos"
        " WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''"
    ).fetchall()
    conn.close()

    name_to_nif: dict[str, str] = {}
    total = 0

    for nif, name in rows:
        total += 1
        if nif and name:
            norm = normalize_name(name)
            if norm not in name_to_nif:
                name_to_nif[norm] = nif

    print(f"  Queried {total} contracts → {len(name_to_nif)} unique entities with NIFs")
    return name_to_nif


def fuzzy_match(query: str, candidates: dict[str, str], threshold: float = 0.75) -> tuple[str, float]:
    """Find the best fuzzy match for query in candidates.
    
    Returns: (matched_key, score) or ("", 0.0)
    """
    q = normalize_name(query)
    best_key = ""
    best_score = 0.0
    
    for key in candidates:
        # Exact substring match is best
        if q in key or key in q:
            score = 0.95
        else:
            score = SequenceMatcher(None, q, key).ratio()
        
        if score > best_score:
            best_score = score
            best_key = key
    
    return (best_key, best_score)


def merge_nifs(dry_run: bool = False, threshold: float = 0.75):
    """Main merge logic."""
    # Init DB
    sys.path.insert(0, str(SCRIPT_DIR))
    from bep_db import init_db, set_nif, get_entities_without_nif, search_entities
    
    conn = init_db(str(DB_PATH))
    
    # Get entities without NIF
    entities = get_entities_without_nif(conn)
    if not entities:
        print("All entities already have NIFs!")
        conn.close()
        return
    
    print(f"\nEntities without NIF: {len(entities)}")
    

    name_to_nif = build_nif_lookup_from_db()
    if not name_to_nif:
        print("ERROR: No NIFs extracted from procurement.db")
        conn.close()
        return
    
    # Match entities against NIF lookup
    matched = 0
    unmatched = []
    
    for e in entities:
        display = e['organismo'] or e['entidade']
        match_key, score = fuzzy_match(display, name_to_nif, threshold)
        
        if score >= threshold and match_key:
            nif = name_to_nif[match_key]
            if dry_run:
                print(f"  [DRY-RUN] {e['id']}  NIF={nif}  {display[:50]:50s}  ← {match_key[:50]} ({score:.2f})")
            else:
                set_nif(conn, e['id'], nif)
                print(f"  ✓ {e['id']}  NIF={nif}  {display[:50]:50s}  ← {match_key[:50]} ({score:.2f})")
            matched += 1
        else:
            unmatched.append((e, score))
    
    if not dry_run:
        conn.commit()
    
    conn.close()
    
    # Summary
    print(f"\n=== Merge complete ===")
    print(f"Matched: {matched}/{len(entities)} entities got NIFs")
    if unmatched:
        print(f"Unmatched ({len(unmatched)}):")
        for e, score in unmatched[:10]:
            display = e['organismo'] or e['entidade']
            print(f"  {e['id']}  (best score: {score:.2f})  {display[:70]}")
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched) - 10} more")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Merge NIFs from dados.gov.pt into BEP entity index")
    parser.add_argument("--dry-run", action="store_true", help="Preview matches without writing")
    parser.add_argument("--threshold", type=float, default=0.75, help="Fuzzy match threshold (0-1)")
    args = parser.parse_args()
    
    merge_nifs(dry_run=args.dry_run, threshold=args.threshold)
