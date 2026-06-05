#!/usr/bin/env python3
"""Law Project Tracker — Portuguese parliamentary initiatives from api.votoaberto.org.

Fetches law projects (projetos de lei), lifecycle events, votes, deputies,
and parties from the open REST API at api.votoaberto.org.  Stores everything
in a local SQLite index for fast querying and MCP integration.

Usage:
    # Fetch recent law projects
    python law_tracker.py fetch --legislatura L17 --limit 100

    # Fetch projects with full lifecycle events
    python law_tracker.py fetch --legislatura L17 --with-events --limit 50

    # Fetch recent votes
    python law_tracker.py votes --legislatura L17 --since 2026-01-01

    # Fetch deputies
    python law_tracker.py deputies --legislatura L17

    # Fetch parties
    python law_tracker.py parties --legislatura L17

    # Search projects
    python law_tracker.py search "educação" --legislatura L17

    # Show project detail + lifecycle
    python law_tracker.py show <ini_id>

    # Show index statistics
    python law_tracker.py stats

    # Start MCP server
    python law_tracker.py mcp

Environment:
    LAW_API_BASE: Override API base URL (default: https://api.votoaberto.org)
    LAW_PAGE_SIZE: Page size for API requests (default: 500, max 500)
"""

import sys
import json
import time
import os
import argparse
import logging
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

logger = logging.getLogger("law_tracker")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("LAW_API_BASE", "https://api.votoaberto.org")
PAGE_SIZE = min(int(os.environ.get("LAW_PAGE_SIZE", "500")), 500)
DEFAULT_LEGISLATURA = "L17"


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

