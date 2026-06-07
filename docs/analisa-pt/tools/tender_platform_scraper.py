#!/usr/bin/env python3
"""Tender Platform Scraper — Extract pre-contract data from Portuguese e-procurement platforms.

Scrapes publicly accessible parts of AcinGov, VortalGOV, and anoGov to extract
tender metadata (Convites, Propostas, Habilitação) that BASE.gov.pt doesn't have.
Cross-references with our existing contract_index.json to identify the "gap"
between platform publication and BASE.gov.pt availability.

Usage:
    python tender_platform_scraper.py search --platform acin --query "município"
    python tender_platform_scraper.py search --platform vortal --nif 500014872
    python tender_platform_scraper.py analyze --limit 100
    python tender_platform_scraper.py gap --nif 500014872
    python tender_platform_scraper.py stats
"""

import sys
import json
import re
import sqlite3
import argparse
import time
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote
from collections import defaultdict
from datetime import datetime, timezone

try:
    import urllib.request
    import ssl
except ImportError:
    print("ERROR: urllib required (built-in)")
    sys.exit(1)

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SCRAPER_DB = DATA_DIR / "tender_platforms.db"
CONTRACT_INDEX = DATA_DIR / "contract_index.json"

# SSL context
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# User agent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

# Platform configurations
PLATFORMS = {
    "acin": {
        "name": "acinGov",
        "public_search": "https://www.acingov.pt/acingovprod/2/zonaPublica/zona_publica_c/indexProcedimentos",
        "base_url": "https://www.acingov.pt",
        "stages": ["DRE", "Convites", "Propostas", "Habilitação", "Revogação", "Impugnação", "Contrato"],
    },
    "vortal": {
        "name": "VortalGOV",
        "public_search": "https://www.vortal.com/portal/external/tendering/default.aspx",
        "base_url": "https://www.vortal.com",
        "stages": ["DRE", "Convites", "Propostas", "Habilitação", "Revogação", "Impugnação", "Contrato"],
    },
    "anogov": {
        "name": "anoGov",
        "public_search": "https://www.anogov.com",
        "base_url": "https://www.anogov.com",
        "stages": ["DRE", "Convites", "Propostas", "Habilitação", "Revogação", "Impugnação", "Contrato"],
    },
}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialize the tender platforms database."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SCRAPER_DB))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scraped_tenders (
            id TEXT PRIMARY KEY,
            platform TEXT,
            entity_name TEXT,
            entity_nif TEXT,
            procedure_type TEXT,
            procedure_number TEXT,
            title TEXT,
            description TEXT,
            status TEXT,
            published_date TEXT,
            deadline TEXT,
            estimated_value REAL,
            url TEXT,
            stage TEXT,
            data_json TEXT,
            scraped_at TEXT,
            source TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT,
            query TEXT,
            results_count INTEGER,
            new_count INTEGER,
            run_at TEXT,
            duration_seconds REAL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gap_analysis (
            nif TEXT,
            platform TEXT,
            entity_name TEXT,
            platform_tenders INTEGER,
            base_contracts INTEGER,
            gap_count INTEGER,
            analyzed_at TEXT,
            PRIMARY KEY (nif, platform)
        )
    """)

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# URL fetching
# ---------------------------------------------------------------------------

def fetch_url(url: str, timeout: int = 20, max_bytes: int = 2_000_000, retries: int = 2) -> tuple[int, str, bytes]:
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


# ---------------------------------------------------------------------------
# AcinGov public zone scraper
# ---------------------------------------------------------------------------

def scrape_acin_public(query: str = "", limit: int = 50) -> list[dict]:
    """Scrape AcinGov's public tender search zone.

    The public zone at acingov.pt allows searching for active tenders
    without authentication, but results are limited.
    """
    platform = PLATFORMS["acin"]
    tenders = []

    try:
        # First, load the search page to get session cookies
        status, ct, data = fetch_url(platform["public_search"])
        if status != 200:
            print(f"  ⚠️  AcinGov public zone returned HTTP {status}")
            return tenders

        html = data.decode("utf-8", errors="replace")

        # Extract any visible tender listings from the HTML
        # AcinGov uses a dynamic search interface, so we parse what's available
        tender_pattern = re.compile(
            r'(?:procedimento|concurso|procedure)[^<]*?(?:id|num)[^<]*?(\d{6,})',
            re.IGNORECASE
        )
        matches = tender_pattern.findall(html)

        # Also look for structured data in JSON/script tags
        json_pattern = re.compile(r'var\s+\w+\s*=\s*(\{[^;]{50,5000}\})', re.DOTALL)
        for jm in json_pattern.finditer(html):
            try:
                data_obj = json.loads(jm.group(1))
                if isinstance(data_obj, dict) and any(k in str(data_obj).lower() for k in ['procedimento', 'concurso', 'tender']):
                    tenders.append({
                        "id": f"acin_{hashlib.md5(str(data_obj).encode()).hexdigest()[:12]}",
                        "platform": "acin",
                        "data_json": json.dumps(data_obj, ensure_ascii=False)[:2000],
                        "source": "acin_public_html",
                    })
            except (json.JSONDecodeError, ValueError):
                pass

        # Parse any visible table rows or list items
        row_pattern = re.compile(
            r'<tr[^>]*>(.*?)</tr>',
            re.DOTALL | re.IGNORECASE
        )
        for rm in row_pattern.finditer(html):
            row_html = rm.group(1)
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
            if len(cells) >= 2:
                # Clean HTML tags from cell content
                clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                text = ' | '.join(clean_cells)
                if any(kw in text.lower() for kw in ['procedimento', 'concurso', 'contrato', 'município', 'câmara']):
                    tenders.append({
                        "id": f"acin_row_{hashlib.md5(text.encode()).hexdigest()[:12]}",
                        "platform": "acin",
                        "title": clean_cells[0] if clean_cells else "",
                        "description": text[:500],
                        "source": "acin_public_table",
                    })

        if not tenders:
            # If no structured data found, record the page was accessed
            tenders.append({
                "id": f"acin_page_{hashlib.md5(platform['public_search'].encode()).hexdigest()[:12]}",
                "platform": "acin",
                "title": "AcinGov Public Zone",
                "description": f"Page accessed successfully. No structured tender data visible without authentication. Query: {query}",
                "url": platform["public_search"],
                "data_json": "",
                "source": "acin_page_check",
            })

    except Exception as e:
        print(f"  ⚠️  Error scraping AcinGov: {e}")

    # Normalize all items to have consistent schema for DB insertion
    normalized = []
    for t in tenders[:limit]:
        normalized.append({
            "id": t["id"],
            "platform": t.get("platform", "acin"),
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "url": t.get("url", platform["public_search"]),
            "data_json": t.get("data_json", ""),
            "source": t.get("source", "acin_public_html"),
        })
    return normalized


# ---------------------------------------------------------------------------
# VortalGOV public scraper
# ---------------------------------------------------------------------------

def scrape_vortal_public(query: str = "", limit: int = 50) -> list[dict]:
    """Scrape VortalGOV's public tender pages.

    Vortal uses entity-specific portals. We check known public URLs.
    """
    platform = PLATFORMS["vortal"]
    tenders = []

    # Known public Vortal portals for Portuguese government entities
    known_portals = [
        "https://www.vortal.com/portal/external/tendering/default.aspx",
        "https://compras.amp.pt",
        "https://compras.cm-porto.pt",
    ]

    for portal_url in known_portals:
        try:
            status, ct, data = fetch_url(portal_url, timeout=15)
            if status == 200:
                html = data.decode("utf-8", errors="replace")

                # Extract tender listings
                listing_pattern = re.compile(
                    r'(?:tender|concurso|procedimento|edital)[^<]{5,200}',
                    re.IGNORECASE
                )
                for m in listing_pattern.finditer(html):
                    text = m.group(0).strip()
                    if len(text) > 10:
                        tenders.append({
                            "id": f"vortal_{hashlib.md5(text.encode()).hexdigest()[:12]}",
                            "platform": "vortal",
                            "title": text[:200],
                            "url": portal_url,
                            "source": "vortal_public_page",
                        })

                if not tenders:
                    tenders.append({
                        "id": f"vortal_check_{hashlib.md5(portal_url.encode()).hexdigest()[:12]}",
                        "platform": "vortal",
                        "title": f"Vortal Portal Check: {portal_url}",
                        "description": f"HTTP {status}. Page accessible but no structured tender data visible.",
                        "url": portal_url,
                        "data_json": "",
                        "source": "vortal_page_check",
                    })
        except Exception as e:
            pass  # Skip failed portals silently

    # Normalize all items to have consistent schema for DB insertion
    normalized = []
    for t in tenders[:limit]:
        normalized.append({
            "id": t["id"],
            "platform": t.get("platform", "vortal"),
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "url": t.get("url", platform["public_search"]),
            "data_json": t.get("data_json", ""),
            "source": t.get("source", "vortal_public_page"),
        })
    return normalized


# ---------------------------------------------------------------------------
# linkPecasProc extraction from existing data
# ---------------------------------------------------------------------------

def extract_platform_urls_from_index(limit: int = 100) -> list[dict]:
    """Extract all platform URLs from contract_index.json link_pecas_proc fields.

    These are the URLs that point to AcinGov, VortalGOV, or anoGov
    tender document pages. We can scrape these for pre-contract metadata.
    """
    if not CONTRACT_INDEX.exists():
        print(f"  ⚠️  Contract index not found at {CONTRACT_INDEX}")
        return []

    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        index = json.load(f)

    urls = []
    for nif, contracts in index.items():
        for c in contracts:
            link = c.get("link_pecas_proc", "")
            if not link:
                continue
            parsed = urlparse(link)
            domain = parsed.netloc.lower()

            platform = None
            if "vortal" in domain:
                platform = "vortal"
            elif "acingov" in domain or "10.13." in domain:
                platform = "acin"
            elif "anogov" in domain:
                platform = "anogov"
            else:
                continue

            urls.append({
                "contract_id": c.get("contract_id"),
                "nif": nif,
                "entity_name": c.get("entity_name", ""),
                "platform": platform,
                "url": link,
                "valor": c.get("valor", 0),
                "data": c.get("data", ""),
                "tipo": c.get("tipo", ""),
                "objeto": c.get("objeto", ""),
                "adjudicatario": c.get("adjudicatario", ""),
            })

            if limit and len(urls) >= limit:
                return urls

    return urls


def scrape_contract_platform_url(url: str, contract_id: int = 0, verbose: bool = False) -> dict:
    """Scrape a single linkPecasProc URL for tender metadata.

    Returns extracted metadata about the tender procedure.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    if "vortal" in domain:
        platform = "vortal"
    elif "acingov" in domain or "10.13." in domain:
        platform = "acin"
    elif "anogov" in domain:
        platform = "anogov"
    else:
        platform = "other"

    result = {
        "contract_id": contract_id,
        "platform": platform,
        "url": url,
        "status": "unknown",
        "metadata": {},
    }

    try:
        status_code, ct, data = fetch_url(url, timeout=20)
        if verbose:
            print(f"    [{platform}] HTTP {status_code}, CT={ct[:40]}, Size={len(data)}")

        if status_code != 200:
            result["status"] = f"http_{status_code}"
            return result

        # Check if it's a ZIP (AcinGov style)
        if data[:2] == b"PK":
            result["status"] = "zip_package"
            result["metadata"]["content_type"] = "zip"
            result["metadata"]["size_bytes"] = len(data)
            return result

        # Check if it's a direct PDF
        if data[:4] == b"%PDF":
            result["status"] = "direct_pdf"
            result["metadata"]["content_type"] = "pdf"
            result["metadata"]["size_bytes"] = len(data)
            return result

        # Parse HTML for metadata
        html = data.decode("utf-8", errors="replace")

        # Extract title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if title_match:
            result["metadata"]["page_title"] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()[:200]

        # Extract procedure number
        proc_match = re.search(r'(?:procedimento|processo|nº?)\s*[.:]?\s*(\d[\d./\-]+)', html, re.IGNORECASE)
        if proc_match:
            result["metadata"]["procedure_number"] = proc_match.group(1)

        # Extract dates
        date_patterns = [
            (r'(?:prazo|deadline|data.*limite)[^<]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', "deadline"),
            (r'(?:publicação|published|data.*publicação)[^<]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', "published"),
            (r'(?:abertura|opening|data.*abertura)[^<]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', "opening"),
        ]
        for pattern, field in date_patterns:
            dm = re.search(pattern, html, re.IGNORECASE)
            if dm:
                result["metadata"][field] = dm.group(1)

        # Extract value/price
        value_match = re.search(r'(?:valor|preço|price|€)\s*[.:]?\s*([\d.,]+)', html, re.IGNORECASE)
        if value_match:
            val_str = value_match.group(1).replace(".", "").replace(",", ".")
            try:
                result["metadata"]["estimated_value"] = float(val_str)
            except ValueError:
                pass

        # Count PDF links
        pdf_links = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, re.IGNORECASE)
        result["metadata"]["pdf_count"] = len(pdf_links)
        result["metadata"]["pdf_links"] = pdf_links[:10]

        # Count download links
        dl_links = re.findall(
            r'href=["\']([^"\']*(?:download|piece|peca|documento|anexo)[^"\']*)["\']',
            html, re.IGNORECASE
        )
        result["metadata"]["download_count"] = len(dl_links)

        # Extract any visible status/state
        status_patterns = [
            r'(?:estado|status|situação)[^<]*?([A-Za-zÀ-ú\s]{3,30})',
            r'(?:aberto|closed|cancelado|adjudicado|em\s*avaliação)',
        ]
        for sp in status_patterns:
            sm = re.search(sp, html, re.IGNORECASE)
            if sm:
                result["metadata"]["tender_status"] = sm.group(0).strip()[:50]
                break

        # Extract entity name from page
        entity_match = re.search(r'(?:entidade|organismo|contracting)[^<]*?([A-ZÀ-Ú][\w\s,\.]{5,80})', html, re.IGNORECASE)
        if entity_match:
            result["metadata"]["entity_on_page"] = entity_match.group(1).strip()[:100]

        result["status"] = "parsed"
        result["metadata"]["html_size"] = len(data)

    except Exception as e:
        result["status"] = f"error: {str(e)[:100]}"

    return result


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def analyze_gap(nif: str = "", limit: int = 50, verbose: bool = False) -> list[dict]:
    """Analyze the gap between platform tender data and BASE.gov.pt contracts.

    Finds contracts with linkPecasProc URLs pointing to platforms,
    scrapes them for metadata, and identifies what pre-contract data
    is available that isn't in our contract_index.json.
    """
    urls = extract_platform_urls_from_index(limit=limit * 3)
    if nif:
        urls = [u for u in urls if u["nif"] == nif]

    if not urls:
        print("  No platform URLs found in contract index.")
        return []

    print(f"  Found {len(urls)} contracts with platform URLs")
    print(f"  Analyzing pre-contract data availability...\n")

    results = []
    for i, u in enumerate(urls[:limit]):
        if verbose:
            print(f"  [{i+1}/{min(limit, len(urls))}] Contract {u['contract_id']} ({u['platform']})")

        scraped = scrape_contract_platform_url(u["url"], u["contract_id"], verbose=verbose)

        # Merge with contract data
        enriched = {
            **u,
            "scraped_status": scraped["status"],
            "scraped_metadata": scraped.get("metadata", {}),
        }
        results.append(enriched)

        time.sleep(0.3)  # Rate limiting

    return results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def print_stats(conn: sqlite3.Connection):
    """Print scraper statistics."""
    total_tenders = conn.execute("SELECT COUNT(*) FROM scraped_tenders").fetchone()[0]
    total_runs = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]

    # Platform distribution
    by_platform = dict(conn.execute(
        "SELECT platform, COUNT(*) FROM scraped_tenders GROUP BY platform"
    ).fetchall())

    # Source distribution
    by_source = dict(conn.execute(
        "SELECT source, COUNT(*) FROM scraped_tenders GROUP BY source"
    ).fetchall())

    # Contract index platform URL counts
    platform_urls = extract_platform_urls_from_index(limit=0)
    by_url_platform = defaultdict(int)
    for u in platform_urls:
        by_url_platform[u["platform"]] += 1

    print(f"\n{'='*70}")
    print(f"  Tender Platform Scraper — Statistics")
    print(f"{'='*70}")
    print(f"\n  Scraped Tenders:")
    print(f"    Total: {total_tenders}")
    for p, c in sorted(by_platform.items(), key=lambda x: -x[1]):
        print(f"      {p:10s}: {c}")
    print(f"\n  By Source:")
    for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"      {s:25s}: {c}")
    print(f"\n  Contract Index Platform URLs:")
    total_urls = sum(by_url_platform.values())
    print(f"    Total: {total_urls}")
    for p, c in sorted(by_url_platform.items(), key=lambda x: -x[1]):
        print(f"      {p:10s}: {c}")
    print(f"\n  Scrape Runs: {total_runs}")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Tender Platform Scraper — Portuguese e-procurement pre-contract data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Search AcinGov public zone
    python tender_platform_scraper.py search --platform acin --query "município"

    # Search all platforms
    python tender_platform_scraper.py search --query "contrato"

    # Analyze pre-contract data for a specific entity
    python tender_platform_scraper.py analyze --nif 500014872 --limit 20

    # Gap analysis: what's on platforms but not on BASE.gov.pt
    python tender_platform_scraper.py gap --nif 500014872

    # Show statistics
    python tender_platform_scraper.py stats

    # Check specific platform URL
    python tender_platform_scraper.py check-url "https://www.acingov.pt/..."
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # Search command
    search = sub.add_parser("search", help="Search platform public zones")
    search.add_argument("--platform", choices=["acin", "vortal", "anogov", "all"], default="all")
    search.add_argument("--query", default="", help="Search query")
    search.add_argument("--limit", type=int, default=50)

    # Analyze command
    analyze = sub.add_parser("analyze", help="Analyze pre-contract data availability")
    analyze.add_argument("--nif", default="", help="Filter by entity NIF")
    analyze.add_argument("--limit", type=int, default=50)
    analyze.add_argument("-v", "--verbose", action="store_true")

    # Gap command
    gap = sub.add_parser("gap", help="Analyze gap between platforms and BASE.gov.pt")
    gap.add_argument("--nif", default="", help="Filter by entity NIF")
    gap.add_argument("--limit", type=int, default=30)
    gap.add_argument("-v", "--verbose", action="store_true")

    # Stats command
    sub.add_parser("stats", help="Show scraper statistics")

    # Check URL command
    check = sub.add_parser("check-url", help="Check a specific platform URL")
    check.add_argument("url", help="Platform URL to check")
    check.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "stats":
        conn = init_db()
        print_stats(conn)
        conn.close()
        return

    if args.command == "search":
        conn = init_db()
        all_tenders = []

        platforms = ["acin", "vortal", "anogov"] if args.platform == "all" else [args.platform]

        for platform in platforms:
            print(f"\n  Searching {PLATFORMS[platform]['name']}...")
            if platform == "acin":
                tenders = scrape_acin_public(args.query, args.limit)
            elif platform == "vortal":
                tenders = scrape_vortal_public(args.query, args.limit)
            else:
                print(f"    ⚠️  {PLATFORMS[platform]['name']} requires authentication for search")
                tenders = []

            all_tenders.extend(tenders)
            print(f"    Found {len(tenders)} items")

            # Store in database
            for t in tenders:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO scraped_tenders "
                        "(id, platform, title, description, url, source, data_json, scraped_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            t["id"],
                            t.get("platform", platform),
                            t.get("title", ""),
                            t.get("description", ""),
                            t.get("url", ""),
                            t.get("source", ""),
                            t.get("data_json", ""),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                except sqlite3.IntegrityError:
                    pass

            time.sleep(1)

        # Log the run
        conn.execute(
            "INSERT INTO scrape_runs (platform, query, results_count, new_count, run_at) VALUES (?, ?, ?, ?, ?)",
            (args.platform, args.query, len(all_tenders), len(all_tenders), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        # Print results
        if all_tenders:
            print(f"\n{'='*70}")
            print(f"  Results ({len(all_tenders)} items)")
            print(f"{'='*70}")
            for t in all_tenders[:20]:
                print(f"  [{t.get('platform', '?')}] {t.get('title', 'No title')[:60]}")
                if t.get("description"):
                    print(f"    {t['description'][:80]}")
            print(f"{'='*70}")

        conn.close()
        return

    if args.command == "analyze":
        results = analyze_gap(args.nif, args.limit, args.verbose)
        if results:
            print(f"\n{'='*70}")
            print(f"  Pre-Contract Data Analysis ({len(results)} contracts)")
            print(f"{'='*70}")
            for r in results:
                meta = r.get("scraped_metadata", {})
                print(f"\n  Contract {r['contract_id']} ({r['platform']})")
                print(f"    Entity: {r['entity_name'][:50]}")
                print(f"    Value: €{r.get('valor', 0):,.2f}")
                print(f"    Status: {r['scraped_status']}")
                if meta.get("page_title"):
                    print(f"    Page Title: {meta['page_title'][:60]}")
                if meta.get("procedure_number"):
                    print(f"    Procedure #: {meta['procedure_number']}")
                if meta.get("pdf_count"):
                    print(f"    PDFs Available: {meta['pdf_count']}")
                if meta.get("tender_status"):
                    print(f"    Tender Status: {meta['tender_status']}")
            print(f"\n{'='*70}")
        return

    if args.command == "gap":
        print(f"\n  Analyzing gap between platforms and BASE.gov.pt...")
        results = analyze_gap(args.nif, args.limit, args.verbose)

        # Categorize by data availability
        has_metadata = [r for r in results if r.get("scraped_metadata")]
        no_metadata = [r for r in results if not r.get("scraped_metadata")]

        print(f"\n{'='*70}")
        print(f"  Gap Analysis Results")
        print(f"{'='*70}")
        print(f"  Total contracts with platform URLs: {len(results)}")
        print(f"  With extractable metadata: {len(has_metadata)}")
        print(f"  Without metadata (auth required): {len(no_metadata)}")

        if has_metadata:
            print(f"\n  Contracts with available pre-contract data:")
            for r in has_metadata[:10]:
                meta = r.get("scraped_metadata", {})
                print(f"    #{r['contract_id']} ({r['platform']}) — {r['entity_name'][:30]}")
                if meta.get("pdf_count"):
                    print(f"      📄 {meta['pdf_count']} documents available")
                if meta.get("procedure_number"):
                    print(f"      📋 Procedure: {meta['procedure_number']}")

        print(f"\n  💡 Insight: {len(no_metadata)} contracts require authentication")
        print(f"     to access full pre-contract data (Convites, Propostas, Habilitação)")
        print(f"{'='*70}\n")
        return

    if args.command == "check-url":
        print(f"\n  Checking URL: {args.url[:80]}")
        result = scrape_contract_platform_url(args.url, verbose=args.verbose)
        print(f"\n  Result:")
        print(f"    Platform: {result['platform']}")
        print(f"    Status: {result['status']}")
        if result.get("metadata"):
            print(f"    Metadata:")
            for k, v in result["metadata"].items():
                if k != "pdf_links":
                    print(f"      {k}: {v}")
                else:
                    print(f"      {k}: {len(v)} links")
        return


if __name__ == "__main__":
    main()
