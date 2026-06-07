# Analisa-PT — Roadmap & Backlog

> Living document capturing ALL identified gaps, opportunities, and next steps.
> Updated: 2026-06-06

## How to Use This Document

**At the start of every session:** Read this file first. It is the persistent backlog.
**While working:** Check off items as you complete them. Add new items as you find them.
**The `suggest_followups` tool is capped at 3 items — this document is NOT.**
**Everything identified in conversations lives here. Nothing gets lost.**

**Philosophy: All data is good data.** Every source should be investigated, even if the result is "confirms what we already know" or "doesn't have what we need." That's still valuable intelligence. Negative findings prevent duplication of effort. Tangential data may reveal unexpected connections.

---

## 🔥 Top 5 Quick Wins (Do These First)

| # | Task | Why | Effort |
|---|------|-----|--------|
| 1 | Create `utils.py` with shared `parse_entity_field`, `fmt` | Bug fixes propagate to all 8+ tools | 2h |
| 2 | Add more INE variable codes | API already integrated, just add codes | 1h |
| 3 | Integrate rotating winners + temporal + bid signals into `anomaly_scanner.py` | Makes existing scanner 3x more powerful | 4h |
| 4 | Run `competitor_recover.py` at scale (140K contracts) | Fills 57% data gap, enables bid rigging detection | 3h |
| 5 | Build `run_corruption_scan.py` automated pipeline | All tools become automated, no manual invocation | 4h |

---

## Known Bugs (from this session)

| Bug | File | Severity | Fix |
|-----|------|----------|-----|
| `top_suppliers` groups by raw `adjudicatarios` text instead of parsed NIF — same supplier appears multiple times with different spellings | `supplier_cross_profiler.py` | Medium | Group by extracted NIF |
| `_get_buyer_total` cache parameter exists but no caller passes a cache dict — N+1 queries | `supplier_cross_profiler.py` | Low | Pass cache dict from `_build_profile` |
| `detect_closed_bidder_groups` bidder name lookup only covers winners, not competitors — competitor-only bidders show NIFs instead of names | `bid_pattern_analyzer.py` | Low | Parse `competitor_text` for names |
| `detect_rotating_winners` still references old `winner_nifs` in one place — may cause NameError at runtime | `bid_pattern_analyzer.py` | Medium | Verify all references updated |

---

## Status Summary

### What Exists (Working)
- **244K contracts** from BASE.gov.pt in `procurement.db` (111K entities)
- **10-signal anomaly scanner** (`anomaly_scanner.py`) — 1,440 entities flagged
- **Municipality risk ranking** — 584 municipalities, 24 dual-anomaly
- **Corruption dashboard** — HTML with charts, filters, risk scoring
- **Entity profiler** — cross-references BEP + procurement + DRE + laws
- **Entity network** — buyer-seller relationships, cross-municipality analysis
- **BEP scraper + RAG** — 2K job listings, semantic search
- **Law tracker + RAG** — 5K parliamentary projects, semantic search
- **DRE crawler** — 10K publications (sparse titles)
- **Price gap analysis** — base vs final price comparison
- **Transparency scraper** (`transparency_scraper.py`) — PRR contracts/entities/projects + budget execution (NEEDS DOWNLOAD)
- **3 new tools** (just built):
  - `supplier_cross_profiler.py` — profile supplier across ALL buyers
  - `temporal_clustering.py` — detect suspicious timing bursts
  - `bid_pattern_analyzer.py` — rotating winners, bid suppression, price similarity

### What's Missing (Gaps)
- **0% contract modification data** — can't detect post-award price changes
- **0% company ownership** — can't link officials to companies
- **0% council member affiliations** — can't track political connections
- **0% payment tracking** — can't verify contracts were actually paid
- **0% lobbying data** — confirmed gap in PDF analysis
- **0% pension reporting** — confirmed gap in PDF analysis
- **57% missing competitor data** — can't measure competition for most contracts
- **No automated scanning** — everything requires manual invocation
- **No alert system** — anomalies are detected but not surfaced automatically
- **No shared code module** — `parse_entity_field` and `fmt` duplicated in 5+ files

---

## Priority 1: Code Quality & Infrastructure

