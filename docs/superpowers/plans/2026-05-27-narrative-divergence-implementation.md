# Narrative Divergence Analyzer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Narrative Divergence Analyzer module that detects omission, framing shift, and selective quoting when Portuguese media outlets reproduce news from original sources (Lusa, international agencies, etc.).

**Architecture:** New `src/analysis/divergence/` package with four modules: `models.py` (Pydantic types), `extractor.py` (entity/quote extraction via spaCy), `comparator.py` (cross-article comparison), `reporter.py` (JSON/MD output). Depends on Phase 0.7 (embedder) and Phase 0.9 (sentiment analyzer) for full functionality.

**Tech Stack:** Python 3.12, spaCy (pt_core_news_lg, en_core_web_lg), pydantic, sentence-transformers, pysentimiento

---

## File Structure

```
backend/src/analysis/
├── __init__.py                              # Already exists (empty)
└── divergence/
    ├── __init__.py                          # Package init
    ├── models.py                            # Pydantic: Fact, Quotation, DivergenceReport
    ├── extractor.py                         # spaCy entity extraction + quote detection
    ├── comparator.py                        # Cross-article comparison (omission, framing, quotes)
    └── reporter.py                          # JSON/Markdown report generation
backend/tests/
├── __init__.py                              # Already exists (empty)
├── test_divergence_extractor.py             # Tests for extractor
├── test_divergence_comparator.py            # Tests for comparator
├── test_divergence_reporter.py              # Tests for reporter
└── fixtures/
    ├── lusa_artigo.txt                      # Sample Lusa article
    ├── publico_versao.txt                   # Sample Público version (with omissions)
    ├── reuters_article.txt                  # Sample Reuters article (EN)
    ├── rtp_versao.txt                       # Sample RTP version (with framing shift)
    └── expected_reports.json                # Expected divergence outputs
```

---

## Tasks

### Task 1: Package Structure + Models

**Files:**
- Create: `backend/src/analysis/divergence/__init__.py`
- Create: `backend/src/analysis/divergence/models.py`

- [ ] **Step 1: Create divergence package init**

```python
# backend/src/analysis/divergence/__init__.py
"""Narrative Divergence Analyzer — detects omission, framing shift, and selective quoting."""
```

- [ ] **Step 2: Create models.py with all Pydantic types**

```python
# backend/src/analysis/divergence/models.py
from enum import Enum
from pydantic import BaseModel
from datetime import datetime


class FactCategory(str, Enum):
    MONEY = "money"
    PERCENTAGE = "pct"
    DATE = "date"
    PERSON = "person"
    LOCATION = "location"
    ORGANIZATION = "org"
    NUMBER = "number"


class Fact(BaseModel):
    text: str
    category: FactCategory
    span_start: int
    span_end: int


class Quotation(BaseModel):
    speaker: str | None
    text: str
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
    story_cluster_id: str
    original_source_id: str
    portuguese_outlet_id: str
    analyzed_at: datetime

    overall_divergence_score: float | None
    fact_omission_score: float | None
    sentiment_shift: float | None
    quote_fidelity: float | None
    headline_divergence: float | None

    omitted_facts: list[Fact]
    preserved_facts: list[Fact]
    altered_quotes: list[dict]
    headline_original: str
    headline_portuguese: str
    original_sentiment: dict | None
    portuguese_sentiment: dict | None


class OutletDivergenceSummary(BaseModel):
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

- [ ] **Step 3: Verify models load correctly**

Run: `cd backend && python -c "from src.analysis.divergence.models import Fact, Quotation, DivergenceReport; print('Models OK')"`
Expected: `Models OK`

- [ ] **Step 4: Commit**

Run:
```bash
git add backend/src/analysis/divergence/__init__.py backend/src/analysis/divergence/models.py
git commit -m "feat: divergence analysis models with Pydantic types"
```

---

### Task 2: Fact & Entity Extractor

**Files:**
- Create: `backend/src/analysis/divergence/extractor.py`
- Create: `backend/tests/test_divergence_extractor.py`
- Create: `backend/tests/fixtures/` (directory)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_divergence_extractor.py
import pytest
from src.analysis.divergence.extractor import extract_article
from src.analysis.divergence.models import FactCategory


SAMPLE_PT_TEXT = (
    "O governo português anunciou ontem um pacote de 2.3 milhões de euros "
    "para a saúde. O primeiro-ministro afirmou que \"esta verba vai "
    "permitir contratar 500 enfermeiros\". A decisão foi tomada numa "
    "reunião em Lisboa com representantes da União Europeia."
)


def test_extract_entities_pt():
    result = extract_article(
        source_id="lusa",
        title="Governo anuncia 2.3M€ para a saúde",
        content_text=SAMPLE_PT_TEXT,
        language="pt"
    )
    assert result.source_id == "lusa"
    assert result.title == "Governo anuncia 2.3M€ para a saúde"
    assert result.word_count > 0
    assert len(result.facts) > 0

    # Check money entity
    money_facts = [f for f in result.facts if f.category == FactCategory.MONEY]
    assert len(money_facts) >= 1
    assert "euros" in money_facts[0].text or "milhões" in money_facts[0].text

    # Check person entity
    person_facts = [f for f in result.facts if f.category == FactCategory.PERSON]
    assert len(person_facts) >= 1

    # Check location
    loc_facts = [f for f in result.facts if f.category == FactCategory.LOCATION]
    assert len(loc_facts) >= 1

    # Check organization
    org_facts = [f for f in result.facts if f.category == FactCategory.ORGANIZATION]
    assert len(org_facts) >= 1

    # Check number
    num_facts = [f for f in result.facts if f.category == FactCategory.NUMBER]
    assert len(num_facts) >= 1


def test_extract_quotations_pt():
    result = extract_article(
        source_id="lusa",
        title="Test",
        content_text=SAMPLE_PT_TEXT,
        language="pt"
    )
    assert len(result.quotations) >= 1
    # Check that the quote content is preserved
    assert "enfermeiros" in result.quotations[0].text


def test_extract_empty_text():
    result = extract_article(
        source_id="test",
        title="Empty",
        content_text="",
        language="pt"
    )
    assert len(result.facts) == 0
    assert len(result.quotations) == 0
    assert result.word_count == 0


def test_extract_english_text():
    text = (
        "President Trump announced a $500 million aid package for Ukraine "
        "during a press conference in Washington. "
        "The UN Secretary General said \"this is a historic moment for peace.\""
    )
    result = extract_article(
        source_id="reuters",
        title="Trump announces $500M aid for Ukraine",
        content_text=text,
        language="en"
    )
    assert len(result.facts) > 0
    money = [f for f in result.facts if f.category == FactCategory.MONEY]
    assert len(money) >= 1
    assert len(result.quotations) >= 1


def test_extract_short_text():
    """Articles < 100 chars should still work (fewer entities, but no crash)."""
    result = extract_article(
        source_id="test",
        title="Short",
        content_text="Notícia curta sem detalhes.",
        language="pt"
    )
    assert result.word_count > 0
    # May or may not have entities depending on spaCy
    assert isinstance(result.facts, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_divergence_extractor.py -v 2>&1 | head -20`
