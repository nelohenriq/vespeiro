"""Law Project Tracker — SQLite persistence layer.

Stores Portuguese parliamentary initiatives (projetos de lei), lifecycle events,
votes, deputies, and parties from api.votoaberto.org.

Tables:
    law_projects      — legislative initiatives (projetos de lei, resoluções, etc.)
    law_events        — lifecycle events per initiative (Entrada, Comissão, Votação, etc.)
    law_votes         — voting records linked to initiatives
    law_deputies      — deputy registry
    law_parties       — parliamentary group registry
"""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from utils_db import connect as db_connect

DB_PATH = Path(__file__).parent / "law_index.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS law_projects (
    ini_id          TEXT PRIMARY KEY,
    ini_nr          TEXT,
    legislatura     TEXT NOT NULL,
    ini_tipo        TEXT,
    ini_desc_tipo   TEXT,
    ini_titulo      TEXT,
    autor_gp        TEXT,           -- JSON array of parliamentary groups
    latest_fase     TEXT,           -- current lifecycle stage
    latest_fase_date TEXT,          -- date of latest stage
    vote_result     TEXT,           -- Aprovado / Rejeitado / etc.
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_law_projects_leg ON law_projects(legislatura);
CREATE INDEX IF NOT EXISTS idx_law_projects_tipo ON law_projects(ini_tipo);
CREATE INDEX IF NOT EXISTS idx_law_projects_fase ON law_projects(latest_fase);

CREATE TABLE IF NOT EXISTS law_events (
    ini_id          TEXT NOT NULL REFERENCES law_projects(ini_id),
    evt_id          TEXT PRIMARY KEY,
    legislatura     TEXT,
    fase            TEXT,           -- e.g. "Entrada", "Comissão", "Votação"
    codigo_fase     TEXT,
    data_fase       TEXT,           -- ISO date
    obs_fase        TEXT,
    votacao         TEXT,           -- JSON if present
    comissao        TEXT,           -- JSON if present
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_law_events_ini ON law_events(ini_id);
CREATE INDEX IF NOT EXISTS idx_law_events_fase ON law_events(fase);
CREATE INDEX IF NOT EXISTS idx_law_events_date ON law_events(data_fase);

CREATE TABLE IF NOT EXISTS law_votes (
    vot_id          TEXT PRIMARY KEY,
    ativ_id         TEXT,
    legislatura     TEXT,
    assunto         TEXT,
    tipo            TEXT,
    data            TEXT,           -- ISO date
    resultado       TEXT,           -- Aprovado / Rejeitado
    has_party_details INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_law_votes_ativ ON law_votes(ativ_id);
CREATE INDEX IF NOT EXISTS idx_law_votes_date ON law_votes(data);

CREATE TABLE IF NOT EXISTS law_deputies (
    dep_cad_id      INTEGER PRIMARY KEY,
    legislatura     TEXT,
    nome_parlamentar TEXT,
    circulo_atual   TEXT,
    partido_atual   TEXT,
    situacao_atual  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS law_parties (
    gp_sigla        TEXT NOT NULL,
    legislatura     TEXT NOT NULL,
    gp_nome         TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (gp_sigla, legislatura)
);
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


def upsert_project(conn: sqlite3.Connection, project: dict) -> bool:
    """Insert or update a law project. Returns True if inserted (new)."""
    ini_id = project.get("ini_id", "")
    if not ini_id:
        return False

    now = _now_iso()
    existing = conn.execute(
        "SELECT ini_id FROM law_projects WHERE ini_id = ?", (ini_id,)
    ).fetchone()

    # Convert autor_gp list to JSON string if needed
    autor_gp = project.get("autor_gp")
    if isinstance(autor_gp, list):
        autor_gp = json.dumps(autor_gp, ensure_ascii=False)
    elif autor_gp is None:
        autor_gp = ""

    if existing:
        conn.execute(
            "UPDATE law_projects SET ini_nr=?, legislatura=?, ini_tipo=?, "
            "ini_desc_tipo=?, ini_titulo=?, autor_gp=?, updated_at=? "
            "WHERE ini_id=?",
            (
                project.get("ini_nr", ""),
                project.get("legislatura", ""),
                project.get("ini_tipo", ""),
                project.get("ini_desc_tipo", ""),
                project.get("ini_titulo", ""),
                autor_gp,
                now,
                ini_id,
            ),
        )
        return False
    else:
        conn.execute(
            "INSERT INTO law_projects "
            "(ini_id, ini_nr, legislatura, ini_tipo, ini_desc_tipo, ini_titulo, "
            "autor_gp, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ini_id,
                project.get("ini_nr", ""),
                project.get("legislatura", ""),
                project.get("ini_tipo", ""),
                project.get("ini_desc_tipo", ""),
                project.get("ini_titulo", ""),
                autor_gp,
                now,
                now,
            ),
        )
        return True


def update_project_stage(
    conn: sqlite3.Connection,
    ini_id: str,
    fase: str,
    fase_date: str,
    vote_result: str = "",
):
    """Update the latest lifecycle stage for a project."""
    sets = ["latest_fase = ?", "latest_fase_date = ?", "updated_at = ?"]
    params: list = [fase, fase_date, _now_iso()]
    if vote_result:
        sets.append("vote_result = ?")
        params.append(vote_result)
    params.append(ini_id)
    conn.execute(
        f"UPDATE law_projects SET {', '.join(sets)} WHERE ini_id = ?", params
    )


def upsert_event(conn: sqlite3.Connection, event: dict) -> bool:
    """Insert a lifecycle event. Returns True if new."""
    evt_id = event.get("evt_id", "")
    if not evt_id:
        # Generate a deterministic ID from the event content
        raw = f"{event.get('ini_id', '')}|{event.get('fase', '')}|{event.get('data_fase', '')}"
        evt_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    existing = conn.execute(
        "SELECT evt_id FROM law_events WHERE evt_id = ?", (evt_id,)
    ).fetchone()

    votacao = event.get("votacao")
    if isinstance(votacao, (dict, list)):
        votacao = json.dumps(votacao, ensure_ascii=False)
    elif votacao is None:
        votacao = ""

    comissao = event.get("comissao")
    if isinstance(comissao, (dict, list)):
        comissao = json.dumps(comissao, ensure_ascii=False)
    elif comissao is None:
        comissao = ""

    if existing:
        return False

    conn.execute(
        "INSERT INTO law_events "
        "(ini_id, evt_id, legislatura, fase, codigo_fase, data_fase, "
        "obs_fase, votacao, comissao, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.get("ini_id", ""),
            evt_id,
            event.get("legislatura", ""),
            event.get("fase", ""),
            event.get("codigo_fase", ""),
            event.get("data_fase", ""),
            event.get("obs_fase", ""),
            votacao,
            comissao,
            _now_iso(),
        ),
    )
    return True


def upsert_vote(conn: sqlite3.Connection, vote: dict) -> bool:
    """Insert a voting record. Returns True if new."""
    vot_id = vote.get("vot_id", "")
    if not vot_id:
        return False

    existing = conn.execute(
        "SELECT vot_id FROM law_votes WHERE vot_id = ?", (vot_id,)
    ).fetchone()

    if existing:
        return False

    conn.execute(
        "INSERT INTO law_votes "
        "(vot_id, ativ_id, legislatura, assunto, tipo, data, resultado, "
        "has_party_details, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            vot_id,
            vote.get("ativ_id", ""),
            vote.get("legislatura", ""),
            vote.get("assunto", ""),
            vote.get("tipo", ""),
            vote.get("data", ""),
            vote.get("resultado", ""),
            1 if vote.get("has_party_details") else 0,
            _now_iso(),
        ),
    )
    return True


