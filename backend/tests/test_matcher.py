"""Tests for the story matching pipeline (cosine similarity + DBSCAN)."""

import pytest
import uuid
import numpy as np
from src.pipeline.matcher import StoryMatcher


@pytest.fixture
def matcher():
    return StoryMatcher(embedding_dim=4)


# ── Similarity tests ────────────────────────────────────────────────────────


def test_cosine_similarity_identical():
    """Identical vectors have similarity = 1.0."""
    v = [0.5, 0.3, 0.8, 0.1]
    sim = StoryMatcher.cosine_similarity(v, v)
    assert sim == pytest.approx(1.0, abs=0.001)


def test_cosine_similarity_orthogonal():
    """Orthogonal vectors have similarity ≈ 0.0."""
    v1 = [1.0, 0.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0, 0.0]
    sim = StoryMatcher.cosine_similarity(v1, v2)
    assert sim == pytest.approx(0.0, abs=0.001)


def test_cosine_similarity_half():
    """Vectors at 45° have similarity ≈ 0.707."""
    v1 = [1.0, 0.0]
    v2 = [1.0, 1.0]
    sim = StoryMatcher.cosine_similarity(v1, v2)
    assert sim == pytest.approx(0.7071, abs=0.01)


def test_cosine_similarity_matrix():
    """Verify similarity matrix shape and diagonal."""
    embeddings = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.5, 0.5, 0.0],
    ]
    matrix = StoryMatcher.cosine_similarity_matrix(embeddings)
    assert matrix.shape == (3, 3)
    assert matrix[0, 0] == pytest.approx(1.0, abs=0.001)
    assert matrix[0, 1] == pytest.approx(0.0, abs=0.01)
    assert matrix[0, 2] == pytest.approx(0.7071, abs=0.01)


def test_similarity_zero_vector():
    """Zero vector should not cause division by zero."""
    v1 = [0.0, 0.0, 0.0]
    v2 = [0.5, 0.3, 0.1]
    sim = StoryMatcher.cosine_similarity(v1, v2)
    assert sim == 0.0


# ── Classification tests ────────────────────────────────────────────────────


def test_classify_exact_republication(matcher):
    assert matcher.classify_match(0.90) == "exact_republication"
    assert matcher.classify_match(0.85) == "exact_republication"


def test_classify_paraphrase(matcher):
    assert matcher.classify_match(0.75) == "paraphrase"
    assert matcher.classify_match(0.70) == "paraphrase"


def test_classify_partial_reference(matcher):
    assert matcher.classify_match(0.60) == "partial_reference"
    assert matcher.classify_match(0.55) == "partial_reference"


def test_classify_original_reporting(matcher):
    assert matcher.classify_match(0.40) == "original_reporting"
    assert matcher.classify_match(0.00) == "original_reporting"


# ── Clustering tests ────────────────────────────────────────────────────────


def test_cluster_less_than_two_articles(matcher):
    """Single article should get label 0."""
    labels = matcher.cluster_articles([[0.1, 0.2, 0.3]])
    assert len(labels) == 1
    assert labels[0] == 0


def test_cluster_similar_articles(matcher):
    """Three similar articles should be in the same cluster."""
    similar = [
        [0.1, 0.2, 0.3, 0.4],
        [0.11, 0.21, 0.31, 0.41],
        [0.09, 0.19, 0.32, 0.39],
    ]
    labels = matcher.cluster_articles(similar)
    assert labels[0] == labels[1] == labels[2]


def test_cluster_different_articles(matcher):
    """Dissimilar articles should be in different clusters."""
    # Group A: all-positive direction
    group_a = [[0.1, 0.2, 0.3], [0.11, 0.21, 0.31]]
    # Group B: opposite direction (cosine sim ≈ -0.97 vs group A)
    group_b = [[-0.9, -0.8, -0.7], [-0.91, -0.81, -0.71]]
    all_embeddings = group_a + group_b
    labels = matcher.cluster_articles(all_embeddings)
    # Articles in the same group should share labels
    assert labels[0] == labels[1], "Group A articles should be in same cluster"
    assert labels[2] == labels[3], "Group B articles should be in same cluster"
    # Groups should be in different clusters
    assert labels[0] != labels[2], "Different clusters expected"


# ── Centroid tests ──────────────────────────────────────────────────────────


