# Postgres Migration Plan — Consolidating 5 SQLite Databases into One PostgreSQL

**Date:** 2026-06-07  
**Context:** SQLite timeout errors on large analytic queries (supplier NIF scan across 244K contracts), bottleneck from single-writer lock, and the need for connection pooling across 20+ detection tools.

---

## 1. Current State

### 1.1 Databases

| # | Database | Location | Rows | Size | Used By | Type |
|---|----------|----------|------|------|---------|------|
| 1 | `vespeiro.db` | `backend/data/` | ~10K | ~10MB | Vespeiro backend (SQLAlchemy async) | News articles, DRE appointments, analysis results |
| 2 | `procurement.db` | `docs/analisa-pt/tools/data/` | 244,897 contracts + 111,495 entities | ~200MB | All detection tools (raw sqlite3) | BASE.gov.pt procurement |
| 3 | `transparency.db` | `docs/analisa-pt/tools/data/` | ~50K (7 tables) | ~50MB | PRR analysis tools (raw sqlite3) | PRR + budget data from dados.gov.pt |
| 4 | `modificacoes_index.db` | `docs/analisa-pt/tools/data/` | Variable | ~10MB | Contract modification analysis | DRE aditivos |
| 5 | `anuncios_index.db` | `docs/analisa-pt/tools/data/` | Variable | ~20MB | Price gap analysis | Anúncios from BASE |
| 6 | `ted_notices.db` | `docs/analisa-pt/tools/data/` | Variable | ~5MB | TED cross-reference | EU tenders |

Plus smaller indices: `bep_index.db`, `dre_index.db`, `law_index.db`

### 1.2 Schemas (Consolidated)

**Vespeiro (SQLAlchemy ORM):**
- `sources` — news sources (id, name, category, language, is_active)
- `articles` — news articles (id, source_id, url, title, content_text, summary, published_at)
- `people` — DRE extracted persons (id, name, normalized_name)
- `appointments` — DRE appointments (id, person_id, organization, role, published_at)

**Procurement (raw SQLite):**
- `contratos` — 244K procurement contracts (41 columns incl. nAnuncio, adjudicante_nif, precoContratual, precoBaseProcedimento, etc.)
- `entidades` — 111K entities (nifEntidade, desigEntidade, totals as buyer/supplier)

**PRR/Transparency (raw SQLite):**
- `prr_contracts` — PRR contracts with cd_base_gov, dt_assinatura, montante
- `prr_entity_contracts` — entity-contract links (cd_entidade, cd_contrato, papel, valor)
- `prr_entities` — PRR entities with NIF, atividade_economica
- `prr_projects` — PRR projects with valor_aprovado, valor_pago
- `prr_locations` — geographic distribution by concelho
- `prr_milestones` — PRR milestones
- `budget` — budget execution data

**Modifications (raw SQLite):**
- `modificacoes` — contract modifications (idcontrato, fundamento, preco_alterado)

---

## 2. Target Architecture

### 2.1 Design Decision: Single Database, Schema-Partitioned

**Recommendation:** ONE Postgres database with schema-based partitioning:

```
postgresql://{user}@{host}:5432/vespeiro
  ├── public       — Vespeiro news/DRE tables (with RLS policies)
  ├── procurement  — BASE.gov.pt contracts + entities + modifications + anúncios
  ├── transparency — PRR + budget data  
  └── analysis     — Pre-computed analysis results
```

**Rationale:**
- Cross-schema queries via `schema.table` are trivial in Postgres (e.g., `SELECT * FROM procurement.contratos JOIN transparency.prr_contracts ON ...`)
- Schemas isolate domains while allowing cross-referencing
- Single connection pool, single backup, single set of credentials
- Supabase's auto-generated REST API can expose all schemas
- No need for `dblink` or application-level joins

### 2.2 Connection Pooling Strategy

Replace raw `sqlite3.connect()` with a shared async connection pool:

```python
# shared pool in backend/src/db/session.py
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@host:5432/vespeiro",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
```

All analisa.pt tools migrate from `sqlite3.connect()` to `async_session`:

```python
# Before: conn = sqlite3.connect("data/procurement.db")
# After:  async with get_session() as session:
#             result = await session.execute(text("SELECT ..."))
```

### 2.3 Performance Gains Expected

