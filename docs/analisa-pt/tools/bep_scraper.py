#!/usr/bin/env python3
"""
BEP (Bolsa de Emprego Público) Scraper & MCP Server

Scrapes Portuguese public sector job listings from https://www.bep.gov.pt/
and exposes them via CLI or MCP (Model Context Protocol) interface.

Usage:
    # CLI mode - fetch a single listing
    python bep_scraper.py fetch 148309

    # CLI mode - fetch multiple listings
    python bep_scraper.py fetch 148300 148301 148302

    # CLI mode - fetch a range of listings
    python bep_scraper.py range 148300 148310

    # MCP server mode
    python bep_scraper.py mcp

Environment:
    BEP_BASE_URL: Override base URL (default: https://www.bep.gov.pt)
    BEP_DELAY: Delay between requests in seconds (default: 0.5)
"""

import sys
import json
import time
import re
import os
import argparse
import logging
from typing import Optional
from dataclasses import dataclass, asdict

import subprocess
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BEP_BASE_URL = "https://www.bep.gov.pt"
DETAIL_PATH = "/pages/oferta/Oferta_Detalhes.aspx"
DEFAULT_DELAY = 0.5  # seconds between requests

logger = logging.getLogger("bep_scraper")

# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class JobListing:
    """Structured representation of a BEP job listing."""
    cod_oferta: str = ""
    titulo: str = ""  # synthetic: built from categoria + organismo
    estado: str = ""
    entidade: str = ""
    organismo: str = ""
    tipo_oferta: str = ""
    carreira: str = ""
    categoria: str = ""
    vinculo: str = ""
    duracao: str = ""
    regime: str = ""
    remuneracao: str = ""
    sup_mensal: str = ""
    total_postos: str = ""
    habilitacoes: str = ""
    hab_desc: str = ""
    funcoes: str = ""
    outros_requisitos: str = ""
    relacao_juridica: str = ""
    req_nacional: str = ""
    local_trabalho: str = ""
    contacto: str = ""
    data_publicacao: str = ""
    data_limite: str = ""
    jornal: str = ""
    texto_pub: str = ""
    observacoes: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class BEPScraper:
    """Scrapes job listings from the BEP portal.

    Uses curl as HTTP backend because BEP blocks Python requests/httpx
    via TLS fingerprinting (connection reset by peer).
    """

    def __init__(self, base_url: str = BEP_BASE_URL, delay: float = DEFAULT_DELAY):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self._cookie_file = "/tmp/bep_session_cookies.txt"
        self._session_initialized = False

    def _init_session(self):
        """Initialize a session by fetching the homepage to get cookies."""
        if not self._session_initialized:
            try:
                subprocess.run(
                    ["curl", "-s", "-c", self._cookie_file, "-o", "/dev/null",
                     "--max-time", "10", self.base_url + "/"],
                    capture_output=True, timeout=15,
                )
                self._session_initialized = True
                logger.info("Session initialized with cookies")
            except Exception as e:
                logger.warning(f"Session init failed: {e}")

    def _curl_get(self, url: str, retries: int = 2) -> tuple[int, str]:
        """Fetch a URL using curl (bypasses TLS fingerprinting).

        Uses session cookies and retries on rate limiting ("Permissão Negada").
        """
        self._init_session()
        for attempt in range(retries + 1):
            try:
                cmd = [
                    "curl", "-s", "-L",
                    "--max-time", "15",
                    "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "-H", "Accept-Language: pt-PT,pt;q=0.9,en;q=0.8",
                ]
                # Use session cookies if available
                if os.path.exists(self._cookie_file):
                    cmd.extend(["-b", self._cookie_file])
                cmd.append(url)
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                html = result.stdout
                # Check for rate limiting
                if "Permissão Negada" in html or "permiss\u00e3o negada" in html.lower():
                    if attempt < retries:
                        wait = 2 ** (attempt + 1)
                        logger.warning(f"Rate limited, waiting {wait}s before retry...")
                        time.sleep(wait)
                        continue
                return (200 if result.returncode == 0 else 0, html)
            except Exception as e:
                logger.error(f"curl failed for {url}: {e}")
                if attempt < retries:
                    time.sleep(2)
                    continue
                return (0, "")
        return (0, "")

    def fetch_listing(self, cod_oferta: int | str) -> Optional[JobListing]:
        """Fetch and parse a single job listing by its CodOferta ID."""
        url = f"{self.base_url}{DETAIL_PATH}?CodOferta={cod_oferta}"
        logger.info(f"Fetching listing {cod_oferta}...")

        status, html = self._curl_get(url)
        if not html or status == 0:
            logger.error(f"Failed to fetch {cod_oferta}: status={status}")
            return None

        # Check if we got redirected to login or session expiry
        if "loginAux" in html or "sessao expirou" in html.lower():
            logger.warning(f"Session expired or login required for {cod_oferta}")
            return None

        return self._parse_detail_page(html, cod_oferta, url)

    def fetch_range(self, start: int, end: int, delay: float | None = None) -> list[JobListing]:
        """Fetch a range of job listings (exclusive end)."""
        delay = delay if delay is not None else self.delay
        listings = []
        for cod in range(start, end):
            listing = self.fetch_listing(cod)
            if listing:
                listings.append(listing)
            if delay > 0:
                time.sleep(delay)
        return listings

    def list_by_date(self, since: str | None = None, until: str | None = None,
                     entity: str | None = None, max_results: int = 100,
                     scan_range: int = 500) -> list[JobListing]:
        """Fetch all job listings published within a date interval, optionally filtered by entity.

        Args:
            since: Start date in YYYY-MM-DD format (inclusive). None = no lower bound.
            until: End date in YYYY-MM-DD format (inclusive). None = no upper bound.
            entity: Filter by entity/organismo name (case-insensitive substring match).
            max_results: Maximum number of listings to return.
            scan_range: How many IDs backwards to scan from the latest.
        """
        from datetime import datetime

        logger.info(f"Listing BEP jobs since={since} until={until} entity={entity} (scan {scan_range} IDs)...")

        latest_id = self._find_latest_id()
        if not latest_id:
            logger.error("Could not determine latest listing ID")
            return []

        since_dt = datetime.strptime(since, "%Y-%m-%d") if since else None
        until_dt = datetime.strptime(until, "%Y-%m-%d") if until else None
        entity_lower = entity.lower() if entity else None
        start = max(1, latest_id - scan_range)

        matches = []
        consecutive_empty = 0

        for cod in range(latest_id, start - 1, -1):
            listing = self.fetch_listing(cod)
            if not listing:
                consecutive_empty += 1
                if consecutive_empty > 20:
                    logger.info(f"Too many consecutive empty IDs, stopping at {cod}")
                    break
                continue

            consecutive_empty = 0

            # Filter by publication date
            if listing.data_publicacao:
                try:
                    pub_date = datetime.strptime(listing.data_publicacao, "%Y-%m-%d")
                    if since_dt and pub_date < since_dt:
                        logger.info(f"  Reached listings before {since}, stopping")
                        break
                    if until_dt and pub_date > until_dt:
                        continue  # Skip, but don't stop scanning
                except ValueError:
                    pass  # Date parsing failed, include listing

            # Filter by entity (substring match against entidade + organismo)
            if entity_lower:
                searchable = f"{listing.entidade} {listing.organismo}".lower()
                if entity_lower not in searchable:
                    continue

            matches.append(listing)
            logger.info(f"  [{listing.data_publicacao}] {cod} - {listing.entidade} / {listing.organismo}")

            if len(matches) >= max_results:
                break

            time.sleep(self.delay)

        logger.info(f"Found {len(matches)} listings in date range")
        return matches

    def search(self, query: str, max_results: int = 20, scan_range: int = 200) -> list[JobListing]:
        """Search BEP for job listings matching a query.

        Strategy: Scan a range of recent listing IDs, fetch each one, and
        filter locally by keyword match against entity, title, location, etc.
        This is more reliable than trying to replicate ASP.NET postback state.
        """
        logger.info(f"Searching BEP for '{query}' (scanning last {scan_range} IDs)...")

        # Find the most recent valid ID by scanning backwards
        latest_id = self._find_latest_id()
        if not latest_id:
            logger.error("Could not determine latest listing ID")
            return []

        start = max(1, latest_id - scan_range)
        logger.info(f"Scanning IDs {start}-{latest_id}")

        query_lower = query.lower()
        matches = []

        for cod in range(latest_id, start - 1, -1):
            listing = self.fetch_listing(cod)
            if not listing:
                continue

            # Check if query matches any field
            searchable = " ".join([
                listing.entidade or "",
                listing.organismo or "",
                listing.categoria or "",
                listing.funcoes or "",
                listing.habilitacoes or "",
                listing.hab_desc or "",
                listing.local_trabalho or "",
                listing.texto_pub or "",
            ]).lower()

            if query_lower in searchable:
                matches.append(listing)
                logger.info(f"  Match: {cod} - {listing.entidade} / {listing.titulo}")
                if len(matches) >= max_results:
                    break

            time.sleep(self.delay)

        logger.info(f"Found {len(matches)} matches for '{query}'")
        return matches

    def _find_latest_id(self) -> Optional[int]:
        """Find the latest valid listing ID by probing recent IDs.

        Uses exponential probe: starts at 150000 and probes forward in large
        jumps until hitting an invalid ID, then scans backward to find the boundary.
        This avoids hardcoding a specific probe_start that goes stale.
        """
        # Phase 1: Find a valid ID by probing forward from a high starting point
        probe_start = 150000
        step = 1000
        valid_cod = None

        for _ in range(20):  # Max 20 jumps = up to 200000
            status, html = self._curl_get(f"{self.base_url}{DETAIL_PATH}?CodOferta={probe_start}")
            if html and ("lblNOCodigo" in html or "lblCodigo" in html):
                valid_cod = probe_start
                probe_start += step
            else:
                if valid_cod is not None:
                    break  # We went past the boundary
                probe_start += step
            time.sleep(0.2)

        if valid_cod is None:
            # Fallback: try known reasonable range
            for fallback in [150000, 149000, 148000, 147000]:
                status, html = self._curl_get(f"{self.base_url}{DETAIL_PATH}?CodOferta={fallback}")
                if html and ("lblNOCodigo" in html or "lblCodigo" in html):
                    valid_cod = fallback
                    break
                time.sleep(0.2)

        if valid_cod is None:
            logger.error("Could not find any valid BEP listing")
            return None

        # Phase 2: Binary search between valid_cod and probe_start to find exact boundary
        lo, hi = valid_cod, probe_start
        while lo < hi:
            mid = (lo + hi + 1) // 2
            status, html = self._curl_get(f"{self.base_url}{DETAIL_PATH}?CodOferta={mid}")
            if html and ("lblNOCodigo" in html or "lblCodigo" in html):
                lo = mid
            else:
                hi = mid - 1
            time.sleep(0.2)

        logger.info(f"Latest valid BEP listing ID: {lo}")
        return lo



    def _parse_detail_page(self, html: str, cod_oferta: str | int, url: str) -> Optional[JobListing]:
        """Parse the HTML of a BEP detail page into a JobListing."""
        soup = BeautifulSoup(html, "lxml")
        listing = JobListing(cod_oferta=str(cod_oferta), url=url)

        # ASP.NET field mappings: (field_name, [span_id_alternatives])
        # Active listings use lblNO* prefix, expired listings use lbl* prefix
        field_map = [
            ("cod_oferta", ["lblNOCodigo", "lblCodigo"]),
            ("estado", ["lblNOEstado", "lblEstado"]),
            ("entidade", ["lblNONivelOrganico", "lblNivelOrganico"]),
            ("organismo", ["lblNOOrganismo", "lblOrganismo"]),
            ("tipo_oferta", ["lblNOTipoOferta", "lblTipoOferta"]),
            ("carreira", ["lblNOCarreira", "lblCarreira"]),
            ("categoria", ["lblNOCategoria", "lblCategoria"]),
            ("vinculo", ["lblNOVinculo", "lblVinculo"]),
            ("duracao", ["lblNODuracao", "lblDuracao"]),
            ("regime", ["lblNORegime", "lblRegime"]),
            ("remuneracao", ["lblNORemuneracao", "lblRemuneracao"]),
            ("sup_mensal", ["lblNOSupMensal", "lblSupMensal"]),
            ("total_postos", ["lblNOTotalPostos", "lblTotalPostos"]),
            ("habilitacoes", ["lblNOHabLit", "lblHabLit"]),
            ("hab_desc", ["lblDesHabLit"]),
            ("funcoes", ["lblNOCarPosto", "lblCarPosto"]),
            ("outros_requisitos", ["lblNOOutrosReqs", "lblOutrosReqs"]),
            ("relacao_juridica", ["lblNORelacaoJuridica", "lblRelacaoJuridica"]),
            ("req_nacional", ["lblNOReqNac", "lblReqNac"]),
            ("local_trabalho", ["lblNOEnvioCand", "lblEnvioCand"]),
            ("contacto", ["lblNOContacto", "lblContacto"]),
            ("data_publicacao", ["lblNODataPub", "lblDataPub"]),
            ("data_limite", ["lblNODataLim", "lblDataLim"]),
            ("jornal", ["lblNOJornal", "lblJornal"]),
            ("texto_pub", ["lblNOTextoPub", "lblTextoPub"]),
            ("observacoes", ["lblNOObs", "lblObs"]),
        ]

        for field_name, span_ids in field_map:
            for span_id in span_ids:
                value = self._extract_field(soup, span_id)
                if value:
                    setattr(listing, field_name, value)
                    break

        # Build a synthetic title from categoria + entidade
        # (BEP has no dedicated title field)
        if listing.categoria:
            listing.titulo = f"{listing.categoria} - {listing.organismo}" if listing.organismo else listing.categoria
        elif listing.organismo:
            listing.titulo = listing.organismo

        # Only return if we got some meaningful data
        if listing.entidade or listing.titulo:
            return listing

        logger.warning(f"No data found for {cod_oferta}")
        return None

    def _extract_field(self, soup: BeautifulSoup, span_id: str) -> str:
        """Extract text from an ASP.NET span element by its ID."""
        # Try exact ID match
        span = soup.find("span", id=span_id)
        if span:
            return self._clean_text(span.get_text())

        # Try partial ID match (ASP.NET sometimes prefixes IDs with container path)
        span = soup.find("span", id=lambda x: x and span_id in x)
        if span:
            return self._clean_text(span.get_text())

        return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted text: normalize whitespace, strip."""
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text).strip()
        # Remove non-breaking spaces
        text = text.replace("\xa0", " ")
        return text


# ---------------------------------------------------------------------------
# MCP Server (JSON-RPC 2.0 over stdio)
# ---------------------------------------------------------------------------

def run_mcp_server():
    """Run a simple MCP server over stdio (JSON-RPC 2.0)."""
    scraper = BEPScraper()

    tools = [
        {
            "name": "fetch_bep_listing",
            "description": "Fetch a job listing from BEP (Bolsa de Emprego Publico) by its ID code. Returns structured job data including entity, title, salary, requirements, and deadlines.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cod_oferta": {
                        "type": "integer",
                        "description": "The BEP offer code (CodOferta), e.g. 148309"
                    }
                },
                "required": ["cod_oferta"]
            }
        },
        {
            "name": "fetch_bep_range",
            "description": "Fetch multiple job listings from BEP by ID range. Returns an array of job listings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start": {
                        "type": "integer",
                        "description": "Start ID (inclusive)"
                    },
                    "end": {
                        "type": "integer",
                        "description": "End ID (exclusive)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max listings to return (default 50)",
                        "default": 50
                    }
                },
                "required": ["start", "end"]
            }
        },
        {
            "name": "search_bep_listings",
            "description": "Search BEP for public sector job listings by keyword. Search by entity name, job title, city, or any keyword. Returns matching listings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g. 'informatica', 'medico', 'Lisboa', 'engenheiro')"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (default 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "list_bep_by_date",
            "description": "List all BEP job offers published within a date interval, optionally filtered by entity. Useful for getting all recent public sector job postings from a specific ministry or organization.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "description": "Start date YYYY-MM-DD (inclusive), e.g. '2026-05-01'"
                    },
                    "until": {
                        "type": "string",
                        "description": "End date YYYY-MM-DD (inclusive), e.g. '2026-05-31'"
                    },
                    "entity": {
                        "type": "string",
                        "description": "Filter by entity/organismo name (case-insensitive substring match), e.g. 'Ministerio da Saude' or 'LNEC'"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max listings to return (default 100)",
                        "default": 100
                    },
                    "scan_range": {
                        "type": "integer",
                        "description": "How many IDs to scan backwards (default 500)",
                        "default": 500
                    }
                }
            }
        }
    ]

    logger.info("BEP MCP server started on stdio")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _send_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
            continue

        method = request.get("method", "")
        req_id = request.get("id")

        if method == "initialize":
            _send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "bep-scraper", "version": "1.0.0"}
                }
            })

        elif method == "tools/list":
            _send_response({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})

        elif method == "tools/call":
            tool_name = request["params"]["name"]
            args = request["params"].get("arguments", {})
            result = _handle_tool_call(tool_name, args, scraper)
            _send_response({"jsonrpc": "2.0", "id": req_id, "result": result})

        elif method == "ping":
            _send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})

        else:
            _send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            })


def _handle_tool_call(tool_name: str, args: dict, scraper: BEPScraper) -> dict:
    """Handle an MCP tool call and return the result."""
    try:
        if tool_name == "fetch_bep_listing":
            listing = scraper.fetch_listing(args["cod_oferta"])
            if listing:
                return {
                    "content": [{"type": "text", "text": json.dumps(listing.to_dict(), ensure_ascii=False, indent=2)}],
                    "structuredContent": listing.to_dict()
                }
            return {"content": [{"type": "text", "text": f"No listing found for CodOferta={args['cod_oferta']}"}], "isError": True}

        elif tool_name == "fetch_bep_range":
            start = args["start"]
            end = min(args["end"], start + args.get("limit", 50))
            listings = scraper.fetch_range(start, end)
            return {
                "content": [{"type": "text", "text": json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=2)}],
                "structuredContent": {
                    "title": f"BEP Listings {start}-{end}",
                    "summary": f"{len(listings)} listings found",
                    "rows": [l.to_dict() for l in listings]
                }
            }

        elif tool_name == "search_bep_listings":
            query = args["query"]
            max_results = args.get("max_results", 10)
            listings = scraper.search(query, max_results=max_results)
            return {
                "content": [{"type": "text", "text": json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=2)}],
                "structuredContent": {
                    "title": f"BEP Search: {query}",
                    "summary": f"{len(listings)} results found",
                    "rows": [l.to_dict() for l in listings]
                }
            }

        elif tool_name == "list_bep_by_date":
            listings = scraper.list_by_date(
                since=args.get("since"), until=args.get("until"),
                entity=args.get("entity"),
                max_results=args.get("max_results", 100),
                scan_range=args.get("scan_range", 500)
            )
            return {
                "content": [{"type": "text", "text": json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=2)}],
                "structuredContent": {
                    "title": f"BEP Listings by Date",
                    "summary": f"{len(listings)} listings found",
                    "rows": [l.to_dict() for l in listings]
                }
            }

        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}


def _send_response(response: dict):
    """Send a JSON-RPC response to stdout."""
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# CLI Command Handlers (DB-backed)
# ---------------------------------------------------------------------------

def _cmd_collect(scraper: BEPScraper, args):
    """Scan BEP and persist listings + entities to SQLite index."""
    from datetime import datetime as dt
    from bep_db import init_db, upsert_entity, upsert_listing, refresh_entity_count

    db_path = args.db
    conn = init_db(db_path)
    db_file = conn.execute("SELECT file FROM pragma_database_list() WHERE name='main'").fetchone()
    print(f"Database: {db_file[0] if db_file else '(in-memory)'}")

    since_dt = dt.strptime(args.since, "%Y-%m-%d") if args.since else None
    until_dt = dt.strptime(args.until, "%Y-%m-%d") if args.until else None
    entity_lower = args.entity.lower() if args.entity else None

    latest_id = scraper._find_latest_id()
    if not latest_id:
        print("ERROR: Could not determine latest listing ID", file=sys.stderr)
        return

    scan_start = max(1, latest_id - args.scan)
    print(f"Scanning IDs {scan_start}-{latest_id} (max {args.max_results} results)...")

    new_listings = 0
    updated_listings = 0
    new_entities = 0
    matches = 0
    consecutive_empty = 0

    for cod in range(latest_id, scan_start - 1, -1):
        listing = scraper.fetch_listing(cod)
        if not listing:
            consecutive_empty += 1
            if consecutive_empty > 25:
                print(f"  Stopping at {cod}: too many consecutive empty IDs")
                break
            continue

        consecutive_empty = 0

        # Date filter
        if listing.data_publicacao:
            try:
                pub_date = dt.strptime(listing.data_publicacao, "%Y-%m-%d")
                if since_dt and pub_date < since_dt:
                    print(f"  Reached listings before {args.since}, stopping")
                    break
                if until_dt and pub_date > until_dt:
                    continue
            except ValueError:
                pass

        # Entity filter
        if entity_lower:
            searchable = f"{listing.entidade} {listing.organismo}".lower()
            if entity_lower not in searchable:
                continue

        # Upsert entity + listing
        eid = upsert_entity(conn, listing.entidade, listing.organismo)
        is_new = upsert_listing(conn, listing.to_dict(), eid)
        refresh_entity_count(conn, eid)

        if is_new:
            new_listings += 1
        else:
            updated_listings += 1
        matches += 1

        # Track new entities (listing_count was 0 before first insert)
        entity_row = conn.execute(
            "SELECT listing_count FROM bep_entities WHERE id = ?", (eid,)
        ).fetchone()
        if entity_row and entity_row[0] == 1:
            new_entities += 1

        print(f"  [{listing.data_publicacao}] {listing.entidade} / {listing.organismo} ({listing.cod_oferta})")

        if matches >= args.max_results:
            break

        time.sleep(scraper.delay)

    conn.commit()
    conn.close()

    print(f"\n=== Collection complete ===")
    print(f"Listings: {new_listings} new, {updated_listings} updated")
    print(f"Entities: {new_entities} new")
    print(f"Total: {matches} listings collected")


def _cmd_entities(args):
    """Show indexed entities from the local DB."""
    from bep_db import init_db, get_entity_stats, search_entities

    conn = init_db(args.db)
   
    if args.query:
        entities = search_entities(conn, args.query)
        print(f"Entities matching '{args.query}':")
    else:
        entities = get_entity_stats(conn)
        print(f"All indexed entities ({len(entities)} total):")

    for e in entities:
        print(f"  {e['id']}  {e['display_name']:60s}  {e['listing_count']:3d} listings  [{e['first_seen'][:10] if e['first_seen'] else '?'} – {e['last_seen'][:10] if e['last_seen'] else '?'}]")

    conn.close()


def _cmd_listings(args):
    """Show listings for a specific entity from the DB."""
    from bep_db import init_db, get_listings_for_entity

    conn = init_db(args.db)
    listings = get_listings_for_entity(conn, args.entity_id)

    if not listings:
        print(f"No listings found for entity {args.entity_id}")
        conn.close()
        return

    print(f"Listings for entity {args.entity_id} ({len(listings)} total):")
    for l in listings:
        print(f"  {l['cod_oferta']}  [{l['data_publicacao']}] {l['titulo'] or '(no title)':60s}  {l['remuneracao'] or '-':15s}  {l['total_postos'] or '-'} posts  {l['url']}")

    conn.close()


def _cmd_set_nif(args):
    """Manually set NIF for an entity."""
    from bep_db import init_db, set_nif

    nif = args.nif.strip()
    if len(nif) != 9 or not nif.isdigit():
        print(f"ERROR: NIF must be exactly 9 digits, got '{nif}'")
        return

    conn = init_db(args.db)
    set_nif(conn, args.entity_id, nif)
    conn.commit()
    conn.close()
    print(f"NIF {nif} set for entity {args.entity_id}")


def _cmd_nifs(args):
    """Show entities with/without NIFs."""
    from bep_db import init_db, get_entity_stats, get_entities_without_nif

    conn = init_db(args.db)
    if args.missing:
        entities = get_entities_without_nif(conn)
        print(f"Entities WITHOUT NIF ({len(entities)} total):")
    else:
        entities = get_entity_stats(conn)
        print(f"All entities with NIF status ({len(entities)} total):")

    for e in entities:
        nif_display = e.get('nif') or '(none)'
        print(f"  {e['id']}  NIF={nif_display:10s}  {e['display_name']:55s}  {e['listing_count']:3d} listings")

    conn.close()


def _cmd_nif(args):
    """Look up an entity by its NIF number."""
    from bep_db import init_db, search_by_nif, get_listings_for_entity

    nif = args.nif.strip()
    if not nif.isdigit():
        print(f"ERROR: NIF must be digits only, got '{nif}'")
        return

    conn = init_db(args.db)
    entities = search_by_nif(conn, nif)

    if not entities:
        print(f"No entity found with NIF {nif}")
        conn.close()
        return

    for e in entities:
        print(f"Entity: {e['display_name']}")
        print(f"  ID:           {e['id']}")
        print(f"  NIF:          {e['nif']}")
        print(f"  Entidade:     {e['entidade']}")
        print(f"  Organismo:    {e['organismo']}")
        print(f"  Listings:     {e['listing_count']}")
        if e['first_seen']:
            print(f"  First seen:   {e['first_seen'][:10]}")
        if e['last_seen']:
            print(f"  Last seen:    {e['last_seen'][:10]}")

        # Show listings for this entity
        listings = get_listings_for_entity(conn, e['id'])
        if listings:
            print(f"  \n  Recent listings:")
            for l in listings:
                print(f"    {l['cod_oferta']}  [{l['data_publicacao']}] {l['titulo'] or '(no title)':50s}  {l['remuneracao'] or '-':15s}")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="BEP (Bolsa de Emprego Publico) Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s fetch 148309              # Fetch a single listing
  %(prog)s fetch 148300 148301       # Fetch multiple listings
  %(prog)s range 148300 148310       # Fetch a range of listings
  %(prog)s list --since 2026-05-01 --until 2026-05-31         # All May 2026 offers
  %(prog)s list --since 2026-05-01 --entity "Saude" -n 20    # May offers from Saude
  %(prog)s search informatica -n 5   # Search by keyword
  %(prog)s mcp                       # Start MCP server (stdio)
        """
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between requests (seconds)")
    parser.add_argument("--base-url", default=BEP_BASE_URL, help="BEP base URL")

    sub = parser.add_subparsers(dest="command", help="Command to run")

    # fetch command
    p_fetch = sub.add_parser("fetch", help="Fetch job listings by ID")
    p_fetch.add_argument("ids", type=int, nargs="+", help="Offer IDs to fetch")

    # range command
    p_range = sub.add_parser("range", help="Fetch a range of listings")
    p_range.add_argument("start", type=int, help="Start ID (inclusive)")
    p_range.add_argument("end", type=int, help="End ID (exclusive)")
    p_range.add_argument("--limit", type=int, default=50, help="Max listings")

    # list command
    p_list = sub.add_parser("list", help="List job offers by date interval")
    p_list.add_argument("--since", help="Start date YYYY-MM-DD (inclusive)")
    p_list.add_argument("--until", help="End date YYYY-MM-DD (inclusive)")
    p_list.add_argument("--entity", help="Filter by entity/organismo name (substring match)")
    p_list.add_argument("-n", "--max-results", type=int, default=100, help="Max results")
    p_list.add_argument("--scan", type=int, default=500, help="IDs to scan backwards")

    # search command
    p_search = sub.add_parser("search", help="Search job listings by keyword")
    p_search.add_argument("query", help="Search query (e.g. 'informatica', 'medico')")
    p_search.add_argument("-n", "--max-results", type=int, default=10, help="Max results")

    # collect command — scan BEP and persist to local SQLite index
    p_collect = sub.add_parser("collect", help="Scan BEP and persist listings + entities to DB")
    p_collect.add_argument("--since", help="Start date YYYY-MM-DD (inclusive)")
    p_collect.add_argument("--until", help="End date YYYY-MM-DD (inclusive)")
    p_collect.add_argument("--entity", help="Filter by entity/organismo name (substring match)")
    p_collect.add_argument("-n", "--max-results", type=int, default=500, help="Max listings to collect")
    p_collect.add_argument("--scan", type=int, default=1000, help="IDs to scan backwards")
    p_collect.add_argument("--db", default=None, help="DB path (default: bep_db.py's bep_index.db)")

    # entities command — show indexed entities from DB
    p_entities = sub.add_parser("entities", help="List indexed entities from local DB")
    p_entities.add_argument("query", nargs="?", help="Substring search on entity name")
    p_entities.add_argument("--db", default=None, help="DB path")

    # listings command — show listings for an entity from DB
    p_listings_cmd = sub.add_parser("listings", help="Show DB listings for an entity ID")
    p_listings_cmd.add_argument("entity_id", help="Entity ID (from 'entities' command)")
    p_listings_cmd.add_argument("--db", default=None, help="DB path")

    # set-nif command — manually set NIF for an entity
    p_setnif = sub.add_parser("set-nif", help="Manually set NIF for an entity")
    p_setnif.add_argument("entity_id", help="Entity ID (from 'entities' command)")
    p_setnif.add_argument("nif", help="The 9-digit NIF to assign")
    p_setnif.add_argument("--db", default=None, help="DB path")

    # nifs command — show entities with/without NIFs
    p_nifs = sub.add_parser("nifs", help="Show entities with their NIFs (or entities missing NIFs)")
    p_nifs.add_argument("--missing", action="store_true", help="Show only entities without a NIF")
    p_nifs.add_argument("--db", default=None, help="DB path")

    # nif command — search entity by NIF number
    p_nif = sub.add_parser("nif", help="Look up an entity by its NIF number")
    p_nif.add_argument("nif", help="9-digit NIF to search for")
    p_nif.add_argument("--db", default=None, help="DB path")

    # mcp command
    sub.add_parser("mcp", help="Start MCP server (stdio)")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    scraper = BEPScraper(base_url=args.base_url, delay=args.delay)

    if args.command == "fetch":
        results = []
        for i, cod in enumerate(args.ids):
            listing = scraper.fetch_listing(cod)
            if listing:
                results.append(listing.to_dict())
                print(listing.to_json())
            else:
                print(json.dumps({"error": f"Not found: {cod}"}))
            if i < len(args.ids) - 1:
                time.sleep(scraper.delay)
        # Summary to stderr
        print(f"\n--- {len(results)}/{len(args.ids)} listings found ---", file=sys.stderr)

    elif args.command == "range":
        limit = min(args.end - args.start, args.limit)
        end = args.start + limit
        listings = scraper.fetch_range(args.start, end)
        print(json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=2))
        print(f"\n--- {len(listings)}/{limit} listings found ---", file=sys.stderr)

    elif args.command == "list":
        listings = scraper.list_by_date(since=args.since, until=args.until,
                                       entity=args.entity, max_results=args.max_results,
                                       scan_range=args.scan)
        for listing in listings:
            print(listing.to_json())
        print(f"\n--- {len(listings)} listings found ---", file=sys.stderr)

    elif args.command == "search":
        listings = scraper.search(args.query, max_results=args.max_results)
        for listing in listings:
            print(listing.to_json())
        print(f"\n--- {len(listings)} results for '{args.query}' ---", file=sys.stderr)

    elif args.command == "collect":
        _cmd_collect(scraper, args)

    elif args.command == "entities":
        _cmd_entities(args)

    elif args.command == "listings":
        _cmd_listings(args)

    elif args.command == "set-nif":
        _cmd_set_nif(args)

    elif args.command == "nifs":
        _cmd_nifs(args)

    elif args.command == "nif":
        _cmd_nif(args)

    elif args.command == "mcp":
        run_mcp_server()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