def test_get_cluster_centroid(matcher):
    """Centroid of identical vectors is the normalized vector."""
    embeddings = [[0.1, 0.2, 0.3, 0.4]] * 3
    centroid = matcher.get_cluster_centroid(embeddings)
    assert len(centroid) == 4
    # Centroid is normalized to unit length
    norm = np.linalg.norm(centroid)
    assert norm == pytest.approx(1.0, abs=0.001)


def test_get_cluster_centroid_normalized(matcher):
    """Centroid of non-normalized vectors should be normalized."""
    embeddings = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    centroid = matcher.get_cluster_centroid(embeddings)
    norm = np.linalg.norm(centroid)
    assert norm == pytest.approx(1.0, abs=0.001)


def test_get_cluster_centroid_empty(matcher):
    """Empty list returns zero vector."""
    centroid = matcher.get_cluster_centroid([])
    assert centroid == [0.0] * 4


# ── Incremental matching tests ──────────────────────────────────────────────


def test_match_to_existing_found(matcher):
    """Similar article should match an existing cluster."""
    cluster_id = "cluster-1"
    centroids = {cluster_id: [0.1, 0.2, 0.3, 0.4]}
    matched_id, score, match_type = matcher.match_to_existing_clusters(
        [0.11, 0.21, 0.31, 0.41], centroids,
    )
    assert matched_id == cluster_id
    assert score is not None and score > 0.90
    assert match_type == "exact_republication"


def test_match_to_existing_not_found(matcher):
    """Unrelated article should not match any cluster."""
    cluster_id = "cluster-1"
    centroids = {cluster_id: [0.1, 0.2, 0.3, 0.4]}
    # Orthogonal vector: cosine similarity ≈ 0.0 (well below 0.70 threshold)
    matched_id, score, match_type = matcher.match_to_existing_clusters(
        [0.4, -0.3, 0.2, -0.1], centroids,
    )
    assert matched_id is None
    assert score is None
    assert match_type is None


def test_match_to_existing_empty_centroids(matcher):
    """No centroids → no match possible."""
    matched_id, score, match_type = matcher.match_to_existing_clusters(
        [0.1, 0.2, 0.3, 0.4], {},
    )
    assert matched_id is None
    assert score is None
    assert match_type is None


def test_match_to_existing_best_centroid_selected(matcher):
    """Should match the best (highest similarity) centroid among options."""
    centroids = {
        "wrong": [0.9, 0.9, 0.9, 0.9],
        "right": [0.1, 0.2, 0.3, 0.4],
    }
    matched_id, score, _ = matcher.match_to_existing_clusters(
        [0.11, 0.21, 0.31, 0.41], centroids,
    )
    assert matched_id == "right"


# ── Full pipeline tests ─────────────────────────────────────────────────────


def test_cluster_and_build_index(matcher):
    """End-to-end: cluster articles and build cluster map + centroids."""
    article_ids = [str(uuid.uuid4()) for _ in range(5)]
    # 3 similar + 2 different (opposite direction)
    embeddings = [
        [0.1, 0.2, 0.3, 0.4],
        [0.11, 0.21, 0.31, 0.41],
        [0.09, 0.19, 0.32, 0.39],
        [-0.9, -0.8, -0.7, -0.6],
        [-0.91, -0.81, -0.71, -0.61],
    ]

    cluster_map, centroids = matcher.cluster_and_build_index(article_ids, embeddings)

    # Should have 2 clusters
    assert len(cluster_map) == 2
    assert len(centroids) == 2

    # Check membership
    all_members = []
    for members in cluster_map.values():
        all_members.extend(members)
    assert len(all_members) == 5  # All articles assigned
    assert set(all_members) == set(article_ids)


def test_cross_lingual_similarity():
    """PT and EN versions of the same story should have high similarity.

    This is a property-based test: multilingual embeddings of semantically
    equivalent texts in different languages should be closer than unrelated texts.
    """
    # Same story across languages: nearly identical embeddings
    story_pt = [0.1, 0.2, 0.3, 0.4]
    story_en = [0.11, 0.21, 0.31, 0.41]  # Slight variation (simulating cross-lingual)
    # Completely different story: orthogonal direction
    different_story = [0.4, -0.3, 0.2, -0.1]

    sim_same = StoryMatcher.cosine_similarity(story_pt, story_en)
    sim_diff = StoryMatcher.cosine_similarity(story_pt, different_story)

    assert sim_same > 0.90, "Same story across languages should be similar"
    assert sim_diff < 0.50, "Different stories should be dissimilar"
    assert sim_same > sim_diff, (
        "Cross-lingual same-story similarity should exceed different-story"
    )
