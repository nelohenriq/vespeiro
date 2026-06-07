# Procurement Anomaly Investigation — FINDINGS

**Last updated:** 2026-06-06  
**Data sources:** BASE.gov.pt procurement (244K contracts), BEP job listings, DRE publications, Law projects  
**Tools:** `anomaly_scanner.py`, `municipality_risk_report.py`, `entity_profile.py`, `entity_network.py`, `bep_procurement_crossref.py`

---

## Executive Summary

Systematic analysis of Portuguese public procurement data reveals **24 municipalities with dual anomalies** (high supplier concentration + price inflation), **1,440 flagged entities** with composite risk signals, and a consistent pattern of closed procurement ecosystems across the country. Fundão stands out as the highest-risk municipality, but it is part of a broader systemic issue.

---

## 1. FUNDÃO — Primary Case Study

### 1.1 Anomaly Profile

| Metric | Value | Context |
|--------|-------|---------|
| Risk score | 87/100 | #1 of 24 dual-anomaly municipalities |
| Supplier concentration | 67.4% top-3 share | 23 unique winners |
| Price inflation rate | 2.3% (10/435 contracts) | 4.6× national average (0.5%) |
| Average inflation | 15.6% on inflated contracts | All via Concurso público |
| Total overrun | €1.45M | All 10 contracts from 2025 |
| Direct award rate | Within normal range | Not a primary concern |

### 1.2 Key Companies

#### Constrobi — Empresa de Construções da Beira Interior, Lda.
- **NIF:** 501089233
- **Address:** Zona Industrial, Lote 27, 6230-280 Fundão
- **Legal form:** Sociedade por Quotas (LLC)
- **Website:** constrobi.pt
- **Contracts:** 11 total — ALL with Município do Fundão
- **Total value:** €3,027,993
- **Pattern:** Fundão-exclusive in our dataset. Zero presence with any other municipality, region, or central government entity.
- **Concern:** A company with zero external clients raises questions about procurement competition. However, the company is a legitimate local construction firm based in Fundão's industrial zone, active for decades.
- **Assessment:** Likely a genuine local contractor, but its exclusivity highlights the closed nature of Fundão's procurement ecosystem.

#### NOW XXI — Engenharia & Construções, Lda.
- **NIF:** 514288256
- **Contracts:** 11 total across multiple municipalities
- **Pattern:** Regional player — wins in Fundão (€6.7M), Covilhã, Belmonte, Odivelas, Oeiras, Seixal
- **Price inflation:** +13% and +17% on Fundão contracts; +15% on Oeiras
- **Assessment:** Legitimate construction company with broad presence. Inflation pattern in Fundão warrants investigation.

#### VectorPlano — Projeto, Construção e Engenharia, Lda.
- **NIF:** 513913157
- **Contracts:** 15 total — Fundão (8), Covilhã (3), Manteigas (2)
- **Pattern:** Regional player across Cova da Beira
- **Price inflation:** +17% and +10% on Fundão PRR housing contracts
- **Assessment:** Legitimate company with regional presence. Inflation in Fundão specifically is notable.

### 1.3 Council Connections

| Official | Role | Party | Connection to companies |
|----------|------|-------|------------------------|
| Miguel Gavinhos | Presidente (since late 2025) | PPD/PSD | None found |
| Paulo Fernandes | Former Presidente (2013-2025) | — | None found |
| Rui Jorge Fernandes Simão | Vice-Presidente | — | None found |

- **DRE publications:** 0 mentions of NOW XXI, Constrobi, VectorPlano, or Fundão council
- **Law projects:** 0 mentions of any of these companies or Fundão council
- **Individual contract winners:** Olga Maria Leitão Ramos Alves and Mariana Brito Páscoa received contracts from Fundão — potential individuals of interest for further investigation

### 1.4 Contract Modification Analysis

- **No aditivo/modification tables** exist in the procurement database
- **No duplicate contract IDs** — each contract appears once
- **Cannot distinguish** between artificially low base prices and post-award modifications
- **All 10 inflated contracts** use public tender (Concurso público) — inflation happens during bid evaluation or contract modification, not through direct award

