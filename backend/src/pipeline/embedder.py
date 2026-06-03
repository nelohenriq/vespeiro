"""Embedding generation using sentence-transformers (local CPU, $0 API costs).

Provides a reusable EmbeddingService class that generates multilingual
embeddings using the ``intfloat/multilingual-e5-large`` model.  All
computation runs on local CPU — no API calls needed.

Embeddings are L2-normalised so that cosine similarity can be computed
as a simple dot product.

Disk caching
-----------
Embeddings are automatically persisted to disk under ``EMBED_CACHE_DIR``
(``data/embedding-cache/`` by default) as JSON files mapping text-hash →
embedding vector.  This avoids re-embedding the same articles across
consecutive stats runs, which is the dominant cost in the daily pipeline:

- ``analyze()`` embeds all articles once → cache hit on subsequent runs
- ``daily_timeline()`` re-uses those same embeddings for free
- ``StatsGenerator.collect()`` pre-warms the cache before running analyzers

The cache is keyed on the article text SHA-256 hash + model version so
any content change forces a re-embed (correctness) while identical content
reuses embeddings (performance).
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ── Lazy-loaded model cache ─────────────────────────────────────────────────

_MODEL: Any | None = None
_MODEL_NAME: str = "intfloat/multilingual-e5-large"

# ── Embedding cache (disk-persisted) ─────────────────────────────────────────
# Saves re-embedding costs across stats runs.  Keyed by text-hash + model.

EMBED_CACHE_DIR = Path(os.environ.get(
    "VESPERO_EMBED_CACHE",
    str(Path(__file__).parent.parent.parent / "data" / "embedding-cache"),
))


def _text_hash(text: str) -> str:
    """SHA-256 hex digest of normalized text — used as cache key.

    Uses the full 64-char hex digest to avoid birthday-paradox collisions
    when the cache grows to thousands of entries.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embed_cache_path() -> Path:
    """Path to the embedding cache JSON file."""
    return EMBED_CACHE_DIR / "embeddings.json"


def _load_embed_cache() -> dict[str, list[float]]:
    """Load embedding cache from disk.

    Returns an empty dict if the cache file doesn't exist or is corrupt.
    """
    cache_path = _embed_cache_path()
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)  # type: ignore[assignment]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load embedding cache: %s", exc)
        return {}


