"""
Client for ``dados.gov.pt`` — Portuguese Open Data Portal.

Uses the CKAN-compatible REST API:

- Search datasets: ``GET /api/1/datasets/?q=<query>``
- Pagination: Uses ``next`` link in response
- httpx auto-encodes query params when passed as dict

Relevant search terms:
- "comunicação social"
- "media" / "imprensa"
- "publicidade institucional"
- "transparência"
"""

from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class Dataset:
    id: str
    title: str
    description: str
    organization: str
    resources: list[dict]
    url: str


API_BASE = "https://dados.gov.pt/api/1/datasets/"


def search_datasets(query: str, max_results: int = 20) -> list[Dataset]:
    """Search for datasets by keyword.

    httpx auto-encodes query params — no manual quoting needed.
    Paginates automatically up to ``max_results``.
    """
    datasets: list[Dataset] = []
    params = {"q": query, "rows": min(max_results, 20)}

    with httpx.Client(timeout=15.0) as client:
        resp = client.get(API_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("data", []):
            ds = _parse_dataset(item)
            if ds is not None:
                datasets.append(ds)

        # Pagination: follow 'next' link if present
        next_url = data.get("next_page") or data.get("links", {}).get("next")
        while next_url and len(datasets) < max_results:
            resp = client.get(next_url)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data", []):
                if len(datasets) >= max_results:
                    break
                ds = _parse_dataset(item)
                if ds is not None:
                    datasets.append(ds)
            next_url = data.get("next_page") or (
                data.get("links", {}).get("next") if "links" in data else None
            )

    return datasets


def _parse_dataset(item: dict) -> Dataset | None:
    """Parse a single dataset dict from the CKAN API."""
    ds_id = item.get("id", "")
    title = item.get("title", "")
    if not ds_id or not title:
        return None

    return Dataset(
        id=ds_id,
        title=title,
        description=item.get("notes", ""),
        organization=item.get("organization", {}).get("title", ""),
        resources=[
            {
                "url": r.get("url", ""),
                "format": r.get("format", ""),
                "description": r.get("description", ""),
            }
            for r in item.get("resources", [])
            if r.get("url")
        ],
        url=item.get("page_url", ""),
    )


def download_resource(url: str, local_path: str) -> bool:
    """Download a dataset resource (CSV, JSON, etc.) to a local file."""
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            return False
        Path(local_path).write_bytes(resp.content)
    return True
