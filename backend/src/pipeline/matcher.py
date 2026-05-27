"""Story matching: cross-lingual article clustering using embedding similarity.

Clusters articles into story groups using:
- Cosine similarity on multilingual embeddings (cross-lingual)
- DBSCAN for density-based clustering
- Incremental matching for new articles against existing clusters
"""

import uuid
import numpy as np


class StoryMatcher:
    """Cross-lingual story clustering using embedding similarity.

    Thresholds are initial values — calibrate with a labeled test set
    of ~100 manually verified article pairs before production use.
    """

    # Similarity thresholds (need calibration)
    EXACT_REPUBLICATION = 0.85
    PARAPHRASE = 0.70
    PARTIAL_REFERENCE = 0.55

    # DBSCAN parameters
    CLUSTER_EPS = 0.30       # Max cosine distance for cluster neighbourhood
    CLUSTER_MIN_SAMPLES = 1  # Allow singleton clusters

    def __init__(self, embedding_dim: int = 1024):
        self.embedding_dim = embedding_dim

    # ── Similarity ──────────────────────────────────────────────────────────

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
        """Compute pairwise cosine similarity matrix for a batch of embeddings."""
        matrix = np.array(embeddings, dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # Avoid division by zero
        normalized = matrix / norms
        return normalized @ normalized.T

    # ── Classification ──────────────────────────────────────────────────────

    def classify_match(self, similarity: float) -> str:
        """Classify the type of match based on similarity score."""
        if similarity >= self.EXACT_REPUBLICATION:
            return "exact_republication"
        elif similarity >= self.PARAPHRASE:
            return "paraphrase"
        elif similarity >= self.PARTIAL_REFERENCE:
            return "partial_reference"
        return "original_reporting"

    # ── Batch clustering (DBSCAN) ───────────────────────────────────────────

    def cluster_articles(
        self,
        embeddings: list[list[float]],
    ) -> np.ndarray:
        """Cluster articles using DBSCAN with cosine distance.

        Args:
            embeddings: List of embedding vectors.

        Returns:
            Array of cluster labels (-1 = noise/outlier, 0, 1, 2, …).
        """
        from sklearn.cluster import DBSCAN

        if len(embeddings) < 2:
            return np.array([0])

        clustering = DBSCAN(
            eps=self.CLUSTER_EPS,
            min_samples=self.CLUSTER_MIN_SAMPLES,
            metric="cosine",
        )
        return clustering.fit_predict(np.array(embeddings, dtype=np.float64))

    def get_cluster_centroid(self, embeddings: list[list[float]]) -> list[float]:
        """Compute the centroid (mean) of a cluster of embeddings."""
        if not embeddings:
            return [0.0] * self.embedding_dim
        centroid = np.mean(np.array(embeddings, dtype=np.float64), axis=0)
        # Normalize
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid.tolist()

    # ── Incremental matching ────────────────────────────────────────────────

    def match_to_existing_clusters(
        self,
        embedding: list[float],
        cluster_centroids: dict[uuid.UUID | str, list[float]],
    ) -> tuple[uuid.UUID | str | None, float | None, str | None]:
        """Match a new article's embedding against existing cluster centroids.

        Args:
            embedding: The embedding of the new article.
            cluster_centroids: Dict mapping cluster_id → centroid embedding.

        Returns:
            Tuple of (best_cluster_id, best_similarity, match_type).
            If no good match, all values are None (orphan — create new cluster).
        """
        best_cluster = None
        best_similarity = 0.0

        for cluster_id, centroid in cluster_centroids.items():
            sim = self.cosine_similarity(embedding, centroid)
            if sim > best_similarity:
                best_similarity = sim
                best_cluster = cluster_id

        if best_similarity >= self.PARAPHRASE:
            match_type = self.classify_match(best_similarity)
            return best_cluster, best_similarity, match_type

        return None, None, None  # Orphan — create new cluster

    # ── Full pipeline helpers ───────────────────────────────────────────────

    def cluster_and_build_index(
        self,
        article_ids: list[uuid.UUID | str],
        embeddings: list[list[float]],
    ) -> tuple[dict[uuid.UUID | str, list[uuid.UUID | str]], dict[uuid.UUID | str, list[float]]]:
        """Full clustering: from article + embedding lists to cluster index.

        Args:
            article_ids: List of article UUIDs/strings.
            embeddings: Corresponding list of embedding vectors.

        Returns:
            Tuple of:
            - cluster_map: dict cluster_id → list[article_id]
            - centroids: dict cluster_id → centroid_embedding
        """
        labels = self.cluster_articles(embeddings)

        # Group articles by cluster label
        cluster_groups: dict[int, list[uuid.UUID | str]] = {}
        for article_id, label in zip(article_ids, labels):
            cluster_groups.setdefault(int(label), []).append(article_id)

        # Assign UUIDs to clusters and compute centroids
        cluster_map: dict[uuid.UUID | str, list[uuid.UUID | str]] = {}
        centroids: dict[uuid.UUID | str, list[float]] = {}

        for label, members in cluster_groups.items():
            cluster_id = str(uuid.uuid4())
            cluster_map[cluster_id] = members
            # Get embeddings of members
            member_embeddings = [
                emb for art_id, emb in zip(article_ids, embeddings)
                if art_id in members
            ]
            centroids[cluster_id] = self.get_cluster_centroid(member_embeddings)

        return cluster_map, centroids
