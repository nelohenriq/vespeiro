"""Tests for advertising-editorial correlation analyzer."""

import pytest
from src.analysis.correlation import CorrelationAnalyzer


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
