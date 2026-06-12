#!/usr/bin/env python3
"""Parliament Law RAG Pipeline — Semantic search over Portuguese law projects.

Chunks law projects from the local SQLite index (law_index.db), embeds them
with sentence-transformers, and stores vectors + text in a persistent LanceDB
table.  Embeddings are pre-computed at index time so search is fast.

Architecture (mirrors bep_rag.py):
    index:  Load model once → compute vectors → store in LanceDB → done
    search: Embed query (model loaded once per process) → LanceDB vector search

Usage:
    python law_rag.py index                        # Index all law projects
    python law_rag.py index --legislatura L17      # Index only L17 projects
    python law_rag.py search "educação"            # Semantic search
    python law_rag.py search "saúde pública" -n 5  # Top 5 results
    python law_rag.py search "orçamento" --tipo J  # Filter by type
    python law_rag.py stats                        # Show index stats
    python law_rag.py reset                        # Wipe and rebuild index
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import lancedb
import pyarrow as pa
from utils_db import connect as db_connect

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "law_index.db"
LANCEDB_DIR = SCRIPT_DIR / "lancedb_law"
TABLE_NAME = "law_projects"

# Multilingual embedding model — same as BEP RAG for consistency.
EMBED_MODEL = os.environ.get(
    "LAW_EMBED_MODEL",
    os.environ.get(
        "BEP_EMBED_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ),
)
EMBED_DIM: int | None = (
    int(os.environ.get("LAW_EMBED_DIM"))
    if os.environ.get("LAW_EMBED_DIM")
    else None
)

logger = logging.getLogger("law_rag")

# ---------------------------------------------------------------------------
# Chunking — law project → searchable text
# ---------------------------------------------------------------------------


def chunk_project(project: dict, events: list[dict]) -> str:
    """Convert a law project row + its events into a text chunk for embedding."""
    parts: list[str] = []

    # Title is the most important field
    titulo = (project.get("ini_titulo") or "").strip()
    if titulo:
        parts.append(f"Título: {titulo}")

    # Type and number
    tipo = (project.get("ini_desc_tipo") or project.get("ini_tipo") or "").strip()
    if tipo:
        parts.append(f"Tipo: {tipo}")

    nr = (project.get("ini_nr") or "").strip()
    if nr:
        parts.append(f"Número: {nr}")

    # Authoring parliamentary groups
    autor_gp = project.get("autor_gp") or ""
    if autor_gp:
        try:
            ag = json.loads(autor_gp)
            autor_text = ", ".join(ag) if isinstance(ag, list) else str(ag)
        except (json.JSONDecodeError, TypeError):
            autor_text = autor_gp
        if autor_text.strip():
            parts.append(f"Autor: {autor_text}")

    # Legislature
    legislatura = (project.get("legislatura") or "").strip()
    if legislatura:
        parts.append(f"Legislatura: {legislatura}")

    # Lifecycle stage
    fase = (project.get("latest_fase") or "").strip()
    if fase:
        parts.append(f"Fase atual: {fase}")

    fase_date = (project.get("latest_fase_date") or "").strip()
    if fase_date:
        parts.append(f"Data fase: {fase_date}")

    # Vote result
    vote_result = (project.get("vote_result") or "").strip()
    if vote_result:
        parts.append(f"Resultado votação: {vote_result}")

    # Lifecycle events — adds temporal context
    if events:
        event_lines: list[str] = []
        for evt in events:
            date = (evt.get("data_fase") or "")[:10]
            fase_name = (evt.get("fase") or "").strip()
            obs = (evt.get("obs_fase") or "").strip()
            line = f"  [{date}] {fase_name}"
            if obs:
                line += f" — {obs[:200]}"
            event_lines.append(line)
        parts.append("Ciclo legislativo:\n" + "\n".join(event_lines))

    if not parts:
        # Last resort: use ini_id
        ini_id = (project.get("ini_id") or "").strip()
        if ini_id:
            parts.append(f"Iniciativa {ini_id}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# DB helpers — read projects + events from law_index.db
# ---------------------------------------------------------------------------


def _all_projects(
    conn: sqlite3.Connection, legislatura: str | None = None
) -> list[dict]:
    """Fetch all projects with their events, optionally filtered."""
    query = "SELECT * FROM law_projects"
    params: list = []
    if legislatura:
        query += " WHERE legislatura = ?"
        params.append(legislatura)
    query += " ORDER BY latest_fase_date DESC NULLS LAST"

    rows = conn.execute(query, params).fetchall()
    columns = [desc[0] for desc in conn.execute("SELECT * FROM law_projects").description]

    projects: list[dict] = []
    for row in rows:
        proj = dict(zip(columns, row))
        # Fetch events for this project
        events = conn.execute(
            "SELECT evt_id, fase, codigo_fase, data_fase, obs_fase "
            "FROM law_events WHERE ini_id = ? ORDER BY data_fase ASC",
            (proj["ini_id"],),
        ).fetchall()
        evt_cols = ["evt_id", "fase", "codigo_fase", "data_fase", "obs_fase"]
        proj["_events"] = [dict(zip(evt_cols, e)) for e in events]
        projects.append(proj)

    return projects


# ---------------------------------------------------------------------------
# Embedding — load model once, compute batch
# ---------------------------------------------------------------------------

_MODEL = None


def _get_embedder():
    """Lazy-load sentence-transformers model (once per process).

    Auto-detects embedding dimension from the model if EMBED_DIM is not set.
    """
    global _MODEL, EMBED_DIM
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s ...", EMBED_MODEL)
        t0 = time.time()
        _MODEL = SentenceTransformer(EMBED_MODEL)
        if EMBED_DIM is None:
            EMBED_DIM = _MODEL.get_sentence_embedding_dimension()
            logger.info("Auto-detected dimension: %d", EMBED_DIM)
        logger.info("Model loaded in %.1fs (dim=%d)", time.time() - t0, EMBED_DIM)
    return _MODEL


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns list of L2-normalised vectors."""
    model = _get_embedder()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


