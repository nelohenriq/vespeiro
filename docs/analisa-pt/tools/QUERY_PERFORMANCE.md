# Query Performance Baseline

**Snapshot:** post-Tier 1 wire-up (Q1 2026)
**Platform:** Windows 10 (10.0.19045)
**Purpose:** canonical reference numbers for the hot query patterns in
the analisa-pt tools. **Re-measure after any schema/optimization
change and append a new section to the Update log below — never
overwrite the existing baseline.**

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
journal_mode = WAL              # persistent (set on the DB file once)
synchronous  = NORMAL           # persistent
temp_store   = MEMORY           # per-connection
cache_size   = -200000          # 200 MB page cache (per-connection)
mmap_size    = (disabled on Windows; 268435456 on POSIX)
```

> **Note:** the persistent PRAGMAs (`journal_mode`, `synchronous`) are
> set on the DB file by the first connection that runs them; all
> subsequent connections (even raw `sqlite3.connect()`) inherit them.
> Only `cache_size` and `temp_store` are per-connection, and `mmap_size`
> is platform-conditional.

Override `mmap_size` for benchmarking: `set ANALISA_MMAP_SIZE=268435456` (or
`0` to disable on POSIX).

---

## Hot Query Baseline (n=10, cold-cache-warm)

| Query | Result | Min | **Median** | Max | Stdev | Index used |
|-------|--------|-----|--------|-----|-----|------------|
| Q1 — per-buyer aggregate | 9,794 groups | 318 ms | **342 ms** | 413 ms | 36 ms | `idx_contratos_buyer_value` (COVERING) |
| Q2 — crossref GROUP BY adjudicatario_nif | 78,881 groups | 250 ms | **266 ms** | 348 ms | 31 ms | `idx_contratos_adjudicatario_nif` (COVERING) |
| Q3 — buyer + date filter | 0 rows (501089233 has no 2023+ contracts) | 0 ms | **< 1 ms** | 1 ms | 0 ms | `idx_contratos_buyer_date` (composite) |

EXPLAIN QUERY PLAN output:

```
Q1: SEARCH contratos USING COVERING INDEX idx_contratos_buyer_value
    (ANY(adjudicante_nif) AND precoContratual>?)
Q2: SEARCH contratos USING COVERING INDEX idx_contratos_adjudicatario_nif
    (adjudicatario_nif>?)
Q3: SEARCH contratos USING INDEX idx_contratos_buyer_date
    (adjudicante_nif=? AND dataCelebracaoContrato>?)
```

> **Run-to-run variance is ~10% of median** (stdev ~30-40 ms on a
> 300-400 ms query). Always report the median of 10 runs, not the
> single-run value, to avoid being misled by the cold-cache spike on
> the first run after a reconnect.

---

## Pre-Tier 1 Baseline (for context)

Before the Tier 1 wire-up and the add_adjudicatario_nif.py migration:

- **`transparency_scraper.py crossref`** — 3+ minutes (180 s+). Was
  scanning all 1.6 M contratos and running a Python regex on
  `adjudicatarios` per row to extract the first supplier NIF. Now
  266 ms (Q2 above) — a **~400× speedup**.
- **per-buyer aggregate** — hundreds of ms using the single-column
  `idx_c_adjudicante_nif` (no composite covering the value column).
  Now 342 ms with `idx_contratos_buyer_value` as a covering index.
- **buyer + date filter** — full scan of `idx_c_data` (single column,
  not composite with `adjudicante_nif`). Now < 1 ms with
  `idx_contratos_buyer_date`.

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
| `idx_proc_ano` | Ano | btree | year filter (populated by the loader from xlsx filename year) |
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
import sys, time, statistics; sys.path.insert(0, '.')
from utils_db import connect
c = connect('data/procurement.db')
# Triple-warm: the 200 MB cache + page faults take 5-10 s on a cold DB
for _ in range(3):
    _ = c.execute('SELECT COUNT(*) FROM contratos').fetchone()

for label, sql in [
    ('Q1 per-buyer aggregate', 'SELECT adjudicante_nif, COUNT(*), SUM(precoContratual) FROM contratos WHERE adjudicante_nif IS NOT NULL AND precoContratual > 0 GROUP BY adjudicante_nif'),
    ('Q2 crossref GROUP BY nif', 'SELECT adjudicatario_nif, COUNT(*) FROM contratos WHERE adjudicatario_nif IS NOT NULL AND adjudicatario_nif != ' + chr(34)*2 + ' GROUP BY adjudicatario_nif'),
    ('Q3 buyer+date filter', \"SELECT idcontrato, precoContratual FROM contratos WHERE adjudicante_nif = '501089233' AND dataCelebracaoContrato >= '2023-01-01'\"),
]:
    times = []
    for _ in range(10):
        t0 = time.time(); c.execute(sql).fetchall(); times.append((time.time()-t0)*1000)
    times.sort()
    print(f'{label:<30s} median {times[5]:>5.0f}ms  stdev {statistics.stdev(times):>5.0f}ms  (n=10)')
"
```