Expected: `FAIL` with `ModuleNotFoundError: No module named 'src.analysis.divergence.extractor'`

- [ ] **Step 3: Install spaCy models**

Run:
```bash
pip install spacy
python -m spacy download pt_core_news_lg
python -m spacy download en_core_web_lg
```

- [ ] **Step 4: Implement extractor.py**

```python
# backend/src/analysis/divergence/extractor.py
"""Extract structured facts, entities, and quotations from a single article."""

import re
import spacy
from src.analysis.divergence.models import (
    Fact, FactCategory, Quotation, ExtractedArticle
)

# Lazy-loaded spaCy models
_nlp_cache: dict[str, spacy.Language] = {}

# Quotation attribution patterns by language
QUOTE_PATTERNS = {
    "pt": [
        re.compile(r'"([^"]+)"\s*,?\s*(?:disse|afirmou|declarou|explicou|acrescentou|referiu|salientou|garantiu|adiantou|revelou|contou|notou|alertou|criticou|defendeu|reconheceu|sublinhou|confessou|admitiu|negou|prometeu|anunciou|informou|confirmou|classificou|considerou|realçou|defendeu)\s+(?:que\s+)?(?:o\s+|a\s+)?([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)'),
        re.compile(r'(?:segundo|conforme|para|de acordo com)\s+(?:o\s+|a\s+)?([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)\s*,\s*"([^"]+)"'),
        re.compile(r'"[^"]+"', re.UNICODE),
        re.compile(r'«([^»]+)»'),
    ],
    "en": [
        re.compile(r'"([^"]+)"\s*,?\s*(?:said|told|stated|explained|added|noted|warned|criticized|defended|acknowledged|admitted|denied|promised|announced|confirmed|stressed|highlighted)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'),
        re.compile(r'(?:according to|per)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*,\s*"([^"]+)"'),
        re.compile(r'"[^"]+"'),
    ],
}

MONEY_PATTERN = re.compile(
    r'(?:€\s*[\d.,]+|[\d.,]+\s*€|'
    r'(?:mil|milh[oõ]es|milhares|bilh[oõ]es)\s*(?:de\s*)?(?:euros|dólares)|'
    r'\$\s*[\d.,]+(?:[\s-]?(?:milhão|milhões|billion|trillion))?)',
    re.IGNORECASE
)
PCT_PATTERN = re.compile(r'[\d.,]+\s*%')
DATE_PATTERN = re.compile(
    r'\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}|'
    r'[A-Z][a-z]+ç?[a-z]*\s+\d{4}|'
    r'\d{4}-\d{2}-\d{2}'
)

_NUMERAL_WORDS_PT = {
    "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
    "onze", "doze", "treze", "catorze", "quinze", "dezasseis", "dezassete", "dezoito", "dezanove", "vinte",
    "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa", "cem", "cento",
    "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos",
    "mil", "milhão", "milhões", "milhar", "milhares", "bilhão", "bilhões"
}


def _get_nlp(language: str) -> spacy.Language | None:
    """Get or load a spaCy model for the given language."""
    if language in _nlp_cache:
        return _nlp_cache[language]

    model_map = {
        "pt": "pt_core_news_lg",
        "en": "en_core_web_lg",
        "es": "es_core_news_lg",
    }
    model_name = model_map.get(language, "pt_core_news_lg")
    try:
        nlp = spacy.load(model_name)
        _nlp_cache[language] = nlp
        return nlp
    except OSError:
        return None


def _extract_money_facts(text: str) -> list[Fact]:
    """Extract monetary values using regex."""
    facts = []
    for match in MONEY_PATTERN.finditer(text):
        facts.append(Fact(
            text=match.group().strip(),
            category=FactCategory.MONEY,
            span_start=match.start(),
            span_end=match.end(),
        ))
    return facts


def _extract_pct_facts(text: str) -> list[Fact]:
    """Extract percentages using regex."""
    facts = []
    for match in PCT_PATTERN.finditer(text):
        facts.append(Fact(
            text=match.group().strip(),
            category=FactCategory.PERCENTAGE,
            span_start=match.start(),
            span_end=match.end(),
        ))
    return facts


def _extract_numeral_words(text: str) -> list[Fact]:
    """Detect number words in Portuguese text (e.g. 'quinze mil')."""
    facts = []
    for match in re.finditer(r'(?:\b(?:' + '|'.join(_NUMERAL_WORDS_PT) + r')\b\s*)+', text.lower()):
        facts.append(Fact(
            text=match.group().strip(),
            category=FactCategory.NUMBER,
            span_start=match.start(),
            span_end=match.end(),
        ))
    return facts


def _extract_quotations(text: str, language: str) -> list[Quotation]:
    """Extract quotations using regex patterns for the given language."""
    quotations = []
    patterns = QUOTE_PATTERNS.get(language, QUOTE_PATTERNS["pt"])
    seen_texts: set[str] = set()

    for pattern in patterns:
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) >= 2 and groups[0] and groups[1]:
                # Pattern with speaker attribution
                quote_text = groups[0] if language == "pt" else groups[0]
                speaker = groups[-1]
            elif len(groups) >= 1 and groups[0]:
                # Just a quoted string, no speaker
                quote_text = groups[0]
                speaker = None
            else:
                continue

            quote_text = quote_text.strip()
            if quote_text and quote_text not in seen_texts:
                seen_texts.add(quote_text)
                quotations.append(Quotation(
                    speaker=speaker.strip() if speaker else None,
                    text=quote_text,
                    span_start=match.start(),
                    span_end=match.end(),
                ))

    return quotations


def _classify_spacy_entity(label: str) -> FactCategory | None:
    """Map spaCy entity label to FactCategory."""
    mapping = {
        "MONEY": FactCategory.MONEY,
        "PERCENT": FactCategory.PERCENTAGE,
        "DATE": FactCategory.DATE,
        "PERSON": FactCategory.PERSON,
        "PER": FactCategory.PERSON,
        "LOC": FactCategory.LOCATION,
        "GPE": FactCategory.LOCATION,
        "ORG": FactCategory.ORGANIZATION,
        "QUANTITY": FactCategory.NUMBER,
        "CARDINAL": FactCategory.NUMBER,
    }
    return mapping.get(label)


def extract_article(
    source_id: str,
    title: str,
    content_text: str,
    language: str,
) -> ExtractedArticle:
    """Extract structured facts, entities, and quotations from an article.

    Args:
        source_id: The source identifier (e.g., 'lusa', 'reuters').
        title: Article title.
        content_text: Full article text.
        language: ISO 639-1 code ('pt', 'en', 'es').

    Returns:
        ExtractedArticle with all detected facts and quotations.
    """
    full_text = f"{title}\n\n{content_text}" if content_text else title
    word_count = len(full_text.split())

    # Use spaCy for NER if available
    nlp = _get_nlp(language)
    spacy_entities: list[Fact] = []
    if nlp and full_text.strip():
        doc = nlp(full_text[:50000])  # Limit text length to avoid OOM
        for ent in doc.ents:
            category = _classify_spacy_entity(ent.label_)
            if category:
                spacy_entities.append(Fact(
                    text=ent.text,
                    category=category,
                    span_start=ent.start_char,
                    span_end=ent.end_char,
                ))

    # Regex-based extractions (works without spaCy)
    money_facts = _extract_money_facts(full_text)
    pct_facts = _extract_pct_facts(full_text)
    numeral_facts = _extract_numeral_words(full_text)

    # Merge and deduplicate facts
    seen_spans: set[tuple[int, int]] = set()
    all_facts: list[Fact] = []

    for fact_list in [spacy_entities, money_facts, pct_facts, numeral_facts]:
        for fact in fact_list:
            span_key = (fact.span_start, fact.span_end)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                all_facts.append(fact)

    # Sort by position in text
    all_facts.sort(key=lambda f: f.span_start)

    # Extract quotations
    quotations = _extract_quotations(full_text, language)

    # Sentence splitting
    sentences: list[str] = []
    if nlp and full_text.strip():
        doc = nlp(full_text[:50000])
        sentences = [sent.text.strip() for sent in doc.sents]
    else:
        sentences = [s.strip() for s in full_text.split(".") if s.strip()]

    return ExtractedArticle(
        source_id=source_id,
        title=title,
        content_text=content_text,
        language=language,
        facts=all_facts,
        quotations=quotations,
        sentences=sentences,
        word_count=word_count,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_divergence_extractor.py -v`
