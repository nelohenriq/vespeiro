"""Extract structured facts, entities, and quotations from a single article."""

import re
from src.analysis.divergence.models import (
    Fact, FactCategory, Quotation, ExtractedArticle,
)

# Lazy-loaded spaCy models (imported inside _get_nlp to avoid slow module-level import)
_nlp_cache: dict[str, "spacy.Language"] = {}

# ── Quotation attribution patterns ──────────────────────────────────────────

QUOTE_PATTERNS = {
    "pt": [
        # "quote" disse X / afirmou X / ...
        re.compile(
            r'"([^"]+)"\s*,?\s*'
            r'(?:disse|afirmou|declarou|explicou|acrescentou|referiu|'
            r'salientou|garantiu|adiantou|revelou|contou|notou|alertou|'
            r'criticou|defendeu|reconheceu|sublinhou|confessou|admitiu|'
            r'negou|prometeu|anunciou|informou|confirmou|classificou|'
            r'considerou|realçou)'
            r'\s+(?:que\s+)?(?:o\s+|a\s+)?'
            r'([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)'
        ),
        # segundo X / conforme X / de acordo com X, "quote"
        re.compile(
            r'(?:segundo|conforme|para|de acordo com)'
            r'\s+(?:o\s+|a\s+)?'
            r'([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)'
            r'\s*,\s*"([^"]+)"'
        ),
        # X disse: "quote"
        re.compile(
            r'([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)'
            r'\s+(?:disse|afirmou|declarou|explicou|acrescentou)'
            r'\s*:\s*"([^"]+)"'
        ),
        # Bare quoted text
        re.compile(r'"([^"]+)"', re.UNICODE),
        re.compile(r'«([^»]+)»'),
    ],
    "en": [
        # "quote" said X
        re.compile(
            r'"([^"]+)"\s*,?\s*'
            r'(?:said|told|stated|explained|added|noted|warned|criticized|'
            r'defended|acknowledged|admitted|denied|promised|announced|'
            r'confirmed|stressed|highlighted)'
            r'\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
        ),
        # according to X, "quote"
        re.compile(
            r'(?:according to|per)'
            r'\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
            r'\s*,\s*"([^"]+)"'
        ),
        # X said: "quote"
        re.compile(
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
            r'\s+(?:said|told|stated|explained|added)\s*:\s*"([^"]+)"'
        ),
        re.compile(r'"([^"]+)"'),
    ],
}

# ── Regex patterns for entity categories ────────────────────────────────────

MONEY_PATTERN = re.compile(
    r'(?:'
    r'€\s*[\d.,]+|'
    r'[\d.,]+\s*€|'
    r'(?:[\d.,]+\s*)?(?:mil|milh[oõ]es|milhares|bilh[oõ]es)\s*(?:de\s*)?'
    r'(?:euros|dólares|dollars)|'
    r'\$\s*[\d.,]+'
        r'(?:[\s-]?(?:milhão|milhões|billion|trillion|million|bn|m))?'
    r')',
    re.IGNORECASE,
)

PCT_PATTERN = re.compile(r'[\d.,]+\s*%')

DATE_PATTERN = re.compile(
    r'\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}|'
    r'[A-Z][a-z]+ç?[a-z]*\s+\d{4}|'
    r'\d{4}-\d{2}-\d{2}'
)

_NUMERAL_WORDS_PT = {
    "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete",
    "oito", "nove", "dez", "onze", "doze", "treze", "catorze",
    "quinze", "dezasseis", "dezassete", "dezoito", "dezanove", "vinte",
    "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta",
    "noventa", "cem", "cento", "duzentos", "trezentos", "quatrocentos",
    "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos",
    "mil", "milhão", "milhões", "milhar", "milhares", "bilhão", "bilhões",
}


# ── Internal helpers ────────────────────────────────────────────────────────

def _get_nlp(language: str) -> "spacy.Language | None":
    """Get or load a spaCy model for the given language."""
    import spacy

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
    if not text.strip():
        return []
    pattern = re.compile(
        r'(?:\b(?:' + '|'.join(_NUMERAL_WORDS_PT) + r')\b\s*)+',
        re.IGNORECASE,
    )
    facts = []
    for match in pattern.finditer(text):
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

            if len(groups) >= 2 and groups[0] and groups[-1]:
                # Pattern with speaker attribution
                # The quote is in groups[0], speaker in groups[-1]
                quote_text = groups[0].strip()
                speaker = groups[-1].strip()
            elif len(groups) >= 1 and groups[0]:
                # Just a quoted string, no speaker
                quote_text = groups[0].strip()
                speaker = None
            else:
                continue

            if quote_text and quote_text not in seen_texts:
                seen_texts.add(quote_text)
                quotations.append(Quotation(
                    speaker=speaker,
                    text=quote_text,
                    span_start=match.start(),
                    span_end=match.end(),
                ))

    return quotations


# ── Public API ──────────────────────────────────────────────────────────────

def extract_article(
    source_id: str,
    title: str,
    content_text: str,
    language: str,
) -> ExtractedArticle:
    """Extract structured facts, entities, and quotations from an article.

    Args:
        source_id: The source identifier (e.g. 'lusa', 'reuters').
        title: Article title.
        content_text: Full article text.
        language: ISO 639-1 code ('pt', 'en', 'es').

    Returns:
        ExtractedArticle with all detected facts and quotations.
    """
    full_text = f"{title}\n\n{content_text}" if content_text else title
    word_count = len(full_text.split())

    # ── spaCy-based NER ──
    nlp = _get_nlp(language)
    spacy_entities: list[Fact] = []
    if nlp and full_text.strip():
        doc = nlp(full_text[:50000])  # limit to avoid OOM
        for ent in doc.ents:
            cat = _classify_spacy_entity(ent.label_)
            if cat:
                spacy_entities.append(Fact(
                    text=ent.text,
                    category=cat,
                    span_start=ent.start_char,
                    span_end=ent.end_char,
                ))

    # ── Regex-based extractions (works without spaCy) ──
    money_facts = _extract_money_facts(full_text)
    pct_facts = _extract_pct_facts(full_text)
    numeral_facts = _extract_numeral_words(full_text)

    # ── Merge and deduplicate facts ──
    seen_spans: set[tuple[int, int]] = set()
    all_facts: list[Fact] = []

    for fact_list in [spacy_entities, money_facts, pct_facts, numeral_facts]:
        for fact in fact_list:
            key = (fact.span_start, fact.span_end)
            if key not in seen_spans:
                seen_spans.add(key)
                all_facts.append(fact)

    all_facts.sort(key=lambda f: f.span_start)

    # ── Quotations ──
    quotations = _extract_quotations(full_text, language)

    # ── Sentence splitting ──
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