For an apples-to-apples comparison, always:
1. **Triple-warm the cache first** (200 MB cache fill + page faults
   take 5-10 s on a cold DB; the first run after reconnect is
   artificially slow)
2. Report the **median of 10 runs** (not single-run, not mean — the
   mean is biased by the cold-cache tail)
3. Capture the **EXPLAIN QUERY PLAN** alongside the timing
4. Note the **DB size, platform, and `utils_db.PRAGMAS`** in the new
   Update log section

---

## Known Bottlenecks (not yet optimized)

1. **openpyxl streaming in `transparency_scraper.py index`** — 5+ min
   for 307 K PRR entities. openpyxl is pure-Python XML parsing; a
   `polars.read_excel` (Arrow-backed xlsx2csv) or `duckdb.read_xlsx`
   swap is *estimated* to be 5-10× faster based on typical polars vs
   openpyxl benchmarks, but **not yet measured in this codebase** —
   re-measure before claiming a win.
2. **`_parse_budget` schema bug** — looks for `Ano`/`Mês` columns, but
   the actual `budget_expense_economic_*.xlsx` files use
   `Ano Sintese` / `Mês Sintese`. Result: the `budget` table has only
   35 rows despite 48+ xlsx files on disk. Fix the column lookup
   before optimizing the parser.
3. **Full-table scan + Python-level winner counting in
   `anomaly_scanner.detect_closed_ecosystem` and
   `detect_exclusive_companies`** — each detector runs ONE
   `SELECT * FROM contratos WHERE ...` (not classical N+1) but the
   Python loop that groups by buyer / builds the `Counter` does
   O(N · parse_entity_field) work per detector. A single SQL
   aggregate (`GROUP BY adjudicante_nif, first_nif`) would replace
   the loop.
4. **`entidades` table is empty** — the loader was last run before
   2026-06. The 0-row count means `procurement_cache.py`'s entity
   join queries currently fall back to per-buyer scans. Re-run
   `procurement_db.py build` to repopulate.

---

## Env var overrides

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANALISA_MMAP_SIZE` | 0 (win32) / 268435456 (POSIX) | Override SQLite mmap_size in bytes |
| `ANALISA_VESPEIRO_DB` | `<repo>/backend/data/vespeiro.db` | Path to DRE appointments DB for `revolving_door_detector.py` |

---

## Update log

Append new snapshots here. **Never overwrite the section above.**

| Date | Commit | Q1 | Q2 | Q3 | Notes |
|------|--------|----|----|----|----|
| 2026-06-12 | (Tier 1 wire-up) | 342 ms (stdev 36) | 266 ms (stdev 31) | < 1 ms | Initial baseline, n=10, Windows 10, mmap disabled |