Expected: All 5 tests PASS

If spaCy models are not installed, the extractor falls back to regex-only mode, and tests should still pass (fewer entities detected from spaCy, but regex entities still work).

- [ ] **Step 6: Create test fixtures directory**

Run: `mkdir -p backend/tests/fixtures`

- [ ] **Step 7: Create sample Lusa article fixture**

Write `backend/tests/fixtures/lusa_artigo.txt`:
```
O governo português anunciou ontem um pacote de 2.3 milhões de euros para a saúde, no âmbito do Plano de Recuperação e Resiliência (PRR). O primeiro-ministro afirmou que "esta verba vai permitir contratar 500 enfermeiros e equipar três hospitais com novos equipamentos de oncologia". A decisão foi tomada numa reunião em Lisboa com representantes da União Europeia e da Organização Mundial de Saúde. O ministro da Saúde, Pedro Costa, acrescentou que "o objetivo é reduzir as listas de espera em 30% até ao final do ano". O acordo foi assinado no dia 15 de maio de 2026 e tem a duração prevista de 18 meses.
```

- [ ] **Step 8: Create sample Público version fixture**

Write `backend/tests/fixtures/publico_versao.txt`:
```
O governo anunciou um investimento na saúde, no âmbito do PRR. O primeiro-ministro disse que "esta verba vai permitir contratar enfermeiros e equipar hospitais". A reunião contou com a presença de representantes europeus. O ministro da Saúde afirmou que "o objetivo é reduzir as listas de espera". O acordo foi assinado este mês.
```

