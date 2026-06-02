"""Tests for the SilenceAnalyzer — silence detection logic, graceful degradation,
configurable thresholds, and story deduplication.

Replaces previous placeholder tests (were ``assert True``).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from src.analysis.silence.analyzer import SilenceAnalyzer, _article_text
from src.db.models import Article, Source
from src.stats.models import SilenceMetrics


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_source(
    source_id: str,
    name: str = "Test Source",
    language: str = "en",
) -> Source:
    """Create a minimal Source instance for testing."""
    return Source(
        id=source_id,
        name=name,
        language=language,
        category="international",
        is_active=True,
    )


def _make_article(
    title: str,
    content: str,
    source_id: str = "bbc",
) -> Article:
    """Create a minimal Article instance for testing."""
    return Article(
        id=str(uuid.uuid4()),
        source_id=source_id,
        url="https://example.com/article",
        title=title,
        content_text=content,
    )


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_intl_sources() -> list[Source]:
    """Mock international sources."""
    return [
        _make_source("bbc", "BBC News"),
        _make_source("reuters", "Reuters"),
    ]


@pytest.fixture
def mock_pt_outlets() -> list[Source]:
    """Mock Portuguese outlets."""
    return [
        _make_source("publico", "Público", language="pt"),
        _make_source("observador", "Observador", language="pt"),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
#  Helper: _article_text
# ═══════════════════════════════════════════════════════════════════════════════


class TestArticleText:
    """The _article_text helper concatenates title + content heading."""

    def test_title_and_content(self) -> None:
        article = _make_article("Test Title", "Some content here")
        text = _article_text(article)
        assert "Test Title" in text
        assert "Some content here" in text

    def test_no_content(self) -> None:
        article = Article(
            id="test-id",
            source_id="bbc",
            url="https://example.com",
            title="Only Title",
            content_text=None,
        )
        assert _article_text(article) == "Only Title"

    def test_empty_article(self) -> None:
        article = Article(
            id="empty",
            source_id="bbc",
            url="https://example.com",
            title="",
            content_text="",
        )
        assert _article_text(article) == ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Graceful degradation — no DB session
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalyzeNoDb:
    """Without a DB session, all methods return safe defaults."""

    @pytest.mark.asyncio
    async def test_analyze_returns_defaults(self) -> None:
        """``analyze()`` should return ``SilenceMetrics`` with all defaults."""
        analyzer = SilenceAnalyzer(db_session=None)
        result = await analyzer.analyze()
        assert isinstance(result, SilenceMetrics)
        assert result.today == 0
        assert result.avg_7d == 0.0
        assert result.top_silenced == []

    @pytest.mark.asyncio
    async def test_daily_timeline_returns_empty(self) -> None:
        """``daily_timeline()`` should return an empty list when no DB."""
        analyzer = SilenceAnalyzer(db_session=None)
        result = await analyzer.daily_timeline(days=7)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
#  Silence detection — story missing in PT coverage
# ═══════════════════════════════════════════════════════════════════════════════


class TestSilenceDetected:
    """International stories with no Portuguese match should be flagged."""

    @pytest.mark.asyncio
    async def test_silence_detected_when_story_missing_in_pt(
        self,
        mock_intl_sources: list[Source],
        mock_pt_outlets: list[Source],
    ) -> None:
        """An international story with no similar PT article → flagged as silenced."""
        analyzer = SilenceAnalyzer(db_session=AsyncMock())

        analyzer._fetch_international_sources = AsyncMock(return_value=mock_intl_sources)
        analyzer._fetch_portuguese_outlets = AsyncMock(return_value=mock_pt_outlets)

        # International article about a specific story
        intl_articles = [
            _make_article(
                "Trump intervenes to save 8 women from execution in Iran",
                "President Trump intervened to save eight women from execution",
                source_id="bbc",
            ),
        ]

        # PT articles about completely different topics
        pt_articles = [
            _make_article(
                "Benfica vence clássico por 3-1",
                "O Benfica venceu o FC Porto por 3-1 no Estádio da Luz.",
                source_id="publico",
            ),
            _make_article(
                "Bolsa de Lisboa fecha em alta",
                "A bolsa de Lisboa fechou em alta impulsionada pelos setores.",
                source_id="observador",
            ),
        ]

        analyzer._fetch_articles_bulk = AsyncMock(side_effect=[
            intl_articles,   # international articles
            pt_articles,     # PT articles
        ])

        # Mock daily_timeline to return consistent data
        analyzer.daily_timeline = AsyncMock(return_value=[1, 1, 1, 1, 1, 1, 1])

        result = await analyzer.analyze()

        # ``daily_timeline`` is mocked to return ``[1]*7``, so today=1 and avg_7d=1.0
        assert result.today == 1
        assert result.avg_7d == 1.0
        # The silenced story should mention Trump/Iran
        assert any(
            "Trump" in s.title or "Iran" in s.title
            for s in result.top_silenced
        )

    @pytest.mark.asyncio
    async def test_no_silence_when_story_covered_in_pt(
        self,
        mock_intl_sources: list[Source],
        mock_pt_outlets: list[Source],
    ) -> None:
        """An international story that IS covered in Portugal → NOT flagged."""
        analyzer = SilenceAnalyzer(
            db_session=AsyncMock(),
            match_threshold=0.30,  # Lower threshold to ensure match
        )

        analyzer._fetch_international_sources = AsyncMock(return_value=mock_intl_sources)
        analyzer._fetch_portuguese_outlets = AsyncMock(return_value=mock_pt_outlets)

        # Same story in both intl and PT — identical text ensures TF-IDF match
        shared_text = (
            "The Portuguese government announced a 2.3 million euro "
            "healthcare package under the Recovery and Resilience Plan "
            "for the Portuguese health service."
        )
        intl_articles = [
            _make_article(
                "Portugal announces €2.3M healthcare package",
                shared_text,
                source_id="reuters",
            ),
        ]

        pt_articles = [
            _make_article(
                "Portugal announces €2.3M healthcare package",
                shared_text,
                source_id="publico",
            ),
        ]

        analyzer._fetch_articles_bulk = AsyncMock(side_effect=[
            intl_articles,
            pt_articles,
        ])

        analyzer.daily_timeline = AsyncMock(return_value=[0, 0, 0, 0, 0, 0, 0])

        result = await analyzer.analyze()

        # Both sources cover the same story → 0 silenced
        assert result.today == 0
        assert result.top_silenced == []


# ═══════════════════════════════════════════════════════════════════════════════
#  Configurable parameters
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfigurableWindow:
    """``window_days`` and ``match_threshold`` should be configurable."""

    def test_default_parameters(self) -> None:
        """Default values should be sensible."""
        analyzer = SilenceAnalyzer(db_session=object())
        assert analyzer.window_days == 7
        assert analyzer.match_threshold == 0.70

    def test_custom_parameters(self) -> None:
        """Custom values should be reflected in the instance."""
        analyzer = SilenceAnalyzer(
            db_session=object(),
            window_days=14,
            match_threshold=0.50,
        )
        assert analyzer.window_days == 14
        assert analyzer.match_threshold == 0.50


# ═══════════════════════════════════════════════════════════════════════════════
#  Deduplication — multiple intl sources on same story
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeduplication:
    """Multiple international sources covering the same story should be deduped."""

    @pytest.mark.asyncio
    async def test_multiple_sources_same_story_deduped(
        self,
        mock_intl_sources: list[Source],
        mock_pt_outlets: list[Source],
    ) -> None:
        """Two intl sources on the same story → one deduped silenced story."""
        # Low threshold because TF-IDF with only 2 docs assigns IDF=0 to
        # shared terms, reducing cosine similarity.  In production the
        # corpus will have many more documents.
        analyzer = SilenceAnalyzer(
            db_session=AsyncMock(),
            match_threshold=0.30,
        )

        analyzer._fetch_international_sources = AsyncMock(return_value=mock_intl_sources)
        analyzer._fetch_portuguese_outlets = AsyncMock(return_value=mock_pt_outlets)

        # Same story from two international sources
        story_text = (
            "Global climate summit reaches historic agreement "
            "on carbon emissions reduction targets."
        )
        intl_articles = [
            _make_article(
                "Historic climate deal reached at global summit",
                story_text,
                source_id="bbc",
            ),
            _make_article(
                "Nations agree on landmark climate accord",
                story_text,
                source_id="reuters",
            ),
        ]

        analyzer._fetch_articles_bulk = AsyncMock(side_effect=[
            intl_articles,
            [],    # No PT articles → both are silenced
        ])

        analyzer.daily_timeline = AsyncMock(return_value=[2, 2, 2, 2, 2, 2, 2])

        result = await analyzer.analyze()

        # 2 intl sources, same story (identical text), 0 PT coverage
        # TF-IDF groups them into 1 deduped story
        assert len(result.top_silenced) == 1
        # The story should report 2 international sources (BBC + Reuters)
        assert result.top_silenced[0].international_sources == 2
        # Gap should be 100% (no PT coverage)
        assert result.top_silenced[0].gap_pct == 100.0