| Problem | SQLite Behavior | Postgres Fix |
|---------|----------------|--------------|
| Single-writer lock | Serializes all writes | MVCC — concurrent reads/writes |
| Supplier NIF scan (244K rows) | Loads ALL rows into Python memory | `LIKE` + GIN trigram index on `adjudicatarios` |
| N+1 perf in geographic overlap | Per-entity query inside loop | `JOIN` across schemas with `IN (...)` |
| No connection pooling | Each tool opens/closes its own conn | `async_session` with 10-pool |
| Text similarity O(n*m) | Python-level Jaccard | `pg_trgm` extension + `similarity()` function |

---

## 3. Consolidated Postgres Schema

### 3.1 Schema: `public` — Vespeiro Core (migrate backend/models.py)

```sql
CREATE TABLE public.sources (
    id          VARCHAR(50) PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    category    VARCHAR(50) NOT NULL,
    language    VARCHAR(5) NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE public.articles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    VARCHAR(50) NOT NULL REFERENCES public.sources(id),
    external_id  VARCHAR(255),
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    content_text TEXT,
    summary      TEXT,
    author       VARCHAR(255),
    published_at TIMESTAMPTZ,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    language     VARCHAR(5)
);
CREATE INDEX idx_articles_source ON public.articles(source_id);
CREATE INDEX idx_articles_published ON public.articles(published_at DESC);

CREATE TABLE public.people (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    source_article_id UUID REFERENCES public.articles(id)
);
CREATE INDEX idx_people_normalized ON public.people(normalized_name);

CREATE TABLE public.appointments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id        UUID NOT NULL REFERENCES public.people(id),
    organization     VARCHAR(255) NOT NULL,
    role             VARCHAR(255),
    appointing_body  VARCHAR(255),
    appointment_type VARCHAR(50),
    article_id       UUID REFERENCES public.articles(id),
    published_at     TIMESTAMPTZ,
    extracted_at     TIMESTAMPTZ DEFAULT NOW(),
    confidence       REAL DEFAULT 0.7
);
CREATE INDEX idx_appointments_org ON public.appointments(organization);
CREATE INDEX idx_appointments_person ON public.appointments(person_id);
```

### 3.2 Schema: `procurement` — BASE.gov.pt