### 1.5 Regional Context

| Municipality | Concentration | Inflation | Assessment |
|--------------|---------------|-----------|------------|
| **Fundão** | 67.4% | 10 inflated, 15.6% avg | #1 dual-anomaly |
| Covilhã | Normal | 0 inflated | No inflation signal |
| Belmonte | Normal | 0 inflated | No inflation signal |
| Penamacor | Normal | 0 inflated | No inflation signal |

**Conclusion:** Price inflation is Fundão-specific, not regional. The Cova da Beira region shows normal procurement patterns except for Fundão.

---

## 2. NATIONAL ANALYSIS

### 2.1 Dual-Anomaly Municipalities (24 total)

Municipalities with BOTH high concentration (top-3 share ≥60%) AND price inflation:

| # | Risk | Conc% | InflRate | Overrun | Municipality |
|---|------|-------|----------|---------|--------------|
| 1 | 87 | 67.4% | 20.0% | €1.4M | Município do Fundão |
| 2 | 84 | 86.5% | 18.6% | €1.1M | Município de Ponte de Sor |
| 3 | 82 | 67.8% | 21.2% | €1.6M | Estado-Maior do Exército |
| 4 | 79 | 72.3% | 15.8% | €2.9M | Lisboa Ocidental, SRU |
| 5 | 76 | 91.2% | 12.4% | €1.8M | Espaço Municipal |

### 2.2 National Statistics

| Metric | Value |
|--------|-------|
| Total contracts analyzed | 244,897 |
| Contracts with base price | 239,437 |
| Inflated contracts (all types) | 296 (0.1%) |
| Construction contracts inflated | 84/15,637 (0.5%) |
| Total overrun (all types) | €56.5M |
| Total overrun (construction) | €53.1M |
| Municipalities with 5+ construction contracts | 590 |
| High concentration (>80% top-3) | 257 (43.6%) |
| Medium concentration (60-80%) | 209 (35.4%) |
| Low concentration (<60%) | 124 (21.0%) |
| National avg top-3 share | 74.7% |

### 2.3 Key Insight

**Supplier concentration is the norm in Portuguese public works**, not the exception. 79% of municipalities have top-3 suppliers taking 60%+ of construction value. The concerning pattern is not concentration alone, but **concentration combined with price inflation**.

---

## 3. ANOMALY SCANNER FINDINGS

### 3.1 Entity-Level Signals (1,440 entities flagged)

| Signal | Count | Description |
|--------|-------|-------------|
| supplier_dominance | 730 | One winner takes >30% of total value |
| direct_award_excess | 466 | >50% of contracts via Ajuste Direto |
| no_competitors | 324 | >80% of contracts have no competitors recorded |
| closed_ecosystem | 227 | Top-3 companies take >60% of value |
| price_inflation | 90 | Contracts where final > base price |
| exclusive_company | ~50 | Company only works with one buyer |
| bep_mismatch | ~30 | High procurement but minimal BEP listings |
| self_referencing | 495 | Entity appears as both buyer and seller |

### 3.2 Top Anomaly Entities

| Entity | Risk | Signals | Key Finding |
|--------|------|---------|-------------|
| Direção-Geral de Recursos da Defesa Nacional | 100 | price_inflation + dominance | 73% single-supplier, €468K overrun |
| Município de Lagoa | 100 | no_competitors + direct | 100% no competitors, 88% direct award |
| Cáritas Arquidiocesana de Braga | 100 | dominance | >90% concentration |
| Centro Juvenil de Campanhã | 100 | dominance | >90% concentration |

---

## 4. BEP-PROCUREMENT CROSS-REFERENCE

### 4.1 Anomaly Signals

**258 entities** have 50+ procurement contracts but ≤2 BEP job listings.

**Genuinely lean (explainable):**
- Health units (ULS/EPE): Hire through hospital-specific channels, not BEP
- Military/Security (GNR, Marinha): Hire through defense ministry
- State Enterprises (EPE/SA): Private HR channels

