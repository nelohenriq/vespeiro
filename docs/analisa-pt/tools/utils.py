#!/usr/bin/env python3
"""Shared utility functions for Analisa.pt tools.

Consolidates duplicated functions across entity_profile.py,
municipality_demographics.py, municipality_directory.py,
nif_mapper.py, and municipality_spending.py.
"""

import re
from typing import Optional, Tuple

from unidecode import unidecode


# =============================================================================
# CURRENCY FORMATTING
# =============================================================================

def format_currency(value: float) -> str:
    """Format a monetary value with € prefix and human-readable suffix.

    Examples:
        23_590_000_000 → '€23.59B'
        1_234_000      → '€1.2M'
        56_000         → '€56.0K'
        42             → '€42'
    """
    if value >= 1_000_000_000:
        return f"€{value / 1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"€{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        return f"€{value / 1_000:.1f}K"
    else:
        return f"€{value:.0f}"


# =============================================================================
# NAME NORMALIZATION
# =============================================================================

def normalize_name(name: str) -> str:
    """Normalize a Portuguese entity name for fuzzy comparison.

    Strips accents, lowercases, removes punctuation, and collapses whitespace.

    Examples:
        'Câmara Municipal de Vila Nova de Gaia' → 'camara municipal de vila nova de gaia'
        'Município do Porto (Sede)'             → 'municipio do porto sede'
    """
    n = unidecode(name.lower().strip())
    n = re.sub(r'[^\w\s]', '', n)
    n = re.sub(r'\s+', ' ', n)
    return n.strip()


# =============================================================================
# ENTITY NAME → LOCATION EXTRACTION
# =============================================================================

# All prefixes, ordered longest-first so "unidade local de saude de" matches
# before "unidade local de saude" which matches before "hospital de".
ENTITY_PREFIXES = [
    # Municipality-level
    "camara municipal de ", "camara municipal do ", "camara municipal da ",
    "municipio de ", "municipio do ", "municipio da ",
    # Sub-municipal
    "junta de freguesia de ", "junta de freguesia do ", "junta de freguesia da ",
    "hospital central de ", "hospital central do ",
    "hospital distrital de ", "hospital distrital do ",
    "unidade local de saude de ", "unidade local de saude do ",
    "unidade local de saude da ",
    "centro hospitalar de ", "centro hospitalar do ",
    "hospital de ", "hospital do ", "hospital da ",
    "agrupamento de escolas de ", "agrupamento de escolas do ",
    "agrupamento de escolas da ", "agrupamento de escolas ",
    "centro de saude de ", "centro de saude do ", "centro de saude da ",
    "escola basica de ", "escola basica do ", "escola basica da ",
    "conselho municipal de ", "conselho municipal do ",
    "comunidade intermunicipal de ", "comunidade intermunicipal do ",
    "associacao de municipios de ", "associacao de municipios do ",
    "associacao de municipios ",
    "empresa municipal de ", "empresa municipal do ",
    "servicos municipalizados de ",
    "fundacao municipio de ", "fundacao municipio do ",
    "instituto politecnico de ", "universidade de ",
]

# Prefixes that indicate a municipality-level entity (for entity_type detection)
_MUNI_PREFIXES = {
    "camara municipal de ", "camara municipal do ", "camara municipal da ",
    "municipio de ", "municipio do ", "municipio da ",
}


def _clean_location(loc: str) -> str:
    """Remove trailing junk from a location name (parentheticals, legal forms, etc.)."""
    loc = re.sub(r',.*$', '', loc)
    loc = re.sub(r'\s*\(.*$', '', loc)
    loc = re.sub(r'\s+-\s+.*$', '', loc)
    loc = re.sub(r'\s+e\.?\s*p\.?\s*e\.?.*$', '', loc)
    loc = re.sub(r'\s+e\.?\s*p\.?.*$', '', loc)
    loc = re.sub(r'\s+s\.?a\.?.*$', '', loc)
    loc = re.sub(r'\s+l\.?d\.?a\.?.*$', '', loc)
    loc = re.sub(r'\s+c\.?r\.?l\.?.*$', '', loc)
    loc = re.sub(r'\s+unipessoal.*$', '', loc)
    return loc.strip()


def extract_location(entity_name: str) -> Optional[str]:
    """Extract the location part from a Portuguese public entity name.

    Returns the normalized location string, or None if no known prefix matches.

    Examples:
        'Câmara Municipal de Vila Nova de Gaia' → 'vila nova de gaia'
        'Município do Porto'                    → 'porto'
        'Hospital de Santa Maria'               → 'santa maria'
        'Junta de Freguesia de Caminha'         → 'caminha'
    """
    n = unidecode(entity_name.lower().strip())
    for prefix in ENTITY_PREFIXES:
        if n.startswith(prefix):
            location = n[len(prefix):].strip()
            location = _clean_location(location)
            if location and len(location) >= 2:
                return location
    return None


def extract_location_typed(entity_name: str) -> Optional[Tuple[str, str]]:
    """Extract location and entity type from a Portuguese entity name.

    Returns (location, entity_type) where entity_type is one of:
        'municipio', 'sub_municipio', or None.

    Returns None if no known prefix matches.
    """
    n = unidecode(entity_name.lower().strip())
    for prefix in ENTITY_PREFIXES:
        if n.startswith(prefix):
            location = n[len(prefix):].strip()
            location = _clean_location(location)
            if location and len(location) >= 2:
                etype = "municipio" if prefix in _MUNI_PREFIXES else "sub_municipio"
                return location, etype
    return None