# ---------------------------------------------------------------------------
# LanceDB — table management
# ---------------------------------------------------------------------------


def _get_db() -> lancedb.DBConnection:
    LANCEDB_DIR.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(LANCEDB_DIR))


def _get_or_create_table(db: lancedb.DBConnection) -> lancedb.Table:
    """Open existing table or create a new one with explicit schema."""
    try:
        table = db.open_table(TABLE_NAME)
        logger.info(
            "Opened existing table: %s (%d rows)", TABLE_NAME, table.count_rows()
        )
        return table
    except Exception:
        pass

    # Explicit schema — vectors are pre-computed, not generated by LanceDB
    schema = pa.schema(
        [
            pa.field("ini_id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), list_size=EMBED_DIM)),
            pa.field("legislatura", pa.string()),
            pa.field("ini_tipo", pa.string()),
            pa.field("ini_desc_tipo", pa.string()),
            pa.field("ini_titulo", pa.string()),
            pa.field("autor_gp", pa.string()),
            pa.field("latest_fase", pa.string()),
            pa.field("latest_fase_date", pa.string()),
            pa.field("vote_result", pa.string()),
            pa.field("ini_nr", pa.string()),
        ]
    )

    table = db.create_table(TABLE_NAME, schema=schema, mode="overwrite")
    logger.info("Created table: %s (dim=%d)", TABLE_NAME, EMBED_DIM)
    return table


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def cmd_index(args):
    """Index law projects into LanceDB with pre-computed embeddings."""
    if not DB_PATH.exists():
        print(f"ERROR: Law database not found at {DB_PATH}")
        print("Run `law_tracker.py fetch --legislatura L17 --with-events` first.")
        sys.exit(1)

    conn = db_connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    projects = _all_projects(conn, legislatura=args.legislatura)
    conn.close()

    if not projects:
        print("No law projects found to index.")
        return

    # Ensure model is loaded so EMBED_DIM is available for schema creation
    _get_embedder()

    db = _get_db()
    table = _get_or_create_table(db)

    # Dedup: get existing IDs from the table
    existing_ids: set[str] = set()
    try:
        arrow = table.to_arrow()
        if "ini_id" in arrow.column_names:
            existing_ids = set(arrow.column("ini_id").to_pylist())
    except Exception:
        pass

    print(f"Projects in DB:    {len(projects)}")
    print(f"Already indexed:   {len(existing_ids)}")

    # Build chunks for new projects only
    new_rows: list[dict] = []
    texts: list[str] = []
    for proj in projects:
        ini_id = proj["ini_id"]
        if ini_id in existing_ids:
            continue
        events = proj.pop("_events", [])
        text = chunk_project(proj, events)
        if not text.strip():
            continue
        new_rows.append(
            {
                "ini_id": ini_id,
                "text": text,
                "legislatura": proj.get("legislatura") or "",
                "ini_tipo": proj.get("ini_tipo") or "",
                "ini_desc_tipo": proj.get("ini_desc_tipo") or "",
                "ini_titulo": proj.get("ini_titulo") or "",
                "autor_gp": proj.get("autor_gp") or "",
                "latest_fase": proj.get("latest_fase") or "",
                "latest_fase_date": proj.get("latest_fase_date") or "",
                "vote_result": proj.get("vote_result") or "",
                "ini_nr": proj.get("ini_nr") or "",
            }
        )
        texts.append(text)

    if not new_rows:
        print("All law projects already indexed. Nothing to do.")
        return

    print(f"New chunks:        {len(new_rows)}")
    print(f"Loading {EMBED_MODEL} + embedding...")

    t0 = time.time()

    # Embed all new texts in one batch (model loaded once)
    BATCH = 200
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        vecs = _embed_texts(batch)
        all_vectors.extend(vecs)
        elapsed = time.time() - t0
        print(
            f"  Embedded [{min(i + BATCH, len(texts))}/{len(texts)}] {elapsed:.1f}s"
        )

    # Attach vectors to rows
    for row, vec in zip(new_rows, all_vectors):
        row["vector"] = vec

    # Insert into LanceDB
    print("  Writing to LanceDB...")
    table.add(new_rows)

    elapsed = time.time() - t0
    total = table.count_rows()
    print(f"\n=== Index complete ===")
    print(f"Embedded + indexed: {len(new_rows)} projects in {elapsed:.1f}s")
    print(f"Total in index:     {total}")
    print(f"Model:              {EMBED_MODEL}")
    print(f"Dimensions:         {EMBED_DIM}")


def cmd_search(args):
    """Vector search over indexed law projects.

    Embeds the query using the same model used for indexing, then performs
    LanceDB vector search.  Model is loaded once per process and cached.
    """
    if not args.query or not args.query.strip():
        print("ERROR: Search query cannot be empty.")
        sys.exit(1)

    db = _get_db()
    try:
        table = db.open_table(TABLE_NAME)
    except Exception:
        print("Index not found. Run `law_rag.py index` first.")
        sys.exit(1)

    count = table.count_rows()
    if count == 0:
        print("Index is empty. Run `law_rag.py index` first.")
        sys.exit(1)

    n = args.num
    print(f'Searching for: "{args.query}" (top {n})')
    print()

    t0 = time.time()

    # Embed the query using the same model
    query_vec = _embed_texts([args.query])[0]

    # Build vector search
    search = table.search(query_vec)

    # Apply metadata filters
    filters: list[str] = []
    if args.legislatura:
        safe = args.legislatura.replace("'", "''")
        filters.append(f"legislatura = '{safe}'")
    if args.tipo:
        safe = args.tipo.replace("'", "''")
        filters.append(f"ini_tipo = '{safe}'")
    if args.fase:
        safe = args.fase.replace("'", "''")
        filters.append(f"latest_fase = '{safe}'")
    if args.vote_result:
        safe = args.vote_result.replace("'", "''")
        filters.append(f"vote_result = '{safe}'")
    if args.since:
        safe_since = args.since.replace("'", "''")
        filters.append(f"latest_fase_date >= '{safe_since}'")
    if args.until:
        safe_until = args.until.replace("'", "''")
        filters.append(f"latest_fase_date <= '{safe_until}'")

    if filters:
        search = search.where(" AND ".join(filters))

    results = search.limit(n).to_list()
    elapsed = time.time() - t0

    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} results ({elapsed:.2f}s)\n")

    for i, row in enumerate(results, 1):
        dist = row.get("_distance", 0.0)
        # Convert L2 distance to similarity (vectors are L2-normalised)
        # For normalised vectors: L2² = 2(1 - cos_sim), so cos_sim = 1 - L2²/2
        similarity = max(0.0, 1.0 - (dist**2) / 2.0) if dist < 3.0 else 0.0

        ini_id = row.get("ini_id", "?")
        titulo = row.get("ini_titulo", "?")
        tipo = row.get("ini_desc_tipo") or row.get("ini_tipo") or ""
        fase = row.get("latest_fase") or ""
        fase_date = (row.get("latest_fase_date") or "")[:10]
        vote = row.get("vote_result") or ""
        nr = row.get("ini_nr") or ""
        autor = row.get("autor_gp") or ""
        legislatura = row.get("legislatura") or ""

        # Parse autor_gp for display
        autor_display = ""
        if autor:
            try:
                ag = json.loads(autor)
                autor_display = ", ".join(ag) if isinstance(ag, list) else str(ag)
            except (json.JSONDecodeError, TypeError):
                autor_display = autor[:80]

        print(f"─── #{i}  score={similarity:.3f}  {ini_id} ───")
        print(f"  Título:      {titulo}")
        if tipo:
            print(f"  Tipo:        {tipo}")
        if nr:
            print(f"  Número:      {nr}")
        if legislatura:
            print(f"  Legislatura: {legislatura}")
        if fase:
            print(f"  Fase:        {fase} ({fase_date})")
        if vote:
            print(f"  Resultado:   {vote}")
        if autor_display:
            print(f"  Autor:       {autor_display}")
        print()
        # Show first 3 lines of text for context
        text = row.get("text", "")
        for line in text.split("\n")[:3]:
            print(f"  {line}")
        print()