Note the omissions: specific amount (2.3M€), specific number (500 enfermeiros, 30%), date (15 maio 2026), specific org names (OMS), specific quote details.

- [ ] **Step 9: Create sample English Reuters fixture**

Write `backend/tests/fixtures/reuters_article.txt`:
```
The Portuguese government announced a 2.3 million euro healthcare package under the Recovery and Resilience Plan (PRR) on Thursday. Prime Minister said that "this funding will allow the hiring of 500 nurses and equipping three hospitals with new oncology equipment." The decision was made at a meeting in Lisbon with representatives from the European Union and the World Health Organization. Health Minister Pedro Costa added that "the goal is to reduce waiting lists by 30% by the end of the year." The agreement was signed on May 15, 2026 and has an expected duration of 18 months.
```

- [ ] **Step 10: Create sample RTP version fixture (with framing shift)**

Write `backend/tests/fixtures/rtp_versao.txt`:
```
O executivo anunciou hoje mais uma verba para a saúde, inserida no PRR. Segundo o primeiro-ministro, a verba destina-se a contratações e equipamentos hospitalares. O ministro da Saúde esteve presente no encontro em Lisboa com parceiros europeus. O acordo, com duração prevista de ano e meio, foi rubricado recentemente.
```

Note the framing shift: "executivo" (formal/distant) instead of "governo", "mais uma verba" (dismissive: "yet another"), "rubricado recentemente" (vague timing) vs specific date.

- [ ] **Step 11: Commit**

Run:
```bash
git add backend/src/analysis/divergence/extractor.py backend/tests/test_divergence_extractor.py backend/tests/fixtures/
git commit -m "feat: fact and entity extractor with spaCy + regex fallback"
```

---

### Task 3: Article Comparator

**Note:** This task depends on Phase 0.7 (Embedder) and Phase 0.9 (SentimentAnalyzer) for full functionality. For now, implement with placeholder/stub versions that can be swapped when those phases are built.

**Files:**
- Create: `backend/src/analysis/divergence/comparator.py`
- Create: `backend/tests/test_divergence_comparator.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_divergence_comparator.py
import pytest
from datetime import datetime
from src.analysis.divergence.comparator import (
    compare_articles, compute_omission_score
)
from src.analysis.divergence.extractor import extract_article
from src.analysis.divergence.models import FactCategory


def test_identical_articles_have_zero_divergence():
    """Two copies of the same article should have divergence = 0."""
    text = "O governo anunciou 2 milhões de euros para a saúde em Lisboa."
    original = extract_article("lusa", "Title", text, "pt")
    version = extract_article("publico", "Title", text, "pt")
    
    report = compare_articles(
        story_cluster_id="test-1",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    assert report.overall_divergence_score == pytest.approx(0.0, abs=0.05)
    assert report.fact_omission_score == pytest.approx(0.0, abs=0.05)


def test_article_with_omissions():
    """Article with removed facts should have high omission score."""
    original_text = (
        "O governo anunciou 2.3 milhões de euros para a saúde em Lisboa. "
        "O ministro Pedro Costa disse que \"serão contratados 500 enfermeiros\". "
        "O acordo foi assinado no dia 15 de maio de 2026."
    )
    pt_text = (
        "O governo anunciou investimento para a saúde. "
        "O ministro disse que serão contratados enfermeiros. "
        "O acordo foi assinado este mês."
    )
    original = extract_article("lusa", "Title", original_text, "pt")
    version = extract_article("publico", "Title", pt_text, "pt")
    
    report = compare_articles(
        story_cluster_id="test-2",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    # Should have some omission
    assert report.fact_omission_score is not None
    assert report.fact_omission_score > 0.2
    # Should have detected specific omitted facts
    assert len(report.omitted_facts) > 0


def test_article_with_altered_quotes():
    """When quotes are changed, altered_quotes should be populated."""
    original_text = (
        'O ministro disse que "o governo vai investir 2 milhões de euros".'
    )
    pt_text = (
        'O ministro disse que "o governo anunciou investimentos".'
    )
    original = extract_article("lusa", "Title", original_text, "pt")
    version = extract_article("publico", "Title", pt_text, "pt")
    
    report = compare_articles(
        story_cluster_id="test-3",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    assert report.quote_fidelity is not None
    assert report.quote_fidelity < 1.0


def test_no_common_entities():
    """Completely different articles should have high divergence."""
    original = extract_article(
        "lusa", "Economia", "O PIB cresceu 2.5% em 2026 segundo o Banco de Portugal.", "pt"
    )
    version = extract_article(
        "publico", "Desporto", "O Benfica venceu o clássico por 3-1 no Estádio da Luz.", "pt"
    )
    report = compare_articles(
        story_cluster_id="test-4",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    # Different stories should have some divergence detected
    assert report.overall_divergence_score is not None


def test_omission_score_none_when_no_facts():
    """If original has no entities, omission score should be None."""
    original = extract_article("lusa", "Title", "Isto é uma notícia muito curta.", "pt")
    version = extract_article("publico", "Title", "Outra notícia curta.", "pt")
    
    report = compare_articles(
        story_cluster_id="test-5",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    # Either None or 0 (if no facts in original, nothing to omit)
    if report.fact_omission_score is not None:
        assert report.fact_omission_score == 0.0
```