**Genuine red flags:**
- INEM: GULF MED AVIATION SERVICES holds 19% share of €81M contracts
- High concentration + low hiring transparency

### 4.2 Constrobi Cross-Reference

- NIF 501089233: 11 contracts, all with Fundão
- Zero presence in any other municipality's procurement
- Legitimate local company but exclusivity is notable

---

## 5. METHODOLOGY & TOOLS

### 5.1 Signals Detected

1. **Price Inflation:** Contracts where `precoContratual > precoBaseProcedimento`
2. **Supplier Dominance:** One winner takes >30% of total value
3. **Self-Referencing:** Same NIF as buyer and seller
4. **Closed Ecosystem:** Top-3 companies take >60% of value
5. **BEP Mismatch:** High contracts but minimal job listings
6. **Direct Award Excess:** >50% of contracts via Ajuste Direto
7. **No Competitors:** >80% of contracts have no competitors recorded
8. **Exclusive Companies:** Company only works with one buyer

### 5.2 Composite Risk Score

Risk = min(100, concentration_score + inflation_score + direct_award_score + exclusive_score + bep_score)

- Concentration: 0-35 points
- Inflation: 0-30 points
- Direct award: 0-15 points
- Exclusive companies: 0-10 points
- BEP mismatch: 0-5 points

### 5.3 Tools Built

| Tool | Purpose | Key Output |
|------|---------|------------|
| `anomaly_scanner.py` | Multi-signal entity scanner | 1,440 flagged entities |
| `municipality_risk_report.py` | Municipality risk ranking | 584 municipalities ranked |
| `generate_municipality_dashboard.py` | Interactive HTML dashboard | 325KB dashboard |
| `entity_profile.py` | Single entity deep-dive | Full procurement profile |
| `entity_network.py` | Buyer-seller network analysis | Self-referencing detection |
| `bep_procurement_crossref.py` | BEP × procurement cross-ref | Hiring vs buying patterns |

---

## 6. CONCERNS & ENVISIONED SOLUTIONS

### 6.1 Systemic Concerns

| Concern | Evidence | Severity |
|---------|----------|----------|
| Closed procurement ecosystems | 79% of municipalities have >60% concentration | Systemic |
| Price inflation in public works | 24 dual-anomaly municipalities | High |
| No competitor data for 57% of contracts | 140K contracts with no competitors | Systemic |
| Direct award bypassing competition | 110K contracts via Ajuste Direto | Moderate |
| Self-referencing entities | 495 entities flagged | Critical per entity |

### 6.2 Fundão-Specific Concerns

| Concern | Evidence | Assessment |
|---------|----------|------------|
| Constrobi exclusivity | 11 contracts, all Fundão | Circumstantial — legitimate local firm |
| Price inflation pattern | 10 contracts, avg +15.6%, all 2025 | Suspicious — needs investigation |
| Individual contract winners | 2 individuals received contracts | Needs investigation |
| Administration transition timing | Inflated contracts in transition year | Needs investigation |

### 6.3 What We Cannot Determine

1. **Contract modifications:** Database lacks aditivo tracking — cannot distinguish low base prices from post-award modifications
2. **Ownership connections:** No company registry data linking officials to companies
3. **Bid rigging:** No bid-level data showing coordinated pricing
4. **Timeline of responsibility:** Cannot determine which administration signed inflated contracts

### 6.4 Envisioned Solutions

| Problem | Solution | Priority |
|---------|----------|----------|
| Closed ecosystems | Mandatory competitive bidding for contracts >€50K | High |
| Price inflation | Automated monitoring of base vs final price ratios | High |
| No competitor data | Mandatory competitor disclosure in BASE.gov.pt | High |
| Self-referencing | Automated cross-reference check at contract registration | Critical |
| BEP mismatch | Cross-reference procurement entities against hiring data | Medium |
| Data gaps | Add contract modification tracking to procurement database | High |

---

## 7. RECOMMENDED NEXT STEPS

