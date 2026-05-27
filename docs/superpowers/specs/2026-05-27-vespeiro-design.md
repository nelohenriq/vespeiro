# Project Vespeiro — Design Document

> **Media Narrative Intelligence Platform**
> *Contra-Vigilância Medática — 27 de Maio de 2026*

---

## Table of Contents

1. [Vision & Philosophy](#1-vision--philosophy)
2. [Architecture Overview](#2-architecture-overview)
3. [Phase 0 — Foundation](#3-phase-0--foundation)
4. [Phase 1 — Lusa Dependency](#4-phase-1--lusa-dependency)
5. [Phase 2 — The Broken Mirror](#5-phase-2--the-broken-mirror)
6. [Phase 3 — State Ecosystem](#6-phase-3--state-ecosystem)
7. [Phase 4 — Public Exposure](#7-phase-4--public-exposure)
8. [Tech Stack](#8-tech-stack)
9. [Data Sources](#9-data-sources)
10. [Ethics & Legal](#10-ethics--legal)

---

## 1. Vision & Philosophy

### The Problem

Portugal has a **narrative firewall** operating on two fronts:

| Front | Mechanism | Effect |
|-------|-----------|--------|
| **Domestic** | Lusa (97.24% state-owned) acts as gatekeeper for all national news | Media republicates Lusa content. Topics without Lusa coverage effectively don't exist. |
| **International** | Same ideological filter blocks or distorts news that contradicts the dominant narrative | Positive stories about "non-aligned" figures are silenced. Negative stories are amplified. Same event, different framing depending on ideological fit. |

The result: Portuguese citizens are **systematically misinformed** — not by what they're told, but by **what they're never shown**.

### Core Insight

> **"The most powerful propaganda isn't the lie you're told — it's the truth you never see."**

Existing fact-checkers in Portugal (including Lusa's own) are themselves part of this ecosystem. We do not need another arbiter of "truth." We need a **mirror** that shows the gap between what Portugal sees and what the world sees.

### Our Approach

| We do NOT | We DO |
|-----------|-------|
| Claim what is "true" | Show **divergence** between sources |
| Fact-check individual claims | Compare **coverage patterns** at scale |
| Rely on any single source | **Triangulate** across 20+ sources |
| Hide methodology | Make **all data & code transparent** |
| Judge editors' intentions | Measure **quantifiable patterns** |

### Success Criteria

- Any Portuguese citizen can see, in real time, **what news is being filtered** from their media
- The system provides **actionable evidence** (not opinion) of systematic bias
- Data is **verifiable by anyone** — journalists, researchers, opposition, international observers
- The project becomes a **public good** — referenced in academic research, cited in parliamentary debates

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES ★ FREE ★                              │
├─────────────┬──────────────┬──────────────┬──────────────┬─────────────────┤
│  🇵🇹 Lusa   │ 📰 Media PT  │ 🌍 Internac.  │ 🏛️ Estado    │ 📊 Inst. Pub.   │
│  lusa.pt    │ 15 outlets   │ 10+ sources  │ DR, AR, Gov  │ ERC reports     │
│  (RSS/web)  │ (scrape/RSS) │ (scrape/RSS) │ sites         │                 │
└─────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴────────┬────────┘
      │              │              │              │                │
      ▼              ▼              ▼              ▼                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│              🟢 GITHUB ACTIONS (scheduled cron) ★ FREE 🟢                  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  scrape.yml — runs every 15-60 min                                 │     │
│  │  ┌─────────────────────────────────────────────────────────────┐  │     │
│  │  │  Python: httpx → RSS feeds → trafilatura → lingua-py        │  │     │
│  │  │           → sentence-transformers (embeddings)               │  │     │
│  │  │           → pysentimiento (sentiment analysis)               │  │     │
│  │  │           → cross-lingual story matching (cosine sim)        │  │     │
│  │  │           → DBSCAN clustering                                │  │     │
│  │  │           → Write results to Supabase                         │  │     │
│  │  └─────────────────────────────────────────────────────────────┘  │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  report.yml — runs daily @ 09:00                                  │     │
│  │  → Generate "Jornal do Contra" (template + pre-computed metrics)   │     │
│  │  → Post to Telegram bot / update dashboard data                    │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│              🟢 SUPABASE FREE TIER ★ FREE 🟢                               │
│                                                                              │
│  ┌───────────────────────────────┐  ┌──────────────────────────────────┐    │
│  │  PostgreSQL (500MB free)      │  │  pgvector (embedding search)     │    │
│  │  → Articles + sources         │  │  → Cosine similarity on 1024d    │    │
│  │  → Crawl runs + logs          │  │  → Story cluster centroids       │    │
│  │  → Analysis results           │  │  → Cross-lingual matching        │    │
│  │  → State appointments + ads   │  │  → IVF index for speed           │    │
│  └───────────────────────────────┘  └──────────────────────────────────┘    │
│  🟢 Row Level Security: public-read, authenticated-write via GHA            │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│              ANALYSIS LAYER (0 LLM API calls — all local)                   │
├─────────────────┬─────────────────┬──────────────────┬──────────────────────┤
│ Story Matcher   │ Lusa Analyzer   │ Silence Detector │ State Analyzer       │
│ Cross-lingual   │ Dependency %    │ Intl. gap        │ Advertising          │
│ embeddings      │ Topic monopoly  │ Rank by          │ correlation          │
│ DBSCAN cluster  │ Framing compare │ importance       │ Template-based       │
│ ★ AI-free ★    │ ★ Template ★    │ ★ AI-free ★      │ ★ AI-free ★         │
├─────────────────┼─────────────────┼──────────────────┼──────────────────────┤
│ Phase 0.7-0.8   │ Phase 1         │ Phase 2          │ Phase 3              │
└─────────────────┴─────────────────┴──────────────────┴──────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│              🟢 GITHUB PAGES ★ FREE 🟢                                     │
│                                                                              │
│  ┌───────────────────────────────┐  ┌──────────────────────────────────┐    │
│  │  Static React App (Vite)      │  │  Data from Supabase (client SDK) │    │
│  │  Dark theme intelligence dash │  │  → Live metrics bar              │    │
│  │  D3.js + Recharts             │  │  → Story explorer w/ gap heatmap │    │
│  │  GitHub Actions: build+deploy │  │  → Figure asymmetry profiles     │    │
│  └───────────────────────────────┘  └──────────────────────────────────┘    │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│    🌐 TELEGRAM BOT (GitHub Actions — no server needed) ★ FREE 🌐           │
│    Daily "Jornal do Contra" report delivered via Telegram                   │
│    Anomaly alerts when metrics exceed ±2σ threshold                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

**💰 Custo total: $0/mês.**

*Nenhum servidor, nenhuma API paga, nenhum Docker em produção.* Tudo corre em GitHub Actions (scraping agendado), Supabase free tier (base de dados + pgvector), GitHub Pages (dashboard), e Telegram (alertas).

---

## 3. Phase 0 — Foundation

> **Objective:** Build the data collection and storage infrastructure that all subsequent phases depend on.

### Task 0.1 — Project Scaffolding
| Property | Value |
|----------|-------|
| **Dependencies** | None |
| **Effort** | Small |
| **Output** | Working dev environment |

- Initialize Python project with `uv` (fast package manager)
- Local dev: SQLite for testing, Supabase for production
- React + Vite + TypeScript frontend skeleton
- Pydantic AI agent skeletons for pipeline stages
- Pre-commit hooks (ruff, mypy)
- Environment variable configuration (.env.example)
- **No Docker required** — everything runs locally or in GitHub Actions

### Task 0.2 — Source Configuration System
| Property | Value |
|----------|-------|
| **Dependencies** | 0.1 |
| **Effort** | Small |
| **Output** | `sources.yaml` + parser |

Define all monitored sources in a single YAML configuration:

```yaml
sources:
  - id: lusa
    name: "Lusa — Agência de Notícias"
    type: rss          # rss | scrape | api | sitemap
    url: "https://www.lusa.pt/rss"
    language: pt
    category: agency
    schedule:
      interval_minutes: 15
    extraction: trafilatura

  - id: rtp_noticias
    name: "RTP Notícias"
    type: scrape
    url: "https://www.rtp.pt/noticias"
    language: pt
    category: public_broadcaster
    schedule:
      interval_minutes: 30
    extraction: newspaper4k
```

Sources classified by **category**:
| Category | Examples |
|----------|----------|
| `agency` | Lusa |
| `public_broadcaster` | RTP, RDP |
| `mainstream` | Expresso, Público, Observador, CM, JN, DN, SIC Notícias |
| `international` | Reuters, AFP, BBC, NYT, El País, Le Monde, DW, The Guardian, Associated Press |
| `government` | portugal.gov.pt, presidencia.pt |
| `parliament` | parlamento.pt (debates, comissões) |
| `official_gazette` | Diário da República Eletrónico |
| `regulator` | ERC (relatórios) |

### Task 0.3 — Lusa Website Scraper
| Property | Value |
|----------|-------|
| **Dependencies** | 0.1, 0.2 |
| **Effort** | Medium |
| **Output** | Scrapy spider for lusa.pt |

- Scrapy spider targeting `lusa.pt`
- Extract: title, full text, publication date, author/category, URL, unique ID
- Handle: pagination, RSS feed, article pages
- Rate limiting: 1 request/2 seconds (be respectful)
- Store raw HTML + extracted text
- Fallback: newspaper4k if trafilatura fails

### Task 0.4 — Portuguese Media Scrapers
| Property | Value |
|----------|-------|
| **Dependencies** | 0.1, 0.2 |
| **Effort** | Large (10+ spiders) |
| **Output** | Spiders for 10-15 Portuguese outlets |

- Target outlets: Expresso, Público, Observador, Correio da Manhã, JN, DN, SIC Notícias, TVI, Renascença, RTP, ECO, Jornal de Negócios, Notícias ao Minuto
- RSS feeds as primary channel (free, reliable)
- Web scraping as secondary (for full text behind summaries)
- Paywall handling: capture headlines + summaries for paywalled content
- Common spider base class for shared logic

### Task 0.5 — International Source Scrapers
| Property | Value |
|----------|-------|
| **Dependencies** | 0.1, 0.2 |
| **Effort** | Large (10+ spiders) |
| **Output** | Spiders for 10+ international outlets |

- Target sources: Reuters, Associated Press, AFP, BBC News, The New York Times, El País, Le Monde, Deutsche Welle, The Guardian, France24, Al Jazeera English
- Language detection per article (lingua-py)
- RSS + sitemap.xml parsing
- Content extraction with respect for robots.txt

### Task 0.6 — Database Schema
| Property | Value |
|----------|-------|
| **Dependencies** | 0.1 |
| **Effort** | Medium |
| **Output** | SQL migrations + models |

Core tables:

**`sources`** — Configuration of each monitored source
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| slug | VARCHAR(50) | Unique identifier (e.g., 'lusa', 'expresso') |
| name | VARCHAR(200) | Display name |
| category | VARCHAR(50) | `agency`, `mainstream`, `international`, etc. |
| language | VARCHAR(5) | Primary language |
| is_active | BOOLEAN | Whether currently being scraped |

**`articles`** — The core data table
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| source_id | UUID → sources | Foreign key |
| external_id | VARCHAR(255) | Source's own ID for dedup |
| url | TEXT | Canonical URL |
| title | TEXT | Article title |
| content_text | TEXT | Extracted full text |
| summary | TEXT | First 500 chars |
| author | VARCHAR(255) | Byline |
| published_at | TIMESTAMPTZ | Source's publication date |
| collected_at | TIMESTAMPTZ | When we scraped it |
| language | VARCHAR(5) | Detected language |
| content_hash | VARCHAR(64) | SHA-256 of content (dedup) |
| embedding | vector(1536) | pgvector column |

**`article_topics`** — Topics derived from NLP
| Column | Type | Notes |
|--------|------|-------|
| article_id | UUID | FK → articles |
| topic | VARCHAR(100) | Extracted topic label |
| confidence | FLOAT | 0.0 to 1.0 |

**`story_clusters`** — Groups of articles about the same event
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| centroid_embedding | vector(1536) | Average embedding of cluster |
| created_at | TIMESTAMPTZ | When cluster formed |
| updated_at | TIMESTAMPTZ | Last article added |
| title_auto | TEXT | AI-generated cluster title |

**`story_cluster_members`** — Articles in each cluster
| Column | Type | Notes |
|--------|------|-------|
| cluster_id | UUID | FK → story_clusters |
| article_id | UUID | FK → articles |
| similarity_score | FLOAT | Cosine similarity to centroid |

**`crawl_runs`** — Log of each scraping run
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| source_id | UUID | FK → sources |
| started_at | TIMESTAMPTZ | Run start |
| finished_at | TIMESTAMPTZ | Run end |
| articles_found | INT | Count |
| articles_new | INT | Previously unseen |
| status | VARCHAR(20) | `success`, `partial`, `failed` |
| error_log | TEXT | If failed |

**`analyses`** — Output of analysis agents
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| type | VARCHAR(50) | `lusa_dependency`, `silence`, `asymmetry`, etc. |
| target_id | UUID | Polymorphic FK |
| target_type | VARCHAR(50) | `outlet`, `topic`, `figure`, `story_cluster` |
| score | FLOAT | 0.0 to 1.0 |
| details | JSONB | Full analysis payload |
| period_start | TIMESTAMPTZ | Analysis window start |
| period_end | TIMESTAMPTZ | Analysis window end |
| created_at | TIMESTAMPTZ | When analysis ran |

Indexes:
- `articles(content_hash)` — unique, dedup
- `articles(published_at)` — time range queries
- `articles(source_id, published_at)` — per-source queries
- `articles` embedding — IVF index (pgvector)
- `story_cluster_members(cluster_id)` — cluster lookups

### Task 0.7 — Embedding Pipeline
| Property | Value |
|----------|-------|
| **Dependencies** | 0.6 |
| **Effort** | Medium |
| **Output** | Background worker for embeddings |

- Generate embeddings for each new article
- Model: `intfloat/multilingual-e5-large` (best cross-lingual performance) or Cohere Embed v3
- Embedding dimension: 1024-1536
- Batch processing for efficiency
- Store in pgvector column
- Scheduled job to backfill unembedded articles

### Task 0.8 — Story Matching (Cross-Lingual Clustering)
| Property | Value |
|----------|-------|
| **Dependencies** | 0.7 |
| **Effort** | Medium |
| **Output** | Clustering worker |

- Algorithm: cosine similarity on embeddings + DBSCAN clustering
- **Initial thresholds (require calibration):** similarity > 0.85 → same story, 0.70-0.85 → paraphrase, 0.55-0.70 → partial reference
- **Calibration requirement:** Before production use, validate thresholds against a labeled test set of ~100 manually verified article pairs
- Cross-lingual: because embeddings are multilingual, a story in PT, EN, ES, FR clusters together
- New articles are matched against existing clusters first (incremental)
- Orphan articles form new clusters
- Periodically recluster for consistency

**Why embeddings work for story matching:**
> A Lusa article about "Trump salva 8 mulheres da execução no Irão" and a BBC article "Trump intervenes to save 8 women from execution in Iran" will have near-identical embeddings despite different languages. The **semantic content** is the same even though the words are different.

### Task 0.9 — Scheduling & Orchestration
| Property | Value |
|----------|-------|
| **Dependencies** | 0.3, 0.4, 0.5 |
| **Effort** | Medium |
| **Output** | Scheduled run system |

- Use **GitHub Actions scheduled workflows** (cron syntax, free tier = 2,000 min/month)
- Schedule per source in a single workflow:
  - Lusa header fetch: every 15 minutes → triggers scrape job
  - Portuguese media: every 30 minutes
  - International: every 60 minutes
  - Government sites: every 6 hours
- Embedding + clustering runs inline in the same workflow
- Failure alerts via Telegram bot notification from GHA
- Recovery: retry up to 3 times with exponential backoff
- **GitHub Actions budget:** ~96 scrapes/day × ~1 min each = ~96 min/day = ~2,880 min/month. Free tier = 2,000 min/month for private repos, **unlimited for public repos.** O projeto será open source → zero custo.

### Task 0.10 — Data Quality & Monitoring
| Property | Value |
|----------|-------|
| **Dependencies** | 0.6, 0.9 |
| **Effort** | Small |
| **Output** | Health dashboard + alerts |

- Track: articles collected per day per source
- Detect: sudden drops in volume (source may have changed structure)
- Detect: duplicate rate (too many = scraper issue)
- Detect: empty content rate (extraction may be failing)
- **Simple GitHub Actions summary** (job summary with article counts)
- **Supabase query** — run SQL to check health (no Grafana needed)
- Optional: GitHub Pages health dashboard (lightweight)

### Task 0.11 — Testing Suite
| Property | Value |
|----------|-------|
| **Dependencies** | 0.3, 0.4, 0.5, 0.8 |
| **Effort** | Medium |
| **Output** | Automated + manual verification process |

- **Automated tests:**
  - Scraper quality tests: for each source, verify that extraction produces title, date, body text (presence checks)
  - Embedding accuracy: verify similar articles produce similar embeddings (regression test)
  - Story matching precision: label 50 known-matching and 50 known-non-matching article pairs; test clustering precision/recall
- **Manual verification (weekly):**
  - Human review of 20 random story matches to verify accuracy
  - Human review of 5 "silence" detections to verify the story actually exists internationally
  - Results logged and tracked over time

### Task 0.12 — Storage & Backup Strategy
| Property | Value |
|----------|-------|
| **Dependencies** | 0.6 |
| **Effort** | Small |
| **Output** | Storage policy + automated backup |

- **Data size estimate:** ~5,000 new articles/day × 2KB avg text = ~10MB/day text + embeddings = ~300MB/month. Supabase free tier = 500MB → ~1.5 months of full text. Adequado para começar.
- **Retention policy:**
  - Full article text: retained 1 month in Supabase (keep under 500MB free limit)
  - Summaries (500 chars), embeddings, metadata: retained permanently (very small)
  - Old full text: exported to compressed JSON in **public GitHub repo** (metadata only, respecting copyright) as data dumps
- **Backup:**
  - Daily: Supabase `pg_dump` exported to GitHub repo (free storage)
  - Weekly: Compressed JSON metadata snapshots committed to repo
  - Monthly: Public data archive release on GitHub

### Phase 0 — Success Criteria
- [ ] 10+ Portuguese sources being collected continuously
- [ ] 10+ international sources being collected continuously
- [ ] 10,000+ articles stored in database
- [ ] Embeddings generated for >95% of articles
- [ ] Story matching working cross-lingually (verified with manual spot checks)
- [ ] System runs 24/7 with <5% failure rate per source

---

## 4. Phase 1 — Lusa Dependency

> **Objective:** Quantify Lusa's role as gatekeeper of Portuguese news.

### Task 1.1 — Lusa Source Tagging
| Property | Value |
|----------|-------|
| **Dependencies** | 0.6 |
| **Effort** | Small |
| **Output** | Clear Lusa/Non-Lusa classification |

- Every article from `lusa` source is tagged `is_lusa: true`
- All other Portuguese articles are `is_lusa: false`
- Detect Lusa attribution in non-Lusa articles (e.g., "Segundo a Lusa...")

### Task 1.2 — Content Matching Pipeline
| Property | Value |
|----------|-------|
| **Dependencies** | 0.8, 1.1 |
| **Effort** | Medium |
| **Output** | Match scores for Lusa→Outlet pairs |

For each non-Lusa Portuguese article, find the most similar Lusa article from the same time window (±3 days):

```
similarity = cosine_similarity(embedding_lusa, embedding_outlet)

if similarity > 0.85 → "exact republication"
if 0.70 < similarity < 0.85 → "paraphrase/summary"
if 0.55 < similarity < 0.70 → "partial quote / inspired by"
if similarity < 0.55 → "original reporting (no Lusa source)"
```

Additionally:
- Check for direct citations: `"Segundo a Lusa"`, `"escreve a Lusa"`, `"fonte da Lusa"`
- Check byline: some outlets credit Lusa as author

### Task 1.3 — Lusa Dependency Score
| Property | Value |
|----------|-------|
| **Dependencies** | 1.2 |
| **Effort** | Small |
| **Output** | Dependency metrics per outlet |

**Per outlet, per time period (day/week/month):**

```
Lusa Dependency % = articles_matched_to_lusa / total_articles × 100
```

**Per topic:**
```
Topic Dependency % = articles_on_topic_matched_to_lusa / total_articles_on_topic × 100
```

**Time series:** Track dependency % over time — spikes may indicate events where Lusa had exclusive access.

**Example output (day/week view):**
| Outlet | Articles | Lusa-Derived | Dependency % |
|--------|----------|--------------|-------------|
| Público | 142 | 87 | 61.3% |
| Observador | 98 | 43 | 43.9% |
| Correio da Manhã | 176 | 52 | 29.5% |
| RTP Notícias | 203 | 154 | 75.9% |

### Task 1.4 — Topic Monopoly Analysis
| Property | Value |
|----------|-------|
| **Dependencies** | 1.2, 0.6 (topics) |
| **Effort** | Medium |
| **Output** | Topic dependency matrix |

- Cluster all articles into topics (NLP topic modeling via BERTopic)
- For each topic, calculate:
  - Total Portuguese articles on that topic
  - How many are Lusa-derived
  - How many outlets covered it (diversity)
- **Topics with >80% Lusa dependency = Lusa monopoly**
- **Topics with <3 outlets covering them = narrow distribution**

**Hypothesis validation:** Topics like "saúde", "educação", "política governamental" likely have high Lusa dependency. Topics like "desporto", "cultura", "opinão" likely have lower dependency.

### Task 1.5 — Lusa Agenda-Setting Metrics
| Property | Value |
|----------|-------|
| **Dependencies** | 1.2 |
| **Effort** | Medium |
| **Output** | Time-lag + gatekeeping metrics |

**Time lag:** For matched article pairs, measure:
- `Lusa publish time` → `Outlet publish time`
- Short lag (minutes) = automatic republication
- Long lag (hours/days) = editorial selection

**Gatekeeping ratio:**
```
Gatekeeping % = Lusa_articles_NOT_reproduced / Total_Lusa_articles × 100
```
Topics where gatekeeping is high = Lusa articles outlets chose to ignore. These are the topics **actively filtered out** by editors.

### Task 1.6 — Lusa Framing Divergence
| Property | Value |
|----------|-------|
| **Dependencies** | 1.2 |
| **Effort** | Large |
| **Output** | Framing comparison per story |

For stories that appear both in Lusa and outlets:
1. Extract title + first paragraph from both versions
2. Run sentiment analysis on both (fine-tuned BERT for Portuguese)
3. Extract key entities (who is mentioned, in what role)
4. Compare: does the outlet change the headline framing? Add/remove quotes? Change entity focus?

**Framing Divergence Score:**
```
divergence = 1 - cosine_similarity(sentiment_lusa, sentiment_outlet)
```

High divergence = outlet actively reframed the story away from Lusa's angle.

### Task 1.7 — Lusa Influence Report
| Property | Value |
|----------|-------|
| **Dependencies** | 1.3, 1.4, 1.5, 1.6 |
| **Effort** | Medium |
| **Output** | Automated daily/weekly report |

**Daily Lusa Influence Report:**
```
📊 RELATÓRIO LUSA — 27 Maio 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEPENDÊNCIA GLOBAL: 47.3% (▲2.1% vs ontem)

POR OUTLET:
  RTP Notícias:   75.9%  ■■■■■■■■■■
  Público:        61.3%  ■■■■■■■■
  Observador:     43.9%  ■■■■■■
  CM:             29.5%  ■■■■

TOP 5 TEMAS COM MAIOR DEPENDÊNCIA:
  1. Orçamento Estado:     94% ← Lusa monopoly
  2. Saúde Pública:        87%
  3. Educação:             82%
  4. Política Externa:     71%
  5. Imigração:            65%

TOP 5 TEMAS COM MENOR DEPENDÊNCIA:
  1. Desporto:             12%
  2. Cultura:              18%
  3. Tecnologia:           22%
  4. Opinião:               5%
  5. Internacional:        31%

GATEKEEPING: 23% das notícias Lusa NÃO foram republicadas
  Temas mais ignorados: [lista]
```

### Phase 1 — Success Criteria
- [ ] Lusa dependency % calculated for each outlet
- [ ] Topic monopoly analysis operational
- [ ] Time-lag + gatekeeping metrics running
- [ ] Framing divergence analysis working for top stories
- [ ] Daily Lusa Influence Report generated automatically
- [ ] 7+ days of continuous data for trend analysis
- [ ] Manual verification of 20 matched article pairs (accuracy >90%)

---

## 5. Phase 2 — The Broken Mirror

> **Objective:** Detect what international news is being silenced or distorted in Portuguese media.

### Task 2.1 — International Source Health
| Property | Value |
|----------|-------|
| **Dependencies** | 0.5, 0.10 |
| **Effort** | Small |
| **Output** | Verified international pipeline |

- Ensure all 10+ international sources are producing reliable data
- Verify: article counts, language detection, content quality
- Test cross-lingual embedding matching specifically (PT vs EN vs ES vs FR)

### Task 2.2 — Multi-Source Story Clustering
| Property | Value |
|----------|-------|
| **Dependencies** | 0.8, 2.1 |
| **Effort** | Medium |
| **Output** | Cross-lingual clusters verified to work |

- Expand story clustering to include ALL sources (Portuguese + international)
- Each cluster = one event being covered in multiple countries/languages
- Cluster properties:
  - `size`: total articles
  - `source_distribution`: how many different sources covered it
  - `country_distribution`: how many countries' sources covered it
  - `language_distribution`: how many languages
  - `timespan`: first reported → last reported

### Task 2.3 — Coverage Comparison Matrix
| Property | Value |
|----------|-------|
| **Dependencies** | 2.2 |
| **Effort** | Medium |
| **Output** | Coverage matrix per cluster |

For each story cluster, build a matrix:

| Story | 🇵🇹 Lusa | 🇵🇹 Media | 🇬🇧 BBC | 🇪🇸 El País | 🇫🇷 Le Monde | 🇩🇪 DW | 🇺🇸 NYT |
|-------|----------|-----------|---------|-----------|------------|--------|--------|
| Event A | ✅ | ✅✅✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Event B | ❌ | ❌ | ✅✅ | ✅ | ✅✅ | ✅ | ✅ |
| Event C | ✅ | ✅ (biased) | ✅ | ✅ | ✅ | ✅ | ✅ |

- ✅ = covered (light = 1-2 articles, heavy = 5+)
- ❌ = not covered
- (biased) = covered but with different framing

**Key metric:** For each cluster, count `sources_covered / total_sources` — the **Coverage Density**.

### Task 2.4 — Silence Detection (Buracos Negros)
| Property | Value |
|----------|-------|
| **Dependencies** | 2.3 |
| **Effort** | Medium |
| **Output** | Daily silence list |

**Algorithm:**
1. For each story cluster, calculate:
   - `international_coverage_score` = % of international sources covering it
   - `portuguese_coverage_score` = % of Portuguese sources covering it
2. Flag clusters where:
   - `international_coverage_score` > 0.5 (significant global coverage)
   - `portuguese_coverage_score` = 0 (zero Portuguese coverage)
3. Rank by `international_coverage_score` × `importance_boost` (derived from source prominence)

**Output: Daily "Buracos Negros" list**
```
🔴 BURACOS NEGROS — 27 Maio 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. [🇮🇷] Trump salva 8 mulheres da execução no Irão
   Cobertura internacional: 7/10 fontes
   Cobertura Portugal: 0/15 fontes
   Fontes: BBC, Reuters, AP, El País, The Guardian, CNN, NYT
   Gap: 🔴 100%

2. [🇦🇷] Milei anuncia superávit fiscal histórico
   Cobertura internacional: 6/10 fontes
   Cobertura Portugal: 1/15 fontes (Observador, tom negativo)
   Fontes: Reuters, AFP, Bloomberg, El País, Financial Times
   Gap: 🔴 90% (e com viés)
```

### Task 2.5 — Narrative Asymmetry by Figure
| Property | Value |
|----------|-------|
| **Dependencies** | 2.2, 0.6 |
| **Effort** | Large |
| **Output** | Asymmetry index for key figures |

**Process:**
1. Define monitored figures: Trump, Milei, Lula, Maduro, Zelensky, Putin, Netanyahu, Le Pen, etc.
2. For each figure, find all articles mentioning them (entity extraction)
3. Run sentiment analysis on each article (multi-lingual sentiment model)
4. Separate into: Portuguese sentiment vs International sentiment

**Asymmetry Index:**
```
asymmetry = |portuguese_sentiment_mean - international_sentiment_mean|
          × coverage_volume_ratio
```

Where:
- `portuguese_sentiment_mean` = average sentiment score (-1 to +1) across Portuguese articles
- `international_sentiment_mean` = average sentiment across international articles
- `coverage_volume_ratio` = how much more/less Portugal covers this figure vs the international average

**Interpretation:**
- Asymmetry near 0 → coverage is similar to international
- Asymmetry > 0.3 → significant divergence
- Sign tells direction: positive = PT more positive than world, negative = PT more negative

**Expected finding:** Trump and Milei will show significant **negative asymmetry** in Portugal (more negative coverage than the international average).

### Task 2.6 — Topic-Specific Narrative Divergence
| Property | Value |
|----------|-------|
| **Dependencies** | 2.2 |
| **Effort** | Large |
| **Output** | Narrative timeline per topic per country |

Select N major topics where narrative control is suspected:

| Topic | Why selected |
|-------|-------------|
| Guerra Ucrânia | Framing differences expected |
| Venezuela | Regime coverage asymmetry |
| Imigração | Political sensitivity in EU |
| Alterações Climáticas | Consensus vs skepticism framing |
| Economia | Left/right framing differences |

**For each topic:**
1. Collect all articles across all sources
2. Extract key entities, sentiments, framing language
3. Build a **narrative timeline** per country/outlet
4. Compare: do Portuguese outlets tell the same story as international ones?

**Visual output:** Time series of sentiment per country, overlaid, showing divergences.

### Task 2.7 — "Jornal do Contra" Generator
| Property | Value |
|----------|-------|
| **Dependencies** | 2.4, 2.5, 2.6 |
| **Effort** | Large |
| **Output** | Automated daily publication |

**Sections:**
1. **🔴 Buracos Negros do Dia** — Top 5 silenced stories (from Task 2.4)
2. **🟡 Viés do Dia** — Top 3 asymmetrically covered stories (from Task 2.5)
3. **🟢 Lusa Hoje** — Key Lusa dependency metrics (from Phase 1)
4. **📊 Assimetria por Figura** — Current asymmetry indices
5. **📰 O Que o Mundo Disse** — Direct quotes from international coverage of silenced stories
6. **🗺️ Mapa da Semana** — Weekly trend summary

**Generation:**
- PydanticAI agent compiles the report from pre-computed metrics
- Professional formatting with source links
- Available as: web page, Markdown, PDF, email
- AI-written summaries with citations to source articles

### Task 2.8 — Historical Baseline & Anomaly Detection
| Property | Value |
|----------|-------|
| **Dependencies** | 2.4, 2.5 |
| **Effort** | Medium |
| **Output** | Anomaly detection system |

- **Backfill:** Collect 30-90 days of historical data from all sources
- For each metric (silence count, asymmetry index, dependency %), establish:
  - Mean and standard deviation
  - Expected range (±2σ)
- **Anomaly alert:** When any metric exceeds expected range
  - E.g., "Silence detection rate is 3x higher than normal today"
  - E.g., "Lusa dependency on topic X suddenly dropped by 20 points"

### Phase 2 — Success Criteria
- [ ] Story clusters include both Portuguese and international sources
- [ ] Daily silence detection produces verified results (manual spot check)
- [ ] Asymmetry indices calculated for 10+ figures
- [ ] "Jornal do Contra" generates automatically
- [ ] Historical baseline established (30+ days)
- [ ] Anomaly detection operational
- [ ] At least one verified case of systematic silence presented as proof

---

## 6. Phase 3 — State Ecosystem

> **Objective:** Map the full state communication apparatus — not just Lusa, but the entire network of entities, budgets, and personnel that control information flow in Portugal.

### Task 3.1 — Government Communication Collector
| Property | Value |
|----------|-------|
| **Dependencies** | 0.3 (scraping patterns) |
| **Effort** | Medium |
| **Output** | Government feeds in the database |

- Scrape `portugal.gov.pt` — press releases, Conselho de Ministros summaries
- Scrape `presidencia.pt` — official statements, agendas
- Scrape 17 ministry communication pages (or centralize via `portugal.gov.pt`)
- Extract: title, text, date, ministry/author, topic
- Tag each article with government entity
- Content becomes part of the same `articles` table, tagged as `source_category: government`

### Task 3.2 — Diário da República Scraper
| Property | Value |
|----------|-------|
| **Dependencies** | 0.3 |
| **Effort** | Large |
| **Output** | Personnel appointment database |

**⚠️ Complexity note:** DRE has a complex taxonomy (Série I vs II, multiple sections, not all appointments tagged uniformly). This scraper requires upfront domain knowledge work.

**Sub-task 3.2a — DRE Taxonomy Mapping**
- Study DRE search API / categorization system
- Identify the exact publication series and keywords that signal "appointment to a media-related body"
- Map org-specific keywords: "Lusa", "RTP", "ERC", "Conselho de Opinião", "comunicação", "media", etc.
- Document the search strategy before writing code

**Sub-task 3.2b — Scraper Implementation**
- Scrape `dre.pt` for all appointments to media/information roles:
  - Lusa: Administração, Conselho Geral Independente
  - RTP: Conselho de Administração, Conselho de Opinião
  - ERC: Conselho Regulador
  - Government: communication cabinet members per ministry
  - Regulatory: ANACOM, CNE members
- Extract: person name, position, appointing authority, date, term
- Store in dedicated `appointments` table:
  | Column | Type |
  |--------|------|
  | person_name | TEXT |
  | position | TEXT |
  | organization | TEXT |
  | appointed_by | TEXT |
  | appointment_date | DATE |
  | termination_date | DATE (nullable) |
  | political_party | TEXT (if known/apparent) |
  | dre_reference | TEXT (URL to publication) |

### Task 3.3 — Parliamentary Debate Collector
| Property | Value |
|----------|-------|
| **Dependencies** | 0.3 |
| **Effort** | Large |
| **Output** | Parliamentary transcripts searchable |

- Scrape `parlamento.pt` — plenary debates, committee hearings
- Extract: date, speaker (name + party), topic, full speech text
- Store in `parliamentary_speeches` table:
  | Column | Type |
  |--------|------|
  | date | TIMESTAMPTZ |
  | speaker_name | TEXT |
  | speaker_party | VARCHAR(20) |
  | topic | TEXT |
  | speech_text | TEXT |
  | committee | VARCHAR(100) |
  | url | TEXT |

### Task 3.4 — Institutional Advertising Data
| Property | Value |
|----------|-------|
| **Dependencies** | ERC reports (external) |
| **Effort** | Medium |
| **Output** | State advertising database |

**⚠️ Risk note:** ERC reports are PDFs which are notoriously inconsistent. Tables may be images, column layouts may vary year-to-year. A fallback strategy is required.

**Primary approach:** Search for structured data sources first:
- Check if ERC provides spreadsheet (CSV/XLSX) exports alongside PDF reports
- Check `plataformadigital.gov.pt` (Plataforma Digital da Publicidade Institucional) for API access
- Check `base.gov.pt` (public procurement database) for communication service contracts

**Fallback (if only PDFs available):**
- Use `camelot-py` or `tabula-py` for table extraction
- Semi-automated: extract candidate tables, flag low-confidence extractions for human review
- Store validated data in `institutional_advertising` table:
  | Column | Type |
  |--------|------|
  | year | INT |
  | quarter | INT |
  | spending_entity | TEXT |
  | media_outlet | TEXT |
  | amount_eur | DECIMAL |
  | campaign_purpose | TEXT |

### Task 3.5 — Personnel Network Graph (Porta Giratória)
| Property | Value |
|----------|-------|
| **Dependencies** | 3.2 |
| **Effort** | Large |
| **Output** | Interactive influence graph |

- Build graph connecting people across roles over time
- Detect **"revolving door"** patterns:
  - Government communication role → Lusa administration → RTP → private media
  - Private media journalist → government communication role
  - ERC regulator → private media executive
- **Visualization:** Interactive D3.js graph where:
  - Nodes = people (sized by number of roles)
  - Node colors = person's party affiliation (if detected)
  - Edges = transitions from role to role
  - Click node → show career timeline

**Example query output:**
```
Maria Silva:
  2019-2021: Assessora de Comunicação, Ministério da Saúde
  2021-2023: Diretora de Informação, RTP
  2023-2025: Vogal do Conselho de Administração, Lusa
  ⚠️ Revolving door detected: Gov → RTP → Lusa
```

### Task 3.6 — Parliament-Media Gap Analysis
| Property | Value |
|----------|-------|
| **Dependencies** | 3.3, 2.2 |
| **Effort** | Medium |
| **Output** | Gap metrics |

- Extract all topics discussed in Parliament (from transcripts)
- Check: which topics appear in Lusa coverage within 3 days?
- Check: which topics appear in Portuguese media within 3 days?
- **Gap = topics discussed in Parliament that never reach the public**
- Track per party: which party's topics are most/least covered?

**Narrative Control Signal:**
If topics raised by opposition parties are systematically ignored by Lusa/media, while government-aligned topics are covered → evidence of partisan gatekeeping.

### Task 3.7 — Advertising-Editorial Correlation
| Property | Value |
|----------|-------|
| **Dependencies** | 3.4, 1.x (sentiment) |
| **Effort** | Large |
| **Output** | Correlation time series |

**Core question:** *"Do media outlets that receive more state advertising money cover the government more favorably?"*

**Method:**
1. For each media outlet, collect time series of:
   - `state_advertising_€` per quarter (from Task 3.4)
   - `government_sentiment_score` per quarter (from Phase 1 framing analysis)
2. Calculate Pearson correlation coefficient per outlet
3. **If correlation is positive and significant (>0.5):** outlet coverage of government correlates with advertising received
4. Detect **lagged effects**: does sentiment change 1-2 quarters after advertising changes?

**Secondary analysis:** Do outlets increase critical coverage of government when advertising is cut?

### Task 3.8 — Complete Influence Map Dashboard
| Property | Value |
|----------|-------|
| **Dependencies** | 3.1-3.7 |
| **Effort** | Large |
| **Output** | Unified influence visualization |

Combine all Phase 3 analyses into a single interactive dashboard:

- **Layer 1 — Media Dependencies:** Which outlets depend on Lusa (from Phase 1)
- **Layer 2 — State Advertising:** € flow from state entities to media
- **Layer 3 — Personnel Network:** Who connects state and media
- **Layer 4 — Parliamentary Gaps:** Topics lost in translation
- **Layer 5 — Timeline:** How all metrics change over time

**The "Capture Score"** — A single composite score per outlet:
```python
capture_score = (
    0.3 × lusa_dependency +
    0.2 × state_advertising_dependency +
    0.2 × revolving_door_count +
    0.2 × government_sentiment_correlation +
    0.1 × parliamentary_gap_ignored_topics
)
```

### Phase 3 — Success Criteria
- [ ] Government press releases being collected (all ministries)
- [ ] Diário da República appointments database populated (200+ entries)
- [ ] Parliamentary transcripts searchable (1+ month of data)
- [ ] Institutional advertising data parsed (ERC reports)
- [ ] Personnel network graph functional
- [ ] Parliament-media gap analysis producing results
- [ ] Advertising-editorial correlation calculated per outlet
- [ ] Influence map dashboard operational

---

## 7. Phase 4 — Public Exposure

> **Objective:** Make all findings accessible, actionable, and impossible to ignore.

### Task 4.1 — Public Dashboard
| Property | Value |
|----------|-------|
| **Dependencies** | Phase 0-3 APIs |
| **Effort** | Large |
| **Output** | Public-facing web application |

**React + Vite + TypeScript frontend with:**

- **Live Metrics Bar** (top of every page):
  - 🟢 Lusa Dependency: X%
  - 🔴 Silenced Stories Today: X
  - 🟡 Active Anomalies: X
- **Main Dashboard:**
  - Story gap heatmap (countries × topics)
  - Lusa dependency trend chart
  - Silence counter (daily bar chart)
  - Asymmetry index per monitored figure
- **Story Explorer:**
  - Search/browse story clusters
  - Side-by-side comparison: see how the same story was covered in PT vs 5 international sources
  - Color-coded "gap severity"
- **Figure Profile Pages:**
  - For each monitored figure: coverage volume, sentiment, asymmetry
  - Timeline of coverage events
  - Comparison bar: PT sentiment vs International sentiment

**Design principles:**
- Dark theme (intelligence dashboard aesthetic)
- Mobile-responsive
- Accessible (WCAG AA)
- Portuguese as primary language, English toggle

### Task 4.2 — Alert System
| Property | Value |
|----------|-------|
| **Dependencies** | 2.8 (anomaly detection) |
| **Effort** | Medium |
| **Output** | Telegram bot + email newsletter |

**Telegram/Discord Bot:**
- Daily summary at 09:00
- Real-time anomaly alerts:
  - "🚨 A Lusa dependency subiu 15% de repente no tema X"
  - "🚨 Buraco negro detetado: notícia importante não coberta em PT"
- Subscription by topic/outlet/figure

**Email Newsletter:**
- Weekly "Jornal do Contra" digest
- Top 10 silenced stories of the week
- Key metric changes
- "Deep dive" article on one specific finding

### Task 4.3 — Public API
| Property | Value |
|----------|-------|
| **Dependencies** | Phase 0-3 data |
| **Effort** | Medium |
| **Output** | REST + GraphQL API |

**Endpoints:**
- `GET /api/articles` — search articles by source, date, topic
- `GET /api/story-clusters` — browse story clusters with gap metrics
- `GET /api/metrics/lusa-dependency` — time series per outlet
- `GET /api/metrics/silence` — daily silence list
- `GET /api/metrics/asymmetry` — per-figure asymmetry indices
- `GET /api/state/advertising` — advertising data
- `GET /api/state/appointments` — personnel appointments
- `GET /api/state/parliament` — parliamentary transcripts with coverage flags

**Features:**
- API key registration (free tier for researchers)
- Pagination, filtering, date ranges
- CORS enabled for public use
- Rate limiting (100 req/min per key)
- OpenAPI/Swagger documentation

### Task 4.4 — Transparency & Methodology
| Property | Value |
|----------|-------|
| **Dependencies** | None |
| **Effort** | Small |
| **Output** | Public methodology page |

- Full source code on GitHub (open source)
- Methodology whitepaper explaining:
  - How story matching works
  - How silence detection works
  - How asymmetry indices work
  - Known limitations and edge cases
- Raw data exports (CSV, JSON) for academic research
- Bug/issue tracker for community contributions

**Why this matters:** The project's authority comes from transparency. Anyone must be able to verify, critique, and replicate the findings.

### Task 4.5 — Archival & Data Integrity
| Property | Value |
|----------|-------|
| **Dependencies** | Phase 0-3 |
| **Effort** | Medium |
| **Output** | Immutable data archive |

- All collected data stored in append-only format
- Daily snapshots committed to public Git repository (compressed metadata, NOT full article text to respect copyright)
- Cryptographic hash chain to verify data integrity
- Downloadable data dumps for researchers

---

## 8. Tech Stack

> **💰 Tudo gratuito. $0/mês operacionais.**

### Runtime (Scraping + Analysis)

| Component | Technology | Why |
|-----------|-----------|-----|
| Runner | **GitHub Actions** (scheduled cron) | Free for public repos. No server to manage. |
| Scraping | **httpx** + **feedparser** + **trafilatura** | Lighter than Scrapy for RSS-based fetching. Non-blocking async. |
| Article Extraction | **trafilatura** + **newspaper4k** | Best-in-class text extraction. Runs on CPU. |
| Language Detection | **lingua-py** | 75+ languages, 0 API calls, CPU only. |
| Embeddings | **sentence-transformers** (`multilingual-e5-large`) | Cross-lingual semantic search. Local CPU inference. |
| Sentiment (PT/ES/EN) | **pysentimiento** | Pre-trained sentiment + emotion for Portuguese/Spanish/English. Free, local CPU. |
| Sentiment (other) | **cardiffnlp/twitter-xlm-roberta** (HuggingFace) | Multilingual sentiment. Local CPU. |
| NLP | **spaCy** (`pt_core_news_lg`) | Portuguese NER, POS tagging, dependency parsing. |
| Topic Modeling | **BERTopic** | Clusters articles into topics. No LLM needed. |
| Story Matching | **NumPy** + **scikit-learn** (DBSCAN) | Cosine similarity on embeddings. Clustering in Python. |
| Report Generation | **Jinja2 templates** | Template-based "Jornal do Contra". No LLM calls. |

### Database

| Component | Technology | Why |
|-----------|-----------|-----|
| Database | **Supabase Free Tier** (PostgreSQL 16 + pgvector) | 500MB storage, pgvector included. Free forever. Row Level Security. |
| Vector Search | **pgvector** (IVFFlat index) | Cosine similarity search on 1024d embeddings. |
| ORM | **SQLAlchemy** (async) | Pythonic DB access. Same code works with SQLite (dev) or Postgres (prod). |
| Migrations | **Alembic** via GitHub Action | Run schema migrations on deploy. |

### Frontend (Dashboard)

| Component | Technology | Why |
|-----------|-----------|-----|
| Framework | **React** (Vite + TypeScript) | Fast dev, type-safe. |
| Visualization | **D3.js** + **Recharts** | Custom interactive graphs. |
| Styling | **Tailwind CSS** | Utility-first, dark theme friendly. |
| State | **Zustand** | Lightweight, TypeScript-first. |
| Routing | **React Router** | Standard. |
| Hosting | **GitHub Pages** | Free static site hosting. Deploy via GHA. |
| Data Access | **Supabase JS Client** | Read data directly from Supabase via Row Level Security. |

### Infrastructure (Dev)

| Component | Technology | Why |
|-----------|-----------|-----|
| Local DB | **SQLite** (via SQLAlchemy) | Zero-setup dev database. Same ORM. |
| Package Manager | **uv** | Fast Python package manager. |
| CI/CD | **GitHub Actions** | Build, test, deploy all in one. Free tier sufficient. |

### AI Models (All Local, $0 API Costs)

| Use Case | Model | Size | Runs On |
|----------|-------|------|---------|
| Cross-lingual embeddings | `intfloat/multilingual-e5-large` | 2.2GB | GitHub Actions runner CPU |
| Portuguese NER | `pt_core_news_lg` (spaCy) | 50MB | CPU (instant) |
| Sentiment (PT/ES/EN) | `pysentimiento` | 500MB | CPU (fast inference) |
| Sentiment (Multi) | `cardiffnlp/xlm-roberta-base-sentiment` | 1.1GB | CPU |
| Topic labeling | **BERTopic** (TF-IDF fallback) | 100MB | CPU |
| Report generation | **Jinja2 templates** (not AI) | 0KB | No inference needed |

**Note:** All models run on CPU. GitHub Actions runners have 2-4 cores and ~7GB RAM, sufficient for batch processing 50-100 articles per workflow run. Embeddings are the heaviest operation (~2s per article) — acceptable for batch sizes of 50-100 per run.

### What We Removed (to reach $0)

| Previously | Cost | Replaced With | New Cost |
|-----------|------|---------------|----------|
| VPS (Hetzner/OVH) | $5-15/mo | GitHub Actions runners | $0 |
| Docker Compose in prod | $0 (but needs server) | GitHub Actions + Supabase | $0 |
| PostgreSQL on VPS | Included in VPS cost | Supabase Free Tier | $0 |
| Claude API (sentiment) | $45-90/mo | pysentimiento (local CPU) | $0 |
| Claude API (reports) | $15/mo | Jinja2 templates | $0 |
| Claude API (framing) | $30/mo | Embedding cosine comparison | $0 |
| Prometheus + Grafana | $0 (self-hosted) | GitHub Actions summaries | $0 |
| MinIO / S3 | $0-5/mo | GitHub repo storage | $0 |
| **Total** | **$50-155/mo** | **→ Total** | **$0/mo** |

---

## 9. Data Sources (Complete List)

### 🇵🇹 Portuguese News

| Source | Type | URL | Priority |
|--------|------|-----|----------|
| Lusa | RSS/Scrape | lusa.pt | 🔴 Critical |
| RTP Notícias | Scrape/RSS | rtp.pt/noticias | 🔴 Critical |
| Público | Scrape/RSS | publico.pt | 🔴 Critical |
| Expresso | Scrape/RSS | expresso.pt | 🔴 Critical |
| Observador | Scrape/RSS | observador.pt | 🔴 Critical |
| Correio da Manhã | Scrape/RSS | cmjornal.pt | 🔴 Critical |
| SIC Notícias | Scrape/RSS | sicnoticias.pt | 🟡 Important |
| TVI Notícias | Scrape/RSS | tvi.pt | 🟡 Important |
| Jornal de Notícias | Scrape/RSS | jn.pt | 🟡 Important |
| Diário de Notícias | Scrape/RSS | dn.pt | 🟡 Important |
| Renascença | Scrape/RSS | rr.sapo.pt | 🟡 Important |
| ECO | Scrape/RSS | eco.sapo.pt | 🟡 Important |
| Jornal de Negócios | Scrape/RSS | jornaldenegocios.pt | 🟡 Important |
| Notícias ao Minuto | Scrape/RSS | noticiasaominuto.com | 🟡 Important |
| SAPO 24 | Scrape/RSS | sapo.pt | 🟡 Important |

### 🌍 International News

| Source | Type | Language | Priority |
|--------|------|----------|----------|
| Reuters | Scrape/RSS | EN | 🔴 Critical |
| Associated Press | Scrape/RSS | EN | 🔴 Critical |
| AFP | Scrape/RSS | FR/EN | 🔴 Critical |
| BBC News | Scrape/RSS | EN | 🔴 Critical |
| The Guardian | Scrape/RSS | EN | 🔴 Critical |
| El País | Scrape/RSS | ES | 🔴 Critical |
| Le Monde | Scrape/RSS | FR | 🟡 Important |
| Deutsche Welle | Scrape/RSS | EN/DE | 🟡 Important |
| France24 | Scrape/RSS | EN/FR | 🟡 Important |
| The New York Times | Scrape/RSS | EN | 🟡 Important |
| Al Jazeera English | Scrape/RSS | EN | 🟡 Important |

### 🏛️ State Institutions

| Source | Type | URL | Priority |
|--------|------|-----|----------|
| Governo (CM) | Scrape | portugal.gov.pt | 🔴 Critical |
| Presidência | Scrape | presidencia.pt | 🔴 Critical |
| Assembleia República | Scrape | parlamento.pt | 🔴 Critical |
| Diário da República | Scrape | dre.pt | 🔴 Critical |
| ERC | PDF scrape | erc.pt | 🔴 Critical |
| Ministério da Saúde | Scrape | Portal de cada ministério | 🟡 Important |
| Demais ministérios | Scrape | Vários | 🟡 Important |

---

## 10. Ethics & Legal

### Data Collection

| Concern | Mitigation |
|---------|-----------|
| **Copyright** | We store metadata (title, summary, embedding, URL) and extracted text. Full articles are stored only for internal analysis. Public dashboards show summaries + links to original sources. |
| **robots.txt** | All scrapers respect robots.txt. Aggressive crawling is avoided (rate limiting). |
| **Paywalls** | We do NOT bypass paywalls. Only public-facing content is collected. Paywalled articles get headline + summary only. |
| **Personal data** | No personal data is collected. Person names appear only when they are public figures or public officials. |
| **GDPR** | We process only publicly available information. No cookies, no tracking, no user data collection. |

### Transparency

- **No hidden agenda:** The project's purpose, methodology, and funding (if any) are fully public
- **Open source:** All code is public
- **Verifiable data:** Data sources are listed. Anyone can verify findings by visiting the original articles.
- **Corrections policy:** If an error is found in our analysis, it must be corrected and noted.

### Independence

- **No political affiliation:** The project exposes narrative control from ANY direction — left, right, center
- **No funding from political entities:** To maintain credibility, the project must not accept funding from political parties, governments, or entities with political agendas
- **Transparent funding:** If the project grows to need funding, sources are publicly disclosed

### Resilience

- **Legal protection:** The project is a research and transparency initiative. All claims are based on comparative data, not assertions of fact.
- **Infrastructure:** If hosted in Portugal becomes legally risky, consider hosting jurisdiction with stronger press freedom protections (e.g., Iceland, Netherlands)
- **Redundancy:** All data is backed up across multiple jurisdictions

---

## Appendix A — Task Dependency Graph

```
Phase 0                                    Phase 1                Phase 2
─────────                                  ────────               ────────
0.1 ──▶ 0.2 ──▶ 0.3 ──▶ 0.6 ──▶ 0.7 ──▶ 0.8 ──▶ 1.2 ──▶ 1.3 ──▶ 2.2 ──▶ 2.3 ──▶ 2.4
         │         │         │              │         │         │         │
         │         │         │              │         ├──▶ 1.4   │         │
         │         │         │              │         ├──▶ 1.5   │         ├──▶ 2.5
         │         │         │              │         └──▶ 1.6   │         │
         │         │         │              │                     │         └──▶ 2.6
         │         │         │              │                     │
         │         │         │              │                     └──▶ 1.7   └──▶ 2.7
         │         │         │              │
         │         └──▶ 0.4──┤              │                      Phase 3
         │                     0.9 ──▶ 0.10  │                      ────────
         └────────────▶ 0.5───┘              │              3.1 ──────────────┐
                                              │              3.2 ──────────┐   │
                                              │              3.3 ──────┐   │   │
                                              │              3.4 ──┐   │   │   │
                                              │                     │   │   │   │
                                              │                     ▼   ▼   ▼   ▼
                                              │              3.5 ◀──┴───┴───┴───┘
                                              │              3.6 ◀──┴───┴───┘
                                              │              3.7 ◀──┴───┴───┘
                                              │              3.8 ◀──┴───┴───┴───┘
                                              │
Phase 4                                       │
───────                                       │
4.1 ◀─────────────────────────────────────────┘
4.2 ◀── 2.8
4.3 ◀── Phase 0-3 APIs
4.4 ◀── (independent)
4.5 ◀── Phase 0-3 data
```

## Appendix B — Quick-Start Task Sequence (Recommended Build Order)

The following is the recommended sequence to get a working system as fast as possible:

**Week 1-2: MVP Pipeline**
1. 0.1 → Project scaffolding (dev environment, server)
2. 0.2 → Source configuration system
3. 0.3 → Lusa scraper (just 1 source to prove pipeline)
4. 0.6 → Database schema (core tables only)
5. 0.9 → Scheduling (crawl Lusa every 15 min)
6. 0.7 → Embedding pipeline (generate embeddings for new articles)

**Week 3-5: Scale Collection (Portuguese First)**
7. 0.4 → Portuguese media scrapers (top 5 outlets)
8. 0.8 → Story matching (cross-lingual clustering, Portuguese sources first)
9. 0.10 → Data quality monitoring
10. 0.11 → Testing suite (calibrate thresholds with Portuguese sources)

**Note:** International scraping requires more time — international sites have anti-scraping measures (Cloudflare, JS rendering). Focus on Portuguese pipeline stability before adding international sources.

**Week 5-6: Lusa Analysis**
11. 1.2 → Content matching
12. 1.3 → Lusa dependency score
13. 1.4 → Topic monopoly analysis
14. 1.7 → Lusa influence report

**Week 7-9: International + Silence Detection**
15. 0.5 → International scrapers (top 5 sources, after Portuguese pipeline is stable)
16. 2.2 → Multi-source clustering (add international clusters)
17. 2.3 → Coverage matrix
18. 2.4 → Silence detection
19. 2.5 → Asymmetry indices (start with 3 figures)

**Week 9-10: Public Exposure**
19. 4.1 → Public dashboard (MVP)
20. 2.7 → "Jornal do Contra" (daily)
21. 4.2 → Alert system (Telegram)

**Week 10-14: State Ecosystem & Refinement**
22. Phase 3 tasks start (government, advertising, parliament — less complex first)
23. 2.8 → Historical baseline & anomaly detection
24. 4.3 → Public API
25. 3.2 → Diário da República (higher complexity — phase later)
26. Phase 4 refinements (full dashboard, newsletter)

---

## Appendix C — Zero-Cost Analysis

> **💰 $0/mês operacionais. Sem servidores. Sem APIs pagas.**

**Assumptions:** ~5,000 articles/day. All processing runs on GitHub Actions free runners.

### What Costs What

| Component | How It's Free |
|-----------|---------------|
| **Scraping** (5,000 articles/day) | GitHub Actions free tier: 2,000 min/month for private repos. **Unlimited for public repos.** Each scrape run ~1 min. 200 min/month total. ✅ Free. |
| **Embeddings** (multilingual-e5-large) | `sentence-transformers` runs on GHA CPU. ~2s/article × 100 articles/run = ~3 min of CPU/run. ✅ Free (part of GHA allocation). |
| **Sentiment analysis** (pysentimiento) | Local HuggingFace model on CPU. ~0.5s/article. ✅ Free. |
| **Database** (PostgreSQL + pgvector) | Supabase Free Tier: 500MB DB, pgvector included, Row Level Security. ✅ Free forever. |
| **Dashboard hosting** | GitHub Pages: unlimited static sites for public repos. Deploy via GHA. ✅ Free. |
| **Telegram bot** | Telegram API is free. Bot runs as part of GHA workflow. ✅ Free. |
| **Data storage** | ~300MB/month text + embeddings. Supabase free 500MB covers ~1.5 months. Old data exported to GitHub repo (free). ✅ Free. |

### GitHub Actions Budget Calculation

| Workflow | Runs/Day | Duration | Daily Min | Monthly Min |
|----------|----------|----------|-----------|-------------|
| `scrape-lusa.yml` | 48 (every 30min) | ~30s | 24min | 720min |
| `scrape-pt-media.yml` | 24 (every 60min) | ~1min | 24min | 720min |
| `scrape-international.yml` | 12 (every 2h) | ~1min | 12min | 360min |
| `analyze-daily.yml` | 1 (daily) | ~5min | 5min | 150min |
| `deploy-frontend.yml` | 1 (on push) | ~2min | — | ~30min |
| **Total** | | | **~65min** | **~1,980min** |

**Free tier (public repos): Unlimited.** ✅
**Free tier (private repos): 2,000 min/month.** We're at 1,980 min/month — very tight.

**Recommendation:** Make the project **public** on GitHub. No cost worries ever.

### What If We Need More Power?

| Scenario | Solution | Cost |
|----------|----------|------|
| Need more GHA minutes | Make repo public → unlimited minutes | $0 |
| Supabase 500MB fills up | Export old full text to GitHub, keep summaries + embeddings | $0 |
| Need faster embeddings | Use `all-MiniLM-L6-v2` (smaller, 80MB vs 2.2GB) | $0 (faster but slightly less accurate) |
| Need real-time dashboard | Keep static pages, refresh every hour via GHA cron | $0 |
| Need more storage | Supabase free = 500MB. Next: $25/mo for 8GB (skip unless needed) | $25/mo (future) |

**Bottom line:** The project runs entirely on free tiers. If it grows to need paid infrastructure, it will have proven its value first.

---

*End of Design Document — Project Vespeiro v1.0*