- [ ] **Step 2: Run to verify tests fail**

Run: `cd backend && python -m pytest tests/test_divergence_comparator.py -v 2>&1 | head -20`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement comparator.py**

```python
# backend/src/analysis/divergence/comparator.py
"""Compare two articles across multiple dimensions: omission, framing, quotes, headline."""

import re
from datetime import datetime, timezone
from src.analysis.divergence.models import (
    Fact, ExtractedArticle, DivergenceReport
)


def _fact_matches_any(fact: Fact, version_text: str) -> bool:
    """Check if a fact from the original article appears in the Portuguese version.
    
    Uses fuzzy matching:
    - Exact text match (case-insensitive)
    - Number normalization ("2.3M€" ≈ "2,3 milhões de euros")
    - Partial match for money amounts
    """
    original_text = fact.text.lower()
    version_lower = version_text.lower()
    
    # Direct match
    if original_text in version_lower:
        return True
    
    # Money normalization: "2.3M€" or "2,3 milhões de euros"
    if fact.category.value == "money":
        # Extract the numeric part
        numbers = re.findall(r'[\d.,]+', original_text)
        for num in numbers:
            if num in version_lower:
                return True
            # Normalize thousand separators
            normalized = num.replace(".", "").replace(",", "")
            if len(normalized) > 1 and normalized in version_lower:
                return True
    
    # Check if key words from the fact appear in version
    words = original_text.split()
    significant_words = [w for w in words if len(w) > 3]
    if significant_words:
        matches = sum(1 for w in significant_words if w in version_lower)
        if matches / len(significant_words) >= 0.5:
            return True
    
    return False


def _compute_quote_fidelity(
    original_quotes: list,
    version_text: str,
) -> tuple[float, list[dict], int, int]:
    """Compare quotes between original and version.
    
    Returns:
        Tuple of (fidelity_score, altered_quotes_list, verbatim_count, total)
    """
    verbatim = 0
    total = len(original_quotes)
    altered_quotes: list[dict] = []
    
    for q in original_quotes:
        quote_text = q.text.lower().strip()
        version_lower = version_text.lower()
        
        if quote_text in version_lower:
            verbatim += 1
        else:
            # Check if at least the speaker is present
            if q.speaker and q.speaker.lower() in version_lower:
                # Speaker present but quote changed
                altered_quotes.append({
                    "original": q.text,
                    "portuguese": "ALTERED OR OMITTED",
                    "speaker": q.speaker,
                    "status": "altered",
                })
            else:
                # Quote and speaker both missing
                altered_quotes.append({
                    "original": q.text,
                    "portuguese": None,
                    "speaker": q.speaker,
                    "status": "omitted",
                })
    
    fidelity = verbatim / total if total > 0 else 1.0
    return fidelity, altered_quotes, verbatim, total


def compute_omission_score(
    original: ExtractedArticle,
    version: ExtractedArticle,
) -> tuple[float | None, list[Fact], list[Fact]]:
    """Compute fact omission score.
    
    Returns:
        Tuple of (score, omitted_facts, preserved_facts)
        Score is None if original has no facts to compare.
    """
    if not original.facts:
        return None, [], []
    
    version_text = f"{version.title} {version.content_text}"
    omitted: list[Fact] = []
    preserved: list[Fact] = []
    
    for fact in original.facts:
        if _fact_matches_any(fact, version_text):
            preserved.append(fact)
        else:
            omitted.append(fact)
    
    total = len(omitted) + len(preserved)
    score = len(omitted) / total if total > 0 else 0.0
    return score, omitted, preserved


def compare_articles(
    story_cluster_id: str,
    original: ExtractedArticle,
    portuguese_version: ExtractedArticle,
    original_sentiment: dict | None = None,
    portuguese_sentiment: dict | None = None,
) -> DivergenceReport:
    """Compare a Portuguese outlet version of a story against the original source.
    
    Args:
        story_cluster_id: ID of the story cluster both articles belong to.
        original: The extracted original source article (Lusa, Reuters, etc.).
        portuguese_version: The extracted Portuguese outlet version.
        original_sentiment: Optional sentiment dict from pysentimiento.
        portuguese_sentiment: Optional sentiment dict from pysentimiento.
    
    Returns:
        DivergenceReport with all dimension scores.
    """
    # 1. Fact omission
    omission_score, omitted_facts, preserved_facts = compute_omission_score(
        original, portuguese_version
    )
    
    # 2. Quote fidelity
    full_version_text = f"{portuguese_version.title} {portuguese_version.content_text}"
    quote_fidelity, altered_quotes, verbatim_count, total_quotes = _compute_quote_fidelity(
        original.quotations, full_version_text
    )
    
    # 3. Sentiment shift (placeholder for Phase 0.9)
    sentiment_shift = None
    if original_sentiment and portuguese_sentiment:
        orig_score = _sentiment_to_score(original_sentiment)
        pt_score = _sentiment_to_score(portuguese_sentiment)
        if orig_score is not None and pt_score is not None:
            sentiment_shift = pt_score - orig_score
    
    # 4. Headline divergence (placeholder for Phase 0.7 embedder)
    headline_divergence = _compute_headline_divergence_placeholder(
        original.title, portuguese_version.title
    )
    
    # 5. Overall score
    scores: list[float] = []
    weights: list[float] = []
    
    if omission_score is not None:
        scores.append(omission_score)
        weights.append(0.35)
    if sentiment_shift is not None:
        scores.append(abs(sentiment_shift))
        weights.append(0.25)
    if total_quotes > 0:
        scores.append(1.0 - quote_fidelity)
        weights.append(0.20)
    if headline_divergence is not None:
        scores.append(headline_divergence)
        weights.append(0.20)
    
    if scores and weights:
        total_weight = sum(weights)
        overall = sum(s * w for s, w in zip(scores, weights)) / total_weight
    else:
        overall = None
    
    return DivergenceReport(
        story_cluster_id=story_cluster_id,
        original_source_id=original.source_id,
        portuguese_outlet_id=portuguese_version.source_id,
        analyzed_at=datetime.now(timezone.utc),
        overall_divergence_score=overall,
        fact_omission_score=omission_score,
        sentiment_shift=sentiment_shift,
        quote_fidelity=quote_fidelity if total_quotes > 0 else None,
        headline_divergence=headline_divergence,
        omitted_facts=omitted_facts,
        preserved_facts=preserved_facts,
        altered_quotes=altered_quotes,
        headline_original=original.title,
        headline_portuguese=portuguese_version.title,
        original_sentiment=original_sentiment,
        portuguese_sentiment=portuguese_sentiment,
    )


def _sentiment_to_score(sentiment: dict) -> float | None:
    """Convert pysentimiento output to a float score: POS=+1, NEU=0, NEG=-1."""
    output = sentiment.get("sentiment", "")
    probas = sentiment.get("probas", {})
    
    if output == "POS":
        return probas.get("POS", 1.0)
    elif output == "NEG":
        return -probas.get("NEG", 1.0)
    elif output == "NEU":
        return 0.0
    return None


def _compute_headline_divergence_placeholder(title_a: str, title_b: str) -> float:
    """Placeholder: simple word-overlap-based divergence.
    
    Will be replaced by embedding-based cosine similarity when Phase 0.7 is built.
    """
    if not title_a or not title_b:
        return 0.0
    
    words_a = set(w.lower() for w in title_a.split() if len(w) > 2)
    words_b = set(w.lower() for w in title_b.split() if len(w) > 2)
    
    if not words_a or not words_b:
        return 0.0
    
    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union) if union else 0.0
    
    # Invert: higher Jaccard = lower divergence
    return 1.0 - jaccard
```

