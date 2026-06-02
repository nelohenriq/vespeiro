"""Tests for advertising-editorial correlation analyzer."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.analysis.correlation import CorrelationAnalyzer
from src.db.models import Article


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_article(
    title: str,
    content: str,
    source_id: str = "publico",
) -> Article:
    """Create a minimal Article instance for testing."""
    return Article(
        id=str(uuid.uuid4()),
        source_id=source_id,
        url="https://example.com/article",
        title=title,
        content_text=content,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Pearson r computation
# ═══════════════════════════════════════════════════════════════════════════════


class TestPearsonR:
    """Test Pearson correlation computation."""

    def test_perfect_positive(self) -> None:
        r = CorrelationAnalyzer._pearson_r([(1, 2), (2, 4), (3, 6), (4, 8)])
        assert r is not None
        assert abs(r - 1.0) < 0.001

    def test_perfect_negative(self) -> None:
        r = CorrelationAnalyzer._pearson_r([(1, 8), (2, 6), (3, 4), (4, 2)])
        assert r is not None
        assert abs(r + 1.0) < 0.001

    def test_no_correlation(self) -> None:
        r = CorrelationAnalyzer._pearson_r([(1, 5), (2, 2), (3, 8), (4, 3)])
        assert r is not None
        assert abs(r) < 0.5

    def test_insufficient_data(self) -> None:
        r = CorrelationAnalyzer._pearson_r([(1, 2), (2, 4)])
        assert r is None

    def test_constant_y(self) -> None:
        """When y is constant, denominator is zero → None."""
        r = CorrelationAnalyzer._pearson_r([(1, 5), (2, 5), (3, 5), (4, 5)])
        assert r is None

    def test_constant_x(self) -> None:
        """When x is constant, denominator is zero → None."""
        r = CorrelationAnalyzer._pearson_r([(5, 1), (5, 2), (5, 3), (5, 4)])
        assert r is None


# ═══════════════════════════════════════════════════════════════════════════════
#  Sentiment text builder
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildSentimentText:
    """``_build_sentiment_text`` extracts title + lead for sentiment analysis."""

    def test_title_and_content(self) -> None:
        article = _make_article(
            "Governo anuncia investimento",
            "O governo anunciou um investimento de 2.3 milhões de euros.",
        )
        text = CorrelationAnalyzer._build_sentiment_text(article)
        assert "Governo" in text
        assert "investimento" in text
        assert "2.3 milhões" in text

    def test_fallback_to_summary(self) -> None:
        """When content_text is empty, falls back to summary."""
        article = Article(
            id="sum-only",
            source_id="publico",
            url="https://example.com",
            title="Resumo sem corpo",
            content_text=None,
            summary="Este é o resumo do artigo com &amp; HTML entities.",
        )
        text = CorrelationAnalyzer._build_sentiment_text(article)
        assert "Resumo" in text
        assert "&amp;" not in text  # HTML entities decoded
        assert "&" in text  # &amp; decoded → &

    def test_empty_article(self) -> None:
        """Empty title and no content → empty string."""
        article = Article(
            id="empty", source_id="publico", url="https://x.com",
            title="", content_text="",
        )
        assert CorrelationAnalyzer._build_sentiment_text(article) == ""


# ═══════════════════════════════════════════════════════════════════════════════
#  _compute_avg_sentiment
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeAvgSentiment:
    """``_compute_avg_sentiment`` with mocked DB and sentiment analyzer."""

    @pytest.mark.asyncio
    async def test_no_db_returns_none(self) -> None:
        """Without a DB session, avg_sentiment is None."""
        analyzer = CorrelationAnalyzer(db_session=None)
        mock_sentiment = MagicMock()
        result = await analyzer._compute_avg_sentiment("publico", mock_sentiment)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_articles_returns_none(self) -> None:
        """When DB returns no articles, avg_sentiment is None."""
        mock_db = MagicMock()
        async_exec = AsyncMock()
        async_exec.return_value = MagicMock()
        async_exec.return_value.scalars.return_value.all.return_value = []
        mock_db.execute = async_exec
        analyzer = CorrelationAnalyzer(db_session=mock_db)
        mock_sentiment = MagicMock()
        result = await analyzer._compute_avg_sentiment("publico", mock_sentiment)
        assert result is None

    @pytest.mark.asyncio
    async def test_avg_sentiment_computed(self) -> None:
        """With article texts and sentiment results, computes correct average."""
        articles = [
            _make_article("Título positivo", "Conteúdo muito bom!", source_id="publico"),
            _make_article("Título negativo", "Conteúdo terrível e mau.", source_id="publico"),
        ]

        mock_db = MagicMock()
        async_exec = AsyncMock()
        async_exec.return_value = MagicMock()
        async_exec.return_value.scalars.return_value.all.return_value = articles
        mock_db.execute = async_exec

        mock_sentiment = MagicMock()
        mock_sentiment.analyze_batch.return_value = [
            {"sentiment": "POS", "probas": {"POS": 0.95, "NEG": 0.03, "NEU": 0.02}},
            {"sentiment": "NEG", "probas": {"POS": 0.02, "NEG": 0.92, "NEU": 0.06}},
        ]
        # Set score as a callable on the mock explicitly
        score_mock = MagicMock(side_effect=lambda r: (
            0.95 if r["sentiment"] == "POS" else -0.92
        ))
        mock_sentiment.score = score_mock

        analyzer = CorrelationAnalyzer(db_session=mock_db)
        result = await analyzer._compute_avg_sentiment("publico", mock_sentiment)
        assert result is not None
        # (0.95 + -0.92) / 2 = 0.015
        assert abs(result - 0.015) < 0.001

    @pytest.mark.asyncio
    async def test_sentiment_failure_graceful(self) -> None:
        """When sentiment analyzer fails, returns None gracefully."""
        articles = [
            _make_article("Título", "Conteúdo.", source_id="publico"),
        ]

        mock_db = MagicMock()
        async_exec = AsyncMock()
        async_exec.return_value = MagicMock()
        async_exec.return_value.scalars.return_value.all.return_value = articles
        mock_db.execute = async_exec

        mock_sentiment = MagicMock()
        mock_sentiment.analyze_batch.return_value = [None]  # Model unavailable
        mock_sentiment.score.return_value = None

        analyzer = CorrelationAnalyzer(db_session=mock_db)
        result = await analyzer._compute_avg_sentiment("publico", mock_sentiment)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
#  Full analyzer
# ═══════════════════════════════════════════════════════════════════════════════


class TestCorrelationAnalyzer:
    """Test the full correlation analyzer."""

    @pytest.mark.asyncio
    async def test_analyze_no_db(self) -> None:
        """Analyzer returns outlets from ownership config even without DB."""
        analyzer = CorrelationAnalyzer(db_session=None)
        report = await analyzer.analyze()
        # Outlets come from ownership.yaml (loaded regardless of DB)
        assert len(report.outlets) >= 10  # 12 known outlet patterns
        assert report.r_spend_vs_articles is None  # No DB → no editorial data
        assert report.r_spend_vs_gov_coverage is None
        assert report.total_ad_spend_estimated == 0.0  # No DB → no spending data

    def test_outlet_patterns_all_known(self) -> None:
        """All known outlet patterns should be present."""
        analyzer = CorrelationAnalyzer()
        assert len(analyzer._OUTLET_PATTERNS) >= 10
        assert "rtp_noticias" in analyzer._OUTLET_PATTERNS
        assert "publico" in analyzer._OUTLET_PATTERNS
        assert "sic_noticias" in analyzer._OUTLET_PATTERNS

    def test_load_ownership_map_no_db(self) -> None:
        """Ownership map loads from YAML regardless of DB."""
        analyzer = CorrelationAnalyzer()
        ownership = analyzer._load_ownership_map()
        # Should load from ownership.yaml
        assert len(ownership) >= 10
        assert "rtp_noticias" in ownership
        assert ownership["rtp_noticias"]["owner"] == "Estado Português"
