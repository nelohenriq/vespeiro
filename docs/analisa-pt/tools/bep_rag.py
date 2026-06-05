#!/usr/bin/env python3
"""BEP RAG Pipeline — Semantic + keyword search over Portuguese public sector job listings.

Chunks BEP job listings from the local SQLite index, embeds them with
sentence-transformers, and stores vectors + text in a persistent LanceDB
table.  Embeddings are pre-computed at index time so search is fast.

Architecture:
    index:  Load model once → compute vectors → store in LanceDB → done
    search: Embed query (model loaded once per process) → LanceDB vector search

Usage:
    python bep_rag.py index                    # Index all listings
    python bep_rag.py index --entity "Gaia"    # Index only listings for an entity
    python bep_rag.py search "engenheiro informático"  # Hybrid search
    python bep_rag.py search "médico Lisboa" -n 5      # Top 5 results
    python bep_rag.py search "professor" --entity "Sintra"  # Filtered search
    python bep_rag.py stats                    # Show index stats
    python bep_rag.py reset                    # Wipe and rebuild index
"""

import argparse
import logging
import os
import sqlite3
import shutil
import sys
import time
from pathlib import Path

import lancedb
import pyarrow as pa

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "bep_index.db"
LANCEDB_DIR = SCRIPT_DIR / "lancedb_bep"
TABLE_NAME = "bep_listings"

# Multilingual embedding model — runs once during index, vectors stored in LanceDB.
EMBED_MODEL = os.environ.get(
    "BEP_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBED_DIM: int | None = (
    int(os.environ.get("BEP_EMBED_DIM"))
    if os.environ.get("BEP_EMBED_DIM")
    else None  # Auto-detect from model on first use
)

logger = logging.getLogger("bep_rag")

# ---------------------------------------------------------------------------
# Chunking — listing → searchable text
# ---------------------------------------------------------------------------

_SEARCHABLE_FIELDS = [
    ("categoria", "Categoria"),
    ("organismo", "Organismo"),
    ("entidade", "Entidade"),
    ("funcoes", "Funções"),
    ("hab_desc", "Habilitações"),
    ("local_trabalho", "Local de trabalho"),
    ("remuneracao", "Remuneração"),
    ("regime", "Regime"),
    ("tipo_oferta", "Tipo"),
    ("carreira", "Carreira"),
    ("outros_requisitos", "Requisitos"),
    ("texto_pub", "Texto publicação"),
]