def upsert_deputy(conn: sqlite3.Connection, deputy: dict) -> bool:
    """Insert or update a deputy. Returns True if inserted."""
    dep_id = deputy.get("dep_cad_id")
    if not dep_id:
        return False

    now = _now_iso()
    existing = conn.execute(
        "SELECT dep_cad_id FROM law_deputies WHERE dep_cad_id = ?", (dep_id,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE law_deputies SET nome_parlamentar=?, circulo_atual=?, "
            "partido_atual=?, situacao_atual=?, updated_at=? WHERE dep_cad_id=?",
            (
                deputy.get("nome_parlamentar", ""),
                deputy.get("circulo_atual", ""),
                deputy.get("partido_atual", ""),
                deputy.get("situacao_atual", ""),
                now,
                dep_id,
            ),
        )
        return False
    else:
        conn.execute(
            "INSERT INTO law_deputies "
            "(dep_cad_id, legislatura, nome_parlamentar, circulo_atual, "
            "partido_atual, situacao_atual, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dep_id,
                deputy.get("legislatura", ""),
                deputy.get("nome_parlamentar", ""),
                deputy.get("circulo_atual", ""),
                deputy.get("partido_atual", ""),
                deputy.get("situacao_atual", ""),
                now,
                now,
            ),
        )
        return True


