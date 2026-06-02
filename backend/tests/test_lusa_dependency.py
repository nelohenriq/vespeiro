"""Behavioral/integration tests for LusaDependencyAnalyzer.

Tests the public API (``analyze()``, ``daily_timeline()``) with mocked DB
sessions and synthetic data.  Core matching logic (TF-IDF / embedding) is
tested separately in ``test_dependency_analyzer.py``.

Replaces previous placeholder tests (were ``assert True``).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from src.analysis.dependency.analyzer import LusaDependencyAnalyzer
from src.db.models import Article, Source
from src.stats.models import LusaDependencyMetrics


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_article(
    title: str,
    content: str,
    source_id: str = "lusa",
) -> Article:
    """Create a minimal Article instance for testing."""
    return Article(
        id=str(uuid.uuid4()),
        source_id=source_id,
        url="https://example.com/article",
        title=title,
        content_text=content,
    )


def _make_source(source_id: str, language: str = "pt") -> Source:
    """Create a minimal Source instance for testing."""
    return Source(
        id=source_id,
        name=source_id.replace("_", " ").title(),
        language=language,
        category="mainstream",
        is_active=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  analyze() — integration with mocked DB
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalyze:
    """``LusaDependencyAnalyzer.analyze()`` with various scenarios."""

    @pytest.mark.asyncio
    async def test_analyze_no_db_returns_defaults(self) -> None:
        """Without a DB session, ``analyze()`` returns all-safe defaults."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        result = await analyzer.analyze()
        assert isinstance(result, LusaDependencyMetrics)
        assert result.global_pct is None
        assert result.per_outlet == {}
        assert result.per_topic == {}

    @pytest.mark.asyncio
    async def test_analyze_without_model_fallback(self) -> None:
        """When embedding model is unavailable, analyze() returns zero metrics."""
        analyzer = LusaDependencyAnalyzer(db_session=AsyncMock())

        lusa_articles = [
            _make_article(
                "Governo anuncia investimento de 2.3 milhões na saúde",
                "O governo português anunciou um investimento de 2.3 milhões "
                "de euros no setor da saúde.",
                source_id="lusa",
            ),
        ]
        pt_outlets = [
            _make_source("publico"),
            _make_source("expresso"),
        ]

        analyzer._fetch_articles = AsyncMock(return_value=lusa_articles)
        analyzer._fetch_portuguese_outlets = AsyncMock(return_value=pt_outlets)

        # When _embed_articles returns None (model unavailable), analyze()
        # should return global_pct=0.0 (safe default) instead of crashing.
        with patch.object(analyzer, "_embed_articles", return_value=None):
            result = await analyzer.analyze()
            assert isinstance(result, LusaDependencyMetrics)
            assert result.global_pct == 0.0

    @pytest.mark.asyncio
    async def test_analyze_with_mock_embeddings(self) -> None:
        """With mocked embeddings, analyze() computes correct dependency scores."""
        analyzer = LusaDependencyAnalyzer(
            db_session=AsyncMock(),
            match_threshold=0.50,
        )

        lusa_articles = [
            _make_article(
                "Saúde: governo investe 2.3 milhões",
                "Texto sobre investimento na saúde.",
            ),
            _make_article(
                "Economia: PIB cresce 2.5%",
                "Texto sobre crescimento económico.",
            ),
        ]
        pt_outlets = [
            _make_source("publico"),
            _make_source("expresso"),
        ]

        # Return a matching article for any outlet
        async def mock_fetch(source_id: str, start, end) -> list[Article]:
            if source_id == "lusa":
                return lusa_articles
            return [
                _make_article(
                    "Governo investe 2.3 milhões na saúde",
                    "O governo investiu 2.3 milhões na área da saúde.",
                    source_id=source_id,
                ),
            ]

        analyzer._fetch_articles = AsyncMock(side_effect=mock_fetch)
        analyzer._fetch_portuguese_outlets = AsyncMock(return_value=pt_outlets)

        # Mock embeddings: make outlet article similar to Lusa health article
        # Lusa vectors: [health, economy]
        # Outlet vectors: [health] — matches first Lusa vector
        mock_lusa_vecs = np.array([
            [0.8, 0.2, 0.1],    # health topic
            [0.1, 0.1, 0.9],    # economy topic
        ], dtype=np.float64)
        mock_outlet_vecs = np.array([
            [0.75, 0.25, 0.15],  # health — should match first Lusa
        ], dtype=np.float64)

        with patch.object(analyzer, "_embed_articles", side_effect=[
            mock_lusa_vecs,     # Lusa embeddings (called once)
            mock_outlet_vecs,   # publico embeddings
            mock_outlet_vecs,   # expresso embeddings
        ]):
            result = await analyzer.analyze()
            assert isinstance(result, LusaDependencyMetrics)
            # global_pct should be > 0 since we mocked high-similarity embeddings
            assert result.global_pct is not None
            assert result.global_pct > 0
            assert "publico" in result.per_outlet
            assert "expresso" in result.per_outlet
            # Both outlets should have a derived article
            assert result.per_outlet["publico"].lusa_derived >= 1
            assert result.per_outlet["expresso"].lusa_derived >= 1
            # per_topic should be populated (topic classification is now active)
            assert isinstance(result.per_topic, dict)
            assert len(result.per_topic) > 0
            for topic_key, pct in result.per_topic.items():
                assert isinstance(topic_key, str)
                assert isinstance(pct, float)


