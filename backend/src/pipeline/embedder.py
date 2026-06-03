"""Embedding generation with API-first strategy and local fallback.

Provider priority (controlled by ``settings.embedding_provider``):

1. **API** (``"auto"`` / ``"api"``): Uses OpenAI-compatible ``/v1/embeddings``
   endpoint.  Works with both **OpenAI** (``text-embedding-3-small``, 1536d,
   $0.02/1M tokens) and **Jina AI** (``jina-embeddings-v3``, 1024d, 10M free
   tokens).  Eliminates the ~26s sentence-transformers model load entirely.

2. **Local** (``"local"`` / fallback): Uses ``sentence-transformers`` with
   ``intfloat/multilingual-e5-large`` (1024d) on local CPU.  No API cost but
   ~26s cold-start for model loading.

Disk caching
-----------
Embeddings are persisted to ``EMBED_CACHE_DIR`` as JSON (text-hash → vector).
Cache keys include the provider name so switching providers never causes
collisions.  Subsequent stats runs hit the cache and skip embedding entirely.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ── Lazy-loaded model cache (local only) ────────────────────────────────────

_MODEL: Any | None = None

# ── Embedding cache (disk-persisted) ─────────────────────────────────────────

EMBED_CACHE_DIR = Path(os.environ.get(
    "VESPERO_EMBED_CACHE",
    str(Path(__file__).parent.parent.parent / "data" / "embedding-cache"),
))


def _text_hash(text: str) -> str:
    """SHA-256 hex digest of normalized text — used as cache key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embed_cache_path() -> Path:
    """Path to the embedding cache JSON file."""
    return EMBED_CACHE_DIR / "embeddings.json"


def _load_embed_cache() -> dict[str, list[float]]:
    """Load embedding cache from disk."""
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
    """Persist embedding cache to disk atomically."""
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


# ── Local model helpers ─────────────────────────────────────────────────────

def _get_model(model_name: str = "intfloat/multilingual-e5-large") -> Any | None:
    """Lazy-load a SentenceTransformer model.

    Returns ``None`` if sentence-transformers is not installed or the model
    cannot be loaded.
    """
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            _MODEL = SentenceTransformer(model_name)
            dim = getattr(
                _MODEL, "get_embedding_dimension", _MODEL.get_sentence_embedding_dimension
            )()
            logger.info("Loaded embedding model: %s (dim=%d)", model_name, dim)
        except Exception as exc:
            logger.warning(
                "Failed to load embedding model '%s': %s. "
                "EmbeddingService will try API or return zero-vectors.",
                model_name,
                exc,
            )
            _MODEL = False  # sentinel
    return _MODEL if _MODEL is not False else None


# ── API embedding (OpenAI-compatible) ───────────────────────────────────────

# Provider presets: (base_url, default_model, default_dim)
_PROVIDER_PRESETS: dict[str, tuple[str, str, int]] = {
    "openai": ("https://api.openai.com/v1", "text-embedding-3-small", 1536),
    "jina": ("https://api.jina.ai/v1", "jina-embeddings-v3", 1024),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "nvidia/nv-embed-v1", 4096),
}