def _save_embed_cache(cache: dict[str, list[float]]) -> None:
    """Persist embedding cache to disk atomically (write-then-rename)."""
    cache_path = _embed_cache_path()
    tmp_path = cache_path.with_suffix(".tmp")
    EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        tmp_path.rename(cache_path)
        logger.debug("Saved %d embeddings to cache", len(cache))
    except OSError as exc:
        logger.warning("Failed to save embedding cache: %s", exc)


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

    Disk caching: see module-level documentation above.

    Usage:
        >>> embedder = EmbeddingService()
        >>> vec = embedder.embed_text("O governo anunciou novas medidas.")
        >>> len(vec)
        1024
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-large",
    ):
        self.model_name = model_name
        self._dim: int | None = None
        self._cache: dict[str, list[float]] | None = None  # lazy-loaded

    # ── Cache ────────────────────────────────────────────────────────────────

    def _cache_key(self, text: str) -> str:
        """Build a cache key for a text using model-version + text hash."""
        return f"{self.model_name}@{_text_hash(text)}"

    @property
    def _embed_cache(self) -> dict[str, list[float]]:
        """Lazy-load the disk cache on first access."""
        if self._cache is None:
            self._cache = _load_embed_cache()
        return self._cache

    def _persist_cache(self) -> None:
        """Write the in-memory cache to disk."""
        if self._cache is not None:
            _save_embed_cache(self._cache)

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

        Checks the disk cache before encoding.  Any newly-encoded text
        is persisted to the cache so subsequent calls (including from
        ``warm_embed_cache``) hit the cache.

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
        cache = self._embed_cache
        key = self._cache_key(truncated)

        if key in cache:
            return cache[key]

        model = _get_model(self.model_name)
        if model is None:
            return [0.0] * self.dimension

        embedding = model.encode(truncated, normalize_embeddings=True)
        emb_list = embedding.tolist()
        cache[key] = emb_list
        self._persist_cache()
        return emb_list

    # ── Batch ───────────────────────────────────────────────────────────────

    def embed_batch(
        self,
        texts: list[str],
        max_chars: int = 8192,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts with disk caching.

        Each text is checked against the disk cache before embedding.
        Newly embedded texts are cached to disk after the batch completes.
        Cache hits avoid both the model encode cost AND the memory
        allocation for zero-vectors.

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

        cache = self._embed_cache
        result: list[list[float]] = []
        to_embed: list[tuple[int, str]] = []  # (index, truncated_text)
        cached_count = 0

        for i, t in enumerate(texts):
            if not (t and t.strip()):
                result.append([0.0] * self.dimension)
                continue

            truncated = t[:max_chars]
            key = self._cache_key(truncated)

            if key in cache:
                result.append(cache[key])
                cached_count += 1
            else:
                result.append([0.0] * self.dimension)  # placeholder
                to_embed.append((i, truncated))

        if to_embed:
            texts_to_encode = [t for _, t in to_embed]
            logger.debug(
                "Cache miss for %d/%d texts — embedding now…",
                len(to_embed), len(texts),
            )
            embeddings = model.encode(
                texts_to_encode,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for (idx, _), emb in zip(to_embed, embeddings):
                emb_list = emb.tolist()
                result[idx] = emb_list
                key = self._cache_key(texts[idx][:max_chars])
                cache[key] = emb_list

        if to_embed:
            self._persist_cache()
            logger.debug(
                "Cached %d new embeddings (total cache: %d)",
                len(to_embed), len(cache),
            )

        logger.debug(
            "embed_batch: %d texts, %d cache hits, %d embedded",
            len(texts), cached_count, len(to_embed),
        )
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


async def warm_embed_cache(db_session, window_days: int = 7) -> int:
    """Pre-populate the embedding cache with articles from the last *window_days*.

    Call this once before running ``StatsGenerator.collect()`` so that
    all analyzers benefit from cache hits instead of re-encoding the
    same articles independently.

    Uses ``embed_batch()`` for efficiency (single model encode call) and
    writes the cache file exactly once at the end (not per-text).

    Returns the number of texts actually embedded (new cache entries).
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from src.db.models import Article

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)

    # Load existing cache so we don't overwrite entries already present
    cache = _load_embed_cache()
    initial_size = len(cache)

    embedder = EmbeddingService()

    # Pre-load the model once so the first embed doesn't block
    _get_model(embedder.model_name)

    try:
        result = await db_session.execute(
            select(Article)
            .where(Article.collected_at >= start)
            .where(
                (Article.content_text.isnot(None) & (Article.content_text != ""))
                | (Article.summary.isnot(None) & (Article.summary != ""))
            )
            .limit(2000)  # cap to avoid unbounded memory
        )
        articles = list(result.scalars().all())
    except Exception as exc:
        logger.warning("warm_embed_cache: DB query failed: %s", exc)
        return 0

    # Build list of texts not yet in cache
    texts_to_cache: list[str] = []
    for article in articles:
        title = (article.title or "").strip()
        content = (article.content_text or article.summary or "").strip()[:800]
        full_text = f"{title} {content}".strip()
        if not full_text:
            continue
        truncated = full_text[:800]
        key = embedder._cache_key(truncated)
        if key not in cache:
            texts_to_cache.append(truncated)

    if texts_to_cache:
        logger.info(
            "warm_embed_cache: pre-embedding %d texts (cache has %d entries)…",
            len(texts_to_cache), initial_size,
        )
        # Use embed_batch for efficiency — single model encode call,
        # results written to embedder._embed_cache (in-memory dict)
        embedder.embed_batch(texts_to_cache)

        # Persist once at the end — not per-text (N writes → 1 write)
        embedder._persist_cache()

        new_entries = len(embedder._embed_cache) - initial_size
        logger.info(
            "warm_embed_cache: done — %d new entries, total %d in cache",
            new_entries, len(embedder._embed_cache),
        )
        return len(texts_to_cache)

    logger.info(
        "warm_embed_cache: no new texts to cache (%d entries already present)",
        initial_size,
    )
    return 0
