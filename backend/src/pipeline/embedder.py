"""Embedding generation using sentence-transformers (local CPU, $0 API costs).

Provides a reusable EmbeddingService class that generates multilingual
embeddings using the ``intfloat/multilingual-e5-large`` model.  All
computation runs on local CPU — no API calls needed.

Embeddings are L2-normalised so that cosine similarity can be computed
as a simple dot product.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ── Lazy-loaded model cache ─────────────────────────────────────────────────

_MODEL: Any | None = None


def _get_model(model_name: str = "intfloat/multilingual-e5-large") -> Any | None:
    """Lazy-load a SentenceTransformer model.

    Caches the model globally so the same model is never loaded twice in
    the same process.  Returns ``None`` if sentence-transformers is not
    installed or the model cannot be loaded (e.g. no internet for first
    download).
    """
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            _MODEL = SentenceTransformer(model_name)
            dim = getattr(_MODEL, "get_embedding_dimension", _MODEL.get_sentence_embedding_dimension)()
            logger.info("Loaded embedding model: %s (dim=%d)", model_name, dim)
        except Exception as exc:
            logger.warning(
                "Failed to load embedding model '%s': %s. "
                "EmbeddingService will return zero-vectors.",
                model_name,
                exc,
            )
            _MODEL = False  # sentinel
    return _MODEL if _MODEL is not False else None


# ── Public API ──────────────────────────────────────────────────────────────


class EmbeddingService:
    """Multilingual embedding generation using sentence-transformers.

    Uses the ``intfloat/multilingual-e5-large`` model (1024-dimensional
    embeddings) which supports 100+ languages including Portuguese,
    English, Spanish, and French.

    All embeddings are L2-normalised so cosine similarity between any
    two vectors is simply their dot product.

    Falls back gracefully (returns zero-vectors) if the model cannot
    be loaded.

    Usage:
        >>> embedder = EmbeddingService()
        >>> vec = embedder.embed_text("O governo anunciou novas medidas.")
        >>> len(vec)
        1024
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large"):
        self.model_name = model_name
        self._dim: int | None = None

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (default 1024)."""
        if self._dim is None:
            model = _get_model(self.model_name)
            if model is not None:
                self._dim = getattr(model, "get_embedding_dimension", model.get_sentence_embedding_dimension)()
            else:
                self._dim = 1024  # Fallback: known dim for multilingual-e5-large
        return self._dim

    # ── Single text ─────────────────────────────────────────────────────────

    def embed_text(self, text: str, max_chars: int = 8192) -> list[float]:
        """Generate an embedding for a single text string.

        Args:
            text: The text to embed.
            max_chars: Truncate to this many characters to avoid token
                       limits (default 8192).

        Returns:
            A list of ``float`` values (L2-normalised embedding vector).
            Returns a zero-vector if the model is unavailable or the
            text is empty/blank.
        """
        if not text or not text.strip():
            return [0.0] * self.dimension

        truncated = text[:max_chars]
        model = _get_model(self.model_name)
        if model is None:
            return [0.0] * self.dimension

        embedding = model.encode(truncated, normalize_embeddings=True)
        return embedding.tolist()

    # ── Batch ───────────────────────────────────────────────────────────────

    def embed_batch(
        self,
        texts: list[str],
        max_chars: int = 8192,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of text strings to embed.
            max_chars: Per-text character truncation limit.

        Returns:
            List of embedding vectors in the same order as the input.
        """
        if not texts:
            return []

        model = _get_model(self.model_name)
        if model is None:
            return [[0.0] * self.dimension] * len(texts)

        # Handle empty/blank strings: return zero-vectors for those
        result: list[list[float]] = []
        valid_texts: list[str] = []
        valid_indices: list[int] = []

        for i, t in enumerate(texts):
            if t and t.strip():
                valid_texts.append(t[:max_chars])
                valid_indices.append(i)
                result.append([0.0] * self.dimension)  # placeholder
            else:
                result.append([0.0] * self.dimension)

        if valid_texts:
            embeddings = model.encode(
                valid_texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for idx, emb in zip(valid_indices, embeddings):
                result[idx] = emb.tolist()

        return result

    # ── Similarity helpers ──────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Cosine similarity between two embedding vectors.

        Because embeddings are L2-normalised, this is equivalent to
        the dot product.
        """
        v1_np = np.array(v1, dtype=np.float64)
        v2_np = np.array(v2, dtype=np.float64)
        norm1 = np.linalg.norm(v1_np)
        norm2 = np.linalg.norm(v2_np)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1_np, v2_np) / (norm1 * norm2))

    @staticmethod
    def cosine_similarity_matrix(embeddings: list[list[float]]) -> np.ndarray:
        """Compute pairwise cosine similarity matrix for a batch."""
        matrix = np.array(embeddings, dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = matrix / norms
        return normalized @ normalized.T