class VotoAbertoClient:
    """HTTP client for api.votoaberto.org REST API."""

    def __init__(self, base_url: str = API_BASE, delay: float = 0.2):
        self.base_url = base_url.rstrip("/")
        self.delay = delay

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Make a GET request and return parsed JSON."""
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urlencode(params)

        logger.info(f"GET {url}")
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "law-tracker/1.0 (analisa-pt)",
        })

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                time.sleep(self.delay)
                return data
        except HTTPError as e:
            logger.error(f"HTTP {e.code} for {url}: {e.reason}")
            return None
        except URLError as e:
            logger.error(f"Network error for {url}: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    # --- Initiatives ---

    def fetch_initiatives(
        self,
        legislatura: str = "",
        ini_tipo: str = "",
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> tuple[list[dict], int]:
        """Fetch a page of initiatives. Returns (items, total_pages)."""
        params: dict = {"page": page, "page_size": page_size}
        if legislatura:
            params["legislatura"] = legislatura
        if ini_tipo:
            params["ini_tipo"] = ini_tipo

        data = self._get("/api/v1/iniciativas/", params)
        if not data:
            return [], 0

        items = data.get("data", [])
        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", 1)

        return items, total_pages

    def fetch_initiative_detail(self, ini_id: str) -> dict | None:
        """Fetch full details for a single initiative."""
        data = self._get(f"/api/v1/iniciativas/{ini_id}")
        return data

    def fetch_initiative_events(self, ini_id: str) -> list[dict]:
        """Fetch lifecycle events for an initiative."""
        data = self._get(f"/api/v1/iniciativas/{ini_id}/eventos")
        if not data:
            return []
        return data.get("data", [])

    # --- Votes ---

    def fetch_votes(
        self,
        legislatura: str = "",
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> tuple[list[dict], int]:
        """Fetch a page of voting records."""
        params: dict = {"page": page, "page_size": page_size}
        if legislatura:
            params["legislatura"] = legislatura

        data = self._get("/api/v1/atividades/votacoes/", params)
        if not data:
            return [], 0

        items = data.get("data", [])
        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", 1)

        return items, total_pages

    # --- Deputies ---

    def fetch_deputies(
        self,
        legislatura: str = "",
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> tuple[list[dict], int]:
        """Fetch a page of deputies."""
        params: dict = {"page": page, "page_size": page_size}
        if legislatura:
            params["legislatura"] = legislatura

        data = self._get("/api/v1/deputados/", params)
        if not data:
            return [], 0

        items = data.get("data", [])
        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", 1)

        return items, total_pages

    # --- Parties ---

    def fetch_parties(
        self,
        legislatura: str = "",
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> tuple[list[dict], int]:
        """Fetch a page of parties."""
        params: dict = {"page": page, "page_size": page_size}
        if legislatura:
            params["legislatura"] = legislatura

        data = self._get("/api/v1/partidos/", params)
        if not data:
            return [], 0

        items = data.get("data", [])
        pagination = data.get("pagination", {})
        total_pages = pagination.get("total_pages", 1)

        return items, total_pages


# ---------------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------------

def _cmd_fetch(client: VotoAbertoClient, args):
    """Fetch law projects and persist to SQLite."""
    from law_db import init_db, upsert_project, upsert_event, update_project_stage, get_projects

    conn = init_db(args.db)
    legislatura = args.legislatura or DEFAULT_LEGISLATURA

    print(f"Fetching initiatives for {legislatura} (max {args.limit})...")

    page = 1
    total_fetched = 0
    new_projects = 0
    total_pages = 999

    while total_fetched < args.limit and page <= total_pages:
        items, total_pages = client.fetch_initiatives(
            legislatura=legislatura,
            ini_tipo=args.tipo or "",
            page=page,
            page_size=min(PAGE_SIZE, args.limit - total_fetched),
        )

        if not items:
            break

        for item in items:
            is_new = upsert_project(conn, item)
            if is_new:
                new_projects += 1
            total_fetched += 1

            if total_fetched >= args.limit:
                break

        logger.info(f"  Page {page}/{total_pages}: {len(items)} items")
        page += 1

    conn.commit()

    # Fetch events for projects if requested
    if args.with_events:
        print(f"\nFetching lifecycle events...")
        projects = get_projects(conn, legislatura=legislatura, limit=args.limit)
        events_added = 0

        for proj in projects:
            events = client.fetch_initiative_events(proj["ini_id"])
            if not events:
                continue

            latest_fase = ""
            latest_date = ""
            vote_result = ""

            for evt in events:
                is_new = upsert_event(conn, evt)
                if is_new:
                    events_added += 1

                # Track the latest lifecycle stage
                data_fase = evt.get("data_fase", "")
                fase = evt.get("fase", "")
                if data_fase and (not latest_date or data_fase > latest_date):
                    latest_fase = fase
                    latest_date = data_fase

                # Track vote result
                votacao = evt.get("votacao")
                if isinstance(votacao, dict) and votacao.get("resultado"):
                    vote_result = votacao["resultado"]

            if latest_fase:
                update_project_stage(conn, proj["ini_id"], latest_fase, latest_date, vote_result)

            logger.info(f"  {proj['ini_id']}: {len(events)} events, latest={latest_fase}")

        conn.commit()
        print(f"  Events added: {events_added}")

    conn.close()

    print(f"\n=== Fetch complete ===")
    print(f"Projects: {total_fetched} fetched, {new_projects} new")
    print(f"Legislature: {legislatura}")


def _cmd_votes(client: VotoAbertoClient, args):
    """Fetch voting records."""
    from law_db import init_db, upsert_vote

    conn = init_db(args.db)
    legislatura = args.legislatura or DEFAULT_LEGISLATURA

    print(f"Fetching votes for {legislatura}...")

    page = 1
    total_fetched = 0
    new_votes = 0
    total_pages = 999

    while total_fetched < args.limit and page <= total_pages:
        items, total_pages = client.fetch_votes(
            legislatura=legislatura,
            page=page,
            page_size=min(PAGE_SIZE, args.limit - total_fetched),
        )

        if not items:
            break

        for item in items:
            is_new = upsert_vote(conn, item)
            if is_new:
                new_votes += 1
            total_fetched += 1

            if total_fetched >= args.limit:
                break

        logger.info(f"  Page {page}/{total_pages}: {len(items)} votes")
        page += 1

    conn.commit()
    conn.close()

    print(f"\n=== Votes fetched ===")
    print(f"Total: {total_fetched}, New: {new_votes}")


def _cmd_deputies(client: VotoAbertoClient, args):
    """Fetch deputy registry."""
    from law_db import init_db, upsert_deputy

    conn = init_db(args.db)
    legislatura = args.legislatura or DEFAULT_LEGISLATURA

    print(f"Fetching deputies for {legislatura}...")

    page = 1
    total_fetched = 0
    new_deps = 0
    total_pages = 999

    while total_fetched < args.limit and page <= total_pages:
        items, total_pages = client.fetch_deputies(
            legislatura=legislatura,
            page=page,
            page_size=min(PAGE_SIZE, args.limit - total_fetched),
        )

        if not items:
            break

        for item in items:
            is_new = upsert_deputy(conn, item)
            if is_new:
                new_deps += 1
            total_fetched += 1

        page += 1

    conn.commit()
    conn.close()

    print(f"\n=== Deputies fetched ===")
    print(f"Total: {total_fetched}, New: {new_deps}")


def _cmd_parties(client: VotoAbertoClient, args):
    """Fetch party registry."""
    from law_db import init_db, upsert_party

    conn = init_db(args.db)
    legislatura = args.legislatura or DEFAULT_LEGISLATURA

    print(f"Fetching parties for {legislatura}...")

    items, _ = client.fetch_parties(legislatura=legislatura)
    new_parties = 0

    for item in items:
        is_new = upsert_party(conn, item)
        if is_new:
            new_parties += 1

    conn.commit()
    conn.close()

    print(f"\n=== Parties fetched ===")
    print(f"Total: {len(items)}, New: {new_parties}")


def _cmd_search(args):
    """Search stored law projects."""
    from law_db import init_db, get_projects

    conn = init_db(args.db)
    projects = get_projects(
        conn,
        legislatura=args.legislatura or "",
        tipo=args.tipo or "",
        fase=args.fase or "",
        search=args.query or "",
        limit=args.limit,
    )
    conn.close()

    if not projects:
        print("No projects found.")
        return

    print(f"Found {len(projects)} projects:\n")
    for p in projects:
        tipo = p.get("ini_desc_tipo") or p.get("ini_tipo") or "?"
        fase = p.get("latest_fase") or "-"
        date = (p.get("latest_fase_date") or "?")[:10]
        result = p.get("vote_result") or ""
        autor = ""
        if p.get("autor_gp"):
            try:
                ag = json.loads(p["autor_gp"])
                autor = ", ".join(ag) if isinstance(ag, list) else str(ag)
            except (json.JSONDecodeError, TypeError):
                autor = p["autor_gp"][:60]

        print(f"  {p['ini_id']}  [{tipo}] {p.get('ini_titulo', '?')[:70]}")
        print(f"    Nr: {p.get('ini_nr', '?')}  |  Fase: {fase} ({date})  |  {result}")
        if autor:
            print(f"    Autor: {autor}")
        print()


def _cmd_show(args):
    """Show a single project with lifecycle events."""
    from law_db import init_db, get_project, get_events

    conn = init_db(args.db)
    project = get_project(conn, args.ini_id)

    if not project:
        print(f"Project {args.ini_id} not found in local index.")
        print("Run `law_tracker.py fetch` first to populate the index.")
        conn.close()
        return

    events = get_events(conn, args.ini_id)
    conn.close()

    # Print project details
    tipo = project.get("ini_desc_tipo") or project.get("ini_tipo") or "?"
    print(f"\n{'='*70}")
    print(f"  {project['ini_id']}  —  {tipo}")
    print(f"{'='*70}")
    print(f"  Título:      {project.get('ini_titulo', '?')}")
    print(f"  Número:      {project.get('ini_nr', '?')}")
    print(f"  Legislatura: {project.get('legislatura', '?')}")
    print(f"  Fase atual:  {project.get('latest_fase') or '?'}")
    print(f"  Data fase:   {project.get('latest_fase_date') or '?'}")
    if project.get("vote_result"):
        print(f"  Resultado:   {project['vote_result']}")
    if project.get("autor_gp"):
        try:
            ag = json.loads(project["autor_gp"])
            autor = ", ".join(ag) if isinstance(ag, list) else str(ag)
            print(f"  Autor:       {autor}")
        except (json.JSONDecodeError, TypeError):
            print(f"  Autor:       {project['autor_gp'][:80]}")

    # Print lifecycle events
    if events:
        print(f"\n  --- Lifecycle ({len(events)} events) ---")
        for evt in events:
            date = evt.get("data_fase", "?")[:10]
            fase = evt.get("fase", "?")
            obs = evt.get("obs_fase", "")
            line = f"    [{date}] {fase}"
            if obs:
                line += f"  — {obs[:60]}"
            print(line)
    else:
        print(f"\n  No lifecycle events stored. Re-fetch with --with-events.")

    print()


def _cmd_stats(args):
    """Show index statistics."""
    from law_db import init_db, get_stats

    conn = init_db(args.db)
    stats = get_stats(conn)
    conn.close()

    print(f"\n=== Law Project Tracker — Index Stats ===")
    print(f"  Projects:  {stats['projects']}")
    print(f"  Events:    {stats['events']}")
    print(f"  Votes:     {stats['votes']}")
    print(f"  Deputies:  {stats['deputies']}")
    print(f"  Parties:   {stats['parties']}")

    if stats["by_tipo"]:
        print(f"\n  By type:")
        for tipo, count in stats["by_tipo"].items():
            print(f"    {tipo or '(unknown)':40s}  {count:5d}")

    if stats["by_fase"]:
        print(f"\n  By lifecycle stage:")
        for fase, count in stats["by_fase"].items():
            print(f"    {fase or '(unknown)':40s}  {count:5d}")

    print()


# ---------------------------------------------------------------------------
# MCP Server (JSON-RPC 2.0 over stdio)
# ---------------------------------------------------------------------------

def run_mcp_server():
    """Run MCP server over stdio (JSON-RPC 2.0)."""
    from law_db import init_db, get_projects, get_project, get_events, get_votes, get_stats

    client = VotoAbertoClient()

    tools = [
        {
            "name": "search_law_projects",
            "description": "Search Portuguese law projects (projetos de lei) by keyword, type, or lifecycle stage. Returns matching initiatives from the Assembleia da República.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword (matches title or number)"},
                    "legislatura": {"type": "string", "description": "Legislature code, e.g. 'L17' (default: current)"},
                    "tipo": {"type": "string", "description": "Initiative type code: J=Projeto de Lei, R=Projeto de Resolução, D=Proposta de Alteração"},
                    "fase": {"type": "string", "description": "Lifecycle stage filter, e.g. 'Entrada', 'Comissão', 'Votação'"},
                    "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                },
            },
        },
        {
            "name": "get_law_project",
            "description": "Get full details and lifecycle timeline for a specific Portuguese law project by its initiative ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ini_id": {"type": "string", "description": "Initiative ID, e.g. '356859'"},
                },
                "required": ["ini_id"],
            },
        },
        {
            "name": "get_law_events",
            "description": "Get lifecycle events (Entrada, Comissão, Votação, etc.) for a law project. Shows the full legislative journey.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ini_id": {"type": "string", "description": "Initiative ID"},
                },
                "required": ["ini_id"],
            },
        },
        {
            "name": "search_votes",
            "description": "Search Portuguese parliamentary voting records. Find how the Assembleia da República voted on specific issues.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "legislatura": {"type": "string", "description": "Legislature code, e.g. 'L17'"},
                    "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                },
            },
        },
        {
            "name": "get_law_stats",
            "description": "Get summary statistics of the local law project index (counts by type, lifecycle stage, etc.).",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]

    logger.info("Law Tracker MCP server started on stdio")

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
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "law-tracker", "version": "1.0.0"},
                },
            })

        elif method == "tools/list":
            _send_response({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})

        elif method == "tools/call":
            tool_name = request["params"]["name"]
            args = request["params"].get("arguments", {})
            result = _handle_mcp_tool(tool_name, args, client, init_db)
            _send_response({"jsonrpc": "2.0", "id": req_id, "result": result})

        elif method == "ping":
            _send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})

        else:
            _send_response({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


def _handle_mcp_tool(tool_name: str, args: dict, client: VotoAbertoClient, init_db_fn) -> dict:
    """Handle an MCP tool call."""
    from law_db import get_projects, get_project, get_events, get_votes, get_stats

    try:
        db_path = args.get("db")
        conn = init_db_fn(db_path)

        if tool_name == "search_law_projects":
            projects = get_projects(
                conn,
                legislatura=args.get("legislatura", ""),
                tipo=args.get("tipo", ""),
                fase=args.get("fase", ""),
                search=args.get("query", ""),
                limit=args.get("limit", 20),
            )
            conn.close()
            return {
                "content": [{"type": "text", "text": json.dumps(projects, ensure_ascii=False, indent=2)}],
                "structuredContent": {
                    "title": "Law Projects Search",
                    "summary": f"{len(projects)} results",
                    "rows": projects,
                },
            }

        elif tool_name == "get_law_project":
            project = get_project(conn, args["ini_id"])
            events = get_events(conn, args["ini_id"]) if project else []
            conn.close()
            if not project:
                return {"content": [{"type": "text", "text": f"Project {args['ini_id']} not found"}], "isError": True}
            project["events"] = events
            return {
                "content": [{"type": "text", "text": json.dumps(project, ensure_ascii=False, indent=2)}],
                "structuredContent": project,
            }

        elif tool_name == "get_law_events":
            events = get_events(conn, args["ini_id"])
            conn.close()
            return {
                "content": [{"type": "text", "text": json.dumps(events, ensure_ascii=False, indent=2)}],
                "structuredContent": {
                    "title": f"Events for {args['ini_id']}",
                    "summary": f"{len(events)} lifecycle events",
                    "rows": events,
                },
            }

        elif tool_name == "search_votes":
            votes = get_votes(
                conn,
                legislatura=args.get("legislatura", ""),
                limit=args.get("limit", 20),
            )
            conn.close()
            return {
                "content": [{"type": "text", "text": json.dumps(votes, ensure_ascii=False, indent=2)}],
                "structuredContent": {
                    "title": "Parliamentary Votes",
                    "summary": f"{len(votes)} results",
                    "rows": votes,
                },
            }

        elif tool_name == "get_law_stats":
            stats = get_stats(conn)
            conn.close()
            return {
                "content": [{"type": "text", "text": json.dumps(stats, ensure_ascii=False, indent=2)}],
                "structuredContent": stats,
            }

        else:
            conn.close()
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}


def _send_response(response: dict):
    """Send a JSON-RPC response to stdout."""
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Law Project Tracker — Portuguese parliamentary initiatives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s fetch --legislatura L17 --limit 100
  %(prog)s fetch --legislatura L17 --with-events --limit 50
  %(prog)s votes --legislatura L17 --limit 100
  %(prog)s deputies --legislatura L17
  %(prog)s parties --legislatura L17
  %(prog)s search "educação" --legislatura L17
  %(prog)s show 356859
  %(prog)s stats
  %(prog)s mcp
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between API requests (seconds)")
    parser.add_argument("--base-url", default=API_BASE, help="API base URL")

    sub = parser.add_subparsers(dest="command")

    # fetch command
    p_fetch = sub.add_parser("fetch", help="Fetch law projects into local index")
    p_fetch.add_argument("--legislatura", default="", help="Legislature code (e.g. L17)")
    p_fetch.add_argument("--tipo", default="", help="Initiative type filter (J/R/D)")
    p_fetch.add_argument("--limit", type=int, default=200, help="Max projects to fetch")
    p_fetch.add_argument("--with-events", action="store_true", help="Also fetch lifecycle events")
    p_fetch.add_argument("--db", default=None, help="DB path")

    # votes command
    p_votes = sub.add_parser("votes", help="Fetch voting records")
    p_votes.add_argument("--legislatura", default="", help="Legislature code")
    p_votes.add_argument("--limit", type=int, default=200, help="Max votes to fetch")
    p_votes.add_argument("--db", default=None, help="DB path")

    # deputies command
    p_deputies = sub.add_parser("deputies", help="Fetch deputy registry")
    p_deputies.add_argument("--legislatura", default="", help="Legislature code")
    p_deputies.add_argument("--limit", type=int, default=500, help="Max deputies")
    p_deputies.add_argument("--db", default=None, help="DB path")

    # parties command
    p_parties = sub.add_parser("parties", help="Fetch party registry")
    p_parties.add_argument("--legislatura", default="", help="Legislature code")
    p_parties.add_argument("--db", default=None, help="DB path")

    # search command
    p_search = sub.add_parser("search", help="Search stored law projects")
    p_search.add_argument("query", nargs="?", default="", help="Search keyword")
    p_search.add_argument("--legislatura", default="", help="Filter by legislature")
    p_search.add_argument("--tipo", default="", help="Filter by type")
    p_search.add_argument("--fase", default="", help="Filter by lifecycle stage")
    p_search.add_argument("-n", "--limit", type=int, default=20, help="Max results")
    p_search.add_argument("--db", default=None, help="DB path")

    # show command
    p_show = sub.add_parser("show", help="Show a single project with lifecycle")
    p_show.add_argument("ini_id", help="Initiative ID")
    p_show.add_argument("--db", default=None, help="DB path")

    # stats command
    p_stats = sub.add_parser("stats", help="Show index statistics")
    p_stats.add_argument("--db", default=None, help="DB path")

    # mcp command
    sub.add_parser("mcp", help="Start MCP server (stdio)")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.command == "mcp":
        run_mcp_server()
        return

    client = VotoAbertoClient(base_url=args.base_url, delay=args.delay)

    commands = {
        "fetch": lambda: _cmd_fetch(client, args),
        "votes": lambda: _cmd_votes(client, args),
        "deputies": lambda: _cmd_deputies(client, args),
        "parties": lambda: _cmd_parties(client, args),
        "search": lambda: _cmd_search(args),
        "show": lambda: _cmd_show(args),
        "stats": lambda: _cmd_stats(args),
    }

    handler = commands.get(args.command)
    if handler:
        handler()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
