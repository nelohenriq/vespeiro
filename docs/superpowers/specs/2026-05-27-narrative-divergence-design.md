# Narrative Divergence Analyzer — Design Document

> **Detetar distorção, omissão e reframing em media portugueses**
> *Parte do Projecto Vespeiro — 27 de Maio de 2026*

---

## Table of Contents

1. [Problem & Motivation](#1-problem--motivation)
2. [Architecture Overview](#2-architecture-overview)
3. [Component Design](#3-component-design)
4. [Data Flow & Pipeline Integration](#4-data-flow--pipeline-integration)
5. [Scoring System](#5-scoring-system)
6. [Edge Cases & Error Handling](#6-edge-cases--error-handling)
7. [Testing Strategy](#7-testing-strategy)
8. [Dependencies & Timeline](#8-dependencies--timeline)

---

## 1. Problem & Motivation

### The Problem

Portuguese media outlets frequently **distort original sources** — Lusa, Reuters, AFP, BBC, etc. — when republishing or adapting news. The distortion takes three forms:

| Type | Description | Example |
|------|-------------|---------|
| **Omission** | Facts from the original are selectively removed | Original: "2.3M€ em fundos da UE" → PT: "investimento de milhões" |
| **Framing shift** | The tone/angle of the story changes | Original: neutral headline → PT: negative/sensational headline |
| **Selective quoting** | Quotes from the original are altered or only partially reproduced | Original: "the minister criticized the policy" → PT: "the minister made comments" |

### Why Existing Plans Don't Cover This

The current Vespeiro design covers:
- **Fase 1.6 — Lusa Framing Divergence:** Sentiment comparison between Lusa and outlets (Lusa-only)
- **Fase 2.5 — Narrative Asymmetry by Figure:** How figures are framed in PT vs international media

This new module **generalizes** and **deepens** those: it compares ANY source (Lusa, international, or official) with ANY Portuguese outlet version, across multiple dimensions simultaneously.

### Success Criteria

- Given a story cluster with an identifiable original source → produce a structured `DivergenceReport`
- Detect **omission**: identify specific facts/entities that were removed
- Detect **framing shift**: quantify sentiment change between source and outlet
- Detect **quote alteration**: flag quotes that were changed or removed
- Calibrate: manual verification of 20 article pairs with >80% accuracy

---

## 2. Architecture Overview

### Position in the Pipeline

```
Scraping Pipeline                 Story Matching                     Divergence Analysis
─────────────────                 ──────────────                     ───────────────────
LusaSpider ─┐                                                       ┌─ extractor.py
            │                   StoryMatcher                         │  (entity extraction,
PortugalMediaSpider ─┐          (Phase 0.8)         DivergenceAnalyzer  quote detection)
            │        │                 │                   │        │
            ▼        ▼                 ▼                   ▼        ├─ comparator.py
       Article DB ──→ Article Clusters ──→ Original Source ID ──→   │  (omission, framing,
            ▲                          ▲                   ▲        │   quote comparison)
            │                          │                   │        │
InternationalSpider ─┘                 │                   │        └─ reporter.py
                                        │                   │           (JSON/MD output)
SentimentAnalyzer ◀─────────────────────┘                   │
(Phase 0.9)                                                    │
                                                               ▼
                                                         DivergenceReport DB
                                                               │
                                                               ▼
                                                      Dashboard / API / Reports
```

### Module Location

```
vespeiro/backend/src/analysis/divergence/
├── __init__.py
├── models.py          # Pydantic models: Fact, Quotation, DivergenceReport
├── extractor.py       # Entity extraction, quote detection from a single article
├── comparator.py      # Compare two articles: omission + framing + quotes
└── reporter.py        # Structured report generation (JSON, Markdown)
```

---

## 3. Component Design

### 3.1 `models.py` — Data Types

```python
class FactCategory(str, Enum):
    MONEY = "money"        # "2.3M€", "$500,000"
    PERCENTAGE = "pct"     # "47%", "três quartos"
    DATE = "date"          # "27 de Maio", "March 2026"
    PERSON = "person"      # "António Costa", "Donald Trump"
    LOCATION = "location"  # "Lisboa", "Brasil"
    ORGANIZATION = "org"   # "UE", "ONU", "Governo"
    NUMBER = "number"      # "8 mulheres", "15 mil"

class Fact(BaseModel):
    text: str
    category: FactCategory
    span_start: int       # Character position in source text
    span_end: int

class Quotation(BaseModel):
    speaker: str | None   # The person being quoted (NER-extracted)
    text: str             # The quoted text
    span_start: int
    span_end: int

class ExtractedArticle(BaseModel):
    source_id: str
    title: str
    content_text: str
    language: str
    facts: list[Fact]
    quotations: list[Quotation]
    sentences: list[str]
    word_count: int

class DivergenceReport(BaseModel):
    """Full divergence report for one source→outlet pair."""
    story_cluster_id: str
    original_source_id: str        # e.g. "lusa", "reuters"
    portuguese_outlet_id: str      # e.g. "publico", "expresso"
    analyzed_at: datetime
    
    # Overall scores
    overall_divergence_score: float   # 0.0 (none) to 1.0 (complete)
    
    # Dimension scores
    fact_omission_score: float | None # 0.0-1.0
    sentiment_shift: float | None     # -1.0 to +1.0
    quote_fidelity: float | None      # 0.0-1.0
    headline_divergence: float | None # 0.0-1.0
    
    # Evidence
    omitted_facts: list[Fact]
    preserved_facts: list[Fact]
    altered_quotes: list[dict]  # [{original, portuguese, speaker}]
    headline_original: str
    headline_portuguese: str
    
    # Sentiment
    original_sentiment: dict | None  # {sentiment, probas}
    portuguese_sentiment: dict | None

class OutletDivergenceSummary(BaseModel):
    """Aggregated metrics per outlet over a time window."""
    outlet_id: str
    period_start: datetime
    period_end: datetime
    stories_analyzed: int
    avg_omission: float
    avg_sentiment_shift: float
    avg_quote_fidelity: float
    avg_headline_divergence: float
    top_omitted_facts: list[str]
```

### 3.2 `extractor.py` — Article Fact Extraction

**Purpose:** Take one article (title + content_text) and extract structured facts, entities, and quotations.

**Input:** `Article` (source_id, title, content_text, language)
**Output:** `ExtractedArticle`

**Implementation details:**

1. **Language detection** → select spaCy model:
   - `"pt"` → `pt_core_news_lg`
   - `"en"` → `en_core_web_lg`
   - `"es"` → `es_core_news_lg`
   - Fallback → use PT model and accept lower accuracy

2. **Entity extraction** (spaCy NER):
   - `MONEY`: `MONEY` label, regex for `€`, `$`, `mil`, `milhões`, `milhares`
   - `PERCENTAGE`: `PERCENT` label, regex for `%`, `por cento`
   - `DATE`: `DATE` label
   - `PERSON`: `PER`/`PERSON` label
   - `LOCATION`: `LOC` label
   - `ORGANIZATION`: `ORG` label
   - `NUMBER`: `QUANTITY`/`CARDINAL` label

3. **Quote detection** (regex-based):
   - Direct quotes: `"..."`, `«...»`, `"..."`
   - Attribution patterns PT: `disse X`, `afirmou Y`, `segundo Z`, `conforme X`, `explicou X`, `acrescentou X`
   - Attribution patterns EN: `said X`, `according to X`, `told X`, `stated X`
   - Match speaker entity to `PERSON` NER when possible

4. **Sentence splitting:** Use spaCy sentence boundary detection.

5. **Article comparison preparation:**
   - Normalize whitespace
   - Strip common boilerplate (copyright notices, "leia também" sections)

**Dependencies:** spaCy, pt_core_news_lg, en_core_web_lg, es_core_news_lg

### 3.3 `comparator.py` — Cross-Article Comparison

**Purpose:** Compare the original source article with the Portuguese outlet version across all dimensions.

**Input:** `(ExtractedArticle original, ExtractedArticle portuguese_version, sentiment_original, sentiment_portuguese)`
**Output:** `DivergenceReport`

**Matching logic:**
- Articles are matched by belonging to the same `StoryCluster` (from Phase 0.8)
- Within a cluster, the **original source** is identified as:
  1. Earliest-published article from a Lusa source (if present)
  2. Earliest-published article from an international source (if no Lusa)
  3. If only PT outlets → skip (no original to compare against)

**Dimension calculations:**

#### Fact Omission Score
```
omission_score = omitted_facts / (omitted_facts + preserved_facts)
```
- A fact is "preserved" if the same entity/value appears in the Portuguese version
- Matching is fuzzy: "2.3M€" ≈ "2,3 milhões de euros"
- A fact is "omitted" if no match is found in the PT version
- Facts are weighted by category (money/date > person/location)

#### Sentiment Shift
```
sentiment_shift = sentiment_portuguese.score - sentiment_original.score
```
- Uses `pysentimiento` scores (Phase 0.9)
- Negative: PT version is more negative
- Positive: PT version is more positive
- Near zero: neutral reframing

#### Quote Fidelity
```
quote_fidelity = verbatim_quotes / total_quotes_in_original
```
- A quote is "verbatim" if the Portuguese text contains the same quote
- Case-insensitive, punctuation-tolerant matching
- A quote is "altered" if the speaker is the same but text differs
- A quote is "omitted" if the speaker or topic is absent from PT version

#### Headline Divergence
```
headline_divergence = 1 - cosine_similarity(embedding_original_title, embedding_pt_title)
```
- Uses the same `SentenceTransformer` as Phase 0.7
- Higher score = headline tells a different story

#### Overall Divergence Score
```python
overall = (
    0.35 * fact_omission_score +
    0.25 * abs(sentiment_shift) +       # absolute: magnitude matters, not direction
    0.20 * (1 - quote_fidelity) +
    0.20 * headline_divergence
)
```
Weights are configurable and will be calibrated with manual test data.

### 3.4 `reporter.py` — Report Generation

**Purpose:** Format divergence analysis results for different consumers.

**Output formats:**

1. **JSON** (primary — for API/dashboard):
```json
{
  "story_cluster_id": "abc-123",
  "original_source": "reuters",
  "portuguese_outlet": "publico",
  "overall_divergence": 0.62,
  "omission": { "score": 0.71, "omitted": ["2.3M€", "UN report date"], "preserved": ["António Costa"] },
  "sentiment_shift": { "score": 0.34, "original": "NEG", "portuguese": "NEU" },
  "quote_fidelity": 0.50,
  "headline_divergence": 0.45
}
```

2. **Markdown** (for reports / Telegram):
```markdown
📊 DIVERGÊNCIA: Reuters → Público
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📐 Geral:     62%
📝 Omissão:   71% — 5/7 factos omitidos
   Perdido: "2.3M€", "relatório da ONU"
🎭 Framing:   Original NEG → Público NEU
💬 Citações:  2/4 preservadas, 1 alterada
📰 Manchete:  45% divergente
```

3. **Aggregated summary** (per outlet, per day/week):
```json
{
  "outlet": "publico",
  "period": "2026-05-20 to 2026-05-27",
  "stories_analyzed": 142,
  "avg_omission": 0.38,
  "avg_sentiment_shift": 0.12,
  "avg_quote_fidelity": 0.72
}
```

---

## 4. Data Flow & Pipeline Integration

### Trigger

The divergence analyzer runs as a **GitHub Actions batch job** (`analyze.yml`):

```yaml
name: Daily Analysis

on:
  schedule:
    - cron: '0 */6 * * *'   # Every 6 hours
  workflow_dispatch:

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install dependencies
        run: pip install -e backend/
      - name: Download spaCy models
        run: |
          python -m spacy download pt_core_news_lg
          python -m spacy download en_core_web_lg
      - name: Run divergence analysis
        run: python backend/run_analysis.py --divergence
```

### Dependencies on Other Phases

| Phase / Module | Dependency | What We Need |
|---------------|-----------|--------------|
| **Phase 0.7** (Embedder) | Required | `SentenceTransformer` for headline comparison |
| **Phase 0.8** (StoryMatcher) | Required | `StoryCluster` objects — can't compare without knowing what's the same story |
| **Phase 0.9** (SentimentAnalyzer) | Required | `SentimentAnalyzer.analyze()` for framing shift |
| **Phase 1.2** (Content Matching) | Complementary | Lusa→outlet matching; our module expands this to all sources |
| **Phase 2.2** (Multi-source clustering) | Complementary | International clusters feed into our analysis |

### Storage

Results stored in:
- **SQLite (dev) / Supabase (prod):** `analyses` table with `type = "divergence"`, `details = DivergenceReport(JSON)`
- **JSON files:** Full reports exported for dashboard consumption

---

## 5. Scoring System

### Per-Outlet Score (Divergence Index)

```python
divergence_index = weighted_average(
    fact_omission_score * 0.35 +
    abs(sentiment_shift) * 0.25 +
    (1 - quote_fidelity) * 0.20 +
    headline_divergence * 0.20
)
```

Ranges:
| Score | Label | Meaning |
|-------|-------|---------|
| 0.00 – 0.20 | 🟢 Fiel | Minimal divergence from source |
| 0.20 – 0.40 | 🟡 Leve | Some facts omitted or tone shifted |
| 0.40 – 0.60 | 🟠 Moderada | Significant omission or reframing |
| 0.60 – 0.80 | 🔴 Alta | Major distortion of the original |
| 0.80 – 1.00 | 🟣 Extrema | Nearly unrecognizable from source |

### Per-Outlet Track Record

After 7+ days of data, each outlet gets a **Divergence Track Record**:
```
Público:  Divergência média 0.38 (🟡 Leve) — 142 histórias analisadas
Expresso: Divergência média 0.52 (🟠 Moderada) — 98 histórias
Correio da Manhã: Divergência média 0.71 (🔴 Alta) — 176 histórias
```

---

## 6. Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Article too short (< 100 chars) | Skip — `None` score, mark as `insufficient_content` |
| No entities detected in either article | `fact_omission_score = None`, overall score excludes omission dimension |
| No quotations in original | `quote_fidelity = None`, overall score excludes quote dimension |
| Language mismatch (original in EN, PT version in PT) | Extract entities in each language independently; quotes matched semantically |
| Duplicate articles (exact republish) | `overall_divergence = 0.0`, fast-path return |
| Original source not identifiable | Skip — no baseline to compare against |
| Empty cluster | Skip gracefully |
| spaCy model not downloaded | Log warning, fall back to regex-only entity extraction |

### Graceful Degradation

If any single dimension fails (e.g., spaCy OOM on large articles), the system:
1. Logs the failure with article ID
2. Returns `None` for that dimension
3. Calculates overall score from remaining dimensions
4. The report indicates which dimensions were skipped

---

## 7. Testing Strategy

### Unit Tests

```
tests/
├── test_divergence_extractor.py
├── test_divergence_comparator.py
├── test_divergence_reporter.py
└── fixtures/
    ├── lusa_artigo.txt
    ├── publico_versao.txt
    ├── reuters_article.txt
    ├── expresso_versao.txt
    └── expected_reports.json
```

**test_divergence_extractor.py:**
- Extract entities from known text → verify entity count and categories
- Extract quotes from known text → verify speaker and text
- Handle empty text → return empty lists
- Handle short text → return what's available

**test_divergence_comparator.py:**
- Compare identical articles → divergence = 0
- Compare article with known omissions → verify omission score matches expected
- Compare article with sentiment shift → verify sentiment_shift matches expected
- Compare with no quotes → quote_fidelity = None
- Compare multilingual (EN→PT) → works cross-lingually

**test_divergence_reporter.py:**
- JSON output → valid JSON, all expected fields
- Markdown output → correct format
- Aggregated summary → correct averages

### Calibration Test Set

Before production, manually verify 20 article pairs:
- 10 pairs with known divergence (identified by user)
- 10 pairs that are faithful reproductions (identified by user)

Measure: precision and recall at each divergence threshold. Adjust weights accordingly.

---

## 8. Dependencies & Timeline

### Dependencies on Other Phases

| Phase | Required By | What |
|-------|-------------|------|
| Phase 0.7 — Embedder | Divergence Analyzer | `SentenceTransformer` for headline comparison |
| Phase 0.8 — StoryMatcher | Divergence Analyzer | `StoryCluster` for article grouping |
| Phase 0.9 — SentimentAnalyzer | Divergence Analyzer | Sentiment scores for framing shift |
| Phase 0.2 — Source Config | Divergence Analyzer | Know which sources are "original" vs "outlet" |
| Phase 0.6 — DB schema | Divergence Analyzer | Storage for analysis results |

### Implementation Order

1. **Phase 0.7-0.9 first** — Need embedder, story matcher, and sentiment analyzer built before divergence can run
2. **models.py** — Define Pydantic data types (can be built in parallel with Phase 0.7-0.9)
3. **extractor.py** — spaCy entity extraction + quote detection
4. **comparator.py** — Core comparison logic
5. **reporter.py** — Output formatting
6. **Tests + Calibration** — Validation with manual test set
7. **Integration** — Wire into pipeline runner + GHA workflow

---

*End of Narrative Divergence Analyzer Design — v1.0*