```sql
CREATE TABLE procurement.contratos (
    idcontrato                  INTEGER PRIMARY KEY,
    n_anuncio                   TEXT,        -- nAnuncio
    tipo_anuncio                TEXT,        -- tipoAnuncio
    id_incm                     TEXT,        -- idINCM
    tipo_contrato               TEXT,        -- tipoContrato
    id_procedimento             TEXT,        -- idprocedimento
    tipo_procedimento           TEXT,        -- tipoprocedimento
    objecto_contrato            TEXT,        -- objectoContrato
    desc_contrato               TEXT,        -- descContrato
    adjudicante                 TEXT,        -- raw "NIF - Name"
    adjudicante_nif             TEXT,        -- extracted NIF
    adjudicante_nome            TEXT,        -- extracted name
    adjudicatarios              TEXT,        -- "NIF - Name; NIF2 - Name2"
    data_publicacao             DATE,
    data_celebracao             DATE,        -- dataCelebracaoContrato
    preco_contratual            NUMERIC(14,2), -- precoContratual
    cpv                         TEXT,        -- CPV
    prazo_execucao              INTEGER,
    local_execucao              TEXT,        -- LocalExecucao
    fundamentacao               TEXT,
    procedimento_centralizado   TEXT,
    num_acordo_quadro           TEXT,
    descr_acordo_quadro         TEXT,
    preco_base_procedimento     NUMERIC(14,2), -- precoBaseProcedimento
    data_decisao_adjudicacao    DATE,
    data_fecho_contrato         DATE,
    preco_total_efetivo         NUMERIC(14,2), -- PrecoTotalEfetivo
    regime                      TEXT,
    justif_n_redu_escr_contrato TEXT,
    tipo_fim_contrato           TEXT,
    crit_materiais              TEXT,
    concorrentes                TEXT,
    link_pecas_proc             TEXT,        -- linkPecasProc
    observacoes                 TEXT,
    contrat_ecologico           TEXT,
    fundament_ajuste_direto     TEXT,
    ano                         SMALLINT,
    adjudicatario_pmes          TEXT,
    nuts                        TEXT,        -- NUTs
    lotes                       TEXT,
    tipo_criterio_adjudicacao   TEXT        -- TipoCriterioAdjudicacao
);

-- Normalised supplier join table (replaces regex extraction from adjudicatarios!)
CREATE TABLE procurement.contract_suppliers (
    id          BIGSERIAL PRIMARY KEY,
    idcontrato  INTEGER NOT NULL REFERENCES procurement.contratos(idcontrato),
    nif         VARCHAR(9) NOT NULL
);
CREATE INDEX idx_cs_contrato ON procurement.contract_suppliers(idcontrato);
CREATE INDEX idx_cs_nif ON procurement.contract_suppliers(nif);

CREATE TABLE procurement.entidades (
    nif_entidade            VARCHAR(9) PRIMARY KEY,
    designacao_entidade     TEXT,
    num_contratos           INTEGER DEFAULT 0,
    tot_adjudicatario       INTEGER DEFAULT 0,
    tot_valor_contrat_ini   NUMERIC(14,2),
    tot_adjudicante         INTEGER DEFAULT 0,
    tot_adjudicante_valor   NUMERIC(14,2),
    desc_pais               TEXT,
    alias_pais              VARCHAR(5)
);

-- Indexes for performance
CREATE INDEX idx_contratos_n_anuncio ON procurement.contratos(n_anuncio);
CREATE INDEX idx_contratos_adjudicante_nif ON procurement.contratos(adjudicante_nif);
CREATE INDEX idx_contratos_tipo ON procurement.contratos(tipo_contrato);
CREATE INDEX idx_contratos_preco ON procurement.contratos(preco_contratual DESC);
CREATE INDEX idx_contratos_proc ON procurement.contratos(tipo_procedimento);
CREATE INDEX idx_contratos_data_celebracao ON procurement.contratos(data_celebracao);
CREATE INDEX idx_contratos_cpv ON procurement.contratos(cpv);
CREATE INDEX idx_contratos_objecto_trgm ON procurement.contratos
    USING gin (objecto_contrato gin_trgm_ops);

-- GIN trigram index for fast supplier NIF search in adjudicatarios text
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_contratos_adjudicatarios_trgm ON procurement.contratos
    USING gin (adjudicatarios gin_trgm_ops);
```

### 3.3 Schema: `transparency` — PRR + Budget Data

