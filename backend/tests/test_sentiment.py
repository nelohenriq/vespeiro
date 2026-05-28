"""Tests for the pipeline sentiment analysis module."""

import time
import pytest
from src.pipeline.sentiment import SentimentAnalyzer


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def module_analyzer() -> SentimentAnalyzer:
    """Module-scoped fixture: model loads once, shared across all tests."""
    return SentimentAnalyzer()


@pytest.fixture
def analyzer(module_analyzer: SentimentAnalyzer) -> SentimentAnalyzer:
    """Alias for convenience; avoids re-creating instance."""
    return module_analyzer


# ── Lazy-loading verification ──────────────────────────────────────────────


class TestLazyLoading:
    """Verify that importing and instantiating SentimentAnalyzer is instant.

    The pysentimiento model is only loaded on the first ``analyze()`` call,
    not on import or construction.  This guarantees that test runners can
    discover and collect these tests without waiting for model downloads.
    """

    def test_import_is_fast(self) -> None:
        """Importing SentimentAnalyzer should not load pysentimiento."""
        import sys

        # Clear cached module to force a real fresh import
        for mod in list(sys.modules.keys()):
            if "pipeline.sentiment" in mod:
                del sys.modules[mod]

        start = time.monotonic()
        from src.pipeline.sentiment import SentimentAnalyzer  # noqa: F811
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Import took {elapsed:.2f}s — expected < 1s"

    def test_init_is_fast(self) -> None:
        """Creating a SentimentAnalyzer should not load pysentimiento."""
        start = time.monotonic()
        sa = SentimentAnalyzer()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"__init__ took {elapsed:.2f}s — expected < 0.5s"
        assert sa is not None


# ── Core functionality ─────────────────────────────────────────────────────


class TestSentimentAnalyzer:
    """Verify pysentimiento sentiment analysis for all supported languages."""

    def test_positive_pt(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("Que dia maravilhoso! Estou muito feliz.", lang="pt")
        assert result is not None
        assert result["sentiment"] == "POS"
        assert result["probas"]["POS"] > 0.5

    def test_negative_pt(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("Esta situação é horrível e completamente injusta.", lang="pt")
        assert result is not None
        assert result["sentiment"] == "NEG"
        assert result["probas"]["NEG"] > 0.5

    def test_neutral_pt(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("O relatório foi entregue na terça-feira.", lang="pt")
        assert result is not None
        # Neutral can be NEU or a weaker POS/NEG — just check it returns
        assert result["sentiment"] in ("POS", "NEG", "NEU")

    def test_positive_en(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("This is absolutely wonderful news!", lang="en")
        assert result is not None
        assert result["sentiment"] == "POS"

    def test_negative_en(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("This is a complete disaster.", lang="en")
        assert result is not None
        assert result["sentiment"] == "NEG"

    def test_negative_es(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("Es una tragedia lo que está pasando.", lang="es")
        assert result is not None
        assert result["sentiment"] == "NEG"

    def test_unsupported_language(self, analyzer: SentimentAnalyzer):
        with pytest.raises(ValueError, match="Unsupported language"):
            analyzer.analyze("Bonjour le monde", lang="fr")

    def test_empty_text(self, analyzer: SentimentAnalyzer):
        result = analyzer.analyze("", lang="pt")
        assert result is not None
        assert result["sentiment"] in ("POS", "NEG", "NEU")

    def test_analyze_batch(self, analyzer: SentimentAnalyzer):
        texts = [
            "Adoro este projeto!",
            "Isto é terrível.",
            "O gato está no tapete.",
        ]
        results = analyzer.analyze_batch(texts, lang="pt")
        assert len(results) == 3
        for r in results:
            assert r is not None
            assert "sentiment" in r
            assert "probas" in r

    def test_score_positive(self, analyzer: SentimentAnalyzer):
        result = {"sentiment": "POS", "probas": {"POS": 0.95, "NEG": 0.03, "NEU": 0.02}}
        score = analyzer.score(result)
        assert score is not None
        assert score > 0.9

    def test_score_negative(self, analyzer: SentimentAnalyzer):
        result = {"sentiment": "NEG", "probas": {"POS": 0.02, "NEG": 0.92, "NEU": 0.06}}
        score = analyzer.score(result)
        assert score is not None
        assert score < -0.9

    def test_score_neutral(self, analyzer: SentimentAnalyzer):
        result = {"sentiment": "NEU", "probas": {"POS": 0.1, "NEG": 0.1, "NEU": 0.8}}
        score = analyzer.score(result)
        assert score == 0.0

    def test_score_none(self, analyzer: SentimentAnalyzer):
        assert analyzer.score(None) is None
