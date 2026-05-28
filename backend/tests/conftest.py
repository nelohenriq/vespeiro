"""Shared test fixtures for all backend modules."""

import uuid
import pytest
from datetime import datetime, timezone


@pytest.fixture
def sample_articles():
    """Generate sample articles for testing pipeline modules."""
    return [
        {
            "id": uuid.uuid4(),
            "source_id": uuid.uuid4(),
            "title": "Governo anuncia novas medidas económicas",
            "content_text": (
                "O governo português anunciou hoje um pacote de medidas económicas "
                "que visam estimular o crescimento e reduzir o desemprego."
            ),
            "published_at": datetime.now(timezone.utc),
            "language": "pt",
        },
        {
            "id": uuid.uuid4(),
            "source_id": uuid.uuid4(),
            "title": "Trump salva 8 mulheres da execução no Irão",
            "content_text": (
                "O presidente dos EUA interveio para salvar oito mulheres da "
                "execução no Irão, segundo fontes diplomáticas."
            ),
            "published_at": datetime.now(timezone.utc),
            "language": "pt",
        },
    ]


@pytest.fixture
def sample_embedding():
    """A small embedding vector for unit tests that don't need real models."""
    return [0.1, 0.2, 0.3, 0.4, 0.5]