def _detect_api_provider() -> tuple[str, str, str, int] | None:
    """Auto-detect API provider from environment variables.

    Returns (provider_name, api_key, base_url, dim) or None if no key found.

    Detection priority:
    1. Explicit ``embedding_api_base`` + ``embedding_api_model`` in settings
    2. Known env vars: ``OPENAI_API_KEY`` → OpenAI, ``JINA_API_KEY`` → Jina
    3. ``embedding_api_key`` in settings (base_url auto-detected)
    4. None (local fallback)

    Supported providers:
    - OpenAI: ``OPENAI_API_KEY`` → text-embedding-3-small (1536d, $0.02/1M tokens)
    - Jina AI: ``JINA_API_KEY`` → jina-embeddings-v3 (1024d, 10M free tokens)
    - Nvidia NIM: ``NVIDIA_API_KEY`` → baai/bge-m3 (1024d, free for dev)
    """
    from src.config.settings import settings

    # If user set explicit base URL + model, use those directly
    if settings.embedding_api_base and settings.embedding_api_key:
        # Infer dimension from model name if possible
        dim = 1536  # default
        model = settings.embedding_api_model or "text-embedding-3-small"
        for preset_name, (p_base, p_model, p_dim) in _PROVIDER_PRESETS.items():
            if settings.embedding_api_base == p_base or preset_name in settings.embedding_api_base:
                dim = p_dim
                if not settings.embedding_api_model:
                    model = p_model
                break
        return ("custom", settings.embedding_api_key, settings.embedding_api_base, dim)

    # Auto-detect from Settings (pydantic-settings loads .env into fields)
    # Priority: OpenAI → Jina → Nvidia
    if settings.openai_api_key:
        base, model, dim = _PROVIDER_PRESETS["openai"]
        return ("openai", settings.openai_api_key, base, dim)
    if settings.jina_api_key:
        base, model, dim = _PROVIDER_PRESETS["jina"]
        return ("jina", settings.jina_api_key, base, dim)
    if settings.nvidia_api_key:
        base, model, dim = _PROVIDER_PRESETS["nvidia"]
        return ("nvidia", settings.nvidia_api_key, base, dim)

    # Fallback: embedding_api_key set in settings without base URL
    if settings.embedding_api_key:
        base = settings.embedding_api_base or "https://api.openai.com/v1"
        model = settings.embedding_api_model or "text-embedding-3-small"
        dim = 1536
        for preset_name, (p_base, p_model, p_dim) in _PROVIDER_PRESETS.items():
            if preset_name in base:
                dim = p_dim
                if not settings.embedding_api_model:
                    model = p_model
                break
        return ("custom", settings.embedding_api_key, base, dim)

    return None


# Nvidia NIM free tier is slow (~700ms/text).  Chunk large batches
# to avoid timeouts and allow incremental progress logging.
_API_BATCH_CHUNK_SIZE = 100


