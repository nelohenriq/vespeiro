"""Compare two articles across multiple dimensions: omission, framing, quotes, headline."""

import re
from datetime import datetime, timezone
from src.analysis.divergence.models import (
    Fact, Quotation, ExtractedArticle, DivergenceReport,
)


# ── Fact matching helpers ───────────────────────────────────────────────────

def _fact_matches_any(fact: Fact, version_text: str) -> bool:
    """Check if a fact from the original article appears in the Portuguese version.

    Uses fuzzy matching:
    - Exact text match (case-insensitive)
    - Number normalization ("2.3M€" ≈ "2,3 milhões de euros")
    - Partial match via significant words
    - Money amount normalisation (remove separators)
    """
    original_text = fact.text.lower()
    version_lower = version_text.lower()

    # Direct substring match
    if original_text in version_lower:
        return True

    # Money normalisation: extract numeric parts
    if fact.category.value == "money":
        numbers = re.findall(r'[\d.,]+', original_text)
        for num in numbers:
            if num in version_lower:
                return True
            # Normalise thousand separators: "2.3" → compute
            stripped = num.replace(".", "").replace(",", "")
            if len(stripped) > 1 and stripped in version_lower:
                return True

    # Check significant words (length > 3)
    words = original_text.split()
    significant = [w for w in words if len(w) > 3]
    if significant:
        matches = sum(1 for w in significant if w in version_lower)
        if matches / len(significant) >= 0.5:
            return True

    return False


def _compute_quote_fidelity(
    original_quotes: list[Quotation],
    version_text: str,
) -> tuple[float, list[dict], int, int]:
    """Compare quotes between original and version.

    Returns:
        Tuple of (fidelity_score, altered_quotes_list, verbatim_count, total).
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
            speaker = getattr(q, "speaker", None)
            if speaker and speaker.lower() in version_lower:
                # Speaker present but quote changed
                altered_quotes.append({
                    "original": q.text,
                    "portuguese": "ALTERED OR OMITTED",
                    "speaker": speaker,
                    "status": "altered",
                })
            else:
                altered_quotes.append({
                    "original": q.text,
                    "portuguese": None,
                    "speaker": speaker,
                    "status": "omitted",
                })

    fidelity = verbatim / total if total > 0 else 1.0
    return fidelity, altered_quotes, verbatim, total


# ── Public API ──────────────────────────────────────────────────────────────

def compute_omission_score(
    original: ExtractedArticle,
    version: ExtractedArticle,
) -> tuple[float | None, list[Fact], list[Fact]]:
    """Compute fact omission score.

    Returns:
        Tuple of (score, omitted_facts, preserved_facts).
        Score is None when the original has no facts to compare.
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
        original: The extracted original source article (Lusa, Reuters, …).
        portuguese_version: The extracted Portuguese outlet version.
        original_sentiment: Optional sentiment dict from pysentimiento.
        portuguese_sentiment: Optional sentiment dict from pysentimiento.

    Returns:
        DivergenceReport with all dimension scores.
    """
    # 1. Fact omission
    omission_score, omitted_facts, preserved_facts = compute_omission_score(
        original, portuguese_version,
    )

    # 2. Quote fidelity
    full_version_text = (
        f"{portuguese_version.title} {portuguese_version.content_text}"
    )
    quote_fidelity, altered_quotes, verbatim_count, total_quotes = (
        _compute_quote_fidelity(original.quotations, full_version_text)
    )

    # 3. Sentiment shift (requires Phase 0.9 pysentimiento)
    sentiment_shift = None
    if original_sentiment and portuguese_sentiment:
        orig_score = _sentiment_to_score(original_sentiment)
        pt_score = _sentiment_to_score(portuguese_sentiment)
        if orig_score is not None and pt_score is not None:
            sentiment_shift = pt_score - orig_score

    # 4. Headline divergence (placeholder — will use embeddings from Phase 0.7)
    headline_divergence = _compute_headline_divergence_placeholder(
        original.title, portuguese_version.title,
    )

    # 5. Overall weighted score
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


# ── Internal helpers ────────────────────────────────────────────────────────

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
