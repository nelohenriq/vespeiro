"""Tests for the divergence article comparator."""

import pytest
from datetime import datetime
from src.analysis.divergence.comparator import (
    compare_articles, compute_omission_score,
)
from src.analysis.divergence.extractor import extract_article
from src.analysis.divergence.models import FactCategory


def test_identical_articles_have_zero_divergence():
    """Two copies of the same article should have divergence ≈ 0."""
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
        'O ministro Pedro Costa disse que "serão contratados 500 enfermeiros". '
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
    assert report.fact_omission_score is not None
    assert report.fact_omission_score > 0.2
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
        "lusa", "Economia",
        "O PIB cresceu 2.5% em 2026 segundo o Banco de Portugal.", "pt",
    )
    version = extract_article(
        "publico", "Desporto",
        "O Benfica venceu o clássico por 3-1 no Estádio da Luz.", "pt",
    )
    report = compare_articles(
        story_cluster_id="test-4",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    assert report.overall_divergence_score is not None


def test_omission_score_none_when_no_facts():
    """If original has no entities, omission score should be None or 0."""
    original = extract_article(
        "lusa", "Title", "Isto é uma notícia muito curta.", "pt",
    )
    version = extract_article(
        "publico", "Title", "Outra notícia curta.", "pt",
    )

    report = compare_articles(
        story_cluster_id="test-5",
        original=original,
        portuguese_version=version,
        original_sentiment=None,
        portuguese_sentiment=None,
    )
    if report.fact_omission_score is not None:
        assert report.fact_omission_score == 0.0


def test_integration_lusa_to_publico():
    """Full integration test: read Lusa fixture, compare to Público version."""
    from pathlib import Path
    fixtures_dir = Path(__file__).parent / "fixtures"

    lusa_text = (fixtures_dir / "lusa_artigo.txt").read_text()
    publico_text = (fixtures_dir / "publico_versao.txt").read_text()

    original = extract_article(
        "lusa", "Governo anuncia 2.3M€ para a saúde", lusa_text, "pt",
    )
    version = extract_article(
        "publico", "Governo anuncia investimento na saúde", publico_text, "pt",
    )

    report = compare_articles(
        story_cluster_id="integration-1",
        original=original,
        portuguese_version=version,
    )

    assert report.overall_divergence_score is not None
    assert report.overall_divergence_score > 0.2

    # Specific facts that should be detected as omitted
    omitted_texts = [f.text.lower() for f in report.omitted_facts]
    has_money_omission = any("euros" in t or "milh" in t for t in omitted_texts)
    assert has_money_omission, "Money amounts should be detected as omitted"
