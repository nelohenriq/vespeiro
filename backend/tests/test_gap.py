"""Tests for parliament-media gap analyzer."""

import pytest
from src.analysis.gap import ParliamentGapAnalyzer


class TestTermExtraction:
    """Test key term extraction from Portuguese text."""

    def test_extract_terms_basic(self) -> None:
        analyzer = ParliamentGapAnalyzer()
        text = "O governo anunciou novas medidas para a comunicação social."
        terms = analyzer._extract_terms_from_text(text)
        assert "comunicação social" in terms or any("comunicação" in t for t in terms)

    def test_extract_terms_empty(self) -> None:
        analyzer = ParliamentGapAnalyzer()
        assert analyzer._extract_terms_from_text("") == set()

    def test_extract_terms_stopwords_filtered(self) -> None:
        analyzer = ParliamentGapAnalyzer()
        # All-stopword bigram should be excluded
        text = "de a o que e do da em um"
        terms = analyzer._extract_terms_from_text(text)
        # Should not contain pure stopword bigrams
        for t in terms:
            words = t.split()
            assert not all(w in analyzer._STOPWORDS for w in words)

    def test_extract_terms_media_keywords(self) -> None:
        analyzer = ParliamentGapAnalyzer()
        text = "A regulação da comunicação social é essencial para a liberdade de imprensa."
        terms = analyzer._extract_terms_from_text(text)
        assert any("comunicação social" in t for t in terms) or any("regulação" in t for t in terms)


class TestParliamentGapAnalyzer:
    """Test the full gap analyzer."""

    @pytest.mark.asyncio
    async def test_analyze_no_db(self) -> None:
        """Analyzer returns empty report without DB session."""
        analyzer = ParliamentGapAnalyzer(db_session=None)
        report = await analyzer.analyze()
        assert report.total_parliament_docs == 0
        assert report.overall_gap_score == 0.0
        assert report.topics == []
