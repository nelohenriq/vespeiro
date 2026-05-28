"""Tests for the EmbeddingService.

Note: The first test that triggers model loading may be slow
(〜10-30s) because the ``intfloat/multilingual-e5-large`` model
must be downloaded and loaded into memory on first use.
Subsequent tests in the same process are fast (cached model).
"""

import pytest
import numpy as np
from src.pipeline.embedder import EmbeddingService


# ── Helpers ─────────────────────────────────────────────────────────────────


def _ensure_model_loaded(embedder: EmbeddingService) -> None:
    """Force model loading so timing is predictable in later tests.
    Called once in a session-scoped fixture or before test groups.
    """
    embedder.embed_text("Warm-up to trigger model download.")


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def embedder() -> EmbeddingService:
    """Module-scoped embedder: model is loaded once, shared across all tests."""
    svc = EmbeddingService()
    # Warm up: trigger model load so individual tests are fast
    _ensure_model_loaded(svc)
    return svc


@pytest.fixture
def short_embedder() -> EmbeddingService:
    """Fresh embedder (no warm-up) for testing lazy-loading behaviour."""
    return EmbeddingService()


# ════════════════════════════════════════════════════════════════════════════
# Basic output shape & type
# ════════════════════════════════════════════════════════════════════════════


class TestOutputShape:
    """Verify that embeddings have the correct dimension and type."""

    def test_embed_text_returns_vector(self, embedder: EmbeddingService):
        """A real text should produce a 1024-dimensional float vector."""
        vector = embedder.embed_text("O governo anunciou novas medidas económicas.")
        assert isinstance(vector, list)
        assert len(vector) > 0
        assert isinstance(vector[0], float)

    def test_dimension_is_1024(self, embedder: EmbeddingService):
        """multilingual-e5-large produces 1024-dimensional embeddings."""
        vector = embedder.embed_text("Teste")
        assert len(vector) == 1024

    def test_embed_text_empty_returns_zero_vector(self, embedder: EmbeddingService):
        """Empty or blank text should return a zero vector."""
        vector = embedder.embed_text("")
        assert len(vector) == 1024
        assert all(v == 0.0 for v in vector)

    def test_embed_text_whitespace_returns_zero_vector(self, embedder: EmbeddingService):
        """Whitespace-only text should also return a zero vector."""
        vector = embedder.embed_text("   \n  \t  ")
        assert len(vector) == 1024
        assert all(v == 0.0 for v in vector)


# ════════════════════════════════════════════════════════════════════════════
# Semantic similarity
# ════════════════════════════════════════════════════════════════════════════


class TestSemanticSimilarity:
    """Similar texts should have higher cosine similarity than dissimilar ones."""

    def test_similar_texts_have_high_similarity(self, embedder: EmbeddingService):
        """Two texts about the same topic should have cosine similarity > 0.80."""
        v1 = embedder.embed_text("O presidente argentino Javier Milei anuncia reformas económicas.")
        v2 = embedder.embed_text("Milei apresenta novo pacote de reformas para a economia argentina.")
        sim = embedder.cosine_similarity(v1, v2)
        assert sim > 0.80, f"Expected sim > 0.80, got {sim:.4f}"

    def test_different_texts_have_lower_similarity(self, embedder: EmbeddingService):
        """Texts about truly unrelated topics should have clearly lower similarity."""
        v1 = embedder.embed_text("O presidente argentino Javier Milei anuncia reformas económicas.")
        v2 = embedder.embed_text("A teoria da relatividade geral foi publicada por Einstein em 1915.")
        sim_same = embedder.cosine_similarity(v1, v1)
        sim_diff = embedder.cosine_similarity(v1, v2)
        # Different topics should be less similar than identical texts
        assert sim_diff < sim_same - 0.10, f"Expected sim_diff < {sim_same - 0.10:.4f}, got {sim_diff:.4f}"

    def test_identical_texts_have_similarity_one(self, embedder: EmbeddingService):
        """Two identical texts should have cosine similarity ≈ 1.0."""
        text = "O governo português anunciou um pacote de 2.3 milhões de euros."
        v1 = embedder.embed_text(text)
        v2 = embedder.embed_text(text)
        assert embedder.cosine_similarity(v1, v2) == pytest.approx(1.0, abs=0.001)

    def test_cross_lingual_similarity(self, embedder: EmbeddingService):
        """Portuguese and English versions of the same story should match."""
        pt = embedder.embed_text("O governo português anunciou investimento na saúde.")
        en = embedder.embed_text("The Portuguese government announced healthcare investment.")
        sim = embedder.cosine_similarity(pt, en)
        assert sim > 0.70, f"Cross-lingual sim expected > 0.70, got {sim:.4f}"