```sql
CREATE TABLE transparency.prr_contracts (
    id             SERIAL PRIMARY KEY,
    cd_contrato    TEXT UNIQUE NOT NULL,
    dt_referencia  DATE,
    ds_contrato    TEXT,
    sumario        TEXT,
    cd_base_gov    TEXT,           -- KEY LINK to procurement.contratos.n_anuncio
    dt_assinatura  DATE,
    montante       NUMERIC(14,2),
    cd_projeto     TEXT,
    ds_projeto     TEXT,
    perc_projeto   REAL
);
CREATE INDEX idx_prr_c_base ON transparency.prr_contracts(cd_base_gov);
CREATE INDEX idx_prr_c_projeto ON transparency.prr_contracts(cd_projeto);
CREATE INDEX idx_prr_c_assinatura ON transparency.prr_contracts(dt_assinatura);

CREATE TABLE transparency.prr_entity_contracts (
    id             SERIAL PRIMARY KEY,
    cd_contrato    TEXT REFERENCES transparency.prr_contracts(cd_contrato),
    dt_referencia  DATE,
    ds_contrato    TEXT,
    cd_entidade    TEXT,
    ds_entidade    TEXT,
    ds_papel       TEXT,           -- Comprador / Adjudicatário
    valor_contrato NUMERIC(14,2),
    UNIQUE(cd_contrato, cd_entidade, ds_papel)
);
CREATE INDEX idx_prr_ec_entidade ON transparency.prr_entity_contracts(cd_entidade);
CREATE INDEX idx_prr_ec_contrato ON transparency.prr_entity_contracts(cd_contrato);

CREATE TABLE transparency.prr_entities (
    id                  SERIAL PRIMARY KEY,
    cd_entidade         TEXT UNIQUE NOT NULL,
    dt_referencia       DATE,
    nif                 VARCHAR(9),
    ds_entidade         TEXT,
    papel               TEXT,
    atividade_economica TEXT,
    localizacao         TEXT,
    valor_contratado    NUMERIC(14,2),
    valor_pago          NUMERIC(14,2),
    cd_projeto          TEXT
);
CREATE INDEX idx_prr_e_nif ON transparency.prr_entities(nif);
CREATE INDEX idx_prr_e_papel ON transparency.prr_entities(papel);

CREATE TABLE transparency.prr_projects (
    id                      SERIAL PRIMARY KEY,
    cd_projeto              TEXT UNIQUE NOT NULL,
    dt_referencia           DATE,
    ds_projeto              TEXT,
    sumario                 TEXT,
    valor_aprovado          NUMERIC(14,2),
    valor_pago              NUMERIC(14,2),
    subvencoes              NUMERIC(14,2),
    emprestimos             NUMERIC(14,2),
    nota_final              REAL,
    cd_investimento         TEXT,
    dt_inicio               DATE,
    dt_prevista_conclusao   DATE,
    dt_efetiva_conclusao    DATE
);

CREATE TABLE transparency.prr_locations (
    id                  SERIAL PRIMARY KEY,
    cd_projeto          TEXT REFERENCES transparency.prr_projects(cd_projeto),
    dt_referencia       DATE,
    cd_nutsii           VARCHAR(5),
    ds_nutsii           TEXT,
    cd_nutsiii          VARCHAR(5),
    ds_nutsiii          TEXT,
    cd_distrito         VARCHAR(5),
    ds_distrito         TEXT,
    cd_concelho         VARCHAR(5),
    ds_concelho         TEXT,
    perc_valor_aprovado REAL,
    perc_valor_pago     REAL,
    UNIQUE(cd_projeto, cd_concelho)
);
CREATE INDEX idx_prr_l_concelho ON transparency.prr_locations(ds_concelho);

CREATE TABLE transparency.prr_milestones (
    id                      SERIAL PRIMARY KEY,
    componente              TEXT,
    data_ref                DATE,
    sequencial              INTEGER,
    codigo_reforma          TEXT,
    designacao_reforma      TEXT,
    tipo                    TEXT,
    designacao              TEXT,
    indicador_qualitativo   TEXT,
    indicador_quantitativo  TEXT,
    referencia              TEXT,
    objetivo                TEXT,
    trimestre               TEXT,
    ano                     SMALLINT,
    fonte_dados             TEXT,
    responsabilidade        TEXT,
    descricao               TEXT,
    pressupostos_riscos     TEXT,
    mecanismo_verificacao   TEXT,
    indicadores_desembolso  TEXT,
    natureza_medida         TEXT,
    data_conclusao          DATE,
    valor_atingido          REAL
);

CREATE TABLE transparency.budget (
    id                  SERIAL PRIMARY KEY,
    dataset_key         TEXT,
    ano                 SMALLINT,
    mes                 SMALLINT,
    nivel_orcamental    TEXT,
    descricao           TEXT,
    valor_previsto      NUMERIC(14,2),
    valor_realizado     NUMERIC(14,2),
    percentagem         REAL,
    UNIQUE(dataset_key, ano, mes, nivel_orcamental, descricao)
);
CREATE INDEX idx_budget_ano ON transparency.budget(ano);
```

### 3.4 Schema: `procurement` — Supporting Tables (Modifications, Anúncios)

```sql
-- Contract modifications (from modificacoes_index.db)
CREATE TABLE procurement.modificacoes (
    id                  SERIAL PRIMARY KEY,
    idcontrato          INTEGER NOT NULL REFERENCES procurement.contratos(idcontrato),
    fundamento          TEXT,
    tipo_acto           TEXT,
    data_modificacao    DATE,
    preco_alterado      NUMERIC(14,2) DEFAULT 0,
    prazo_execucao      INTEGER,
    ano                 SMALLINT
);
CREATE INDEX idx_modificacoes_contrato ON procurement.modificacoes(idcontrato);

-- Anúncios (from anuncios_index.db) — used for price gap analysis
CREATE TABLE procurement.anuncios (
    id                  SERIAL PRIMARY KEY,
    n_anuncio           TEXT NOT NULL,
    id_incm             TEXT,
    data_publicacao     DATE,
    nif_entidade        VARCHAR(9),
    designacao_entidade TEXT,
    tipos_contrato      TEXT,
    preco_base          NUMERIC(14,2),
    tipo_acto           TEXT,
    descricao           TEXT,
    cpvs                TEXT
);
CREATE INDEX idx_anuncios_n_anuncio ON procurement.anuncios(n_anuncio);
CREATE INDEX idx_anuncios_nif ON procurement.anuncios(nif_entidade);
```