### P1.1 — Consolidate shared code
- [ ] Create `vespeiro/docs/analisa-pt/tools/utils.py` with `parse_entity_field`, `fmt`, `parse_date`, `days_between`
- [ ] Refactor all tools to import from `utils.py` instead of duplicating
- [ ] Files to update: `anomaly_scanner.py`, `entity_network.py`, `entity_profile.py`, `supplier_cross_profiler.py`, `temporal_clustering.py`, `bid_pattern_analyzer.py`, `municipality_risk_report.py`, `bep_procurement_crossref.py`
- **Impact:** Bug fixes propagate to all tools, reduced maintenance burden
- **Effort:** Low (2-3 hours)

### P1.2 — Build automated scan pipeline
- [ ] Create `run_corruption_scan.py` that runs ALL detection tools
- [ ] Runs: anomaly_scanner, supplier profiler (top suppliers), temporal clustering, bid patterns
- [ ] Produces unified JSON risk report with baseline comparison
- [ ] Compares against previous scan (use `anomaly_diff.py` pattern)
- **Impact:** Corruption detection becomes automated instead of manual
- **Effort:** Medium (4-6 hours)

### P1.3 — Wire alerts into Telegram
- [ ] Connect `run_corruption_scan.py` output to `run_alert.py` / Telegram bot
- [ ] Alert on: new self-referencing entities, new dual-anomaly municipalities, significant inflation increases
- [ ] Use existing `BaselineThresholds` pattern from `baseline.py`
- **Impact:** Anomalies surface automatically, no manual checking needed
- **Effort:** Medium (3-4 hours)

### P1.4 — Update corruption dashboard
- [ ] Add rotating winners, temporal clustering, and bid suppression to `generate_corruption_dashboard.py`
- [ ] Add supplier cross-buyer reach as a new section
- [ ] Add temporal burst visualization
- **Impact:** Dashboard becomes the single source of truth
- **Effort:** Medium (4-6 hours)

---

## Priority 2: New Data Sources (from PDF analysis)

### P2.1a — dados.gov.pt PRR + Budget (READY TO RUN)
- [x] `transparency_scraper.py` already built — handles PRR + budget execution via dados.gov.pt
- [ ] Download and index PRR data: `python transparency_scraper.py download --type prr && python transparency_scraper.py index`
- [ ] Download and index budget data: `python transparency_scraper.py download --type budget && python transparency_scraper.py index`
- [ ] Run `python transparency_scraper.py crossref` to cross-reference with procurement.db
- **Impact:** HIGH — data is ready to download, just needs to be run
- **Effort:** Low (already built, just run download + index)

### P2.1b — Transparency+ Portal (transparencia.gov.pt)
- [x] **RESEARCHED:** No direct public API — portal is a dashboard, not a data source
- [x] Data from this portal is published through dados.gov.pt (P2.1a already handles this)
- [ ] Investigate `transparencia.gov.pt/pt/municipalities/indicadores-por-municipio/` for municipality-level indicators
- [ ] Check PRR barometer at transparencia.gov.pt for execution status data
- **URL:** `https://transparencia.gov.pt`
- **Access:** Web dashboard only, no REST API. Raw data via dados.gov.pt
- **Impact:** LOW-MEDIUM — most data already available via dados.gov.pt
- **Effort:** Low (research done, just need to verify what additional data exists on the dashboard vs dados.gov.pt)

### P2.2 — Registo Comercial (Company Registry)
- [x] **RESEARCHED:** NO public API exists. Official portal: `registo.justica.gov.pt`
- [x] **Certidão Permanente** available per-company (requires NIF, costs €3.60/document)
- [x] **RCBE (Registo Central do Beneficiário Efetivo)** at `justica.gov.pt/Servicos/Registo-Central-do-Beneficiario-Efetivo` — beneficial owners, but RESTRICTED to "obliged entities" (banks, lawyers) for AML compliance
- [x] Portugal participates in EU BRIS (Business Registers Interconnection System) — cross-border but not public
- [x] Third-party aggregators exist (credit bureaus) but proprietary and potentially scraping against ToS
- [ ] **UNVERIFIED Option A:** Build scraper for Certidão Permanente (per-NIF queries, ~€3.60 each, slow but legal) — needs prototype test
- [ ] **UNVERIFIED Option B:** Research if any third-party aggregator offers bulk access — needs market research
- [ ] **UNVERIFIED Option C:** Check if dados.gov.pt has any company registry datasets — needs API query
- **CRITICAL BLOCKER** — without ownership data, self-referencing and network analysis (P3.4, P3.6) are limited
- **Impact:** CRITICAL — enables official→company linking for conflict of interest detection
- **Effort:** High (no clean API path, requires creative approach)

