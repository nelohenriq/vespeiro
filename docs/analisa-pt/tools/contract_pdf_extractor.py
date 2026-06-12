#!/usr/bin/env python3
"""Contract Document PDF Link Extractor (On-Demand)

Follows linkPecasProc URLs from BASE.gov.pt contracts to extract
PDF download links. Uses per-contract SQLite caching so each contract
is only fetched once.

Usage:
    python contract_pdf_extractor.py get 11122539         # Get PDFs for one contract
    python contract_pdf_extractor.py get 11122539 -v      # Verbose
    python contract_pdf_extractor.py cache                # Show cache stats
    python contract_pdf_extractor.py extract --limit 50   # Batch extract (cached)
"""

import sys
import json
import re
import sqlite3
import argparse
import zipfile
import io
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin
from collections import defaultdict
from utils_db import connect as db_connect

try:
    import urllib.request
    import ssl
except ImportError:
    print("ERROR: urllib required (built-in)")
    sys.exit(1)

# Paths
SCRIPT_DIR = Path(__file__).parent
PROCUREMENT_DB = SCRIPT_DIR / "data" / "procurement.db"
PDF_CACHE_DB = SCRIPT_DIR / "data" / "contract_pdfs.db"
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"

# SSL context for HTTPS
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# User agent to avoid blocks
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AnalisaPT/1.0)"}


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def init_pdf_cache(db_path: Path = PDF_CACHE_DB) -> sqlite3.Connection:
    """Initialize the PDF cache database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db_connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contract_pdfs (
            contract_id INTEGER PRIMARY KEY,
            nif TEXT,
            entity_name TEXT,
            link_pecas_proc TEXT,
            url_type TEXT,
            documents TEXT,
            status TEXT,
            extracted_at TEXT
        )
    """)
    conn.commit()
    return conn