def chunk_listing(row: dict) -> str:
    """Convert a DB listing row into a text chunk for embedding."""
    parts: list[str] = []
    for field, label in _SEARCHABLE_FIELDS:
        value = (row.get(field) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    if not parts:
        fallback = (row.get("titulo") or "").strip()
        if fallback:
            parts.append(fallback[:800])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# DB helpers — read listings from bep_index.db
# ---------------------------------------------------------------------------

def _all_listings(conn: sqlite3.Connection, entity_filter: str | None = None) -> list[dict]:
    """Fetch all listings with entity info, optionally filtered."""
    query = """
        SELECT l.cod_oferta, l.titulo, l.estado, l.entidade, l.organismo,
               l.tipo_oferta, l.carreira, l.categoria, l.vinculo, l.duracao,
               l.regime, l.remuneracao, l.sup_mensal, l.total_postos,
               l.habilitacoes, l.hab_desc, l.funcoes, l.outros_requisitos,
               l.relacao_juridica, l.req_nacional, l.local_trabalho,
               l.contacto, l.data_publicacao, l.data_limite, l.jornal,
               l.texto_pub, l.observacoes, l.url,
               l.entity_id, e.display_name, e.nif
        FROM bep_listings l
        JOIN bep_entities e ON l.entity_id = e.id
    """
    params: list = []
    if entity_filter:
        query += " WHERE e.display_name LIKE ? OR e.organismo LIKE ? OR e.entidade LIKE ?"
        q = f"%{entity_filter}%"
        params = [q, q, q]
    query += " ORDER BY l.data_publicacao DESC"
    rows = conn.execute(query, params).fetchall()
    columns = [
        "cod_oferta", "titulo", "estado", "entidade", "organismo",
        "tipo_oferta", "carreira", "categoria", "vinculo", "duracao",
        "regime", "remuneracao", "sup_mensal", "total_postos",
        "habilitacoes", "hab_desc", "funcoes", "outros_requisitos",
        "relacao_juridica", "req_nacional", "local_trabalho",
        "contacto", "data_publicacao", "data_limite", "jornal",
        "texto_pub", "observacoes", "url",
        "entity_id", "display_name", "nif",
    ]
    return [dict(zip(columns, r)) for r in rows]


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
        logger.info("Opened existing table: %s (%d rows)", TABLE_NAME, table.count_rows())
        return table
    except Exception:
        pass

    # Explicit schema — vectors are pre-computed, not generated by LanceDB
    schema = pa.schema([
        pa.field("cod_oferta", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), list_size=EMBED_DIM)),
        pa.field("entity_id", pa.string()),
        pa.field("display_name", pa.string()),
        pa.field("nif", pa.string()),
        pa.field("entidade", pa.string()),
        pa.field("organismo", pa.string()),
        pa.field("data_publicacao", pa.string()),
        pa.field("data_limite", pa.string()),
        pa.field("url", pa.string()),
        pa.field("titulo", pa.string()),
    ])

    table = db.create_table(TABLE_NAME, schema=schema, mode="overwrite")
    logger.info("Created table: %s (dim=%d)", TABLE_NAME, EMBED_DIM)
    return table


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_index(args):
    """Index BEP listings into LanceDB with pre-computed embeddings."""
    if not DB_PATH.exists():
        print(f"ERROR: BEP database not found at {DB_PATH}")
        print("Run `bep_scraper.py collect` first to build the index.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    listings = _all_listings(conn, entity_filter=args.entity)
    conn.close()

    if not listings:
        print("No listings found to index.")
        return

    # Ensure model is loaded so EMBED_DIM is available for schema creation
    _get_embedder()

    db = _get_db()
    table = _get_or_create_table(db)

    # Dedup: get existing IDs from the table
    existing_ids: set[str] = set()
    try:
        arrow = table.to_arrow()
        if "cod_oferta" in arrow.column_names:
            existing_ids = set(arrow.column("cod_oferta").to_pylist())
    except Exception:
        pass

    print(f"Listings in DB:     {len(listings)}")
    print(f"Already indexed:    {len(existing_ids)}")

    # Build chunks for new listings only
    new_rows: list[dict] = []
    texts: list[str] = []
    for row in listings:
        cid = row["cod_oferta"]
        if cid in existing_ids:
            continue
        text = chunk_listing(row)
        if not text.strip():
            continue
        new_rows.append({
            "cod_oferta": cid,
            "text": text,
            "entity_id": row.get("entity_id", ""),
            "display_name": row.get("display_name", ""),
            "nif": row.get("nif") or "",
            "entidade": row.get("entidade") or "",
            "organismo": row.get("organismo") or "",
            "data_publicacao": row.get("data_publicacao") or "",
            "data_limite": row.get("data_limite") or "",
            "url": row.get("url") or "",
            "titulo": row.get("titulo") or "",
        })
        texts.append(text)

    if not new_rows:
        print("All listings already indexed. Nothing to do.")
        return

    print(f"New chunks:         {len(new_rows)}")
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
        print(f"  Embedded [{min(i + BATCH, len(texts))}/{len(texts)}] {elapsed:.1f}s")

    # Attach vectors to rows
    for row, vec in zip(new_rows, all_vectors):
        row["vector"] = vec

    # Insert into LanceDB
    print(f"  Writing to LanceDB...")
    table.add(new_rows)

    elapsed = time.time() - t0
    total = table.count_rows()
    print(f"\n=== Index complete ===")
    print(f"Embedded + indexed: {len(new_rows)} listings in {elapsed:.1f}s")
    print(f"Total in index:     {total}")
    print(f"Model:              {EMBED_MODEL}")
    print(f"Dimensions:         {EMBED_DIM}")


def cmd_search(args):
    """Vector search over indexed BEP listings.

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
        print("Index not found. Run `bep_rag.py index` first.")
        sys.exit(1)

    count = table.count_rows()
    if count == 0:
        print("Index is empty. Run `bep_rag.py index` first.")
        sys.exit(1)

    n = args.num
    print(f"Searching for: \"{args.query}\" (top {n})")
    print()

    t0 = time.time()

    # Embed the query using the same model
    query_vec = _embed_texts([args.query])[0]

    # Build vector search
    search = table.search(query_vec)

    # Apply metadata filters
    filters: list[str] = []
    if args.entity:
        safe = args.entity.replace("'", "''")
        filters.append(
            f"(display_name LIKE '%{safe}%' OR organismo LIKE '%{safe}%')"
        )
    if args.since:
        safe_since = args.since.replace("'", "''")
        filters.append(f"data_publicacao >= '{safe_since}'")
    if args.until:
        safe_until = args.until.replace("'", "''")
        filters.append(f"data_publicacao <= '{safe_until}'")

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
        similarity = max(0.0, 1.0 - (dist ** 2) / 2.0) if dist < 3.0 else 0.0

        pub_date = row.get("data_publicacao", "?")
        deadline = row.get("data_limite", "")
        entity = row.get("display_name", "?")
        cod = row.get("cod_oferta", "?")
        nif = row.get("nif", "")
        url = row.get("url", "")
        text = row.get("text", "")

        print(f"─── #{i}  score={similarity:.3f}  [{pub_date}]  {cod} ───")
        print(f"  Entidade: {entity}")
        if nif:
            print(f"  NIF:      {nif}")
        if deadline:
            print(f"  Deadline: {deadline}")
        print()
        for line in text.split("\n"):
            print(f"  {line}")
        print()
        if url:
            print(f"  {url}")
        print()


def cmd_stats(args):
    """Show index statistics."""
    if not LANCEDB_DIR.exists():
        print("No index found. Run `bep_rag.py index` first.")
        return

    db = _get_db()
    try:
        table = db.open_table(TABLE_NAME)
    except Exception:
        print("No index found. Run `bep_rag.py index` first.")
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
        dates = sample_df["data_publicacao"].dropna().sort_values().tolist()
        entities = sample_df["display_name"].dropna().unique()

        if dates:
            print(f"Date range:  {dates[0]} → {dates[-1]}")
        print(f"Entities:    {len(entities)} unique (from sampled docs)")

        entity_counts = sample_df["display_name"].value_counts()
        print(f"\nTop entities in index:")
        for name, cnt in entity_counts.head(10).items():
            print(f"  {cnt:4d}  {name}")
    except Exception as e:
        print(f"  (could not compute stats: {e})")


def cmd_reset(args):
    """Wipe the LanceDB index."""
    if not LANCEDB_DIR.exists():
        print("No index to reset.")
        return
    shutil.rmtree(LANCEDB_DIR)
    print(f"Removed {LANCEDB_DIR}")
    print("Index cleared. Run `bep_rag.py index` to rebuild.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="BEP RAG Pipeline — Hybrid search over public sector job listings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s index                              # Index all listings
  %(prog)s index --entity "Saude"             # Index only Saude listings
  %(prog)s search "engenheiro informático"
  %(prog)s search "médico hospital" -n 5
  %(prog)s search "professor" --entity "Sintra"
  %(prog)s search "enfermeiro" --since 2026-05-01
  %(prog)s stats                              # Show index stats
  %(prog)s reset                              # Wipe index

Environment:
  BEP_EMBED_MODEL: Embedding model (default: paraphrase-multilingual-MiniLM-L12-v2)
  BEP_EMBED_DIM:   Embedding dimensions (auto-detected, override with env var)
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p_index = sub.add_parser("index", help="Index listings into LanceDB")
    p_index.add_argument("--entity", help="Filter by entity/organismo name")

    p_search = sub.add_parser("search", help="Hybrid search (vector + keyword)")
    p_search.add_argument("query", help="Search query (natural language)")
    p_search.add_argument("-n", "--num", type=int, default=10, help="Number of results (default 10)")
    p_search.add_argument("--entity", help="Filter by entity name")
    p_search.add_argument("--since", help="Filter by publication date (YYYY-MM-DD)")
    p_search.add_argument("--until", help="Filter by publication date (YYYY-MM-DD)")

    sub.add_parser("stats", help="Show index statistics")
    sub.add_parser("reset", help="Wipe the index")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