def upsert_party(conn: sqlite3.Connection, party: dict) -> bool:
    """Insert a party. Returns True if new."""
    sigla = party.get("gp_sigla", "")
    legislatura = party.get("legislatura", "")
    if not sigla or not legislatura:
        return False

    existing = conn.execute(
        "SELECT gp_sigla FROM law_parties WHERE gp_sigla=? AND legislatura=?",
        (sigla, legislatura),
    ).fetchone()

    if existing:
        return False

    conn.execute(
        "INSERT INTO law_parties (gp_sigla, legislatura, gp_nome, created_at) "
        "VALUES (?, ?, ?, ?)",
        (sigla, legislatura, party.get("gp_nome", ""), _now_iso()),
    )
    return True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_projects(
    conn: sqlite3.Connection,
    legislatura: str = "",
    tipo: str = "",
    fase: str = "",
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query law projects with optional filters."""
    where = []
    params: list = []

    if legislatura:
        where.append("legislatura = ?")
        params.append(legislatura)
    if tipo:
        where.append("ini_tipo = ?")
        params.append(tipo)
    if fase:
        where.append("latest_fase = ?")
        params.append(fase)
    if search:
        where.append("(ini_titulo LIKE ? OR ini_nr LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    params.extend([limit, offset])

    rows = conn.execute(
        f"SELECT ini_id, ini_nr, legislatura, ini_tipo, ini_desc_tipo, "
        f"ini_titulo, autor_gp, latest_fase, latest_fase_date, vote_result "
        f"FROM law_projects{clause} "
        f"ORDER BY latest_fase_date DESC NULLS LAST, ini_nr DESC "
        f"LIMIT ? OFFSET ?",
        params,
    ).fetchall()

    return [
        {
            "ini_id": r[0], "ini_nr": r[1], "legislatura": r[2],
            "ini_tipo": r[3], "ini_desc_tipo": r[4], "ini_titulo": r[5],
            "autor_gp": r[6], "latest_fase": r[7], "latest_fase_date": r[8],
            "vote_result": r[9],
        }
        for r in rows
    ]


def get_project(conn: sqlite3.Connection, ini_id: str) -> dict | None:
    """Get a single project by ID."""
    row = conn.execute(
        "SELECT ini_id, ini_nr, legislatura, ini_tipo, ini_desc_tipo, "
        "ini_titulo, autor_gp, latest_fase, latest_fase_date, vote_result "
        "FROM law_projects WHERE ini_id = ?",
        (ini_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "ini_id": row[0], "ini_nr": row[1], "legislatura": row[2],
        "ini_tipo": row[3], "ini_desc_tipo": row[4], "ini_titulo": row[5],
        "autor_gp": row[6], "latest_fase": row[7], "latest_fase_date": row[8],
        "vote_result": row[9],
    }


def get_events(conn: sqlite3.Connection, ini_id: str) -> list[dict]:
    """Get lifecycle events for a project."""
    rows = conn.execute(
        "SELECT evt_id, fase, codigo_fase, data_fase, obs_fase "
        "FROM law_events WHERE ini_id = ? ORDER BY data_fase ASC",
        (ini_id,),
    ).fetchall()
    return [
        {"evt_id": r[0], "fase": r[1], "codigo_fase": r[2],
         "data_fase": r[3], "obs_fase": r[4]}
        for r in rows
    ]


def get_votes(
    conn: sqlite3.Connection,
    legislatura: str = "",
    since: str = "",
    limit: int = 50,
) -> list[dict]:
    """Query voting records."""
    where = []
    params: list = []

    if legislatura:
        where.append("legislatura = ?")
        params.append(legislatura)
    if since:
        where.append("data >= ?")
        params.append(since)

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT vot_id, ativ_id, legislatura, assunto, data, resultado, "
        f"has_party_details FROM law_votes{clause} "
        f"ORDER BY data DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {"vot_id": r[0], "ativ_id": r[1], "legislatura": r[2],
         "assunto": r[3], "data": r[4], "resultado": r[5],
         "has_party_details": bool(r[6])}
        for r in rows
    ]


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get summary statistics."""
    projects = conn.execute("SELECT COUNT(*) FROM law_projects").fetchone()[0]
    events = conn.execute("SELECT COUNT(*) FROM law_events").fetchone()[0]
    votes = conn.execute("SELECT COUNT(*) FROM law_votes").fetchone()[0]
    deputies = conn.execute("SELECT COUNT(*) FROM law_deputies").fetchone()[0]
    parties = conn.execute("SELECT COUNT(*) FROM law_parties").fetchone()[0]

    by_tipo = conn.execute(
        "SELECT ini_desc_tipo, COUNT(*) FROM law_projects "
        "GROUP BY ini_desc_tipo ORDER BY COUNT(*) DESC"
    ).fetchall()

    by_fase = conn.execute(
        "SELECT latest_fase, COUNT(*) FROM law_projects "
        "WHERE latest_fase IS NOT NULL "
        "GROUP BY latest_fase ORDER BY COUNT(*) DESC"
    ).fetchall()

    return {
        "projects": projects,
        "events": events,
        "votes": votes,
        "deputies": deputies,
        "parties": parties,
        "by_tipo": {r[0]: r[1] for r in by_tipo},
        "by_fase": {r[0]: r[1] for r in by_fase},
    }
