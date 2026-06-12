#!/usr/bin/env python3
"""Shared utility functions for Analisa.pt tools.

Consolidates duplicated functions across entity_profile.py,
municipality_demographics.py, municipality_directory.py,
nif_mapper.py, municipality_spending.py, anomaly_scanner.py,
entity_network.py, entity_profile.py, supplier_cross_profiler.py,
temporal_clustering.py, bid_pattern_analyzer.py,
municipality_risk_report.py, and bep_procurement_crossref.py.

Public helpers:
    fmt, format_currency      — currency formatting
    normalize_name            — accent-strip + lowercase + collapse
    extract_location          — location string from entity name
    extract_location_typed    — (location, entity_type) tuple
    parse_entity_field        — "NIF - Name; NIF - Name" → list[dict]
    parse_date                — 7+ common date formats incl. timezone-aware ISO (Z, +HH:MM) → datetime
    days_between              — abs() days between two dates/datetimes
    signed_days_between       — signed (end - start) days; sign carries order
"""

import re
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple, Union

from unidecode import unidecode


# =============================================================================
# DATE PARSING & ARITHMETIC
# =============================================================================

# Common Portuguese procurement / parliamentary date formats.
# Order matters: longer/more-specific formats first so e.g. "2025-03-15T10:30:00"
# is caught by the datetime form before the bare date form.
_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",  # ISO with microseconds + tz offset (e.g. 2025-03-15T10:30:00.123456+0000)
    "%Y-%m-%dT%H:%M:%S%z",     # ISO datetime + tz offset (e.g. 2025-03-15T10:30:00+0000)
    "%Y-%m-%dT%H:%M:%S.%f",    # ISO datetime with microseconds
    "%Y-%m-%dT%H:%M:%S",       # ISO datetime
    "%Y-%m-%d %H:%M:%S",       # space-separated datetime
    "%Y-%m-%d",                # bare ISO date
    "%d/%m/%Y",                # Portuguese style
    "%d-%m-%Y",
    "%d.%m.%Y",
)


# Timezone-offset suffixes that strptime cannot match directly. We normalize
# them up-front so a single %z format works for all common wire formats.
_TZ_SUFFIX_RE = re.compile(
    r"(Z|\+|-)(\d{2}):?(\d{2})$"   # Z, +HH:MM, +HHMM, -HH:MM, -HHMM
)


def _normalize_iso_tz(s: str) -> str:
    """Normalize timezone suffixes to the ``+HHMM`` form strptime expects.

    Handles three common wire formats:
        'Z'         -> '+0000'   (Zulu / UTC shorthand)
        '+00:00'    -> '+0000'   (ISO 8601 with colon)
        '+0000'     -> '+0000'   (already normalized)

    If the string has no recognizable suffix, it is returned unchanged.
    """
    match = _TZ_SUFFIX_RE.search(s)
    if not match:
        return s
    sign, hh, mm = match.group(1), match.group(2), match.group(3)
    if sign == "Z":
        sign = "+"
    return s[: match.start()] + f"{sign}{hh}{mm}"