def cache_get(conn: sqlite3.Connection, contract_id: int) -> dict | None:
    """Get cached PDF extraction result for a contract."""
    row = conn.execute(
        "SELECT nif, entity_name, link_pecas_proc, url_type, documents, status, extracted_at "
        "FROM contract_pdfs WHERE contract_id = ?",
        (contract_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "contract_id": contract_id,
        "nif": row[0],
        "entity_name": row[1],
        "link_pecas_proc": row[2],
        "url_type": row[3],
        "documents": json.loads(row[4]) if row[4] else [],
        "status": row[5],
        "extracted_at": row[6],
    }


def cache_put(conn: sqlite3.Connection, result: dict):
    """Store PDF extraction result in cache."""
    import datetime
    conn.execute(
        "INSERT OR REPLACE INTO contract_pdfs "
        "(contract_id, nif, entity_name, link_pecas_proc, url_type, documents, status, extracted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            result["contract_id"],
            result.get("nif", ""),
            result.get("entity_name", ""),
            result.get("link_pecas_proc", ""),
            result.get("url_type", ""),
            json.dumps(result.get("documents", []), ensure_ascii=False),
            result.get("status", ""),
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def cache_stats(conn: sqlite3.Connection) -> dict:
    """Get cache statistics."""
    total = conn.execute("SELECT COUNT(*) FROM contract_pdfs").fetchone()[0]
    with_docs = conn.execute(
        "SELECT COUNT(*) FROM contract_pdfs WHERE documents != '[]' AND documents != 'null'"
    ).fetchone()[0]
    by_type = dict(conn.execute(
        "SELECT url_type, COUNT(*) FROM contract_pdfs GROUP BY url_type"
    ).fetchall())
    return {"total": total, "with_docs": with_docs, "by_type": by_type}


# ---------------------------------------------------------------------------
# URL fetching & extraction
# ---------------------------------------------------------------------------

def classify_url(url: str) -> str:
    """Classify the URL type based on domain."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if "vortal" in domain:
        return "vortal"
    elif "acingov" in domain or "10.13." in domain:
        return "acin"
    elif "anogov" in domain:
        return "anogov"
    else:
        return "other"


def fetch_url(url: str, timeout: int = 20, max_bytes: int = 5_000_000, retries: int = 2) -> tuple[int, str, bytes]:
    """Fetch a URL with retry logic."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)
            content_type = resp.headers.get("Content-Type", "unknown")
            data = resp.read(max_bytes)
            return resp.getcode(), content_type, data
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1 * (attempt + 1))
    return 0, str(last_err), b""


def extract_from_acin(data: bytes) -> list[dict]:
    """Extract PDF info from ACIN ZIP response."""
    documents = []
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if not info.is_dir() and info.filename.lower().endswith(".pdf"):
                        documents.append({
                            "filename": info.filename,
                            "size_bytes": info.file_size,
                            "type": "pdf",
                            "source": "acin_zip",
                        })
        except (zipfile.BadZipFile, zipfile.LargeFileNotAllowedError):
            pass
    elif data[:4] == b"%PDF":
        documents.append({
            "filename": "document.pdf",
            "size_bytes": len(data),
            "type": "pdf",
            "source": "acin_direct",
        })
    return documents


def extract_from_html(html: str, base_url: str) -> list[dict]:
    """Extract PDF links from HTML page."""
    documents = []
    pdf_pattern = r'href=["\']([^"\']*\.pdf[^"\']*)["\']'
    for match in re.finditer(pdf_pattern, html, re.IGNORECASE):
        url = match.group(1)
        if not url.startswith("http"):
            url = urljoin(base_url, url)
        documents.append({
            "url": url,
            "filename": urlparse(url).path.split("/")[-1],
            "type": "pdf_link",
            "source": "html",
        })
    return documents


def extract_pdfs_for_url(url: str, verbose: bool = False) -> dict:
    """Fetch a linkPecasProc URL and extract PDF info. Returns result dict."""
    url_type = classify_url(url)

    result = {
        "url_type": url_type,
        "documents": [],
        "status": "ok",
        "error": None,
    }

    if verbose:
        print(f"  [{url_type}] {url[:80]}")

    if url_type == "acin":
        status, content_type, data = fetch_url(url)
        if verbose:
            print(f"    status={status} ct={content_type[:40]} len={len(data)}")
        if status == 200:
            if "zip" in content_type.lower() or data[:2] == b"PK" or data[:4] == b"%PDF":
                result["documents"] = extract_from_acin(data)
            elif b"<html" in data[:1000].lower():
                html = data.decode("utf-8", errors="replace")
                result["documents"] = extract_from_html(html, url)
                if not result["documents"]:
                    result["status"] = "html_no_pdfs"
            else:
                result["status"] = "non_zip_content"
        else:
            result["status"] = f"http_{status}"
            result["error"] = content_type

    elif url_type in ("vortal", "anogov", "other"):
        status, content_type, data = fetch_url(url)
        if verbose:
            print(f"    status={status} ct={content_type[:40]} len={len(data)}")
        if status == 200:
            if data[:4] == b"%PDF":
                result["documents"] = [{
                    "filename": "document.pdf",
                    "size_bytes": len(data),
                    "type": "pdf",
                    "source": "direct",
                }]
            elif b"<html" in data[:1000].lower() or b"<!doctype" in data[:1000].lower():
                html = data.decode("utf-8", errors="replace")
                result["documents"] = extract_from_html(html, url)
                if url_type == "vortal":
                    # Look for Vortal-specific download patterns
                    dl_pattern = r'(https?://[^"\'\\s]*(?:download|piece|peca|documento)[^"\'\\s]*)'
                    for m in re.finditer(dl_pattern, html, re.IGNORECASE):
                        dl_url = m.group(1)
                        if not any(d.get("url") == dl_url for d in result["documents"]):
                            result["documents"].append({
                                "url": dl_url,
                                "filename": urlparse(dl_url).path.split("/")[-1] or "document",
                                "type": "download_link",
                                "source": "vortal_page",
                            })
                if not result["documents"]:
                    result["status"] = "no_pdfs_found"
            else:
                result["status"] = "unknown_content"
        else:
            result["status"] = f"http_{status}"
            result["error"] = content_type

    return result


# ---------------------------------------------------------------------------
# Public API (for use by other scripts like entity_profile.py)
# ---------------------------------------------------------------------------

def get_contract_pdfs(contract_id: int, link_url: str = "", verbose: bool = False) -> list[dict]:
    """Get PDF documents for a contract. Checks cache first, then fetches.

    Args:
        contract_id: The BASE.gov.pt contract ID
        link_url: The linkPecasProc URL (if known, skips XLSX lookup)
        verbose: Print extraction details

    Returns:
        List of document dicts with 'filename', 'size_bytes' or 'url', 'type', 'source'
    """
    conn = init_pdf_cache()
    cached = cache_get(conn, contract_id)
    if cached:
        if verbose:
            print(f"  [cache hit] Contract {contract_id}: {len(cached['documents'])} docs")
        conn.close()
        return cached["documents"]

    # Need to find the link URL from the contract index if not provided
    if not link_url and CONTRACT_INDEX.exists():
        with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
            index = json.load(f)
        # Search all NIFs for this contract_id
        for nif, contracts in index.items():
            for c in contracts:
                if c.get("contract_id") == contract_id:
                    link_url = c.get("link_pecas_proc", "")
                    if not link_url:
                        # No document link for this contract
                        result = {
                            "contract_id": contract_id,
                            "nif": c.get("nif", ""),
                            "entity_name": c.get("entity_name", ""),
                            "link_pecas_proc": "",
                            "url_type": "",
                            "documents": [],
                            "status": "no_link",
                        }
                        cache_put(conn, result)
                        conn.close()
                        return []
                    break
            if link_url:
                break

    if not link_url:
        if verbose:
            print(f"  [not found] Contract {contract_id}: no linkPecasProc URL")
        conn.close()
        return []

    # Fetch and extract
    if verbose:
        print(f"  [fetching] Contract {contract_id}: {link_url[:80]}")
    extraction = extract_pdfs_for_url(link_url, verbose=verbose)

    # Cache result
    result = {
        "contract_id": contract_id,
        "link_pecas_proc": link_url,
        "url_type": extraction["url_type"],
        "documents": extraction["documents"],
        "status": extraction["status"],
    }
    cache_put(conn, result)
    conn.close()
    return extraction["documents"]


def print_cache_stats(conn: sqlite3.Connection):
    """Print cache statistics."""
    stats = cache_stats(conn)
    print(f"\n{'='*60}")
    print(f"  PDF Extraction Cache Stats")
    print(f"{'='*60}")
    print(f"  Contracts cached:    {stats['total']}")
    print(f"  With documents:      {stats['with_docs']}")
    print(f"  By URL type:")
    for url_type, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
        print(f"    {url_type:10s}: {count}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Contract Document PDF Link Extractor (On-Demand)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # Get command (on-demand for a single contract)
    get = sub.add_parser("get", help="Get PDFs for a single contract (cached)")
    get.add_argument("contract_id", type=int, help="Contract ID (idcontrato)")
    get.add_argument("-v", "--verbose", action="store_true")

    # Cache command
    sub.add_parser("cache", help="Show cache statistics")

    # Batch extract command (for pre-warming cache)
    ext = sub.add_parser("extract", help="Batch extract PDFs for multiple contracts")
    ext.add_argument("--limit", type=int, default=50, help="Max contracts to process")
    ext.add_argument("--nif", default="", help="Filter by entity NIF")
    ext.add_argument("--delay", type=float, default=0.5, help="Delay between requests (seconds)")
    ext.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "cache":
        conn = init_pdf_cache()
        print_cache_stats(conn)
        conn.close()
        return

    if args.command == "get":
        docs = get_contract_pdfs(args.contract_id, verbose=args.verbose)
        if docs:
            print(f"\n  Contract {args.contract_id}: {len(docs)} documents found")
            for doc in docs:
                if "url" in doc:
                    print(f"    📄 {doc['filename']} → {doc['url']}")
                else:
                    print(f"    📄 {doc['filename']} ({doc.get('size_bytes', 0):,} bytes)")
        else:
            print(f"  Contract {args.contract_id}: no documents found")
        return

    if args.command == "extract":
        # Batch mode: load contracts from procurement.db
        if not PROCUREMENT_DB.exists():
            print(f"ERROR: procurement.db not found at {PROCUREMENT_DB}")
            sys.exit(1)

        import sqlite3 as _sqlite3
        print(f"  Loading contracts from procurement.db...")
        _conn = db_connect(str(PROCUREMENT_DB))
        _rows = _conn.execute(
            "SELECT idcontrato, linkPecasProc, adjudicante_nif, adjudicante_nome"
            " FROM contratos WHERE linkPecasProc IS NOT NULL AND linkPecasProc != ''"
        ).fetchall()
        _conn.close()

        contracts = []
        for cid, link, nif, name in _rows:
            if not link or not str(link).strip():
                continue
            if args.nif and (nif or "") != args.nif:
                continue
            contracts.append({"contract_id": int(cid), "link_pecas_proc": str(link).strip(),
                              "nif": nif or "", "entity_name": name or ""})
            if args.limit and len(contracts) >= args.limit:
                break

        conn = init_pdf_cache()
        total = len(contracts)
        new = 0
        cached = 0
        for i, c in enumerate(contracts):
            existing = cache_get(conn, c["contract_id"])
            if existing:
                cached += 1
            else:
                extraction = extract_pdfs_for_url(c["link_pecas_proc"], verbose=args.verbose)
                result = {"contract_id": c["contract_id"], "nif": c["nif"],
                          "entity_name": c["entity_name"], "link_pecas_proc": c["link_pecas_proc"],
                          "url_type": extraction["url_type"], "documents": extraction["documents"],
                          "status": extraction["status"]}
                cache_put(conn, result)
                new += 1
                if args.delay > 0:
                    time.sleep(args.delay)
            if (i + 1) % 10 == 0 or (i + 1) == total:
                print(f"  Progress: {i+1}/{total} ({cached} cached, {new} new)")

        print_cache_stats(conn)
        conn.close()


if __name__ == "__main__":
    main()