def cmd_stats(args):
    """Show index statistics."""
    if not LANCEDB_DIR.exists():
        print("No index found. Run `law_rag.py index` first.")
        return

    db = _get_db()
    try:
        table = db.open_table(TABLE_NAME)
    except Exception:
        print("No index found. Run `law_rag.py index` first.")
        return

    count = table.count_rows()
    print(f"Table:       {TABLE_NAME}")
    print(f"Directory:   {LANCEDB_DIR}")
    print(f"Documents:   {count}")
    print(f"Model:       {EMBED_MODEL}")
    print(f"Dimensions:  {EMBED_DIM}")

    if count == 0:
        print("\nIndex is empty.")
        return

    try:
        sample_df = table.search().limit(min(count, 500)).to_pandas()

        # Legislature distribution
        if "legislatura" in sample_df.columns:
            legs = sample_df["legislatura"].dropna().value_counts()
            print(f"\nBy legislature:")
            for leg, cnt in legs.items():
                print(f"  {leg or '(unknown)':10s}  {cnt:4d}")

        # Type distribution
        if "ini_desc_tipo" in sample_df.columns:
            tipos = sample_df["ini_desc_tipo"].dropna().value_counts()
            if not tipos.empty:
                print(f"\nBy type:")
                for tipo, cnt in tipos.items():
                    print(f"  {tipo or '(unknown)':40s}  {cnt:4d}")

        # Lifecycle stage distribution
        if "latest_fase" in sample_df.columns:
            fases = sample_df["latest_fase"].dropna().value_counts()
            if not fases.empty:
                print(f"\nBy lifecycle stage:")
                for fase, cnt in fases.items():
                    print(f"  {fase or '(unknown)':40s}  {cnt:4d}")

        # Date range
        if "latest_fase_date" in sample_df.columns:
            dates = sample_df["latest_fase_date"].dropna().sort_values()
            if not dates.empty:
                print(f"\nDate range:  {dates.iloc[0][:10]} → {dates.iloc[-1][:10]}")

        # Vote results
        if "vote_result" in sample_df.columns:
            votes = sample_df["vote_result"].dropna().value_counts()
            if not votes.empty:
                print(f"\nVote results:")
                for vr, cnt in votes.items():
                    print(f"  {vr:30s}  {cnt:4d}")

    except Exception as e:
        print(f"  (could not compute stats: {e})")