### P2.3 — CFP (Conselho de Fiscalidade)
- [x] **RESEARCHED:** Independent fiscal watchdog, established 2011. No REST API
- [x] **Interactive data:** `cfp.pt/pt/dados/projecoes-macroeconomicas` — macroeconomic projections with comparison tools
- [x] **Publications:** PDF reports on budget analysis, fiscal sustainability, State Budget assessments
- [ ] Download macroeconomic projections data from CFP interactive tools
- [ ] Download and parse budget analysis reports (PDFs)
- [ ] Cross-reference fiscal sustainability findings with 24 dual-anomaly municipalities
- [ ] Use CFP data to validate/contradict our inflation rate signals
- **URL:** `https://www.cfp.pt`
- **Access:** Public reports (PDF), interactive data tables (web). No API
- **Impact:** HIGH — validates our anomaly signals against official independent fiscal analysis
- **Effort:** Low-Medium (public data, needs PDF parsing)

### P2.4 — Tribunal de Contas
- [x] **RESEARCHED:** Supreme audit institution. Domain: `tcontas.pt` (NOT tc.pt)
- [x] Publishes: audit opinions (*pareceres*) on Conta Geral do Estado, thematic audits on procurement/PPP, annual reports
- [x] **No REST API.** Reports in PDF format on the website
- [x] TdC increasingly using data analytics for procurement risk assessment (per OECD studies)
- [ ] Download audit reports from tcontas.pt
- [ ] Parse PDF audit findings for mentions of specific entities or municipalities
- [ ] Cross-reference audit findings with anomaly scanner output
- [ ] Check if any procurement-specific audits overlap with our 24 dual-anomaly municipalities
- **URL:** `https://www.tcontas.pt`
- **Access:** Public audit reports (PDF). No API
- **Impact:** HIGH — official confirmation of corruption patterns we detect
- **Effort:** Medium (PDF parsing, entity matching)

### P2.5 — Portal Autárquico (DGAL)
- [x] **RESEARCHED:** Has downloadable CSV/Excel data ("código aberto"), NOT just PDFs!
- [x] **Contas de Gerência:** Balance sheets, income statements, revenue/expenditure by economic classification
- [x] **Historical data back to 2003** — all municipalities, all years
- [x] **Direct download links** available at `portalautarquico.dgal.gov.pt/pt-PT/financas-locais/dados-financeiros/contas-de-gerencia/`
- [x] **DGAL also publishes:** Annual reports, monthly/quarterly monitoring, SEL (Local Business Sector) data, debt monitoring
- [ ] Download Contas de Gerência CSV/Excel files for all municipalities (2020-2025)
- [ ] Parse and index in SQLite — revenue, expenditure, balance sheets per municipality per year
- [ ] Build budget execution ratio (previsto vs realizado) per municipality
- [ ] Cross-reference with procurement.db to detect spending anomalies
- [ ] This fills the "No final paid price" gap (16.8% → potentially 100%) and "Budget execution" gap
- **URL:** `https://portalautarquico.dgal.gov.pt`
- **Data URL:** `https://portalautarquico.dgal.gov.pt/pt-PT/financas-locais/dados-financeiros/contas-de-gerencia/`
- **Access:** Public CSV/Excel downloads. No API, but structured data
- **Impact:** HIGH — enables true cost overrun analysis, budget execution tracking, financial health scoring
- **Effort:** Medium (structured downloads, needs parsing and indexing)

### P2.6 — PRR Portal
- [x] **PARTIAL** — `transparency_scraper.py` already handles PRR contracts, entities, projects, locations, milestones
- [x] **RESEARCHED:** PRR data is published through dados.gov.pt, not a separate portal
- [x] **PRR barometer** also available at transparencia.gov.pt (dashboard, not raw data)
- [ ] **IMMEDIATE:** `python transparency_scraper.py download --type prr && python transparency_scraper.py index`
- [ ] **IMMEDIATE:** `python transparency_scraper.py prr` for corruption signal analysis
- [ ] **IMMEDIATE:** `python transparency_scraper.py crossref` to cross-reference with procurement.db
- [ ] Fundão PRR housing contracts (VectorPlano) need PRR fund context — cross-ref with procurement.db
- [ ] Check PRR milestone completion rates against actual contract execution
- **Impact:** MEDIUM-HIGH — data pipeline exists, just needs to be run
- **Effort:** Low (already built, just run commands)