### 3.5 Schema: `analysis` — Pre-computed Results

> **Note:** These tables are **populated by the detection tools** after each scan (INSERT from Python), not by the SQLite→Postgres data migration. The migration script only creates the table schemas.

```sql
-- Populated by tools (INSERT from Python after each scan), not migrated from SQLite.
-- The migration script only creates the table schema; data is written by:
--   anomaly_scanner.py → analysis.anomaly_scores
--   prr_procurement_crossref.py → analysis.dual_role_entities
--   municipality_risk_report.py → analysis.municipality_risk
CREATE TABLE analysis.anomaly_scores (
    id                  SERIAL PRIMARY KEY,
    nif                 VARCHAR(9) NOT NULL,
    entity_name         TEXT,
    risk_score          REAL,
    signals             TEXT[],         -- Postgres array of signal names
    total_contracts     INTEGER,
    total_value         NUMERIC(14,2),
    inflated_count      INTEGER,
    overrun             NUMERIC(14,2),
    scanned_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_anomaly_nif ON analysis.anomaly_scores(nif);
CREATE INDEX idx_anomaly_score ON analysis.anomaly_scores(risk_score DESC);

CREATE TABLE analysis.dual_role_entities (
    id                  SERIAL PRIMARY KEY,
    nif                 VARCHAR(9) NOT NULL,
    entity_name         TEXT,
    risk_score          REAL,
    role_type           TEXT,           -- triple_role / prr_beneficiary_buyer / prr_beneficiary_supplier
    prr_value           NUMERIC(14,2),
    prr_paid            NUMERIC(14,2),
    base_buyer_contracts INTEGER DEFAULT 0,
    base_supplier_contracts INTEGER DEFAULT 0,
    cdbg_matches        INTEGER DEFAULT 0,
    text_similarity_max REAL DEFAULT 0,
    scanned_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE analysis.municipality_risk (
    id                  SERIAL PRIMARY KEY,
    municipality_name   TEXT NOT NULL,
    risk_score          REAL,
    concentration_pct   REAL,
    inflation_rate      REAL,
    total_overrun       NUMERIC(14,2),
    supplier_count      INTEGER,
    scanned_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Materialized view: PRR ↔ BASE contract links via cd_base_gov
CREATE MATERIALIZED VIEW analysis.prr_base_contract_links AS
SELECT
    pc.cd_contrato            AS prr_contrato,
    pc.ds_contrato            AS prr_descricao,
    pc.montante               AS prr_montante,
    pc.dt_assinatura          AS prr_data,
    pc.cd_base_gov            AS codigo_ligacao,
    c.idcontrato              AS base_idcontrato,
    c.preco_contratual        AS base_preco,
    c.adjudicante_nif         AS base_adjudicante_nif,
    c.adjudicante_nome        AS base_adjudicante_nome,
    c.preco_base_procedimento AS base_preco_referencia,
    CASE WHEN c.preco_base_procedimento > 0 AND c.preco_contratual > c.preco_base_procedimento
         THEN c.preco_contratual - c.preco_base_procedimento ELSE 0 END AS overrun
FROM transparency.prr_contracts pc
JOIN procurement.contratos c ON c.n_anuncio = pc.cd_base_gov
WHERE pc.cd_base_gov != '';

CREATE UNIQUE INDEX idx_mv_prr_base ON analysis.prr_base_contract_links(prr_contrato, base_idcontrato);
```

### 3.5 Schema: `supabase` — RLS Policies

The existing RLS policies from `backend/alembic/versions/2026_05_28_rls_public_api.sql` apply to the `public` schema. The `procurement`, `transparency`, and `analysis` schemas are **internal only** (accessed via service_role key, not anon).

```sql
-- Internal schemas are NOT exposed to anon role
REVOKE ALL ON SCHEMA procurement FROM anon;
REVOKE ALL ON SCHEMA transparency FROM anon;
REVOKE ALL ON SCHEMA analysis FROM anon;
```