def parse_date(value: Union[str, datetime, date, None]) -> Optional[datetime]:
    """Parse a date string in any of several common formats.

    Supports timezone-aware ISO 8601 strings (the ``Z`` suffix and ``+HH:MM``
    offsets) by normalizing them to the ``+HHMM`` form before strptime.

    Returns a ``datetime`` on success, or ``None`` for empty/invalid input.
    Already-parsed ``datetime`` / ``date`` values are returned as-is.
    Naive datetimes are returned as-is when input is a ``datetime``.

    Note: TZ-aware inputs (e.g. ``...Z``, ``...+00:00``) return timezone-aware
    datetimes; naive inputs return naive datetimes. Python raises ``TypeError``
    when comparing aware vs naive results, so callers that mix them should
    normalize with ``.replace(tzinfo=None)`` first.

    Examples:
        '2025-03-15'                     -> datetime(2025, 3, 15)
        '15/03/2025'                     -> datetime(2025, 3, 15)
        '2025-03-15T10:30:00'            -> datetime(2025, 3, 15, 10, 30)
        '2025-03-15T10:30:00Z'           -> datetime(2025, 3, 15, 10, 30, tz=UTC)
        '2025-03-15T10:30:00+00:00'      -> datetime(2025, 3, 15, 10, 30, tz=UTC)
        '2025-03-15T10:30:00-05:00'      -> datetime(2025, 3, 15, 10, 30, tz=UTC-5)
        '' or None                       -> None
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    if not s or s in ("-", "None", "nan"):
        return None
    s = _normalize_iso_tz(s)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _raw_days_between(start: Union[str, datetime, date, None],
                      end: Union[str, datetime, date, None]) -> Optional[int]:
    """Return the signed ``(end - start).days``, or ``None`` if either side is unparseable.

    Private helper shared by :func:`days_between` (which applies ``abs()``)
    and :func:`signed_days_between` (which returns the raw signed value).
    """
    s = parse_date(start)
    e = parse_date(end)
    if s is None or e is None:
        return None
    return (e - s).days


def days_between(start: Union[str, datetime, date, None],
                 end: Union[str, datetime, date, None]) -> Optional[int]:
    """Return the absolute number of whole days between two dates.

    Returns the non-negative integer day count, or ``None`` if either side
    is unparseable. ``abs()`` is applied so callers don't have to think
    about argument order — this matches the legacy local helper that
    previously lived in ``temporal_clustering.py``.

    Examples:
        days_between('2025-01-01', '2025-01-15')  -> 14
        days_between('2025-01-15', '2025-01-01')  -> 14  (same — abs)
        days_between(None, '2025-01-15')          -> None
    """
    delta = _raw_days_between(start, end)
    return None if delta is None else abs(delta)


def signed_days_between(start: Union[str, datetime, date, None],
                        end: Union[str, datetime, date, None]) -> Optional[int]:
    """Return the signed number of whole days between two dates.

    Positive when ``end`` is after ``start``, negative when ``end`` is
    before, zero when they are equal. Returns ``None`` if either side is
    unparseable (same contract as ``days_between``).

    Use this when the *order* of the two dates carries meaning
    (e.g. "is this contract dated after the law took effect?", or
    "how many days *overdue* is this deadline?"). For plain distance
    use ``days_between``.

    Argument order matters here, unlike ``days_between``.

    Examples:
        signed_days_between('2025-01-01', '2025-01-15')  -> 14   (end is later)
        signed_days_between('2025-01-15', '2025-01-01')  -> -14  (end is earlier)
        signed_days_between('2025-01-15', '2025-01-15')  -> 0    (same day)
        signed_days_between(None, '2025-01-15')          -> None
    """
    return _raw_days_between(start, end)


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


# =============================================================================
# ENTITY FIELD PARSING
# =============================================================================


def parse_entity_field(text: str) -> List[Dict[str, str]]:
    """Parse 'NIF - Name' or 'NIF1 - Name1; NIF2 - Name2' format.

    Returns a list of dicts with 'nif' and 'name' keys.

    Examples:
        '501089233 - CÂMARA MUNICIPAL DE LISBOA'
            -> [{'nif': '501089233', 'name': 'CÂMARA MUNICIPAL DE LISBOA'}]
        '501089233 - CML; 502345678 - JUNTA DE FREGUESIA'
            -> [{'nif': '501089233', 'name': 'CML'}, {'nif': '502345678', 'name': 'JUNTA DE FREGUESIA'}]
    """
    if not text:
        return []
    text = str(text).strip()
    if text in ("-", "- -", "", "None"):
        return []
    entities = []
    for part in text.split(";"):
        part = part.strip()
        match = re.match(r"(\d{9})\s*-\s*(.+)", part)
        if match:
            entities.append({"nif": match.group(1), "name": match.group(2).strip()})
        elif part and part != "-":
            entities.append({"nif": "", "name": part.strip()})
    return entities


# =============================================================================
# CURRENCY FORMATTING (short form — handles None/zero)
# =============================================================================


def fmt(val) -> str:
    """Format a monetary value with € prefix and human-readable suffix.

    Handles None/zero values and large number abbreviations.

    Examples:
        23_590_000_000 → '\u20ac23.6B'
        1_234_000      → '\u20ac1.2M'
        56_000         → '\u20ac56K'
        42             → '\u20ac42'
        None           → '\u20ac0'
        0              → '\u20ac0'
    """
    if val is None or val == 0:
        return "\u20ac0"
    if val >= 1_000_000_000:
        return f"\u20ac{val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"\u20ac{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"\u20ac{val / 1_000:.0f}K"
    return f"\u20ac{val:.0f}"