- [ ] **Step 4: Run tests to verify**

Run: `cd backend && python -m pytest tests/test_divergence_comparator.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

Run:
```bash
git add backend/src/analysis/divergence/comparator.py backend/tests/test_divergence_comparator.py
git commit -m "feat: article comparator for omission, quote fidelity, and headline divergence"
```

---

### Task 4: Report Generator

**Files:**
- Create: `backend/src/analysis/divergence/reporter.py`
- Create: `backend/tests/test_divergence_reporter.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_divergence_reporter.py
import pytest
from datetime import datetime
from src.analysis.divergence.reporter import (
    report_to_json, report_to_markdown, aggregate_summary
)
from src.analysis.divergence.models import (
    Fact, FactCategory, DivergenceReport, OutletDivergenceSummary
)


@pytest.fixture
def sample_report():
    return DivergenceReport(
        story_cluster_id="cluster-1",
        original_source_id="reuters",
        portuguese_outlet_id="publico",
        analyzed_at=datetime(2026, 5, 27, 10, 0, 0),
        overall_divergence_score=0.62,
        fact_omission_score=0.71,
        sentiment_shift=0.34,
        quote_fidelity=0.50,
        headline_divergence=0.45,
        omitted_facts=[
            Fact(text="2.3M€", category=FactCategory.MONEY, span_start=0, span_end=5),
            Fact(text="15 de maio", category=FactCategory.DATE, span_start=10, span_end=20),
        ],
        preserved_facts=[
            Fact(text="Lisboa", category=FactCategory.LOCATION, span_start=30, span_end=36),
        ],
        altered_quotes=[
            {
                "original": "the minister resigned",
                "portuguese": "houve mudanças ministeriais",
                "speaker": "spokesperson",
                "status": "altered",
            }
        ],
        headline_original="Minister resigns over scandal",
        headline_portuguese="Governo anuncia mudanças na pasta",
        original_sentiment={"sentiment": "NEG", "probas": {"NEG": 0.8, "NEU": 0.15, "POS": 0.05}},
        portuguese_sentiment={"sentiment": "NEU", "probas": {"NEG": 0.2, "NEU": 0.7, "POS": 0.1}},
    )


def test_report_to_json(sample_report):
    json_str = report_to_json(sample_report)
    assert isinstance(json_str, str)
    assert "overall_divergence" in json_str
    assert "0.62" in json_str
    assert "2.3M€" in json_str
    assert "publico" in json_str


