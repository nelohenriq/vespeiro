"""BEP Entity Index Database

Provides SQLAlchemy models and sync helpers for persisting BEP job listings
and building a searchable entity index. Uses plain sqlite3 for simplicity
(same DB can be queried with sqlite3 CLI).

Tables:
    bep_entities    — unique entity index (entidade + organismo pair)
    bep_listings    — individual job listings linked to an entity
"""

import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from utils_db import connect as db_connect

DB_PATH = Path(__file__).parent / "bep_index.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bep_entities (
    id              TEXT PRIMARY KEY,   -- sha256(entidade|organismo)[:12]
    entidade        TEXT NOT NULL,       -- top-level (e.g. "Câmaras Municipais")
    organismo       TEXT NOT NULL,       -- specific agency (e.g. "Câmara Municipal de Vila Nova de Gaia")
    display_name    TEXT NOT NULL,       -- best human-readable name
    nif             TEXT,                -- NIF/tax ID if found
    listing_count   INTEGER DEFAULT 0,
    first_seen      TEXT,                -- ISO datetime
    last_seen       TEXT,                -- ISO datetime
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bep_entities_entidade ON bep_entities(entidade);
CREATE INDEX IF NOT EXISTS idx_bep_entities_organismo ON bep_entities(organismo);

CREATE TABLE IF NOT EXISTS bep_listings (
    cod_oferta      TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL REFERENCES bep_entities(id),
    titulo          TEXT,
    estado          TEXT,
    entidade        TEXT,
    organismo       TEXT,
    tipo_oferta     TEXT,
    carreira        TEXT,
    categoria       TEXT,
    vinculo         TEXT,
    duracao         TEXT,
    regime          TEXT,
    remuneracao     TEXT,
    sup_mensal      TEXT,
    total_postos    TEXT,
    habilitacoes    TEXT,
    hab_desc        TEXT,
    funcoes         TEXT,
    outros_requisitos TEXT,
    relacao_juridica TEXT,
    req_nacional    TEXT,
    local_trabalho  TEXT,
    contacto        TEXT,
    data_publicacao TEXT,
    data_limite     TEXT,
    jornal          TEXT,
    texto_pub       TEXT,
    observacoes     TEXT,
    url             TEXT,
    collected_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bep_listings_entity ON bep_listings(entity_id);
CREATE INDEX IF NOT EXISTS idx_bep_listings_pub_date ON bep_listings(data_publicacao);
"""


def _entity_id(entidade: str, organismo: str) -> str:
    """Generate a deterministic entity ID from the pair."""
    raw = f"{entidade}|{organismo}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create tables if needed and return a connection."""
    path = db_path or DB_PATH
    conn = db_connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    # Migrations for existing DBs
    try:
        conn.execute("ALTER TABLE bep_entities ADD COLUMN nif TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    return conn


def _rows_to_entities(rows: list) -> list[dict]:
    """Convert SQLite rows to entity dicts."""
    return [
        {
            "id": r[0], "entidade": r[1], "organismo": r[2],
            "display_name": r[3], "nif": r[4], "listing_count": r[5],
            "first_seen": r[6], "last_seen": r[7],
        }
        for r in rows
    ]


def upsert_entity(conn: sqlite3.Connection, entidade: str, organismo: str) -> str:
    """Insert or update an entity in the index. Returns the entity ID.
    Does NOT increment listing_count — use refresh_entity_count() after inserts."""
    eid = _entity_id(entidade, organismo)
    now = _now_iso()
    display = organismo if organismo else entidade

    existing = conn.execute(
        "SELECT id FROM bep_entities WHERE id = ?", (eid,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE bep_entities SET last_seen = ?, display_name = ? WHERE id = ?",
            (now, display, eid),
        )
    else:
        conn.execute(
            "INSERT INTO bep_entities (id, entidade, organismo, display_name, "
            "listing_count, first_seen, last_seen, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
            (eid, entidade, organismo, display, now, now, now),
        )
    return eid


def refresh_entity_count(conn: sqlite3.Connection, entity_id: str):
    """Recompute listing_count for an entity from actual listing rows."""
    conn.execute(
        "UPDATE bep_entities SET listing_count = "
        "(SELECT count(*) FROM bep_listings WHERE entity_id = ?) WHERE id = ?",
        (entity_id, entity_id),
    )


def upsert_listing(conn: sqlite3.Connection, listing: dict, entity_id: str) -> bool:
    """Insert or update a listing. Returns True if inserted (new), False if updated."""
    now = _now_iso()
    existing = conn.execute(
        "SELECT cod_oferta FROM bep_listings WHERE cod_oferta = ?",
        (listing.get("cod_oferta", ""),),
    ).fetchone()

    fields = [
        "cod_oferta", "titulo", "estado", "entidade", "organismo",
        "tipo_oferta", "carreira", "categoria", "vinculo", "duracao",
        "regime", "remuneracao", "sup_mensal", "total_postos",
        "habilitacoes", "hab_desc", "funcoes", "outros_requisitos",
        "relacao_juridica", "req_nacional", "local_trabalho", "contacto",
        "data_publicacao", "data_limite", "jornal", "texto_pub",
        "observacoes", "url",
    ]

    values = {f: listing.get(f, "") for f in fields}
    values["entity_id"] = entity_id
    values["collected_at"] = now

    if existing:
        # Update non-empty fields
        sets = []
        params = []
        for f in fields:
            if values[f]:
                sets.append(f"{f} = ?")
                params.append(values[f])
        if sets:
            params.append(listing.get("cod_oferta", ""))
            conn.execute(
                f"UPDATE bep_listings SET {', '.join(sets)} WHERE cod_oferta = ?",
                params,
            )
        return False
    else:
        cols = list(values.keys())
        placeholders = ", ".join(["?"] * len(cols))
        conn.execute(
            f"INSERT INTO bep_listings ({', '.join(cols)}) VALUES ({placeholders})",
            [values[c] for c in cols],
        )
        return True


def get_entity_stats(conn: sqlite3.Connection) -> list[dict]:
    """Get all entities with their listing counts, sorted by count desc."""
    rows = conn.execute(
        "SELECT id, entidade, organismo, display_name, nif, listing_count, "
        "first_seen, last_seen FROM bep_entities ORDER BY listing_count DESC"
    ).fetchall()
    return _rows_to_entities(rows)


def search_entities(conn: sqlite3.Connection, query: str) -> list[dict]:
    """Search entities by substring match on entidade, organismo, or display_name."""
    q = f"%{query}%"
    rows = conn.execute(
        "SELECT id, entidade, organismo, display_name, nif, listing_count, "
        "first_seen, last_seen FROM bep_entities "
        "WHERE entidade LIKE ? OR organismo LIKE ? OR display_name LIKE ? "
        "ORDER BY listing_count DESC",
        (q, q, q),
    ).fetchall()
    return _rows_to_entities(rows)


def set_nif(conn: sqlite3.Connection, entity_id: str, nif: str) -> bool:
    """Set NIF for an entity. Returns True if a row was updated."""
    cur = conn.execute("UPDATE bep_entities SET nif = ? WHERE id = ?", (nif, entity_id))
    return cur.rowcount > 0


def get_entities_without_nif(conn: sqlite3.Connection) -> list[dict]:
    """Get all entities that don't have a NIF yet."""
    rows = conn.execute(
        "SELECT id, entidade, organismo, display_name, nif, listing_count, "
        "first_seen, last_seen FROM bep_entities WHERE nif IS NULL OR nif = '' "
        "ORDER BY listing_count DESC"
    ).fetchall()
    return _rows_to_entities(rows)


def search_by_nif(conn: sqlite3.Connection, nif: str) -> list[dict]:
    """Search entities by NIF."""
    rows = conn.execute(
        "SELECT id, entidade, organismo, display_name, nif, listing_count, "
        "first_seen, last_seen FROM bep_entities WHERE nif = ?",
        (nif,),
    ).fetchall()
    return _rows_to_entities(rows)


def get_listings_for_entity(conn: sqlite3.Connection, entity_id: str) -> list[dict]:
    """Get all listings for a given entity."""
    rows = conn.execute(
        "SELECT cod_oferta, titulo, estado, categoria, remuneracao, "
        "total_postos, data_publicacao, data_limite, url "
        "FROM bep_listings WHERE entity_id = ? ORDER BY data_publicacao DESC",
        (entity_id,),
    ).fetchall()
    return [
        {
            "cod_oferta": r[0], "titulo": r[1], "estado": r[2],
            "categoria": r[3], "remuneracao": r[4], "total_postos": r[5],
            "data_publicacao": r[6], "data_limite": r[7], "url": r[8],
        }
        for r in rows
    ]
