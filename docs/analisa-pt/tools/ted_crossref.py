#!/usr/bin/env python3
"""TED Cross-Reference — EU Threshold Compliance Checker

Cross-references Portuguese procurement contracts from procurement.db with
TED (Tenders Electronic Daily) to identify contracts above EU thresholds
that may not have been properly published on TED.

EU Thresholds (2024-2025):
  - Works: €5,538,000
  - Supplies & Services (Central Govt): €143,000
  - Supplies & Services (Sub-central): €221,000

Usage:
    python ted_crossref.py check          # Check TED compliance for all contracts
    python ted_crossref.py check --min-value 100000  # Only check contracts > €100K
    python ted_crossref.py search "Porto" # Search TED for notices from an entity
    python ted_crossref.py stats          # Summary statistics
    python ted_crossref.py sync           # Download all PT notices from TED
    python ted_crossref.py export         # Export results to JSON
"""

import sys
import json
import sqlite3
import argparse
import time
from pathlib import Path
from collections import defaultdict

try:
    import urllib.request
    import ssl
except ImportError:
    print("ERROR: urllib required (built-in)")
    sys.exit(1)

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
TED_DB = DATA_DIR / "ted_notices.db"

# TED API v3 configuration
TED_API_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_NOTICE_URL = "https://api.ted.europa.eu/v3/notices"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "analisa-pt/1.0",
}

# SSL context (skip verification for government APIs)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# EU procurement thresholds (EUR, 2024-2025)
# From Official Journal of the EU
EU_THRESHOLDS = {
    "works": 5_538_000,           # Works contracts
    "supplies_services_central": 143_000,   # Supplies & services - central government
    "supplies_services_subcentral": 221_000, # Supplies & services - sub-central
}

# CPV code ranges for contract type classification
CPV_WORKS_PREFIXES = ("45", "44")  # Construction, building
CPV_SUPPLIES_PREFIXES = ("3",)     # Goods
CPV_SERVICES_PREFIXES = ("5", "6", "7", "8", "9")  # Services


# =============================================================================
# TED DATABASE
# =============================================================================

def init_ted_db(db_path: Path = TED_DB) -> sqlite3.Connection:
    """Initialize the TED notices cache database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ted_notices (
            publication_number TEXT PRIMARY KEY,
            procedure_id TEXT,
            title TEXT,
            buyer_name TEXT,
            buyer_country TEXT,
            notice_type TEXT,
            contract_type TEXT,
            cpv TEXT,
            estimated_value REAL,
            publication_date TEXT,
            links TEXT,
            raw_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ted_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            synced_at TEXT,
            total_notices INTEGER,
            status TEXT
        )
    """)
    conn.commit()
    return conn


def ted_search(query: str, fields: list[str] = None, limit: int = 100, page: int = 1) -> dict:
    """Search TED API v3 for notices.
    
    Returns: {"notices": [...], "totalNoticeCount": int}
    """
    if fields is None:
        fields = [
            "BT-21-Procedure",
            "BT-22-Procedure", 
            "BT-24-Procedure",
            "BT-27-Procedure",
            "BT-131(d)-Lot",
            "BT-131(t)-Lot",
            "BT-262-Procedure",
        ]
    
    payload = json.dumps({
        "query": query,
        "scope": "LATEST",
        "fields": fields,
        "page": page,
        "limit": limit,
    }).encode("utf-8")
    
    req = urllib.request.Request(TED_API_URL, data=payload, method="POST", headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=30, context=SSL_CTX)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  TED API Error {e.code}: {body[:200]}", file=sys.stderr)
        return {"notices": [], "totalNoticeCount": 0}
    except Exception as e:
        print(f"  TED API Error: {type(e).__name__}: {e}", file=sys.stderr)
        return {"notices": [], "totalNoticeCount": 0}