# ═══════════════════════════════════════════════════════════════════════════════
#  daily_timeline() — behavioral tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDailyTimeline:
    """``LusaDependencyAnalyzer.daily_timeline()`` behavior."""

    @pytest.mark.asyncio
    async def test_daily_timeline_no_db(self) -> None:
        """Without DB, ``daily_timeline()`` returns an empty list."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        result = await analyzer.daily_timeline(days=7)
        assert result == []

    @pytest.mark.asyncio
    async def test_daily_timeline_with_mock(self) -> None:
        """With mocked DB/embeddings, returns list of the correct length."""
        analyzer = LusaDependencyAnalyzer(
            db_session=AsyncMock(),
            match_threshold=0.50,
        )

        lusa_articles = [
            _make_article("Saúde: investimento", "Texto sobre saúde."),
        ]
        pt_outlets = [_make_source("publico")]

        analyzer._fetch_articles = AsyncMock(return_value=lusa_articles)
        analyzer._fetch_portuguese_outlets = AsyncMock(return_value=pt_outlets)

        mock_vecs = np.array([[0.8, 0.2, 0.1]], dtype=np.float64)

        with patch.object(analyzer, "_embed_articles", return_value=mock_vecs):
            result = await analyzer.daily_timeline(days=7)
            assert len(result) == 7
            assert all(isinstance(v, float) for v in result)


# ═══════════════════════════════════════════════════════════════════════════════
#  _count_derived_from_vecs — direct unit tests with synthetic vectors
# ═══════════════════════════════════════════════════════════════════════════════


class TestCountDerivedFromVecs:
    """Direct tests of ``_count_derived_from_vecs`` with synthetic vectors.

    Unlike the embedding-dependent tests in ``test_dependency_analyzer.py``,
    these work with raw numpy arrays and don't need a model.
    """

    def test_perfect_match(self) -> None:
        """Similar vectors should count as derived."""
        analyzer = LusaDependencyAnalyzer(db_session=None, match_threshold=0.50)
        lusa_vecs = np.array([[0.8, 0.2, 0.1]], dtype=np.float64)
        outlet_vecs = np.array([[0.75, 0.25, 0.15]], dtype=np.float64)
        assert analyzer._count_derived_from_vecs(lusa_vecs, outlet_vecs) == 1

    def test_no_match(self) -> None:
        """Very dissimilar vectors should NOT count as derived."""
        analyzer = LusaDependencyAnalyzer(db_session=None, match_threshold=0.50)
        lusa_vecs = np.array([[0.8, 0.2, 0.1]], dtype=np.float64)
        outlet_vecs = np.array([[0.1, 0.8, 0.1]], dtype=np.float64)
        assert analyzer._count_derived_from_vecs(lusa_vecs, outlet_vecs) == 0

    def test_multiple_lusa_articles(self) -> None:
        """With multiple Lusa articles, best match determines derivation."""
        analyzer = LusaDependencyAnalyzer(db_session=None, match_threshold=0.50)
        lusa_vecs = np.array([
            [0.8, 0.2, 0.1],    # health topic
            [0.1, 0.1, 0.8],    # sports topic
        ], dtype=np.float64)
        outlet_vecs = np.array([
            [0.75, 0.25, 0.15],  # health → matches first Lusa
            [0.12, 0.08, 0.85],  # sports → matches second Lusa
        ], dtype=np.float64)
        assert analyzer._count_derived_from_vecs(lusa_vecs, outlet_vecs) == 2

    def test_empty_vectors(self) -> None:
        """Empty vectors should return 0 without crashing."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        empty = np.array([], dtype=np.float64)
        non_empty = np.array([[0.5, 0.5]], dtype=np.float64)
        assert analyzer._count_derived_from_vecs(empty, non_empty) == 0
        assert analyzer._count_derived_from_vecs(non_empty, empty) == 0
        assert analyzer._count_derived_from_vecs(empty, empty) == 0

    def test_dependency_calculation_scenario(self) -> None:
        """Scenario: 2 Lusa articles, 2 outlet articles → 1 derived → 50%."""
        analyzer = LusaDependencyAnalyzer(db_session=None, match_threshold=0.50)

        # 2 Lusa articles: health (sim to outlet[0]), economy (sim to outlet[1])
        lusa_vecs = np.array([
            [0.8, 0.2, 0.1],    # health
            [0.1, 0.1, 0.8],    # economy
        ], dtype=np.float64)

        # 2 outlet articles: health (matches Lusa[0]), sports (matches nothing)
        outlet_vecs = np.array([
            [0.75, 0.25, 0.15],  # health → derived (sim ~0.98) ✅
            [0.05, 0.95, 0.05],  # sports → NOT derived (sim ~0.08) ❌
        ], dtype=np.float64)

        derived = analyzer._count_derived_from_vecs(lusa_vecs, outlet_vecs)
        assert derived == 1
        # This proves a scenario: 1/2 → 50% dependency
        pct = derived / 2 * 100
        assert pct == 50.0