### P2.7 — DGAL additional reports (beyond Portal Autárquico)
- [x] **RESEARCHED:** DGAL manages Portal Autárquico (P2.5 handles the main data)
- [x] **Estudos e Relatórios:** `portalautarquico.dgal.gov.pt/pt-PT/estudos-e-relatorios/`
- [x] **Publicações On-line:** `portalautarquico.dgal.gov.pt/pt-PT/servicos-on-line/biblioteca/publicacoes-on-line`
- [ ] Download DGAL annual reports on municipal financial health (PDF)
- [ ] Download SEL (Local Business Sector) data for municipal enterprise analysis
- [ ] Build municipality financial health index from DGAL reports + Portal Autárquico CSV data (P2.5)
- **Note:** Portal Autárquico structured data is covered in P2.5. This item covers DGAL's additional PDF reports and studies.
- **Impact:** MEDIUM — complements procurement anomaly analysis with financial health context
- **Effort:** Medium (reports need parsing, but structured downloads available in P2.5)

### P2.8 — INE expanded indicators
- [ ] Add more INE variable codes beyond current 12
- [ ] Consider: education enrollment, social security beneficiaries, construction permits
- [ ] This is a TRIVIAL change — just adding codes to existing API integration
- **Impact:** MEDIUM — richer municipality profiles
- **Effort:** Very Low (30 min — just add variable codes)

---

## Priority 3: Corruption Detection Enhancements

### P3.1 — Integrate new signals into `anomaly_scanner.py`
- [ ] Add rotating winners detection as new signal
- [ ] Add temporal clustering as new signal
- [ ] Add bid suppression as new signal
- [ ] Update composite risk score to include new signals
- [ ] This makes the existing scanner 3x more powerful without requiring separate tools
- **Impact:** HIGH — existing scanner becomes comprehensive
- **Effort:** Medium (4h — port logic from new tools into scanner class)

### P3.2 — Contract modification tracker
- [ ] Enhance DRE crawler to fetch actual publication content (currently empty titles)
- [ ] Parse aditivos/amendments from DRE publications
- [ ] Cross-reference with `contratos` table to detect post-award price changes
- [ ] This fills the CRITICAL "No contract modifications" gap (0% coverage)
- **Impact:** CRITICAL — detects the most common corruption mechanism
- **Effort:** High (DRE content scraping + NLP parsing)

### P3.3 — Competitor recovery expansion
- [ ] Run `competitor_recover.py` on ALL 140K contracts missing competitor data
- [ ] Currently only 42.6% coverage — target 80%+
- [ ] Use BASE.gov.pt API with caching
- **Impact:** HIGH — enables bid rigging detection on most contracts
- **Effort:** Medium (API calls, ~140K requests with caching)

### P3.4 — Self-referencing deep-dive
- [ ] For all 495 self-referencing entities, check company registry (needs P2.2)
- [ ] Map ownership chains to identify if self-referencing is through subsidiaries
- [ ] Priority: entities with >€1M in self-referencing contracts
- **Impact:** HIGH — most critical corruption signal
- **Effort:** Medium-High (depends on Registo Comercial access)

### P3.5 — Election cycle analysis
- [ ] Map contract award timing to election cycles
- [ ] Detect if spending spikes correlate with pre-election periods
- [ ] Use `temporal_clustering.py` with election date overlay (data already available)
- **Impact:** MEDIUM — detects political corruption patterns
- **Effort:** Low (data already in temporal_clustering.py)

### P3.6 — Cross-entity network analysis
- [ ] Build graph of entities sharing directors/owners (needs P2.2)
- [ ] Detect shell company patterns
- [ ] Identify circular ownership chains
- **Impact:** HIGH — reveals hidden corruption networks
- **Effort:** High (depends on Registo Comercial data)

### P3.7 — Baseline comparison system
- [ ] Formalize `anomaly_diff.py` to run automatically after each scan
- [ ] Track: new entities flagged, new municipalities, inflation rate changes
- [ ] Generate diff reports for monitoring
- **Impact:** MEDIUM — enables trend analysis
- **Effort:** Low (infrastructure exists, just needs automation)

---

## Priority 4: Dashboard & Visualization

### P4.1 — Corruption dashboard v2
- [ ] Add rotating winners section
- [ ] Add temporal clustering visualization
- [ ] Add bid suppression patterns
- [ ] Add supplier cross-buyer reach map
- [ ] Add risk score history charts
- **Impact:** HIGH — makes findings accessible to non-technical users
- **Effort:** Medium-High (HTML/JS generation)

