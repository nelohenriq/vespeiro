"""Tests for the dados.gov.pt open data portal client."""

from src.public_sources.dados_gov_pt import search_datasets


def test_search_communication():
    """Verify the API returns results for relevant queries."""
    datasets = search_datasets("comunicação", max_results=5)
    assert len(datasets) > 0
    for ds in datasets:
        assert ds.id
        assert ds.title


def test_search_media():
    datasets = search_datasets("media", max_results=5)
    assert len(datasets) > 0


def test_search_broad_query():
    """A broad query should return results."""
    datasets = search_datasets("saúde", max_results=3)
    assert len(datasets) > 0


def test_dataset_structure():
    """Verify returned datasets have the expected fields."""
    datasets = search_datasets("transparência", max_results=3)
    for ds in datasets:
        assert isinstance(ds.id, str)
        assert isinstance(ds.title, str)
        assert isinstance(ds.organization, str)
        assert isinstance(ds.resources, list)
