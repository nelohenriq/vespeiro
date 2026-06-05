# Analisa-PT Tools — Status Tracker

## ✅ Completed

### BEP Scraper (`bep_scraper.py`)
- [x] Scrape job listings from bep.gov.pt via curl (bypasses TLS fingerprinting)
- [x] Parse ASP.NET detail pages with BeautifulSoup
- [x] CLI: `fetch`, `range`, `list`, `search`, `collect`
- [x] MCP server mode (JSON-RPC over stdio)
- [x] Date range + entity filtering
- [x] Binary search for latest listing ID

### BEP Entity Index (`bep_db.py`)
- [x] SQLite schema: `bep_entities` + `bep_listings` tables
- [x] Deterministic entity IDs via SHA256
- [x] Upsert entities + listings with dedup
- [x] Entity search, listing query
- [x] `nif` column with schema migration for existing DBs
- [x] `set_nif()`, `get_entities_without_nif()`, `search_by_nif()`
- [x] CLI: `entities`, `listings`, `set-nif`, `nifs`, `nif`
- [x] WAL mode + busy_timeout for reliability

### NIF Enrichment (`merge_nifs.py`)
- [x] Download contratos2025.xlsx from dados.gov.pt (IMPIC procurement data)
- [x] Extract NIF + entity name from `adjudicante` column (format: "NIF - Entity Name")
- [x] Fuzzy name matching with SequenceMatcher + normalized names
- [x] Merge NIFs into bep_entities table
- [x] Both test entities matched with correct NIFs

### Dead Code Cleanup
- [x] Removed `_fetch_url`, `_extract_nif_from_html`, `search_nif_on_web` from bep_db.py
- [x] Removed `enrich-nifs` CLI command from bep_scraper.py (depended on removed code)
- [x] Zero orphaned references confirmed

### Parliament Research (READ-ONLY)
- [x] Analyzed vespeiro's ParliamentSpider — downloads DAR debate transcripts (PDFs), NOT law projects
- [x] Analyzed vespeiro's DRESpider — uses Exa/Tavily for media appointments only
- [x] Analyzed vespeiro's GapAnalyzer — compares debate topics vs media coverage
- [x] Researched `api.votoaberto.org` (parlamentodb) — 21+ REST endpoints, FastAPI + DuckDB
- [x] Researched `oparlamento.pt` — civic tech aggregator, live (HTTP 200)
- [x] Researched `dados.parlamento.pt` — official open data (XML/JSON), currently unreachable
- [x] Researched `pesquisa-legislativa.parlamento.pt` — search interface, currently unreachable
- [x] Researched DRE — no public API, ELI standard, `data.dre.pt` redirects to `diariodarepublica.pt`
- [x] **Key finding: vespeiro tracks DEBATES not LAWS — critical gap identified**

---

### BEP RAG Pipeline (`bep_rag.py`) — ✅ WORKING (2000 listings)
- [x] LanceDB with pre-computed embeddings architecture
- [x] Using `paraphrase-multilingual-MiniLM-L12-v2` (470MB, 384d)
- [x] 2000 listings indexed in ~148s
- [x] Semantic search with strong relevance:
  - "médico" → Health units (score 0.68)
  - "professor ensino" → Schools (score 0.71)
  - "enfermeiro" → Hospitals (score 0.80)
  - "engenheiro informático" → Universities (score 0.72)
  - "advogado jurista" → Justice Ministry (score 0.52)
  - "cargo direção" + Sintra filter → Câmara Municipal de Sintra (score 0.64)
- [x] Metadata filtering (--entity, --since, --until)
- [x] Auto-detect EMBED_DIM from model
- [x] All dead code removed
- [x] Code reviewed and approved

---

## ❌ Not Started

### Law Project Tracker
- [ ] Build scraper for `api.votoaberto.org` — law projects, authors, votes
- [ ] Store law projects in SQLite
- [ ] Track law lifecycle: proposal → committee → vote → DRE publication

### DRE Publication Crawler
- [ ] Enumerate recent DRE publications by date range (not search-based)
- [ ] Download + extract law text from `files.dre.pt`
- [ ] Store in SQLite for RAG pipeline

### Parliament Law RAG
- [ ] Chunk law projects into searchable text
- [ ] Index into LanceDB with embeddings
- [ ] Semantic search over Portuguese legislation

### Parliament Research → Implementation
- [ ] Evaluate `api.votoaberto.org` endpoints (test with curl)
- [ ] Evaluate `oparlamento.pt` data format
- [ ] Decide on primary data source for law tracking

---

## Environment Constraints
- **Disk:** 32GB total, ~2.2GB available
- **RAM:** Limited (2.2GB model causes OOM/segfault)
- **Network:** Outbound OK, some government sites unreachable (dados.parlamento.pt)
- **Cached models:** `intfloat/multilingual-e5-large` (2.2GB) — too large for this env
- **Available packages:** lancedb 0.33.0, tantivy 0.26.0, chromadb removed