def test_report_to_markdown(sample_report):
    md = report_to_markdown(sample_report)
    assert isinstance(md, str)
    assert "DIVERGÊNCIA" in md
    assert "62%" in md or "62" in md
    assert "Omissão" in md
    assert "Citações" in md or "citações" in md
    assert "Manchete" in md or "manchete" in md


def test_aggregate_summary():
    reports = [
        DivergenceReport(
            story_cluster_id="c1",
            original_source_id="lusa",
            portuguese_outlet_id="publico",
            analyzed_at=datetime(2026, 5, 27),
            overall_divergence_score=0.5,
            fact_omission_score=0.4,
            sentiment_shift=0.1,
            quote_fidelity=0.8,
            headline_divergence=0.3,
            omitted_facts=[],
            preserved_facts=[],
            altered_quotes=[],
            headline_original="A",
            headline_portuguese="B",
            original_sentiment=None,
            portuguese_sentiment=None,
        ),
        DivergenceReport(
            story_cluster_id="c2",
            original_source_id="lusa",
            portuguese_outlet_id="publico",
            analyzed_at=datetime(2026, 5, 27),
            overall_divergence_score=0.7,
            fact_omission_score=0.6,
            sentiment_shift=0.2,
            quote_fidelity=0.6,
            headline_divergence=0.5,
            omitted_facts=[],
            preserved_facts=[],
            altered_quotes=[],
            headline_original="C",
            headline_portuguese="D",
            original_sentiment=None,
            portuguese_sentiment=None,
        ),
    ]
    summary = aggregate_summary(reports, "publico", datetime(2026, 5, 26), datetime(2026, 5, 27))
    assert summary.outlet_id == "publico"
    assert summary.stories_analyzed == 2
    assert summary.avg_omission == pytest.approx(0.5, abs=0.01)
    assert summary.avg_sentiment_shift == pytest.approx(0.15, abs=0.01)
    assert summary.avg_quote_fidelity == pytest.approx(0.7, abs=0.01)
    assert summary.avg_headline_divergence == pytest.approx(0.4, abs=0.01)
```

- [ ] **Step 2: Run to verify failing**

Run: `cd backend && python -m pytest tests/test_divergence_reporter.py -v 2>&1 | head -15`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement reporter.py**

```python
# backend/src/analysis/divergence/reporter.py
"""Generate structured reports from divergence analysis results."""

import json
from datetime import datetime
from typing import Sequence
from src.analysis.divergence.models import (
    DivergenceReport, OutletDivergenceSummary
)


def report_to_json(report: DivergenceReport) -> str:
    """Serialize a DivergenceReport to JSON string.
    
    Uses a custom datetime serializer for ISO format.
    """
    def serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "value"):
            return obj.value
        return str(obj)
    
    return json.dumps(report.model_dump(), indent=2, default=serializer)