# ════════════════════════════════════════════════════════════════════════════
# Batch embedding
# ════════════════════════════════════════════════════════════════════════════


class TestBatchEmbedding:
    """Batch embedding should handle lists, empty lists, and mixed content."""

    def test_embed_batch_returns_correct_count(self, embedder: EmbeddingService):
        """Batch of 3 texts should return 3 embeddings."""
        texts = [
            "Primeiro artigo sobre economia.",
            "Segundo artigo sobre desporto.",
            "Terceiro artigo sobre política.",
        ]
        vectors = embedder.embed_batch(texts)
        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)

    def test_embed_batch_empty_list(self, embedder: EmbeddingService):
        """An empty list should return an empty list."""
        assert embedder.embed_batch([]) == []

    def test_embed_batch_with_empty_strings(self, embedder: EmbeddingService):
        """Mixed batch with empty strings should return zero-vectors for empties."""
        texts = ["Texto normal.", "", "Outro texto normal."]
        vectors = embedder.embed_batch(texts)
        assert len(vectors) == 3
        # Middle one should be zero-vector
        assert all(v == 0.0 for v in vectors[1])


# ════════════════════════════════════════════════════════════════════════════
# Similarity matrix
# ════════════════════════════════════════════════════════════════════════════


class TestSimilarityMatrix:
    """The matrix utility should compute pairwise similarities correctly."""

    def test_identity_on_diagonal(self, embedder: EmbeddingService):
        """Diagonal of the matrix should be 1.0."""
        texts = ["Notícia A", "Notícia B", "Notícia C"]
        embeddings = embedder.embed_batch(texts)
        matrix = embedder.cosine_similarity_matrix(embeddings)
        assert matrix.shape == (3, 3)
        for i in range(3):
            assert matrix[i, i] == pytest.approx(1.0, abs=0.001)

    def test_symmetric(self, embedder: EmbeddingService):
        """Similarity matrix should be symmetric."""
        texts = [
            "Governo anuncia medidas económicas.",
            "Benfica vence campeonato.",
            "Novo hospital abre em Lisboa.",
        ]
        embeddings = embedder.embed_batch(texts)
        matrix = embedder.cosine_similarity_matrix(embeddings)
        for i in range(3):
            for j in range(3):
                assert matrix[i, j] == pytest.approx(matrix[j, i], abs=0.001)


# ════════════════════════════════════════════════════════════════════════════
# Edge cases & robustness
# ════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Test unusual inputs and edge cases."""

    def test_very_long_text_truncated(self, embedder: EmbeddingService):
        """Text longer than 8192 chars should be truncated, not crash."""
        long_text = "Palavra repetida. " * 2000
        vector = embedder.embed_text(long_text)
        assert len(vector) == 1024

    def test_single_word(self, embedder: EmbeddingService):
        """Single word should still produce a valid embedding."""
        vector = embedder.embed_text("Portugal")
        assert len(vector) == 1024
        # Should not be zero-vector for a real word
        assert any(v != 0.0 for v in vector)

    def test_portuguese_specific_text(self, embedder: EmbeddingService):
        """Portuguese text with special characters should embed correctly."""
        vector = embedder.embed_text(
            "A comunicação social portuguesa reflete uma assimetria informativa "
            "que privilegia determinadas narrativas em detrimento de outras."
        )
        assert len(vector) == 1024
        assert any(v != 0.0 for v in vector)

    def test_consecutive_calls_return_same_result(self, embedder: EmbeddingService):
        """Same text → same embedding (deterministic)."""
        text = "Notícia sobre a Lusa e os media portugueses."
        v1 = embedder.embed_text(text)
        v2 = embedder.embed_text(text)
        assert v1 == pytest.approx(v2, abs=1e-6)


# ════════════════════════════════════════════════════════════════════════════
# Lazy-loading (no warm-up)
# ════════════════════════════════════════════════════════════════════════════


class TestLazyLoading:
    """Module-level import should be instant — model loads only on first use."""

    def test_import_is_fast(self):
        """Importing the module should not trigger model loading."""
        import time
        start = time.monotonic()
        from src.pipeline import embedder  # noqa: F811
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Module import took {elapsed:.2f}s (expected < 1s)"

    def test_embedder_init_is_fast(self, short_embedder: EmbeddingService):
        """Creating an instance should not trigger model loading."""
        import time
        start = time.monotonic()
        _ = short_embedder.dimension  # Access dimension property (no model load)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Creating instance took {elapsed:.2f}s (expected < 1s)"