1. **Investigate Ponte de Sor** (#2 dual-anomaly, 86.5% concentration)
2. **Deep-dive individual contract winners** (Olga Maria Leitão Ramos Alves, Mariana Brito Páscoa)
3. **Check contract timing** — which administration signed the 10 inflated Fundão contracts
4. **Expand Constrobi research** — company registry, ownership, historical contracts
5. **Build automated monitoring** — periodic anomaly scans with alert thresholds
6. **Cross-reference with Tribunal de Contas** — check for audit findings on flagged entities
7. **Add contract modification tracking** to procurement database schema

---

## 8. DATA AUDIT — What We Have vs What We Need

### 8.1 Current Coverage

| Data Category | Coverage | Notes |
|---------------|----------|-------|
| **Total contracts** | 244,897 (€23.5B) | Full BASE.gov.pt dataset |
| **Total entities** | 111,495 | Buyers + suppliers |
| **Winner data (adjudicatarios)** | **100%** | All contracts have winner info |
| **Base price (precoBaseProcedimento)** | **97.9%** (239,705) | Excellent — enables inflation analysis |
| **Final paid price (PrecoTotalEfetivo)** | **16.8%** (41,123) | **Missing for 83%** — limits true inflation analysis |
| **Geographic (NUTs region)** | **99.1%** | Excellent coverage |
| **Execution location (LocalExecucao)** | **99.6%** | Present but format varies |
| **Freguesia-level detail** | **5.5%** (13,353) | Only contracts with 3+ commas in LocalExecucao |
| **CPV codes** | **99.999%** | Nearly complete — 1 contract missing |
| **Construction CPV (45)** | 17,357 contracts | Our focus subset |
| **Competitor count (concorrentes)** | **42.6%** (104,341) | **Missing for 57%** — cannot measure competition |
| **Contract modifications/amendments** | **0%** | **No data** — critical gap |
| **Company ownership/directors** | **0%** | Not in procurement DB |
| **Council member affiliations** | **0%** | Not in procurement DB |
| **Payment/billing records** | **0%** | Not in procurement DB |
| **Contract delivery status** | **0%** | Not in procurement DB |
| **Budget vs actual spending** | **Partial** | Only base vs contracted, not budget execution |

### 8.2 Key Gaps That Limit Analysis

| Gap | Impact | Could Fix With |
|-----|--------|----------------|
| **No contract modifications** | Cannot detect post-award price changes (aditivos) | BASE.gov.pt aditivos API + DRE publications |
| **No competitor details** | Cannot detect bid rigging patterns | BASE.gov.pt licitações data |
| **No final paid price** | Cannot measure true cost overrun | Portal Autárquico financial reports |
| **No freguesia mapping** | Cannot pinpoint which parishes are affected | Manual mapping + INE geographic data |
| **No company registry** | Cannot link officials to companies | Registo Comercial (partial API) |
| **No payment tracking** | Cannot verify if contracts were actually paid | DGAL financial reports |

### 8.3 Available Open Data Sources to Extend Platform

| Source | API | Data | Update Freq | What It Adds |
|--------|-----|------|-------------|--------------|
| **BASE.gov.pt** | ✅ JSON/CSV | Contracts, bids, adjudicações | Continuous | Competitor data, contract phases |
| **Portal da Transparência** | ❌ Dashboard | Government spending, PRR | Variable | PRR project tracking, budget execution |
| **INE Portugal** | ✅ API/JSON | Census, demographics, economic indicators | Periodic | Population-normalized metrics, economic context |
| **Registo Comercial** | Partial | Company ownership, directors, legal status | Real-time | Ownership chains, beneficial owners |
| **Portal Autárquico** | ❌ PDF/Reports | Municipal accounts, financial reports | Annual | Actual spending, budget vs execution |
| **PRR Portal** | ❌ Dashboard | PRR projects, beneficiaries, investment | Continuous | Fundão PRR housing contracts context |
| **Transparência Int. PT** | ❌ Reports | Corruption perception indices | Annual | Benchmarking, comparative analysis |
| **DGAL** | ❌ Reports | Local government financial data | Annual | Municipality financial health |

### 8.4 What We Could Build With This Data

1. **Contract Modification Tracker** — Parse DRE publications for aditivos/amendments, detect post-award price changes
2. **Competition Analysis** — Use concorrentes data (42.6% coverage) to identify sole-bidder patterns and potential bid rigging
3. **Ownership Network Graph** — Cross-reference Registo Comercial data to build beneficial ownership chains
4. **Budget Execution Dashboard** — Compare contracted vs actual spending using Portal Autárquico data
5. **PRR Project Monitor** — Track PRR fund execution at municipality level, flag anomalies
6. **Freguesia-Level Mapping** — Map LocalExecucao to official freguesia boundaries using INE geographic data
7. **Financial Health Index** — Combine procurement patterns with DGAL financial reports to assess municipality fiscal health
8. **Temporal Trend Analysis** — Track how procurement patterns change across election cycles and administration transitions

---

## 9. NEW TOOLS — Data Gap Resolution

### 9.1 Freguesia Resolver (`freguesia_resolver.py`)

Resolves LocalExecucao strings to INE 6-digit codes for geographic analysis.

| Metric | Result |
|--------|--------|
| Locations processed | 3,443 unique |
| Exact matches | 3,300 (95.8%) |
| Partial matches | 99 (2.9%) |
| Fuzzy matches | 15 (0.4%) |
| Unresolved | 29 (0.8%) — international locations |

**Known issue:** INE codes currently generate NUTS-like format (e.g., PT1700) instead of proper CAOP 6-digit codes (e.g., 110800). Needs refinement with official CAOP code table.

### 9.2 Competitor Recovery (`competitor_recover.py`)

Recovers missing concorrentes (competitor) data from BASE.gov.pt with caching.

| Coverage | Contracts | Percentage |
|----------|-----------|------------|
| With competitors | 104,341 | 42.6% |
| Missing competitors | 140,556 | 57.4% |
| Empreitadas (works) | 10,232/15,851 | 64.6% |
| Services | 48,782/97,949 | 49.8% |

**Key finding:** Constrobi (NIF 501089233) appears in 18 contracts as competitor, bidding against VectorPlano (10 shared bids) and NOW XXI (1 shared bid). This confirms the regional construction ecosystem.

### 9.3 Modification Tracker (`modification_tracker.py`)

Parses DRE publications for contract amendments (aditivos/modifications).

| Status | Result |
|--------|--------|
| DRE publications scanned | 218 |
| Modification candidates | 0 |
| Reason | DRE database too sparse (empty titles) |

**Note:** DRE crawler needs enhancement to fetch actual publication content. Current database has 218 rows with mostly empty titles.

---

## 10. DATABASE SCHEMA REFERENCE

### contratos table (244,897 rows)

| Column | Type | Purpose |
|--------|------|---------|
| idcontrato | INTEGER | Unique contract ID |
| adjudicante_nif | TEXT | Buyer NIF |
| adjudicante_nome | TEXT | Buyer name |
| adjudicatarios | TEXT | Winner(s) — format: "NIF - Name" |
| precoContratual | REAL | Contracted price |
| precoBaseProcedimento | REAL | Base/reference price (97.9% coverage) |
| PrecoTotalEfetivo | REAL | Final paid price (16.8% coverage) |
| CPV | TEXT | EU procurement classification code |
| tipoprocedimento | TEXT | Procedure type (Concurso/Ajuste Direto) |
| tipoContrato | TEXT | Contract type (Serviços/Obras/Fornecimentos) |
| concorrentes | TEXT | Competitor count/info (42.6% coverage) |
| NUTs | TEXT | NUTS region code + name |
| LocalExecucao | TEXT | Execution location string |
| Ano | INTEGER | Contract year |
| dataCelebracaoContrato | TEXT | Contract date |
| prazoExecucao | INTEGER | Execution deadline (days) |

### entidades table (111,495 rows)

| Column | Type | Purpose |
|--------|------|---------|
| nifEntidade | TEXT | Entity NIF (primary key) |
| desigEntidade | TEXT | Entity name |
| totAdjudicatario | INTEGER | Times as winner |
| totValorContratIni | REAL | Total value as winner |
| totAdjudicante | INTEGER | Times as buyer |
| totAdjudicanteValorContratIni | REAL | Total value as buyer |
| AliasPais | TEXT | Country code |

### Other databases

| Database | Tables | Records | Purpose |
|----------|--------|---------|---------|
| bep_index.db | bep_entities, bep_listings | 842 + 2,041 | BEP job listings |
| dre_index.db | dre_publications | ~10,000 | Diário da República index |
| law_index.db | law_projects | ~5,000 | Parliamentary law projects |

---

---

## 11. MONITORING PROTOCOL

### 9.1 Scan Schedule

| Scan Type | Frequency | Trigger | Output |
|-----------|-----------|---------|--------|
| Full entity scan | Monthly | Scheduled | `anomaly_scanner.py --export` |
| Municipality risk | Monthly | Scheduled | `municipality_risk_report.py --export` |
| New contract ingestion | After each scrape | Data update | Compare new contracts against baselines |
| Deep-dive investigation | As needed | Alert triggered | Entity profile + web research |

### 9.2 Alert Thresholds

| Signal | Threshold | Action |
|--------|-----------|--------|
| **Price inflation** | >15% average on >3 contracts | Flag for investigation |
| **Supplier dominance** | >70% share with >€1M value | Flag for investigation |
| **Self-referencing** | Any occurrence | Immediate flag — critical |
| **Exclusive company** | >10 contracts, €500K+ with single buyer | Flag for investigation |
| **Closed ecosystem** | Top-3 >80% share, >€5M total | Flag for monitoring |
| **Direct award rate** | >80% on >€2M procurement | Flag for investigation |
| **No competitors** | >90% rate on >50 contracts | Flag for monitoring |
| **BEP mismatch** | >100 contracts, <3 listings | Flag for investigation |

### 9.3 Comparison Baselines

When re-running scans, compare against these baselines:

| Metric | Baseline (2026-06-06) | Change to watch |
|--------|----------------------|------------------|
| Total flagged entities | 1,440 | >10% increase |
| Dual-anomaly municipalities | 24 | Any new additions |
| National inflation rate (construction) | 0.5% | >0.8% |
| Fundão risk score | 87/100 | Any decrease (positive sign) |
| Constrobi contract count | 11 | Any new contracts |
| Total overrun | €56.5M | >€70M |

### 9.4 Data Refresh Checklist

Before each scan:
- [ ] Run `python procurement_db.py build` to refresh BASE.gov.pt data
- [ ] Run `python bep_scraper.py` to refresh BEP job listings
- [ ] Run `python dre_crawler.py` to refresh DRE publications
- [ ] Run `python law_tracker.py` to refresh law projects
- [ ] Verify database file sizes have increased
- [ ] Check for schema changes in source data

### 9.5 Investigation Workflow

1. **Automated scan** → `anomaly_scanner.py --export anomalies.json`
2. **Municipality scan** → `municipality_risk_report.py --export risk.json`
3. **Diff against baseline** → Compare new results vs previous scan
4. **New flags** → Deep-dive with `entity_profile.py` and web research
5. **Update FINDINGS.md** → Document new findings, update baselines
6. **Dashboard refresh** → `generate_municipality_dashboard.py` and `generate_corruption_dashboard.py`

### 9.6 Escalation Criteria

| Finding | Escalation Level | Action |
|---------|-----------------|--------|
| Self-referencing entity | Critical | Document + notify oversight |
| New dual-anomaly municipality | High | Add to investigation queue |
| Inflation rate increase >0.3% | Medium | Review methodology |
| New exclusive company >€1M | High | Add to investigation queue |
| Tribunal de Contas audit match | High | Cross-reference findings |

---

*This document is maintained as part of the Analisa-PT investigation toolkit. Update after each significant finding.*