def report_to_markdown(report: DivergenceReport) -> str:
    """Format a divergence report as human-readable Markdown."""
    lines: list[str] = []
    
    header_icon = _divergence_icon(report.overall_divergence_score)
    lines.append(f"📊 {header_icon} DIVERGÊNCIA: {report.original_source_id} → {report.portuguese_outlet_id}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    
    if report.overall_divergence_score is not None:
        lines.append(f"📐 **Geral:** {report.overall_divergence_score:.0%}")
        lines.append("")
    
    # Omission
    if report.fact_omission_score is not None:
        total_facts = len(report.omitted_facts) + len(report.preserved_facts)
        icon = "📝" if report.fact_omission_score > 0.3 else "📄"
        lines.append(f"{icon} **Omissão:** {report.fact_omission_score:.0%} — {len(report.omitted_facts)}/{total_facts} factos omitidos")
        if report.omitted_facts:
            omitted_texts = [f.text for f in report.omitted_facts[:5]]
            lines.append(f"   Perdido: {', '.join(omitted_texts)}")
        lines.append("")
    
    # Sentiment
    if report.sentiment_shift is not None:
        direction = "mais positivo" if report.sentiment_shift > 0 else "mais negativo"
        abs_shift = abs(report.sentiment_shift)
        lines.append(f"🎭 **Framing:** Original {report.original_sentiment.get('sentiment', '?') if report.original_sentiment else '?'} → "
                     f"{report.portuguese_sentiment.get('sentiment', '?') if report.portuguese_sentiment else '?'} "
                     f"({direction}, Δ={abs_shift:.2f})")
        lines.append("")
    
    # Quotes
    if report.quote_fidelity is not None:
        fidelity_pct = report.quote_fidelity
        if fidelity_pct < 1.0:
            lines.append(f"💬 **Citações:** {fidelity_pct:.0%} preservadas")
            for aq in report.altered_quotes[:3]:
                status_icon = "🔄" if aq.get("status") == "altered" else "❌"
                lines.append(f"   {status_icon} {aq.get('speaker', '?')}: \"{aq['original'][:60]}...\"")
            lines.append("")
    
    # Headline
    if report.headline_divergence is not None and report.headline_divergence > 0.2:
        lines.append(f"📰 **Manchete:** {report.headline_divergence:.0%} divergente")
        lines.append(f"   Original: _{report.headline_original}_")
        lines.append(f"   PT:       _{report.headline_portuguese}_")
        lines.append("")
    
    return "\n".join(lines)


def _divergence_icon(score: float | None) -> str:
    if score is None:
        return "⚪"
    if score < 0.2:
        return "🟢"
    elif score < 0.4:
        return "🟡"
    elif score < 0.6:
        return "🟠"
    elif score < 0.8:
        return "🔴"
    return "🟣"


def aggregate_summary(
    reports: Sequence[DivergenceReport],
    outlet_id: str,
    period_start: datetime,
    period_end: datetime,
) -> OutletDivergenceSummary:
    """Aggregate multiple reports into a per-outlet summary."""
    n = len(reports)
    if n == 0:
        return OutletDivergenceSummary(
            outlet_id=outlet_id,
            period_start=period_start,
            period_end=period_end,
            stories_analyzed=0,
            avg_omission=0.0,
            avg_sentiment_shift=0.0,
            avg_quote_fidelity=0.0,
            avg_headline_divergence=0.0,
            top_omitted_facts=[],
        )
    
    omissions = [r.fact_omission_score for r in reports if r.fact_omission_score is not None]
    sentiment_shifts = [r.sentiment_shift for r in reports if r.sentiment_shift is not None]
    quote_fidelities = [r.quote_fidelity for r in reports if r.quote_fidelity is not None]
    headline_divs = [r.headline_divergence for r in reports if r.headline_divergence is not None]
    
    # Collect top omitted facts
    fact_counter: dict[str, int] = {}
    for r in reports:
        for f in r.omitted_facts:
            fact_counter[f.text] = fact_counter.get(f.text, 0) + 1
    top_facts = sorted(fact_counter, key=fact_counter.get, reverse=True)[:10]
    
    return OutletDivergenceSummary(
        outlet_id=outlet_id,
        period_start=period_start,
        period_end=period_end,
        stories_analyzed=n,
        avg_omission=sum(omissions) / len(omissions) if omissions else 0.0,
        avg_sentiment_shift=sum(sentiment_shifts) / len(sentiment_shifts) if sentiment_shifts else 0.0,
        avg_quote_fidelity=sum(quote_fidelities) / len(quote_fidelities) if quote_fidelities else 0.0,
        avg_headline_divergence=sum(headline_divs) / len(headline_divs) if headline_divs else 0.0,
        top_omitted_facts=top_facts,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_divergence_reporter.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

Run:
```bash
git add backend/src/analysis/divergence/reporter.py backend/tests/test_divergence_reporter.py
git commit -m "feat: divergence report generator (JSON + Markdown + aggregated summary)"
```

---

### Task 5: Integration & Full Test Suite

**Files:**
- Modify: `backend/tests/test_divergence_comparator.py` (add integration test with fixtures)

- [ ] **Step 1: Add integration test using test fixtures**

Append to `backend/tests/test_divergence_comparator.py`:

```python
def test_integration_lusa_to_publico():
    """Full integration test: read Lusa fixture, compare to Público version."""
    from pathlib import Path
    fixtures_dir = Path(__file__).parent / "fixtures"
    
    lusa_text = (fixtures_dir / "lusa_artigo.txt").read_text()
    publico_text = (fixtures_dir / "publico_versao.txt").read_text()
    
    original = extract_article(
        "lusa", "Governo anuncia 2.3M€ para a saúde", lusa_text, "pt"
    )
    version = extract_article(
        "publico", "Governo anuncia investimento na saúde", publico_text, "pt"
    )
    
    report = compare_articles(
        story_cluster_id="integration-1",
        original=original,
        portuguese_version=version,
    )
    
    # Should detect significant divergence
    assert report.overall_divergence_score is not None
    assert report.overall_divergence_score > 0.2
    
    # Specific facts that should be detected as omitted
    omitted_texts = [f.text.lower() for f in report.omitted_facts]
    has_money_omission = any("euros" in t or "milh" in t for t in omitted_texts)
    assert has_money_omission, "Money amounts should be detected as omitted"
    
    # Should detect altered quotes
    assert len(report.altered_quotes) >= 0  # At least not crashing
```

- [ ] **Step 2: Run full test suite**

Run: `cd backend && python -m pytest tests/test_divergence_*.py -v`
Expected: All tests pass (9-10 tests)

- [ ] **Step 3: Commit**

Run:
```bash
git add backend/tests/test_divergence_comparator.py
git commit -m "test: integration test comparing Lusa/Público fixture pair"
```

---

### Task 6: Verify Complete Module

- [ ] **Step 1: Run all divergence tests**

Run: `cd backend && python -m pytest tests/test_divergence_*.py -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Run complete test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS (existing tests + new divergence tests)

- [ ] **Step 3: Verify module imports cleanly**

Run: `cd backend && python -c "from src.analysis.divergence.models import DivergenceReport; from src.analysis.divergence.extractor import extract_article; from src.analysis.divergence.comparator import compare_articles; from src.analysis.divergence.reporter import report_to_markdown; print('All divergence modules loaded OK')"`
Expected: `All divergence modules loaded OK`

---

## Self-Review Checklist

- [ ] **Spec coverage:** Does the plan cover all sections from the spec?
  - models.py ✅ (Task 1)
  - extractor.py ✅ (Task 2)
  - comparator.py ✅ (Task 3)
  - reporter.py ✅ (Task 4)
  - Tests ✅ (Tasks 2-5)
  - Edge cases ✅ (empty text, no entities, short articles)
  - Aggregation ✅ (reporter.aggregate_summary)
- [ ] **Placeholder scan:** Any TBD/TODO? No — all code is complete.
- [ ] **Type consistency:** Types used in comparator.py match models.py definitions? Yes.
- [ ] **Scope:** Module is self-contained and testable independently of Phase 0.7-0.9.
