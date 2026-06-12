# Query Performance Baseline

**Snapshot date:** 2026-06-12 (post-Tier 1 wire-up, commit `fd9a095`)
**Platform:** Windows 10 (10.0.19045)
**Purpose:** canonical reference numbers for the hot query patterns in
the analisa-pt tools. Re-measure after any schema/optimization change
and append a new section below; never overwrite the existing baseline.

---

## Environment

| Database | Size | Tables | Rows |
|----------|------|--------|------|
| `procurement.db` | **2,109 MB** (WAL) | `contratos` | 1,607,222 |
|                 |                    | `entidades` | 0 (loader not re-run since 2026-06) |
| `transparency.db` | 301 MB (WAL)   | `prr_entities` | 306,999 |
|                  |                  | `prr_projects` | 377,971 |
|                  |                  | `prr_locations` | 379,680 |
|                  |                  | `prr_contracts` | 6,410 |
|                  |                  | `budget` | 35 (parser schema bug, see §5) |

---

## Active PRAGMAs (`utils_db.connect`)

```
journal_mode = WAL              # persistent
synchronous  = NORMAL           # persistent
temp_store   = MEMORY           # per-connection
cache_size   = -200000          # 200 MB page cache (per-connection)
mmap_size    = (disabled on Windows; 268435456 on POSIX)
```

Override `mmap_size` for benchmarking: `set ANALISA_MMAP_SIZE=268435456` (or
`0` to disable on POSIX).

---

## Hot Query Baseline (median of 3 runs, cold-cache-warm)

| Query | Result | Time | Index used |
|-------|--------|------|------------|
| Q1 — per-buyer aggregate | 9,794 groups | **374 ms** | `idx_contratos_buyer_value` (COVERING) |
| Q2 — crossref GROUP BY adjudicatario_nif | 78,881 groups | **311 ms** | `idx_contratos_adjudicatario_nif` (COVERING) |
| Q3 — buyer + date filter | 0 rows (501089233 has no 2023+ contracts) | **< 1 ms** | `idx_contratos_buyer_date` (composite) |

EXPLAIN QUERY PLAN output:

```
Q1: SEARCH contratos USING COVERING INDEX idx_contratos_buyer_value
    (ANY(adjudicante_nif) AND precoContratual>?)
Q2: SEARCH contratos USING COVERING INDEX idx_contratos_adjudicatario_nif
    (adjudicatario_nif>?)
Q3: SEARCH contratos USING INDEX idx_contratos_buyer_date
    (adjudicante_nif=? AND dataCelebracaoContrato>?)
```

---

## Pre-Tier 1 Baseline (for context)

Before commit `fd9a095` (and the add_adjudicatario_nif.py migration that
preceded it):

- **`transparency_scraper.py crossref`** — 3+ minutes. Was scanning all
  1.6 M contratos and running a Python regex on `adjudicatarios` per row
  to extract the first supplier NIF.
- **per-buyer aggregate** — hundreds of ms using the single-column
  `idx_c_adjudicante_nif` (no composite covering the value column).
- **buyer + date filter** — full scan of `idx_c_data` (single column,
  not composite with `adjudicante_nif`).

---

## Index Inventory on `contratos`

| Index | Columns | Type | Used by |
|-------|---------|------|---------|
| `idx_c_adjudicante_nif` | adjudicante_nif | btree | legacy single-column filters |
| `idx_c_data` | dataPublicacao | btree | date-range scans |
| `idx_c_link` | linkPecasProc | btree | link lookups |
| `idx_c_nAnuncio` | nAnuncio | btree | announcement lookups |
| `idx_c_preco` | precoContratual | btree | value filters |
| `idx_c_proc` | tipoprocedimento | btree | procedure-type filters |
| `idx_c_tipo` | tipoContrato | btree | contract-type filters |
| `idx_proc_ano` | Ano | btree | year filter (separate table) |
| `idx_proc_base` | precoBaseProcedimento | btree | base-price filter |
| `idx_proc_price` | precoContratual | btree | value filter (alt) |
| **`idx_contratos_adjudicatario_nif`** | adjudicatario_nif | btree, **partial `WHERE IS NOT NULL`** | **Q2 (crossref)** |
| **`idx_contratos_buyer_date`** | adjudicante_nif, dataCelebracaoContrato | composite | **Q3 (buyer + date)** |
| **`idx_contratos_buyer_value`** | adjudicante_nif, precoContratual | composite | **Q1 (per-buyer aggregate)** |

**Bold = added in Tier 1.**

---

## How to re-measure

```bash
cd vespeiro/docs/analisa-pt/tools
python -c "
import sys, time; sys.path.insert(0, '.')
from utils_db import connect
c = connect('data/procurement.db')
_ = c.execute('SELECT COUNT(*) FROM contratos').fetchone()  # warm

for label, sql in [
    ('Q1 per-buyer aggregate', 'SELECT adjudicante_nif, COUNT(*), SUM(precoContratual) FROM contratos WHERE adjudicante_nif IS NOT NULL AND precoContratual > 0 GROUP BY adjudicante_nif'),
    ('Q2 crossref GROUP BY nif', 'SELECT adjudicatario_nif, COUNT(*) FROM contratos WHERE adjudicatario_nif IS NOT NULL AND adjudicatario_nif != ' + chr(34)*2 + ' GROUP BY adjudicatario_nif'),
    ('Q3 buyer+date filter', \"SELECT idcontrato, precoContratual FROM contratos WHERE adjudicante_nif = '501089233' AND dataCelebracaoContrato >= '2023-01-01'\"),
]:
    times = []
    for _ in range(3):
        t0 = time.time(); c.execute(sql).fetchall(); times.append(time.time()-t0)
    times.sort()
    print(f'{label:<30s} median {times[1]*1000:>6.0f} ms')
"
```

For an apples-to-apples comparison, always:
1. Run the command twice (first run warms the 200 MB cache)
2. Report the **median** of 3 runs (not the mean)
3. Capture the EXPLAIN QUERY PLAN alongside the timing
4. Note the DB size, platform, and `utils_db.PRAGMAS` in the new section

---

## Known Bottlenecks (not yet optimized)

1. **openpyxl streaming in `transparency_scraper.py index`** — 5+ min
   for 307 K PRR entities. The streaming path (`_stream_prr_entities`)
   helps, but openpyxl itself is the bottleneck. DuckDB's
   `read_xlsx` or a `polars.read_excel` swap would be a 5-10× win.
2. **`_parse_budget` schema bug** — looks for `Ano`/`Mês` columns, but
   the actual `budget_expense_economic_*.xlsx` files use
   `Ano Sintese` / `Mês Sintese`. Result: the `budget` table has only
   35 rows despite 48+ xlsx files on disk. Fix the column lookup
   before optimizing the parser.
3. **N+1 in `anomaly_scanner.detect_closed_ecosystem` and
   `detect_exclusive_companies`** — the Python-level winner-counting
   loop is O(N · parse) per buyer. A single SQL aggregate
   (`GROUP BY adjudicante_nif, first_nif`) would replace the loop.
4. **`entidades` table is empty** — the loader was last run before
   2026-06. The 0-row count means `procurement_cache.py`'s entity
   join queries currently fall back to the per-buyer scans.

---

## Env var overrides

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANALISA_MMAP_SIZE` | 0 (win32) / 268435456 (POSIX) | Override SQLite mmap_size in bytes |
| `ANALISA_VESPEIRO_DB` | `<repo>/backend/data/vespeiro.db` | Path to DRE appointments DB for `revolving_door_detector.py` |