### P4.2 — Municipality comparison tool
- [ ] Side-by-side municipality risk comparison
- [ ] Benchmark against national averages
- [ ] Show temporal trends per municipality
- **Impact:** MEDIUM — enables targeted investigation
- **Effort:** Medium

### P4.3 — Supplier network visualization
- [ ] Interactive graph of buyer→supplier relationships
- [ ] Color-coded by risk signals
- [ ] Filter by entity type, region, value
- **Impact:** MEDIUM — visual corruption pattern detection
- **Effort:** Medium-High (D3.js or similar)

---

## Priority 5: Data Quality & Gaps

### P5.1 — Freguesia code resolution
- [ ] Fix CAOP code format (currently generates NUTS-like PT1700 instead of 110800)
- [ ] Download official CAOP code table
- [ ] Re-run `freguesia_resolver.py` with correct mapping
- **Impact:** MEDIUM — enables parish-level analysis
- **Effort:** Low-Medium

### P5.2 — Entity name normalization
- [ ] Build entity name deduplication (same entity, different spellings)
- [ ] Cross-reference NIFs to merge duplicate entities
- [ ] Use `nif_mapping.json` pattern for Câmara↔Município bridging
- **Impact:** MEDIUM — cleaner entity analysis
- **Effort:** Medium

### P5.3 — Historical data expansion
- [ ] Fetch older BASE.gov.pt data (pre-2020)
- [ ] Expand BEP scraper to cover more historical listings
- [ ] Fetch L16/L15 legislatures for law RAG
- **Impact:** MEDIUM — enables longer-term trend analysis
- **Effort:** Medium (API calls, storage)

---

## Monitoring Protocol

### Scan Schedule (Target State)
| Frequency | Tool | Output |
|-----------|------|--------|
| Weekly | `run_corruption_scan.py` | Unified risk report + Telegram alerts |
| Monthly | `anomaly_scanner.py --export` | Full entity scan baseline |
| Monthly | `municipality_risk_report.py --export` | Municipality risk ranking |
| Quarterly | Dashboard refresh | Updated HTML dashboard |
| On demand | `entity_profile.py` | Deep-dive investigation |

### Alert Thresholds
| Signal | Threshold | Action |
|--------|-----------|--------|
| New self-referencing entity | Any | Immediate Telegram alert |
| New dual-anomaly municipality | Any | Alert + investigation queue |
| Inflation rate increase | >0.3% | Methodology review |
| New exclusive company >€1M | Any | Investigation queue |
| Total overrun increase | >€15M | Escalation |

---

## Additional Data Sources (from PDF — investigated per session)

| Source | What It Provides | Access | Status |
|--------|-----------------|--------|--------|
### Already Integrated (from PDF sources)
| Source | Tool | Status |
|--------|------|--------|
| **TED (Tender Electronic Daily)** | `ted_crossref.py` | ✅ EU procurement cross-reference built |
| **Portal das Finanças** | `debt_checker.py` | ✅ Tax debt list scraping built |
| **ERC** | `erc_advertising.py` | ✅ Institutional advertising reports spider built |
| **dados.gov.pt** | `dados_gov_pt.py`, `announce_index.py`, `transparency_scraper.py` | ✅ CKAN API client + PRR/budget scraper built |

### New Sources (from PDF — not yet in codebase)
| Source | What It Provides | Access | Next Step |
|--------|-----------------|--------|-----------|
| **Central de Dados** | Independent aggregator with "Segue o Dinheiro" budget tracker. Found €1.5B municipal spending gap. | `centraldedados.com` | Investigate — valuable for cross-validation |
| **govtransparency.eu** | EU governance scorecards, perception surveys, efficiency metrics | `govtransparency.eu` | Investigate — benchmarking Portugal against EU peers |
| **GitHub open data list** (Ricardo Lafuente) | Community-curated links to niche datasets (tax data, corporate incentives) | GitHub Gist | Review for additional discoverable datasets |
| **Huwise Open Data Guide** | Training guide on cleaning/harmonizing Portuguese public data | Online guide | Review for data quality methodology |
| **Trading Economics** | Global aggregator of official data, historical trends, cross-country comparisons | `tradingeconomics.com` | Low priority — INE covers most |
| **Banco de Portugal** | Financial stability reports, banking data | `bportugal.pt` | ~~Investigate~~ ✅ **BPStat API confirmed working** — see P2.9 below |