def cmd_reset(args):
    """Wipe the LanceDB index."""
    if not LANCEDB_DIR.exists():
        print("No index to reset.")
        return
    shutil.rmtree(LANCEDB_DIR)
    print(f"Removed {LANCEDB_DIR}")
    print("Index cleared. Run `law_rag.py index` to rebuild.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Parliament Law RAG — Semantic search over Portuguese law projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s index                              # Index all projects
  %(prog)s index --legislatura L17            # Index only L17 legislature
  %(prog)s search "educação"                  # Semantic search
  %(prog)s search "saúde pública" -n 5        # Top 5 results
  %(prog)s search "orçamento" --tipo J        # Filter: Projeto de Lei only
  %(prog)s search "habitação" --fase "Votação"  # Filter by lifecycle stage
  %(prog)s search "fiscalidade" --since 2026-01-01
  %(prog)s stats                              # Show index stats
  %(prog)s reset                              # Wipe index

Environment:
  LAW_EMBED_MODEL: Embedding model (default: paraphrase-multilingual-MiniLM-L12-v2)
  LAW_EMBED_DIM:   Embedding dimensions (auto-detected, override with env var)
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p_index = sub.add_parser("index", help="Index law projects into LanceDB")
    p_index.add_argument(
        "--legislatura", help="Filter by legislature code (e.g. L17)"
    )

    p_search = sub.add_parser("search", help="Semantic search over indexed projects")
    p_search.add_argument("query", help="Search query (natural language)")
    p_search.add_argument(
        "-n",
        "--num",
        type=int,
        default=10,
        help="Number of results (default 10)",
    )
    p_search.add_argument("--legislatura", help="Filter by legislature code")
    p_search.add_argument(
        "--tipo",
        help="Filter by initiative type (J=Projeto de Lei, R=Projeto de Resolução)",
    )
    p_search.add_argument("--fase", help="Filter by lifecycle stage")
    p_search.add_argument("--vote-result", help="Filter by vote result")
    p_search.add_argument("--since", help="Filter by date (YYYY-MM-DD)")
    p_search.add_argument("--until", help="Filter by date (YYYY-MM-DD)")

    sub.add_parser("stats", help="Show index statistics")
    sub.add_parser("reset", help="Wipe the index")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
        )
    else:
        logging.basicConfig(level=logging.WARNING)

    commands = {
        "index": cmd_index,
        "search": cmd_search,
        "stats": cmd_stats,
        "reset": cmd_reset,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