def cmd_sync(args):
    """Download all Portuguese contract notices from TED."""
    conn = init_ted_db()
    
    print("Syncing TED notices for Portugal...")
    
    # Sync different notice types
    # TED API v3 only supports these notice types
    notice_types = [
        ("cn-standard", "Contract Notices"),
        ("cn-standard", "Contract Awards"),  # Awards are also cn-standard in v3
    ]
    
    total_synced = 0
    
    for notice_type, description in notice_types:
        print(f"\n  Syncing {description}...")
        
        page = 1
        synced = 0
        has_more = True
        
        while has_more:
            query = f"buyer-country=PRT AND notice-type={notice_type}"
            result = ted_search(query, limit=100, page=page)
            
            notices = result.get("notices", [])
            total = result.get("totalNoticeCount", 0)
            
            if page == 1:
                print(f"    Total {description}: {total}")
            
            for notice in notices:
                pub_num = notice.get("publication-number", "")
                if not pub_num:
                    continue
                
                # Extract fields
                title = ""
                if "BT-21-Procedure" in notice:
                    t = notice["BT-21-Procedure"]
                    if isinstance(t, dict):
                        title = t.get("por", t.get("eng", ""))
                    else:
                        title = str(t)
                
                buyer = ""
                if "BT-22-Procedure" in notice:
                    b = notice["BT-22-Procedure"]
                    if isinstance(b, dict):
                        buyer = b.get("por", b.get("eng", ""))
                    else:
                        buyer = str(b)
                
                desc = ""
                if "BT-24-Procedure" in notice:
                    d = notice["BT-24-Procedure"]
                    if isinstance(d, dict):
                        desc = d.get("por", d.get("eng", ""))
                    else:
                        desc = str(d)
                
                cpv = ""
                if "BT-131(d)-Lot" in notice:
                    c = notice["BT-131(d)-Lot"]
                    if isinstance(c, list):
                        cpv = str(c[0]) if c else ""
                    else:
                        cpv = str(c)
                
                # Store in DB — ensure all params are strings/ints/floats (not lists)
                proc_id = notice.get("BT-262-Procedure", "")
                if isinstance(proc_id, list):
                    proc_id = proc_id[0] if proc_id else ""
                
                conn.execute(
                    """INSERT OR REPLACE INTO ted_notices 
                       (publication_number, procedure_id, title, buyer_name,
                        buyer_country, notice_type, contract_type, cpv,
                        estimated_value, publication_date, links, raw_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pub_num,
                        str(proc_id),
                        title[:500],
                        buyer[:500],
                        "PRT",
                        notice_type,
                        classify_contract_type(cpv),
                        cpv[:100],
                        extract_value(notice),
                        extract_pub_date(notice),
                        json.dumps(notice.get("links", {})),
                        json.dumps(notice, default=str)[:5000],
                    ),
                )
                synced += 1
            
            has_more = len(notices) == 100
            page += 1
            
            # Rate limiting: 1 request per second
            if has_more:
                time.sleep(1)
        
        conn.commit()
        print(f"    Synced: {synced:,} {description}")
        total_synced += synced
    
    # Log sync
    conn.execute(
        "INSERT INTO ted_sync_log (synced_at, total_notices, status) VALUES (?, ?, ?)",
        (time.strftime("%Y-%m-%d %H:%M:%S"), total_synced, "ok"),
    )
    conn.commit()
    conn.close()
    
    print(f"\n  Total TED notices synced: {total_synced:,}")
    print(f"  Database: {TED_DB}")


def classify_contract_type(cpv: str) -> str:
    """Classify contract type based on CPV code prefix."""
    if not cpv:
        return "unknown"
    prefix = cpv[:2] if len(cpv) >= 2 else cpv
    if prefix in CPV_WORKS_PREFIXES:
        return "works"
    elif prefix.startswith("3"):
        return "supplies"
    elif prefix in CPV_SERVICES_PREFIXES:
        return "services"
    return "unknown"


def extract_value(notice: dict) -> float:
    """Extract estimated contract value from a TED notice."""
    # Try BT-27-Procedure (estimated total value)
    val = notice.get("BT-27-Procedure")
    if val is not None:
        if isinstance(val, (int, float)):
            return float(val)
        elif isinstance(val, dict):
            return float(val.get("amount", 0) or 0)
    return 0.0


def extract_pub_date(notice: dict) -> str:
    """Extract publication date from a TED notice."""
    # Publication number format: NNNNNNN-YYYY
    pub_num = notice.get("publication-number", "")
    if "-" in pub_num:
        return pub_num.split("-")[-1]
    return ""


# =============================================================================
# COMPLIANCE CHECK
# =============================================================================

def cmd_check(args):
    """Check TED compliance for Portuguese contracts."""
    if not PROCUREMENT_DB.exists():
        print(f"ERROR: procurement.db not found at {PROCUREMENT_DB}")
        sys.exit(1)
    
    conn_proc = sqlite3.connect(str(PROCUREMENT_DB))
    conn_proc.row_factory = sqlite3.Row
    
    min_value = args.min_value
    
    # Get contracts above the sub-central threshold (highest threshold)
    threshold = min_value if min_value > 0 else EU_THRESHOLDS["supplies_services_subcentral"]
    
    print(f"\n{'='*80}")
    print(f"  TED Compliance Check — EU Threshold: €{threshold:,.0f}")
    print(f"{'='*80}")
    
    # Get contracts from procurement.db
    contracts = conn_proc.execute(
        """SELECT idcontrato, adjudicante_nif, adjudicante_nome, objectoContrato,
                  precoContratual, precoBaseProcedimento, tipoContrato, CPV,
                  dataCelebracaoContrato, linkPecasProc, nAnuncio
           FROM contratos
           WHERE precoContratual >= ?
           ORDER BY precoContratual DESC""",
        (threshold,),
    ).fetchall()
    
    print(f"\n  Contracts above €{threshold:,.0f}: {len(contracts):,}")
    
    if not contracts:
        print("  No contracts above threshold.")
        conn_proc.close()
        return
    
    # Check against TED notices
    conn_ted = init_ted_db()
    ted_notices = conn_ted.execute(
        "SELECT publication_number, title, buyer_name, cpv FROM ted_notices"
    ).fetchall()
    
    # Build TED lookup by buyer name (fuzzy)
    ted_by_buyer = defaultdict(list)
    for pub, title, buyer, cpv in ted_notices:
        if buyer:
            ted_by_buyer[buyer.lower().strip()].append(pub)
    
    # Categorize contracts
    above_works = []
    above_services_subcentral = []
    
    for c in contracts:
        val = c["precoContratual"]
        cpv = c["CPV"] or ""
        
        contract_type = classify_contract_type(cpv)
        
        # Determine applicable threshold
        if contract_type == "works":
            applicable = EU_THRESHOLDS["works"]
        else:
            applicable = EU_THRESHOLDS["supplies_services_subcentral"]
        
        # Check if contract should be on TED
        if val >= applicable:
            # Try to find in TED
            buyer_name = (c["adjudicante_nome"] or "").lower().strip()
            found_in_ted = False
            ted_match = ""
            
            # Exact buyer name match
            if buyer_name in ted_by_buyer:
                found_in_ted = True
                ted_match = ted_by_buyer[buyer_name][0]
            
            # Also check object/contract ID
            if not found_in_ted:
                obj = (c["objectoContrato"] or "").lower()
                for pub, title, buyer, _ in ted_notices:
                    if title and (obj[:30] in title.lower() or title.lower()[:30] in obj):
                        found_in_ted = True
                        ted_match = pub
                        break
            
            result = {
                "contract_id": c["idcontrato"],
                "buyer_nif": c["adjudicante_nif"],
                "buyer_name": c["adjudicante_nome"],
                "object": c["objectoContrato"][:100] if c["objectoContrato"] else "",
                "value": val,
                "contract_type": contract_type,
                "threshold": applicable,
                "found_in_ted": found_in_ted,
                "ted_match": ted_match,
                "date": c["dataCelebracaoContrato"],
            }
            
            if contract_type == "works":
                above_works.append(result)
            elif contract_type in ("services", "supplies"):
                above_services_subcentral.append(result)
            # 'unknown' CPV type — still flag if above threshold
            else:
                above_services_subcentral.append(result)
    
    # Summary
    missing = [r for r in above_works + above_services_subcentral if not r["found_in_ted"]]
    found = [r for r in above_works + above_services_subcentral if r["found_in_ted"]]
    
    total_value_missing = sum(r["value"] for r in missing)
    total_value_found = sum(r["value"] for r in found)
    
    print(f"\n  📊 Compliance Summary")
    print(f"  {'─'*60}")
    print(f"  Contracts checked:          {len(contracts):,}")
    print(f"  Above applicable threshold: {len(above_works) + len(above_services_subcentral):,}")
    print(f"  Found in TED:               {len(found):,} (€{total_value_found:,.0f})")
    print(f"  NOT found in TED:           {len(missing):,} (€{total_value_missing:,.0f})")
    
    if missing:
        print(f"\n  🔴 Contracts NOT Found in TED (Potential Non-Compliance)")
        print(f"  {'─'*100}")
        print(f"  {'#':<4}{'ID':<12}{'Buyer':<35}{'Value':>16}{'Type':<10}{'Date':<12}")
        print(f"  {'─'*4}{'─'*12}{'─'*35}{'─'*16}{'─'*10}{'─'*12}")
        
        for i, r in enumerate(missing[:50], 1):
            buyer = (r["buyer_name"] or "N/A")[:33]
            print(f"  {i:<4}{r['contract_id']:<12}{buyer:<35}€{r['value']:>14,.0f}{r['contract_type']:<10}{r['date'] or 'N/A':<12}")
            if r["object"]:
                print(f"      Object: {r['object'][:70]}")
        
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more")
    
    if found:
        print(f"\n  🟢 Contracts Found in TED (Compliant)")
        print(f"  {'─'*100}")
        for i, r in enumerate(found[:20], 1):
            buyer = (r["buyer_name"] or "N/A")[:33]
            print(f"  {i:<4}{r['contract_id']:<12}{buyer:<35}€{r['value']:>14,.0f}{r['contract_type']:<10}{r['ted_match']}")
        if len(found) > 20:
            print(f"  ... and {len(found) - 20} more")
    
    # Threshold analysis
    print(f"\n  📋 EU Threshold Analysis")
    print(f"  {'─'*60}")
    print(f"  Works threshold:            €{EU_THRESHOLDS['works']:>14,.0f}")
    print(f"  Supplies/Services (Central): €{EU_THRESHOLDS['supplies_services_central']:>13,.0f}")
    print(f"  Supplies/Services (Sub-central): €{EU_THRESHOLDS['supplies_services_subcentral']:>9,.0f}")
    
    conn_proc.close()
    conn_ted.close()


def cmd_search(args):
    """Search TED notices for a specific entity or keyword."""
    conn = init_ted_db()
    
    query = args.query
    
    print(f"\n{'='*80}")
    print(f"  TED Search: {query}")
    print(f"{'='*80}")
    
    # Search in local DB first
    results = conn.execute(
        """SELECT publication_number, title, buyer_name, notice_type, 
                  cpv, estimated_value
           FROM ted_notices
           WHERE title LIKE ? OR buyer_name LIKE ?
           ORDER BY estimated_value DESC""",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    
    if results:
        print(f"\n  Local database results: {len(results)}")
        for i, (pub, title, buyer, ntype, cpv, val) in enumerate(results[:20], 1):
            print(f"  {i}. [{pub}] {title[:60]}")
            print(f"     Buyer: {buyer[:50]} | Type: {ntype} | Value: €{val:,.0f}")
    else:
        print(f"\n  No results in local database.")
        print(f"  Run: python ted_crossref.py sync")
    
    conn.close()


def cmd_stats(args):
    """Show TED database statistics."""
    if not TED_DB.exists():
        print("TED database not found. Run: python ted_crossref.py sync")
        return
    
    conn = init_ted_db()
    
    total = conn.execute("SELECT COUNT(*) FROM ted_notices").fetchone()[0]
    
    print(f"\n{'='*60}")
    print(f"  TED Database Statistics")
    print(f"{'='*60}")
    print(f"  Total notices: {total:,}")
    
    # By notice type
    print(f"\n  By Notice Type:")
    for row in conn.execute(
        "SELECT notice_type, COUNT(*) FROM ted_notices GROUP BY notice_type ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {row[0]:30s}: {row[1]:,}")
    
    # By contract type
    print(f"\n  By Contract Type:")
    for row in conn.execute(
        "SELECT contract_type, COUNT(*) FROM ted_notices GROUP BY contract_type ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {row[0]:30s}: {row[1]:,}")
    
    # Last sync
    last_sync = conn.execute(
        "SELECT synced_at, total_notices FROM ted_sync_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last_sync:
        print(f"\n  Last sync: {last_sync[0]} ({last_sync[1]:,} notices)")
    
    conn.close()


def cmd_export(args):
    """Export TED data to JSON."""
    if not TED_DB.exists():
        print("TED database not found. Run: python ted_crossref.py sync")
        return
    
    conn = init_ted_db()
    
    notices = conn.execute(
        "SELECT * FROM ted_notices ORDER BY estimated_value DESC"
    ).fetchall()
    
    columns = ["publication_number", "procedure_id", "title", "buyer_name",
                "buyer_country", "notice_type", "contract_type", "cpv",
                "estimated_value", "publication_date"]
    
    output = [dict(zip(columns, row)) for row in notices]
    
    out_path = DATA_DIR / "ted_notices.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=1, default=str)
    
    print(f"Exported {len(output):,} TED notices to {out_path}")
    conn.close()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="TED Cross-Reference — EU Threshold Compliance Checker",
    )
    sub = parser.add_subparsers(dest="command")
    
    # Check command
    check_p = sub.add_parser("check", help="Check TED compliance")
    check_p.add_argument("--min-value", type=float, default=0, help="Min contract value (EUR)")
    
    # Search command
    search_p = sub.add_parser("search", help="Search TED notices")
    search_p.add_argument("query", help="Entity name or keyword")
    
    # Sync command
    sub.add_parser("sync", help="Download PT notices from TED")
    
    # Stats command
    sub.add_parser("stats", help="Show database statistics")
    
    # Export command
    sub.add_parser("export", help="Export TED data to JSON")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == "sync":
        cmd_sync(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "export":
        cmd_export(args)


if __name__ == "__main__":
    main()