---

## 4. Migration Strategy

### 4.1 Migration Tool: Alembic

The Vespeiro backend already uses Alembic. Extend it to manage all schemas:

```python
# backend/alembic/env.py
from src.db.session import Base

# Import ALL models (Vespeiro + after we add procurement/transparency models)
target_metadata = Base.metadata
```

For the procurement and transparency schemas, we have two options:

**Option A: SQLAlchemy ORM models** — Define ORM models for procurement & transparency tables, then use Alembic auto-generation. More maintainable long-term.

**Option B: Raw SQL migrations** — Write raw SQL `CREATE TABLE` statements (like the existing RLS migration). Faster to implement, no ORM overhead for analytic tools.

**Recommendation: Mix A + B.** Create ORM models for:
- `public.*` (already done)
- `analysis.*` (insert/query frequently from tools)
- `procurement.entidades` (queried by name/NIF lookup)

Use raw SQL for:
- `procurement.contratos` (41 columns, INSERT-only)
- `transparency.*` (INSERT-only, cargo-culted from SQLite)

### 4.2 Migration Steps (Ordered)

| Step | Action | Duration | Risk |
|------|--------|----------|------|
| 1 | Provision Postgres (Supabase or local Docker) | 1h | Low |
| 2 | Run schema creation migrations (all schemas) | 10min | Low |
| 3 | Migrate `vespeiro.db` data (small, easiest) | 5min | Low |
| 4 | Migrate `procurement.db` → `procurement` schema | 30min | Medium |
| 5 | Migrate `transparency.db` → `transparency` schema | 15min | Medium |
| 6 | Build `contract_suppliers` join table from adjudicatarios | 20min | Medium |
| 7 | Migrate smaller DBs (modifications, anúncios, etc.) | 15min | Low |
| 8 | Create materialized views and indexes | 10min | Low |
| 9 | Run first analysis scan in Postgres | 30min | High |
| 10 | Update tools to use Postgres connection | 2-4h | High |
| 11 | Remove old SQLite files after validation | 5min | Low |

### 4.3 Data Migration Script (Python)

Create a migration script at `backend/scripts/migrate_to_postgres.py`:

```python
"""Migrate all SQLite data to PostgreSQL.

Usage:
    python scripts/migrate_to_postgres.py                # Full migration
    python scripts/migrate_to_postgres.py --dry-run       # Preview
    python scripts/migrate_to_postgres.py --only procurement  # Single schema
"""

import sqlite3
import asyncpg
from pathlib import Path

# SQLite sources
SQLITE_DBS = {
    "vespeiro": Path("backend/data/vespeiro.db"),
    "procurement": Path("docs/analisa-pt/tools/data/procurement.db"),
    "transparency": Path("docs/analisa-pt/tools/data/transparency.db"),
}

# Mapping: (sqlite_table, pg_schema, pg_table, batch_size)
TABLE_MAP = [
    ("sources",           "public",        "sources",           500),
    ("articles",          "public",        "articles",          500),
    ("people",            "public",        "people",            500),
    ("appointments",      "public",        "appointments",      500),
    ("contratos",         "procurement",   "contratos",         1000),
    ("entidades",         "procurement",   "entidades",         1000),
    ("prr_contracts",     "transparency",  "prr_contracts",     500),
    ("prr_entity_contracts", "transparency", "prr_entity_contracts", 500),
    ("prr_entities",      "transparency",  "prr_entities",      500),
    ("prr_projects",      "transparency",  "prr_projects",      500),
    ("prr_locations",     "transparency",  "prr_locations",     500),
    ("prr_milestones",    "transparency",  "prr_milestones",    500),
    ("budget",            "transparency",  "budget",            500),
]

async def migrate_table(pg_pool, sqlite_path, sqlite_table, pg_schema, pg_table, batch_size):
    """Copy a table from SQLite to PostgreSQL in batches."""
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    # Get column names from SQLite
    cursor = sqlite_conn.execute(f"SELECT * FROM {sqlite_table} LIMIT 0")
    columns = [desc[0] for desc in cursor.description]

    # Count rows
    count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {sqlite_table}").fetchone()[0]
    print(f"  Migrating {sqlite_table} ({count:,} rows) → {pg_schema}.{pg_table}")

    # Read + insert in batches
    offset = 0
    while offset < count:
        rows = sqlite_conn.execute(
            f"SELECT * FROM {sqlite_table} LIMIT {batch_size} OFFSET {offset}"
        ).fetchall()

        # Convert to list of dicts with proper types
        batch = []
        for row in rows:
            record = dict(row)
            # Convert None to proper Python None
            batch.append(record)

        # Insert into Postgres (batched executemany)
        col_names = ", ".join(columns)
        placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
        batch_values = [[record[col] for col in columns] for record in batch]
        async with pg_pool.acquire() as conn:
            await conn.executemany(
                f"INSERT INTO {pg_schema}.{pg_table} ({col_names}) "
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                batch_values
            )

        offset += batch_size
        if offset % (batch_size * 10) == 0:
            print(f"    Progress: {min(offset, count):,}/{count:,}")

    sqlite_conn.close()
```

