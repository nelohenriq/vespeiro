"""Tests for the divergence report generator."""

import pytest
from datetime import datetime
from src.analysis.divergence.reporter import (
    report_to_json, report_to_markdown, aggregate_summary,
)
from src.analysis.divergence.models import (
    Fact, FactCategory, DivergenceReport, OutletDivergenceSummary,
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
            },
        ],
        headline_original="Minister resigns over scandal",
        headline_portuguese="Governo anuncia mudanças na pasta",
        original_sentiment={"sentiment": "NEG", "probas": {"NEG": 0.8, "NEU": 0.15, "POS": 0.05}},
        portuguese_sentiment={"sentiment": "NEU", "probas": {"NEG": 0.2, "NEU": 0.7, "POS": 0.1}},
    )


def test_report_to_json(sample_report):
    json_str = report_to_json(sample_report)
    assert isinstance(json_str, str)
    assert "overall_divergence_score" in json_str
    assert "0.62" in json_str
    assert "2.3M" in json_str  # € is escaped as \u20ac in JSON
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
    summary = aggregate_summary(
        reports, "publico",
        datetime(2026, 5, 26), datetime(2026, 5, 27),
    )
    assert summary.outlet_id == "publico"
    assert summary.stories_analyzed == 2
    assert summary.avg_omission == pytest.approx(0.5, abs=0.01)
    assert summary.avg_sentiment_shift == pytest.approx(0.15, abs=0.01)
    assert summary.avg_quote_fidelity == pytest.approx(0.7, abs=0.01)
    assert summary.avg_headline_divergence == pytest.approx(0.4, abs=0.01)