def _api_embed_batch(
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    max_chars: int = 8192,
    dim: int = 1536,
) -> list[list[float]]:
    """Call an OpenAI-compatible /v1/embeddings endpoint for a batch of texts.

    Large batches are automatically chunked to avoid timeouts and provide
    incremental progress.  Returns a list of embedding vectors (L2-normalised)
    in the same order as the input.

    Args:
        dim: Expected embedding dimension for error-case zero-vectors.
    """
    import httpx

    url = f"{base_url.rstrip('/')}/embeddings"
    all_embeddings: list[list[float]] = []
    total_tokens = 0

    for chunk_start in range(0, len(texts), _API_BATCH_CHUNK_SIZE):
        chunk = [t[:max_chars] for t in texts[chunk_start:chunk_start + _API_BATCH_CHUNK_SIZE]]
        chunk_idx = chunk_start // _API_BATCH_CHUNK_SIZE + 1
        n_chunks = (len(texts) + _API_BATCH_CHUNK_SIZE - 1) // _API_BATCH_CHUNK_SIZE

        try:
            resp = httpx.post(
                url,
                json={"model": model, "input": chunk},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()

            items = sorted(data.get("data", []), key=lambda x: x["index"])
            chunk_embs = [item["embedding"] for item in items]

            if len(chunk_embs) != len(chunk):
                logger.warning(
                    "API chunk %d/%d: returned %d for %d — padding",
                    chunk_idx, n_chunks, len(chunk_embs), len(chunk),
                )
                cdim = len(chunk_embs[0]) if chunk_embs else dim
                while len(chunk_embs) < len(chunk):
                    chunk_embs.append([0.0] * cdim)

            all_embeddings.extend(chunk_embs)
            total_tokens += data.get("usage", {}).get("total_tokens", 0)
            logger.debug(
                "API chunk %d/%d: %d texts, %.1fms",
                chunk_idx, n_chunks, len(chunk),
                resp.elapsed.total_seconds() * 1000,
            )

        except Exception as exc:
            logger.warning(
                "API chunk %d/%d failed: %s — padding with zeros",
                chunk_idx, n_chunks, exc,
            )
            all_embeddings.extend([[0.0] * dim] * len(chunk))

    logger.info(
        "API embeddings: %d texts, %d chunks, %s tokens",
        len(texts),
        max(1, (len(texts) + _API_BATCH_CHUNK_SIZE - 1) // _API_BATCH_CHUNK_SIZE),
        total_tokens or "?",
    )

    # L2-normalise all embeddings
    if all_embeddings:
        vecs = np.array(all_embeddings, dtype=np.float64)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        return [row.tolist() for row in vecs]

    return [[0.0] * dim] * len(texts)


# ── Public API ──────────────────────────────────────────────────────────────

class EmbeddingService:
    """Embedding generation with API-first strategy and local fallback.

    Provider selection (``settings.embedding_provider``):

    - ``"auto"`` (default): API if OPENAI_API_KEY, JINA_API_KEY, or
      NVIDIA_API_KEY is set, else local sentence-transformers.
    - ``"api"``: forces API (requires ``embedding_api_key``).
    - ``"local"``: forces local sentence-transformers.

    Both OpenAI and Jina use the same OpenAI-compatible ``/v1/embeddings``
    endpoint, so the same code path handles both.

    All embeddings are L2-normalised so cosine similarity is a dot product.

    Disk caching persists embeddings across runs (keyed by provider + model
    + text hash).

    Usage:
        >>> embedder = EmbeddingService()
        >>> vec = embedder.embed_text("O governo anunciou novas medidas.")
        >>> len(vec)  # 1536 (OpenAI) or 1024 (Jina / local)
        1536
    """

    def __init__(self) -> None:
        from src.config.settings import settings

        self._dim: int | None = None
        self._cache: dict[str, list[float]] | None = None

        # Resolve provider
        provider_setting = settings.embedding_provider

        if provider_setting == "local":
            self._provider = "local"
            self._api_key = ""
            self._api_base = ""
            self._api_model = settings.embedding_local_model
            self._model_name = settings.embedding_local_model
        elif provider_setting == "api":
            detected = _detect_api_provider()
            if detected is None:
                logger.warning(
                    "embedding_provider='api' but no API key found — "
                    "falling back to local"
                )
                self._provider = "local"
                self._api_key = ""
                self._api_base = ""
                self._api_model = ""
                self._model_name = settings.embedding_local_model
            else:
                name, key, base, dim = detected
                self._provider = "api"
                self._api_key = key
                self._api_base = base
                self._api_model = settings.embedding_api_model or _PROVIDER_PRESETS.get(
                    name, (None, "text-embedding-3-small", 1536)
                )[1]
                self._model_name = f"api:{self._api_model}"
                self._dim = dim
        else:  # "auto"
            detected = _detect_api_provider()
            if detected is not None:
                name, key, base, dim = detected
                self._provider = "api"
                self._api_key = key
                self._api_base = base
                self._api_model = _PROVIDER_PRESETS.get(
                    name, (None, "text-embedding-3-small", 1536)
                )[1]
                self._model_name = f"api:{self._api_model}"
                self._dim = dim
                logger.info("Embedding provider: API (%s)", name)
            else:
                self._provider = "local"
                self._api_key = ""
                self._api_base = ""
                self._api_model = ""
                self._model_name = settings.embedding_local_model
                logger.info("Embedding provider: local (no API key found)")

    @property
    def is_api(self) -> bool:
        """True if using an API provider (no local model load needed)."""
        return self._provider == "api"

    # ── Cache ────────────────────────────────────────────────────────────────

    def _cache_key(self, text: str) -> str:
        """Build a cache key using provider-qualified model name + text hash."""
        return f"{self._model_name}@{_text_hash(text)}"

    @property
    def _embed_cache(self) -> dict[str, list[float]]:
        if self._cache is None:
            self._cache = _load_embed_cache()
        return self._cache

    def _persist_cache(self) -> None:
        if self._cache is not None:
            _save_embed_cache(self._cache)

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        if self._dim is None:
            if self._provider == "local":
                model = _get_model(self._model_name)
                if model is not None:
                    self._dim = getattr(
                        model, "get_embedding_dimension", model.get_sentence_embedding_dimension
                    )()
                else:
                    self._dim = 1024
            else:
                self._dim = 1024  # fallback
        return self._dim

    # ── Single text ─────────────────────────────────────────────────────────

    def embed_text(self, text: str, max_chars: int = 8192) -> list[float]:
        """Generate an embedding for a single text string.

        Checks the disk cache first.  Returns a zero-vector for empty text
        or when no provider is available.
        """
        if not text or not text.strip():
            return [0.0] * self.dimension

        truncated = text[:max_chars]
        cache = self._embed_cache
        key = self._cache_key(truncated)

        if key in cache:
            return cache[key]

        # Generate embedding
        if self._provider == "api":
            results = _api_embed_batch(
                [truncated], self._api_key, self._api_base, self._api_model, max_chars, dim=self.dimension
            )
            emb_list = results[0] if results else [0.0] * self.dimension
        else:
            model = _get_model(self._model_name)
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

        Cache hits skip both the API call and local model encode.
        """
        if not texts:
            return []

        cache = self._embed_cache
        dim = self.dimension
        result: list[list[float]] = []
        to_embed: list[tuple[int, str]] = []
        cached_count = 0

        for i, t in enumerate(texts):
            if not (t and t.strip()):
                result.append([0.0] * dim)
                continue

            truncated = t[:max_chars]
            key = self._cache_key(truncated)

            if key in cache:
                result.append(cache[key])
                cached_count += 1
            else:
                result.append([0.0] * dim)  # placeholder
                to_embed.append((i, truncated))

        if to_embed:
            texts_to_encode = [t for _, t in to_embed]
            logger.debug(
                "Cache miss for %d/%d texts — embedding now…",
                len(to_embed), len(texts),
            )

            if self._provider == "api":
                api_results = _api_embed_batch(
                    texts_to_encode, self._api_key, self._api_base,
                    self._api_model, max_chars, dim=dim,
                )
                for (idx, txt), emb in zip(to_embed, api_results):
                    emb_list = emb
                    result[idx] = emb_list
                    cache_key = self._cache_key(txt[:max_chars])
                    cache[cache_key] = emb_list
            else:
                model = _get_model(self._model_name)
                if model is None:
                    # Leave zero-vectors in place
                    pass
                else:
                    embeddings = model.encode(
                        texts_to_encode,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    for (idx, txt), emb in zip(to_embed, embeddings):
                        emb_list = emb.tolist()
                        result[idx] = emb_list
                        cache_key = self._cache_key(txt[:max_chars])
                        cache[cache_key] = emb_list

        if to_embed:
            self._persist_cache()
            logger.debug(
                "Cached %d new embeddings (total cache: %d)",
                len(to_embed), len(cache),
            )

        logger.debug(
            "embed_batch: %d texts, %d cache hits, %d embedded (provider=%s)",
            len(texts), cached_count, len(to_embed), self._provider,
        )
        return result

    # ── Similarity helpers ──────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Cosine similarity between two embedding vectors."""
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


# ── Module-level helper (backward compat) ───────────────────────────────────

def is_api_available() -> bool:
    """Check if an API embedding provider is configured and available."""
    return _detect_api_provider() is not None


# ── Cache warm-up ───────────────────────────────────────────────────────────

async def warm_embed_cache(db_session, window_days: int = 7) -> int:
    """Pre-populate the embedding cache with articles from the last *window_days*.

    Call this before running ``StatsGenerator.collect()`` so that all analyzers
    benefit from cache hits.  With API provider, this eliminates the 26s
    model load entirely.

    Returns the number of texts actually embedded (new cache entries).
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from src.db.models import Article

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)

    cache = _load_embed_cache()
    initial_size = len(cache)

    embedder = EmbeddingService()

    # Pre-load local model only if using local provider
    if not embedder.is_api:
        _get_model(embedder._model_name)

    try:
        result = await db_session.execute(
            select(Article)
            .where(Article.collected_at >= start)
            .where(
                (Article.content_text.isnot(None) & (Article.content_text != ""))
                | (Article.summary.isnot(None) & (Article.summary != ""))
            )
            .limit(2000)
        )
        articles = list(result.scalars().all())
    except Exception as exc:
        logger.warning("warm_embed_cache: DB query failed: %s", exc)
        return 0

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
            "warm_embed_cache: pre-embedding %d texts via %s (cache has %d entries)…",
            len(texts_to_cache), embedder._provider, initial_size,
        )
        embedder.embed_batch(texts_to_cache)
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
