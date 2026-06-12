"""DRE Publication Crawler — SQLite persistence layer.

Stores Diário da República publications enumerated via ELI URIs.
Links publications to BEP entities and law projects for cross-referencing.

Tables:
    dre_publications  — daily DRE issues (série, number, date, URL)
    dre_documents     — individual documents within each issue
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from utils_db import connect as db_connect

DB_PATH = Path(__file__).parent / "dre_index.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dre_publications (
    pub_id          TEXT PRIMARY KEY,   -- serie-number-year
    serie           INTEGER NOT NULL,   -- 1 or 2
    numero          INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    eli_url         TEXT NOT NULL,
    redirect_url    TEXT,               -- final canonical URL
    unique_id       TEXT,               -- DRE internal unique ID from redirect
    title           TEXT,
    publication_date TEXT,
    collected_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dre_pub_date ON dre_publications(publication_date);
CREATE INDEX IF NOT EXISTS idx_dre_pub_serie ON dre_publications(serie);

CREATE TABLE IF NOT EXISTS dre_documents (
    doc_id          TEXT PRIMARY KEY,   -- unique_id from DRE
    pub_id          TEXT REFERENCES dre_publications(pub_id),
    title           TEXT,
    doc_type        TEXT,               -- Lei, Decreto-Lei, Portaria, etc.
    emiting_body    TEXT,
    dre_url         TEXT,
    collected_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dre_doc_pub ON dre_documents(pub_id);
"""


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
    conn.commit()
    return conn


def upsert_publication(conn: sqlite3.Connection, pub: dict) -> bool:
    """Insert or update a publication. Returns True if new."""
    pub_id = pub.get("pub_id", "")
    if not pub_id:
        return False

    existing = conn.execute(
        "SELECT pub_id FROM dre_publications WHERE pub_id = ?", (pub_id,)
    ).fetchone()

    if existing:
        # Update redirect_url if we have a better one now
        if pub.get("redirect_url"):
            conn.execute(
                "UPDATE dre_publications SET redirect_url=?, unique_id=?, title=? WHERE pub_id=?",
                (pub["redirect_url"], pub.get("unique_id", ""), pub.get("title", ""), pub_id),
            )
        return False

    conn.execute(
        "INSERT INTO dre_publications "
        "(pub_id, serie, numero, year, eli_url, redirect_url, unique_id, title, publication_date, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            pub_id,
            pub.get("serie", 0),
            pub.get("numero", 0),
            pub.get("year", 0),
            pub.get("eli_url", ""),
            pub.get("redirect_url", ""),
            pub.get("unique_id", ""),
            pub.get("title", ""),
            pub.get("publication_date", ""),
            _now_iso(),
        ),
    )
    return True


def upsert_document(conn: sqlite3.Connection, doc: dict) -> bool:
    """Insert a document. Returns True if new."""
    doc_id = doc.get("doc_id", "")
    if not doc_id:
        return False

    existing = conn.execute(
        "SELECT doc_id FROM dre_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if existing:
        return False

    conn.execute(
        "INSERT INTO dre_documents "
        "(doc_id, pub_id, title, doc_type, emiting_body, dre_url, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            doc_id,
            doc.get("pub_id", ""),
            doc.get("title", ""),
            doc.get("doc_type", ""),
            doc.get("emiting_body", ""),
            doc.get("dre_url", ""),
            _now_iso(),
        ),
    )
    return True


def get_publications(
    conn: sqlite3.Connection,
    serie: int = 0,
    year: int = 0,
    since: str = "",
    search: str = "",
    limit: int = 50,
) -> list[dict]:
    """Query publications."""
    where = []
    params: list = []
    if serie:
        where.append("serie = ?")
        params.append(serie)
    if year:
        where.append("year = ?")
        params.append(year)
    if since:
        where.append("publication_date >= ?")
        params.append(since)
    if search:
        where.append("(title LIKE ? OR pub_id LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT pub_id, serie, numero, year, publication_date, redirect_url, title "
        f"FROM dre_publications{clause} "
        f"ORDER BY year DESC, serie DESC, numero DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {"pub_id": r[0], "serie": r[1], "numero": r[2], "year": r[3],
         "publication_date": r[4], "redirect_url": r[5], "title": r[6]}
        for r in rows
    ]


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get summary statistics."""
    pubs = conn.execute("SELECT COUNT(*) FROM dre_publications").fetchone()[0]
    docs = conn.execute("SELECT COUNT(*) FROM dre_documents").fetchone()[0]
    s1 = conn.execute("SELECT COUNT(*) FROM dre_publications WHERE serie=1").fetchone()[0]
    s2 = conn.execute("SELECT COUNT(*) FROM dre_publications WHERE serie=2").fetchone()[0]
    date_range = conn.execute(
        "SELECT MIN(publication_date), MAX(publication_date) FROM dre_publications"
    ).fetchone()
    return {
        "publications": pubs, "documents": docs,
        "serie_1": s1, "serie_2": s2,
        "date_range": (date_range[0], date_range[1]) if date_range[0] else ("", ""),
    }
