"""Tests for the EmbeddingService (API-first, local fallback).

Tests are provider-aware:
- When OPENAI_API_KEY or JINA_API_KEY is set, tests run against the API (fast, no model load)
- When no API key is set, tests run against local sentence-transformers (~26s model load)
- Cache tests verify that disk caching works for both providers
"""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.pipeline.embedder import (
    EmbeddingService,
    _detect_api_provider,
    _api_embed_batch,
    _PROVIDER_PRESETS,
    is_api_available,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def embedder() -> EmbeddingService:
    """Module-scoped embedder: provider is resolved once, shared across tests."""
    svc = EmbeddingService()
    # Warm up: trigger first embed so subsequent tests are fast (cache hit)
    svc.embed_text("Warm-up to trigger provider init and cache load.")
    return svc


@pytest.fixture
def short_embedder() -> EmbeddingService:
    """Fresh embedder for testing lazy-loading behaviour."""
    return EmbeddingService()


# ════════════════════════════════════════════════════════════════════════════
# Provider detection
# ════════════════════════════════════════════════════════════════════════════


class TestProviderDetection:
    """Auto-detect embedding provider from Settings fields."""

    def test_detect_returns_tuple_or_none(self):
        """_detect_api_provider returns (name, key, base, dim) or None."""
        result = _detect_api_provider()
        if result is not None:
            assert len(result) == 4
            assert isinstance(result[0], str)
            assert isinstance(result[1], str)
            assert isinstance(result[2], str)
            assert isinstance(result[3], int)

    def test_provider_presets_have_required_fields(self):
        """All presets have base_url, model, and dimension."""
        for name, (base, model, dim) in _PROVIDER_PRESETS.items():
            assert base.startswith("https://")
            assert isinstance(model, str) and len(model) > 0
            assert dim > 0

    def test_is_api_available_matches_detect(self):
        """is_api_available() should match _detect_api_provider() result."""
        assert is_api_available() == (_detect_api_provider() is not None)

    def _make_settings(self, **kwargs):
        """Create a mock Settings object with all detection fields."""
        defaults = {
            "openai_api_key": "",
            "jina_api_key": "",
            "nvidia_api_key": "",
            "embedding_api_key": "",
            "embedding_api_base": "",
            "embedding_api_model": "",
        }
        defaults.update(kwargs)
        m = MagicMock()
        for k, v in defaults.items():
            setattr(m, k, v)
        return m

    def test_detect_openai(self):
        """With openai_api_key set, detects OpenAI provider."""
        mock_settings = self._make_settings(openai_api_key="test-key-123")
        with patch("src.config.settings.settings", mock_settings):
            result = _detect_api_provider()
            assert result is not None
            assert result[0] == "openai"
            assert result[1] == "test-key-123"

    def test_detect_jina(self):
        """With jina_api_key set (no OpenAI), detects Jina provider."""
        mock_settings = self._make_settings(jina_api_key="test-key-456")
        with patch("src.config.settings.settings", mock_settings):
            result = _detect_api_provider()
            assert result is not None
            assert result[0] == "jina"
            assert result[1] == "test-key-456"

    def test_detect_nvidia(self):
        """With nvidia_api_key set (no OpenAI/Jina), detects Nvidia NIM."""
        mock_settings = self._make_settings(nvidia_api_key="test-nvidia-key")
        with patch("src.config.settings.settings", mock_settings):
            result = _detect_api_provider()
            assert result is not None
            assert result[0] == "nvidia"
            assert result[1] == "test-nvidia-key"
            assert result[2] == "https://integrate.api.nvidia.com/v1"
            assert result[3] == 4096

    def test_detect_priority_openai_over_jina(self):
        """OpenAI key takes priority over Jina when both set."""
        mock_settings = self._make_settings(
            openai_api_key="openai-key", jina_api_key="jina-key"
        )
        with patch("src.config.settings.settings", mock_settings):
            result = _detect_api_provider()
            assert result is not None
            assert result[0] == "openai"

    def test_detect_explicit_base_url(self):
        """Explicit embedding_api_base + embedding_api_key is used directly."""
        mock_settings = self._make_settings(
            embedding_api_key="custom-key",
            embedding_api_base="https://integrate.api.nvidia.com/v1",
        )
        with patch("src.config.settings.settings", mock_settings):
            result = _detect_api_provider()
            assert result is not None
            assert result[0] == "custom"
            assert result[1] == "custom-key"
            assert result[2] == "https://integrate.api.nvidia.com/v1"
            assert result[3] == 4096  # Inferred from nvidia base URL

    def test_detect_returns_none_without_keys(self):
        """Without any API key, returns None (local fallback)."""
        mock_settings = self._make_settings()
        with patch("src.config.settings.settings", mock_settings):
            result = _detect_api_provider()
            assert result is None


# ════════════════════════════════════════════════════════════════════════════
# Basic output shape & type
# ════════════════════════════════════════════════════════════════════════════


class TestOutputShape:
    """Verify that embeddings have the correct dimension and type."""

    def test_embed_text_returns_vector(self, embedder: EmbeddingService):
        """A real text should produce a non-empty float vector."""
        vector = embedder.embed_text("O governo anunciou novas medidas económicas.")
        assert isinstance(vector, list)
        assert len(vector) > 0
        assert isinstance(vector[0], float)

    def test_dimension_matches_provider(self, embedder: EmbeddingService):
        """Dimension should match the active provider's output."""
        dim = embedder.dimension
        assert dim in (1024, 1536, 4096), f"Unexpected dimension: {dim}"
        vector = embedder.embed_text("Teste")
        assert len(vector) == dim

    def test_embed_text_empty_returns_zero_vector(self, embedder: EmbeddingService):
        """Empty or blank text should return a zero vector."""
        dim = embedder.dimension
        vector = embedder.embed_text("")
        assert len(vector) == dim
        assert all(v == 0.0 for v in vector)

    def test_embed_text_whitespace_returns_zero_vector(self, embedder: EmbeddingService):
        """Whitespace-only text should also return a zero vector."""
        dim = embedder.dimension
        vector = embedder.embed_text("   \n  \t  ")
        assert len(vector) == dim
        assert all(v == 0.0 for v in vector)


# ════════════════════════════════════════════════════════════════════════════
# Semantic similarity
# ════════════════════════════════════════════════════════════════════════════


class TestSemanticSimilarity:
    """Similar texts should have higher cosine similarity than dissimilar ones."""

    def test_similar_texts_have_high_similarity(self, embedder: EmbeddingService):
        """Two texts about the same topic should have cosine similarity > 0.70."""
        v1 = embedder.embed_text("O presidente argentino Javier Milei anuncia reformas económicas.")
        v2 = embedder.embed_text("Milei apresenta novo pacote de reformas para a economia argentina.")
        sim = embedder.cosine_similarity(v1, v2)
        assert sim > 0.70, f"Expected sim > 0.70, got {sim:.4f}"

    def test_different_texts_have_lower_similarity(self, embedder: EmbeddingService):
        """Texts about truly unrelated topics should have clearly lower similarity."""
        v1 = embedder.embed_text("O presidente argentino Javier Milei anuncia reformas económicas.")
        v2 = embedder.embed_text("A teoria da relatividade geral foi publicada por Einstein em 1915.")
        sim_same = embedder.cosine_similarity(v1, v1)
        sim_diff = embedder.cosine_similarity(v1, v2)
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
        assert sim > 0.60, f"Cross-lingual sim expected > 0.60, got {sim:.4f}"


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
        dim = embedder.dimension
        assert all(len(v) == dim for v in vectors)

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
        assert len(vector) == embedder.dimension

    def test_single_word(self, embedder: EmbeddingService):
        """Single word should still produce a valid embedding."""
        vector = embedder.embed_text("Portugal")
        assert len(vector) == embedder.dimension
        assert any(v != 0.0 for v in vector)

    def test_portuguese_specific_text(self, embedder: EmbeddingService):
        """Portuguese text with special characters should embed correctly."""
        vector = embedder.embed_text(
            "A comunicação social portuguesa reflete uma assimetria informativa "
            "que privilegia determinadas narrativas em detrimento de outras."
        )
        assert len(vector) == embedder.dimension
        assert any(v != 0.0 for v in vector)

    def test_consecutive_calls_return_same_result(self, embedder: EmbeddingService):
        """Same text → same embedding (deterministic via cache)."""
        text = "Notícia sobre a Lusa e os media portugueses."
        v1 = embedder.embed_text(text)
        v2 = embedder.embed_text(text)
        assert v1 == pytest.approx(v2, abs=1e-6)


# ════════════════════════════════════════════════════════════════════════════
# Lazy-loading (no warm-up)
# ════════════════════════════════════════════════════════════════════════════


class TestLazyLoading:
    """Module-level import should be instant — no model loading at import time."""

    def test_import_is_fast(self):
        """Importing the module should not trigger model loading."""
        import time
        start = time.monotonic()
        from src.pipeline import embedder  # noqa: F811
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Module import took {elapsed:.2f}s (expected < 2s)"

    def test_init_is_fast(self, short_embedder: EmbeddingService):
        """Creating an instance should not trigger model loading."""
        import time
        start = time.monotonic()
        _ = short_embedder.dimension
        elapsed = time.monotonic() - start
        # API provider: instant; local: may trigger model load
        if short_embedder.is_api:
            assert elapsed < 1.0, f"API init took {elapsed:.2f}s (expected < 1s)"
        else:
            # Local may be slow on first access — that's expected
            pass


# ════════════════════════════════════════════════════════════════════════════
# API-specific tests (mocked)
# ════════════════════════════════════════════════════════════════════════════


class TestAPIEmbedding:
    """Test API embedding path with mocked HTTP responses."""

    def test_api_embed_batch_success(self):
        """Successful API call returns embeddings."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"embedding": [0.1] * 1536, "index": 0},
                {"embedding": [0.2] * 1536, "index": 1},
            ],
            "usage": {"total_tokens": 10},
        }
        mock_resp.elapsed.total_seconds.return_value = 0.05

        with patch("httpx.post", return_value=mock_resp):
            results = _api_embed_batch(
                ["text one", "text two"],
                api_key="fake-key",
                base_url="https://api.openai.com/v1",
                model="text-embedding-3-small",
            )

        assert len(results) == 2
        assert len(results[0]) == 1536
        # Results should be L2-normalised
        norm = np.linalg.norm(results[0])
        assert abs(norm - 1.0) < 0.01, f"Expected unit vector, got norm={norm}"

    def test_api_embed_batch_failure_returns_zeros(self):
        """Failed API call returns zero-vectors."""
        import httpx
        with patch("httpx.post", side_effect=httpx.ConnectError("Connection refused")):
            results = _api_embed_batch(
                ["text one"],
                api_key="fake-key",
                base_url="https://api.openai.com/v1",
                model="text-embedding-3-small",
            )

        assert len(results) == 1
        assert len(results[0]) == 1536
        assert all(v == 0.0 for v in results[0])

    def test_api_embed_batch_wrong_count_pads(self):
        """API returning fewer embeddings than requested gets padded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"embedding": [0.1] * 1536, "index": 0}],
            "usage": {"total_tokens": 5},
        }
        mock_resp.elapsed.total_seconds.return_value = 0.05

        with patch("httpx.post", return_value=mock_resp):
            results = _api_embed_batch(
                ["text one", "text two"],
                api_key="fake-key",
                base_url="https://api.openai.com/v1",
                model="text-embedding-3-small",
            )

        assert len(results) == 2
        # First has data, second is padded zeros
        assert any(v != 0.0 for v in results[0])
        assert all(v == 0.0 for v in results[1])