---

## What We Cannot Determine (Blockers) — Updated with Research

| Gap | Status | Blocker | Potential Solution |
|-----|--------|---------|-------------------|
| Company ownership | **NO PUBLIC API** | Registo Comercial requires per-company queries (€3.60 each), RCBE restricted to AML obliged entities | Scrape Certidão Permanente (slow, costly), or find third-party aggregator |
| Contract modifications | 0% coverage | DRE titles empty | Enhance DRE crawler to fetch actual PDF content |
| Bid rigging patterns | 42.6% competitor coverage | Missing data for 140K contracts | Run competitor_recover.py at scale |
| ~~Budget execution (municipal)~~ | **RESOLVED** | ~~PDF-only~~ → CSV/Excel available at Portal Autárquico | P2.5 covers this — no longer a blocker |
| Official-company links | Depends on P2.2 | No ownership data | Registo Comercial (P2.2) — see blocker above |
| Payment verification | 0% | No payment data | DGAL financial reports (P2.7) — partially available |
| Lobbying data | **Not available anywhere** | Confirmed gap — no Portuguese dataset exists | N/A |
| Pension reporting | **Not available anywhere** | Confirmed gap — no Portuguese dataset exists | N/A |
| Employee compensation | Dashboard only | transparencia.gov.pt has data but no API | Scrape dashboard or check dados.gov.pt |
| Fiscal audit findings | PDF only | CFP and TdC publish reports as PDFs, no API | Parse PDF reports, cross-reference with anomaly scanner |

---

### P2.9 — Banco de Portugal BPStat API (CONFIRMED WORKING)
- [x] **RESEARCHED:** Full REST API at `https://bpstat.bportugal.pt/data/v1/`
- [x] **No authentication required** — open access, rate-limited (X-Throttle header)
- [x] **JSON-stat v2.0 format** — standard statistical data format, pyjstat library available
- [x] **80+ statistical domains** covering: budgetary execution, public debt, national accounts, enterprise indicators by region, employment, CPI, financial stability, and more
- [x] **Domain 10 (Execução orçamental):** 128 series of budget execution data — monthly revenue/expenditure breakdowns in millions of euros, institutional sector (Estado/Segurança social), line items (IVA, petroleum tax, capital receipts)
- [x] **Domain 178 (Enterprise indicators by region):** Economic/financial indicators per region — enables geographic corruption pattern analysis
- [x] **Domain 27 (Public Admin Financing):** Government financing data
- [x] **Domain 28 (Public Debt):** 8 datasets — debt stock, issuance, maturities
- [x] **Domain 172 (Public Admin Non-Financial Accounts):** Budget execution by institutional sector
- [x] **Domain 31/54/55 (GDP series):** National accounts — expenditure and production approaches
- [ ] Download and index budgetary execution data — cross-reference with Portal Autárquico (P2.5)
- [ ] Fetch enterprise indicators by region — compare procurement patterns against regional economic activity
- [ ] Build correlation: budget execution rates vs procurement anomaly signals per region
- [ ] Use public debt data to flag municipalities with unsustainable borrowing
- **API URL:** `https://bpstat.bportugal.pt/data/v1/`
- **Docs URL:** `https://bpstat.bportugal.pt/data/docs`
- **Key endpoints:**
  - `GET /domains/` — list all statistical domains
  - `GET /domains/{id}/datasets/` — list datasets in a domain
  - `GET /domains/{id}/datasets/{id}/?series_ids=X` — fetch observations (JSON-stat)
  - `GET /series/?series_ids=X,Y` — get series metadata (domain, dataset, dimensions)
  - `GET /domains/{id}/dimensions/` — list dimensions for a domain
- **Access:** Public REST API, no auth, rate-limited
- **Impact:** HIGH — enables macro-economic context for procurement anomalies, regional economic baselines, budget execution validation
- **Effort:** Low-Medium (API works, needs a scraper/indexer script)

---

*This document is the single source of truth for the analisa-pt roadmap. Updated after each session with research findings and implementation progress.*
*Last major research session: 2026-06-06 — PDF opendatasources_2.pdf analysis + web research on all Portuguese government data portals.*
*Updated 2026-06-07 — BPStat API (Banco de Portugal) confirmed working with budgetary execution, public debt, enterprise regional indicators.*