### 4.4 Building `contract_suppliers` Join Table

This is the **key performance improvement** — replacing the expensive regex scan with a proper join table:

```python
# After migrating contratos, extract NIFs from adjudicatarios
async def build_contract_suppliers(pg_pool):
    nif_pattern = re.compile(r"\b(\d{9})\b")
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT idcontrato, adjudicatarios FROM procurement.contratos "
            "WHERE adjudicatarios IS NOT NULL"
        )
        batch = []
        for row in rows:
            nifs = set(nif_pattern.findall(row["adjudicatarios"] or ""))
            for nif in nifs:
                batch.append((row["idcontrato"], nif))
        await conn.executemany(
            "INSERT INTO procurement.contract_suppliers (idcontrato, nif) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
            batch
        )
```

Similarly, extraction of supplier names from `"NIF - Name"` format happens here too, but the `contract_suppliers` table stores only the NIF for simplicity. Names are available via `entidades.designacao_entidade`.

After this, the expensive supplier scan becomes a simple index lookup:

```python
# BEFORE: regex scan all 244K rows in Python
adjudicatarios_rows = conn.execute("SELECT adjudicatarios FROM contratos").fetchall()
# AFTER: indexed join table
supplier_nifs = await conn.fetch(
    "SELECT nif FROM procurement.contract_suppliers WHERE nif = ANY($1)",
    prr_nifs
)
```

---

## 5. Tool Migration Guide

### 5.1 Migration Pattern for Each Tool

Every raw `sqlite3` tool follows the same migration pattern:

```python
# BEFORE (raw sqlite3):
import sqlite3
conn = sqlite3.connect("data/procurement.db")
rows = conn.execute("SELECT ...").fetchall()
conn.close()

# AFTER (asyncpg with shared pool):
import asyncpg
from src.db.session import get_pool  # shared connection pool

async def query():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ...")
    return rows
```

### 5.2 Migration Priority by Tool

| Tool | Priority | Effort | Reason |
|------|----------|--------|--------|
| `prr_base_cdgov_detector.py` | **High** | 2h | Text similarity + cdgov matching are the most DB-intensive new tools |
| `prr_procurement_crossref.py` | **High** | 2h | Supplier NIF scan across 244K contracts — biggest bottleneck |
| `transparency_scraper.py` | **High** | 3h | Downloads 12 XLSX files, inserts into DB |
| `anomaly_scanner.py` | **Med** | 1h | Heavy read workload |
| `entity_network.py` | **Med** | 1h | Self-referencing detection |
| `run_corruption_scan.py` | **Med** | 2h | Pipeline orchestrator — needs connection pool management |
| `municipality_risk_report.py` | **Med** | 1h | Aggregation-heavy |
| `price_gap_analysis.py` | **Low** | 1h | Cross-DB queries (anúncios + contratos) |
| `bid_pattern_analyzer.py` | **Low** | 1h | Pattern analysis |
| `temporal_clustering.py` | **Low** | 1h | Date-based grouping |
| `supplier_cross_profiler.py` | **Low** | 0.5h | Simple aggregation |
| Own reports/dashboards | **Low** | 0.5h each | JSON-based, DB-independent |

### 5.3 Configuration-driven Connection

All tools should use a shared connection string, configurable per environment:

```python
# backend/src/db/session.py (extended)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://vespeiro:password@localhost:5432/vespeiro"
)

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=5,
            max_size=20,
        )
    return _pool
```

Analisa.pt tools import from `backend.src.db.session`:

```python
# In any analisa.pt tool
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from src.db.session import get_pool
```

---

## 6. Migration Timeline

### Phase 1: Setup (Day 1)
- [ ] Provision Postgres (Supabase or local Docker)
- [ ] Configure `DATABASE_URL` in `.env`
- [ ] Extend Alembic to manage all schemas
- [ ] Write schema creation migrations
- [ ] Test: `alembic upgrade head` succeeds

### Phase 2: Data Migration (Day 2-3)
- [ ] Write `migrate_to_postgres.py` script
- [ ] Run migration for `public.*` (vespeiro.db — quick, ~5min)
- [ ] Run migration for `procurement.*` (244K rows — ~30min)
- [ ] Run migration for `transparency.*` (7 tables — ~15min)
- [ ] Build `contract_suppliers` join table (~20min)
- [ ] Verify row counts match between SQLite and Postgres

### Phase 3: Tool Migration (Day 3-5)
- [ ] Migrate high-priority tools to asyncpg:
  - `prr_base_cdgov_detector.py`
  - `prr_procurement_crossref.py`
  - `transparency_scraper.py`
- [ ] Migrate medium-priority tools:
  - `anomaly_scanner.py`
  - `entity_network.py`
  - `run_corruption_scan.py`
  - `municipality_risk_report.py`
- [ ] Migrate low-priority tools

### Phase 4: Validation (Day 5-6)
- [ ] Run full analysis pipeline against Postgres
- [ ] Compare results against last SQLite run
- [ ] Benchmark supplier NIF scan (was ~5min, should be <1s)
- [ ] Benchmark text similarity (was O(n*m), should benefit from pg_trgm)
- [ ] Check for any schema mismatches

### Phase 5: Cutover (Day 6)
- [ ] Switch default `DATABASE_URL` to Postgres
- [ ] Keep SQLite files as read-only backup
- [ ] Update documentation
- [ ] Remove raw `sqlite3.connect()` calls from migrated tools

---

## 7. Key Benefits After Migration

| Metric | Before (SQLite) | After (Postgres) | Improvement |
|--------|----------------|-------------------|-------------|
| Supplier NIF scan over 244K rows | ~5min (Python regex + full table load) | ~0.5s (GIN trigram index + contract_suppliers table) | **600×** |
| Connection overhead per tool | 100-500ms (open/close SQLite) | ~5ms (pooled async connection) | **20-100×** |
| Concurrent tool execution | Impossible (single-writer lock) | 20 concurrent connections | **20×** |
| Data export (full) | ~30s (DB locked during export) | Near-instant (MVCC snapshot) | **60×** |
| Text similarity scan (10K × 20K) | ~2min (Python Jaccard, O(n*m)) | ~30s (pg_trgm, index-assisted) | **4×** |
| Cross-schema queries | Not possible (separate DBs) | One SQL JOIN across schemas | **New capability** |
| Backup | File copy (requires exclusive lock) | `pg_dump` (online, consistent) | **Continuous ops** |

---

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| PostgreSQL column type mismatches (SQLite TEXT vs Postgres DATE) | Migration failures | Test with schema validation first |
| Tool-specific SQL constructs (SQLite `LIKE` vs Postgres) | Runtime errors | `REPLACE()` Postgres-compatible SQL patterns |
| Supabase connection limits (free tier: 15 connections) | Pool exhaustion | Use `pool_size=5, max_overflow=5` |
| Python async migration (sync tools → async) | Refactoring effort | Keep sync `sqlite3` fallback, add async path |
| Data freshness (XLSX → Postgres vs XLSX → SQLite) | Stale data | Automate refresh in pipeline |

---

## 9. Rollback Plan

If Postgres migration causes issues:

1. Set `DATABASE_URL=sqlite+aiosqlite:///data/vespeiro.db` in `.env`
2. Tools keep their `sqlite3.connect()` fallback for 3 months
3. SQLite files remain untouched during migration (copy-mode, not move-mode)
4. All migration scripts have `--dry-run` flag for preview

---

*This is a design document. Review and approve before implementation.*
