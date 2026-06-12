#!/usr/bin/env python3
"""Freguesia Resolver — Map LocalExecucao strings to official INE codes.

Parses the LocalExecucao field from procurement contracts and resolves
location strings to official Portuguese administrative codes (CAOP/INE).

The 6-digit code structure: DDDDMMFF
  DD = District (Distrito)
  MM = Municipality (Concelho)
  FF = Freguesia (Parish)

Usage:
    python freguesia_resolver.py resolve         # Resolve all contracts
    python freguesia_resolver.py resolve --nif 501089233  # By entity
    python freguesia_resolver.py stats           # Coverage statistics
    python freguesia_resolver.py unmapped        # Show unresolved strings
    python freguesia_resolver.py export          # Export mapping to JSON
"""

import sys
import json
import sqlite3
import argparse
import re
from pathlib import Path
from collections import Counter
from difflib import get_close_matches
from utils_db import connect as db_connect
from caop_codes import (
    DISTRICT_CODES, CODE_TO_DISTRICT, MUNICIPALITY_CODES,
    CODE_TO_MUNICIPALITY, resolve_municipality, resolve_municipality_6digit,
    get_municipality_name, get_district_name, _normalize_name
)

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "procurement.db"
MAPPING_PATH = DATA_DIR / "local_execucao_to_ine.json"
MUNI_DIR_PATH = DATA_DIR / "municipality_directory.json"
NIF_DB_PATH = DATA_DIR / "freguesia_nif_database.json"
NIF_DB_URL = "https://dados.gov.pt/s/dadosGovFiles/Freguesiasdadosgerais.xlsx"


# Pre-computed sorted municipality names (longest first for greedy matching)
_SORTED_MUNI_NAMES = sorted(MUNICIPALITY_CODES.keys(), key=lambda x: -len(x))

# ── Abbreviation expansion ──────────────────────────────────────────────────
# Portuguese procurement data often abbreviates "Vila Nova", "Vila Franca",
# "São João", etc. Map common abbreviations → full forms.
ABBREVIATION_MAP = {
    "v.n.": "vila nova",
    "v.n": "vila nova",
    "v.f.": "vila franca",
    "v.f": "vila franca",
    "s.j.": "são joão",
    "s.j": "são joão",
    "s.t.": "santo",
    "s.t": "santo",
    "s.to": "santo",
    "st.to": "santo",
    "s.pe.": "são pedro",
    "s.pe": "são pedro",
    "p.d.": "porto de",
    "p.de": "porto de",
    "v.d.": "vila do",
    "v.de": "vila do",
    "v.d": "vila do",
    "v.c.": "vila nova de",
    "m.d.": "marco de",
    "m.de": "marco de",
    "c.d.": "castelo de",
    "c.de": "castelo de",
    "p.d.s.": "peso da régua",
    "v.g.": "vila franca de xira",
    "m.d.c.": "marco de canaveses",
    "c.b.": "castelo branco",
    "v.r.": "vila real",
    "v.c.": "vila do conde",
    "v.p.": "vila pouca de aguiar",
    "v.n.f.": "vila nova de foz coa",
    "v.n.p.": "vila nova de paiva",
    "v.n.c.": "vila nova de cerveira",
    "v.n.b.": "vila nova da barquinha",
    "v.n.g.": "vila nova de gaia",
    "p.d.l.": "ponte de lima",
    "p.d.b.": "ponte da barca",
    "p.d.c.": "paredes de coura",
    "s.m.f.": "santa maria da feira",
}

# ── Rural / neighborhood location prefixes ──────────────────────────────────
LOCATION_PREFIXES = [
    "lugar de ", "lugar do ", "lugar da ",
    "aldeia de ", "aldeia do ", "aldeia da ",
    "povoação de ", "povoação do ",
    "sítio de ", "sítio do ",
    "monte de ", "monte do ",
    "bairro de ", "bairro do ", "bairro da ",
    "zona industrial de ", "zona industrial do ",
    "zona comercial de ", "zona comercial do ",
    "zona urbana de ", "zona urbana do ",
    "zona rural de ", "zona rural do ",
    "zona de ", "zona do ",
    "quinta de ", "quinta do ", "quinta da ",
    "herdade de ", "herdade do ", "herdade da ",
    "pago de ", "pago do ",
    "eira de ",
    "outeiro de ",
    "reguengo de ",
    "couto de ",
    "paço de ", "paço do ",
    "solar de ",
    "moinho de ",
    "ribeira de ", "ribeira do ", "ribeira da ",
    "vala de ",
    "cascaldeira de ",
    "lameiro de ",
    "fonte de ", "fonte do ",
]

# Common non-location words that should be stripped when trying to find a municipality
NOISE_WORDS = {
    "edifício", "escritório", "loja", "armazém", "depósito",
    "oficina", "estaleiro", "canteiro", "sede", "gabinete",
    "norte", "sul", "leste", "oeste", "central", "principal",
    "anexo", "delegação", "secundário", "cabo", "piso",
    "r/ch", "1º", "2º", "3º", "4º", "5º",
    "trás", "aquém", "além",
    "lote", "polígono", "loteamento",
    "cc", "centro comercial",
}



def _ensure_database():
    """Ensure procurement.db exists with the contratos table.

    If the database is missing or has no contratos table, attempts to build
    it from the XLSX source files via procurement_db.py.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Quick check: does the file exist and have the contratos table?
    if DB_PATH.exists():
        try:
            conn = db_connect(str(DB_PATH))
            has_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='contratos'"
            ).fetchone()
            conn.close()
            if has_table:
                return  # Database is fine
        except sqlite3.DatabaseError:
            pass  # Corrupted DB, rebuild

    # Database missing or incomplete — try to build
    print(f"  WARNING: procurement.db missing or incomplete at {DB_PATH}")
    print(f"  Attempting auto-build from XLSX files...")

    xlsx_dir = DATA_DIR
    contratos_xlsx = xlsx_dir / "contratos2025.xlsx"
    if not contratos_xlsx.exists():
        # Also check for any contratos*.xlsx variant
        contratos_xlsx = next(xlsx_dir.glob("contratos*.xlsx"), None)
    if not contratos_xlsx or not contratos_xlsx.exists():
        print(f"  ERROR: No contratos XLSX file found in {xlsx_dir}")
        print(f"  Download data from dados.gov.pt first, then run:")
        print(f"    python procurement_db.py build")
        sys.exit(1)

    # Try importing and running procurement_db
    try:
        from procurement_db import init_db, parse_contratos_xlsx, parse_entidades_xlsx
        conn = init_db(force=False)
        n_c = parse_contratos_xlsx(conn)
        n_e = parse_entidades_xlsx(conn)
        conn.close()
        if n_c > 0:
            print(f"  OK: Built procurement.db: {n_c:,} contratos, {n_e:,} entidades")
        else:
            print(f"  ERROR: Build produced 0 contratos. Check XLSX files in {xlsx_dir}")
            sys.exit(1)
    except ImportError:
        print(f"  ERROR: Cannot import procurement_db.py — is openpyxl installed?")
        print(f"    pip install openpyxl")
        sys.exit(1)
    except Exception as e:
        print(f"  ERROR: Build failed: {e}")
        print(f"    Run manually: python procurement_db.py build")
        sys.exit(1)


class FreguesiaResolver:
    """Resolves LocalExecucao location strings to INE codes."""

    def __init__(self):
        _ensure_database()
        self.conn = db_connect(str(DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.muni_map = self._load_municipality_map()
        self.local_exec_map = self._load_existing_mapping()
        # Load official freguesia NIF database (from dados.gov.pt)
        self._nif_db = self._load_nif_database()
        self._nif_by_name = self._build_nif_name_index()
        # Pre-build normalized → code lookup from CAOP
        self._caop_lookup = {}
        for name, (dist, muni) in MUNICIPALITY_CODES.items():
            norm = _normalize_name(name)
            self._caop_lookup[norm] = dist + muni
            # Also without hyphens
            norm_nh = norm.replace("-", " ").replace("  ", " ").strip()
            self._caop_lookup[norm_nh] = dist + muni

    def _load_municipality_map(self) -> dict:
        """Load municipality directory and build name → CAOP code lookup.

        Only loads codes that are proper 4-digit CAOP format (DDMM).
        NUTs codes from the database are NOT used — they produce incorrect
        codes like 'PT17' instead of proper CAOP codes like '0906'.
        """
        muni_map = {}

        # Load from municipality_directory.json if exists
        if MUNI_DIR_PATH.exists():
            try:
                with open(MUNI_DIR_PATH) as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for key, val in data.items():
                        if isinstance(val, dict):
                            name = val.get("name", key).lower().strip()
                            code = val.get("code", "")
                            # Only accept proper 4-digit CAOP codes (DDMM format)
                            if name and len(code) >= 4 and code[:4].isdigit():
                                muni_map[name] = code[:4]
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            name = item.get("name", item.get("municipality", "")).lower().strip()
                            code = item.get("code", item.get("codigo", ""))
                            # Only accept proper 4-digit CAOP codes (DDMM format)
                            if name and len(code) >= 4 and code[:4].isdigit():
                                muni_map[name] = code[:4]
            except (json.JSONDecodeError, KeyError):
                pass

        # NOTE: We intentionally do NOT build from NUTs codes in the database.
        # NUTs codes (e.g., 'PT17') are a different coding system than CAOP
        # (e.g., '0906' for Fundão). Using NUTs codes produces incorrect
        # ine_code values like 'PT1700' instead of proper CAOP '090600'.
        # The CAOP lookup in _caop_lookup (built from caop_codes.py) is the
        # authoritative source for all municipality resolution.

        return muni_map

    def _load_existing_mapping(self) -> dict:
        """Load existing LocalExecucao → INE mapping."""
        if MAPPING_PATH.exists():
            try:
                with open(MAPPING_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, KeyError):
                pass
        return {}

    def _load_nif_database(self) -> dict:
        """Load the official freguesia NIF database from dados.gov.pt.

        This database contains ~3,000 parishes with their NIFs, INE codes,
        municipality names, and district names. It's the authoritative source
        for mapping parish names to municipalities.

        If the database file doesn't exist, attempts to download it.
        """
        if not NIF_DB_PATH.exists():
            self._download_nif_database()

        if not NIF_DB_PATH.exists():
            return {}

        try:
            with open(NIF_DB_PATH, encoding="utf-8") as f:
                data = json.load(f)
            freguesias = data.get("freguesias", {})
            if freguesias:
                print(f"  OK: Loaded {len(freguesias):,} parishes from NIF database")
            return freguesias
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  WARNING: Could not load NIF database: {e}")
            return {}

    def _download_nif_database(self):
        """Download the freguesia NIF database from dados.gov.pt."""
        print(f"  Downloading freguesia NIF database from dados.gov.pt...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        xlsx_path = DATA_DIR / "freguesiasdadosgerais.xlsx"
        try:
            import urllib.request
            urllib.request.urlretrieve(NIF_DB_URL, xlsx_path)
            print(f"  OK: Downloaded to {xlsx_path}")
        except Exception as e:
            print(f"  ERROR: Download failed: {e}")
            print(f"    Run manually: python freguesia_downloader.py download")
            return

        # Parse the XLSX file
        try:
            from freguesia_downloader import parse_xlsx, save_database
            freguesias = parse_xlsx()
            if freguesias:
                save_database(freguesias)
                print(f"  OK: Built NIF database with {len(freguesias):,} parishes")
            else:
                print(f"  ERROR: No parishes found in downloaded file")
        except ImportError:
            print(f"  ERROR: Cannot parse XLSX — is openpyxl installed?")
            print(f"    pip install openpyxl")
        except Exception as e:
            print(f"  ERROR: Parse failed: {e}")

    def _build_nif_name_index(self) -> dict:
        """Build a normalized parish name → NIF lookup index.

        Returns a dict mapping normalized parish names to their NIF database
        entries. This allows matching LocalExecucao strings that contain
        parish names (e.g., 'Freguesia de Alfama') to their municipality.
        """
        if not self._nif_db:
            return {}

        index = {}
        for nif, entry in self._nif_db.items():
            name = entry.get("name", "")
            if not name:
                continue
            norm = _normalize_name(name)
            if norm and len(norm) >= 3:
                # Store the best entry for this normalized name
                if norm not in index or len(name) > len(index[norm].get("name", "")):
                    index[norm] = {
                        "nif": nif,
                        "name": name,
                        "ine_code": entry.get("ine_code", ""),
                        "municipality": entry.get("municipality", ""),
                        "district": entry.get("district", ""),
                    }

        return index

    def resolve_parish_to_municipality(self, parish_name: str) -> dict | None:
        """Resolve a parish name to its municipality using the NIF database.

        Returns dict with 'nif', 'name', 'municipality', 'district', 'ine_code'
        or None if not found.
        """
        if not self._nif_by_name:
            return None

        norm = _normalize_name(parish_name)
        if not norm:
            return None

        # Direct match
        if norm in self._nif_by_name:
            return self._nif_by_name[norm]

        # Try fuzzy matching
        matches = get_close_matches(norm, list(self._nif_by_name.keys()), n=1, cutoff=0.7)
        if matches:
            return self._nif_by_name[matches[0]]

        return None

    def resolve_nif(self, nif: str) -> dict | None:
        """Resolve a NIF to parish information.

        Returns dict with parish details or None if not found.
        """
        if not self._nif_db:
            return None

        entry = self._nif_db.get(nif)
        if entry:
            return {
                "nif": nif,
                "name": entry.get("name", ""),
                "ine_code": entry.get("ine_code", ""),
                "municipality": entry.get("municipality", ""),
                "district": entry.get("district", ""),
            }

        return None

    def _expand_abbreviations(self, text: str) -> str:
        """Expand common Portuguese abbreviations in location strings.

        Handles patterns like:
          - "V.N. Gaia" → "Vila Nova Gaia" (→ Vila Nova de Gaia)
          - "V.F. Xavier" → "Vila Franca Xavier" (→ Vila Franca de Xira)
          - "S.J. Madeira" → "São João Madeira" (→ São João da Madeira)
        """
        text_lower = text.lower().strip()

        # Try matching abbreviation patterns: "XX. XX." or "XX. XX" at start
        # Pattern: two-letter abbreviation followed by dot, then space, then more text
        m = re.match(r'^([a-z]\.[a-z]\.?\s+)(.+)$', text_lower)
        if m:
            abbr = m.group(1).strip().rstrip('.')
            rest = m.group(2).strip()
            # Look up abbreviation (with and without trailing dot)
            full = ABBREVIATION_MAP.get(abbr, ABBREVIATION_MAP.get(abbr + '.', ''))
            if full:
                # Replace the abbreviation with its expansion
                expanded = full + text[len(m.group(1)):].lstrip()
                return expanded

        return text

    def _normalize(self, s: str) -> str:
        """Normalize a string for comparison."""
        return _normalize_name(s)

    def _try_resolve_name(self, name: str) -> str | None:
        """Try to resolve a name (possibly multi-word) to a 4-digit CAOP code.

        Tries the full name first, then progressively shorter substrings.
        Handles abbreviations, multi-word names like "Vila Nova de Gaia".
        """
        norm = _normalize_name(name)

        # Direct CAOP match
        if norm in self._caop_lookup:
            return self._caop_lookup[norm]

        # Try resolve_municipality (has substring matching)
        code4 = resolve_municipality(name)
        if code4:
            return code4

        # Fallback to municipality directory
        if norm in self.muni_map:
            return self.muni_map[norm]
        matches = get_close_matches(norm, list(self.muni_map.keys()), n=1, cutoff=0.7)
        if matches:
            return self.muni_map[matches[0]]

        # Try with abbreviation expansion
        expanded = self._expand_abbreviations(name)
        if expanded != name:
            norm_exp = _normalize_name(expanded)
            if norm_exp in self._caop_lookup:
                return self._caop_lookup[norm_exp]
            code4 = resolve_municipality(expanded)
            if code4:
                return code4

        return None

    def _clean_location_text(self, text: str) -> str:
        """Clean a location string: remove entity prefixes, suffixes, and junk.

        Handles patterns like:
          - "Município de Lisboa - Sede" → "Lisboa"
          - "Câmara Municipal do Porto" → "Porto"
          - "Freguesia de Alfama" → "Alfama"
          - "Junta de Freguesia de Benfica" → "Benfica"
          - "Escola Básica de Sintra" → "Sintra"
          - "Lugar de Aldeia Nova" → "Aldeia Nova"
          - "Zona Industrial de Sintra" → "Sintra"
        """
        text = text.strip()

        # Remove entity-type prefixes (longest first)
        entity_prefixes = [
            "união das freguesias de ", "união das freguesias do ",
            "união das freguesias da ",
            "junta de freguesia de ", "junta de freguesia do ",
            "junta de freguesia da ",
            "freguesia de ", "freguesia do ", "freguesia da ",
            "câmara municipal de ", "câmara municipal do ",
            "câmara municipal da ",
            "município de ", "município do ", "município da ",
            "empresa municipal de ", "empresa municipal do ",
            "serviços municipalizados de ",
            "fundação município de ",
            "conselho municipal de ",
            "centro hospitalar de ", "centro hospitalar do ",
            "hospital central de ", "hospital distrital de ",
            "unidade local de saúde de ", "unidade local de saúde do ",
            "hospital de ", "hospital do ", "hospital da ",
            "agrupamento de escolas de ", "agrupamento de escolas do ",
            "centro de saúde de ",
            "escola básica de ", "escola básica do ",
            "instituto politécnico de ", "universidade de ",
            "comissão de coordenação e desenvolvimento regional de ",
            "direção regional de ", "subdireção regional de ",
            "governo regional de ", "secretaria regional de ",
            "presidência do conselho de ", "assembleia municipal de ",
            "assembleia de freguesia de ", "assembleia de freguesia do ",
            "edifício ", "escritório ",
            "código postal ", "cód. postal ", "cód postal ",
            "centro de formação de ", "núcleo de ",
            "conselho de ",
        ]
        text_lower = text.lower()
        for prefix in entity_prefixes:
            if text_lower.startswith(prefix):
                text = text[len(prefix):]
                text_lower = text.lower()
                break

        # Remove rural/location-type prefixes: "Lugar de X", "Bairro de X", etc.
        for prefix in LOCATION_PREFIXES:
            if text_lower.startswith(prefix):
                text = text[len(prefix):]
                text_lower = text.lower()
                break

        # Remove "Concelho de X" / "Distrito de X" wrappers
        for wrapper in ["concelho de ", "concelho do ", "concelho da ",
                        "distrito de ", "distrito do ", "distrito da "]:
            if text_lower.startswith(wrapper):
                text = text[len(wrapper):]
                text_lower = text.lower()
                break

        # Remove trailing suffixes: " - Sede", " - Gabinete", " (Norte)", etc.
        text = re.sub(r'\s*[-–]\s*(Sede|Gabinete|Sul|Norte|Leste|Oeste|Central|Principal|Anexo|Escritório|Delegação|Secundário|Norte\s*/\s*Sul|Sul\s*/\s*Norte).*$', '', text, flags=re.IGNORECASE)
        # Remove parenthetical qualifiers: "(Sul)", "(Zona Urbana)", etc.
        text = re.sub(r'\s*\([^)]*(?:sul|norte|leste|oeste|zona|sede|gabinete)[^)]*\)\s*$', '', text, flags=re.IGNORECASE)
        # Remove any remaining trailing parenthetical
        text = re.sub(r'\s*\([^)]{1,30}\)\s*$', '', text)

        return text.strip()

    def _extract_parts(self, local_execucao: str) -> list[str]:
        """Extract location parts from LocalExecucao string.

        Handles common patterns:
          - "Portugal, Lisboa, Lisboa"
          - "Lisboa"
          - "Freguesia de X, Concelho de Y, Distrito de Z"
          - "Rua X, 123, 1234-567 Lisboa"
          - "1200-123 Lisboa"
          - "LISBOA"
          - "Município de Sintra"
        """
        if not local_execucao:
            return []

        # Split by comma, newline, or semicolon
        parts = re.split(r'[,;\n]', local_execucao)
        parts = [p.strip() for p in parts if p.strip()]

        # Remove "Portugal" if first element
        if parts and parts[0].lower() in ("portugal", "pt"):
            parts = parts[1:]

        # Remove postal code parts (e.g., "1234-567" or "1234 567 Lisboa" → keep "Lisboa")
        cleaned = []
        for p in parts:
            # Pure postal code: "1234-567" or "1234 567"
            if re.match(r'^\d{4}\s*-?\s*\d{3}$', p.strip()):
                continue
            # Postal code prefix: "1234-567 Lisboa" → extract "Lisboa"
            m = re.match(r'^\d{4}\s*-?\s*\d{3}\s+(.+)$', p.strip())
            if m:
                cleaned.append(m.group(1).strip())
                continue
            cleaned.append(p)
        parts = cleaned

        # Remove parts that look like street addresses or non-location identifiers
        street_words = ['rua', 'r.', 'r ', 'av.', 'av ', 'avenida', 'estrada',
                        'travessa', 'praça', 'largo', 'rotunda', 'ecrã', 'km',
                        'n.º', 'nº', 'n.°', 'beco', 'caminho', 'calçada',
                        'escadinhas', 'pátio', 'viela', 'canto', 'campo',
                        'pç.', 'pça', 'pc.', 'lrg.', 'av.', 'avda',
                        'r/alta', 'r/baixa', 'escadas', 'rampa',
                        'estrada municipal', 'via', 'autoestrada',
                        'ic19', 'ic20', 'a1', 'a2', 'a6', 'a22', 'a23',
                        'em', 'en ', 'ip', 'it ',]
        parts = [p for p in parts if not any(p.strip().lower().startswith(sw) for sw in street_words)]

        # Remove numeric-only parts (building numbers, floor numbers, etc.)
        parts = [p for p in parts if not re.match(r'^[\d\s/ºª.]+$', p.strip())]

        # Remove very short parts (1-2 chars) that are likely noise
        parts = [p for p in parts if len(p.strip()) > 2]

        # Clean each part: remove entity prefixes, Concelho/Distrito wrappers
        parts = [self._clean_location_text(p) for p in parts]
        parts = [p for p in parts if p]

        return parts

    def _resolve_district(self, name: str) -> str | None:
        """Resolve a district name to its 2-digit code."""
        norm = self._normalize(name)
        for dist_name, code in DISTRICT_CODES.items():
            if norm == dist_name or norm in dist_name or dist_name in norm:
                return code
        matches = get_close_matches(norm, list(DISTRICT_CODES.keys()), n=1, cutoff=0.6)
        if matches:
            return DISTRICT_CODES[matches[0]]
        return None

    def _resolve_municipality(self, name: str) -> str | None:
        """Resolve a municipality name to its 4-digit CAOP code (DDMM)."""
        return self._try_resolve_name(name)

    def resolve(self, local_execucao: str) -> dict:
        """Resolve a LocalExecucao string to an INE code and metadata.

        Strategy (priority order):
          1. Check cache
          2. Try full string as municipality (handles "Lisboa", "Fundão", "LISBOA")
          3. Try full string after entity prefix removal
          4. Split by comma and try combinations
          5. Fallback: try each part as municipality
        """
        result = {
            "ine_code": "",
            "district": "",
            "municipality": "",
            "freguesia": "",
            "confidence": "none",
            "raw": local_execucao,
        }

        if not local_execucao:
            return result

        # Check cache first
        cache_key = local_execucao.strip().lower()
        if cache_key in self.local_exec_map:
            cached = self.local_exec_map[cache_key]
            result.update(cached)
            result["confidence"] = "cached"
            return result

        # Strategy 1: Try the full string as a municipality name
        # This handles simple cases like "Fundão", "LISBOA", "Porto"
        cleaned_full = self._clean_location_text(local_execucao)
        if cleaned_full:
            muni_code = self._try_resolve_name(cleaned_full)
            if muni_code:
                result["municipality"] = cleaned_full
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "exact"
                dist_code = muni_code[:2]
                result["district"] = get_district_name(dist_code) or ""
                return result

            # Also try with abbreviation expansion on the cleaned text
            expanded = self._expand_abbreviations(cleaned_full)
            if expanded != cleaned_full:
                muni_code = self._try_resolve_name(expanded)
                if muni_code:
                    result["municipality"] = expanded
                    result["ine_code"] = muni_code + "00"
                    result["confidence"] = "exact"
                    dist_code = muni_code[:2]
                    result["district"] = get_district_name(dist_code) or ""
                    return result

        # Strategy 2: Try to match the full string against multi-word municipality names
        # by trying substrings of decreasing length (longest-first for greedy match)
        norm_full = _normalize_name(local_execucao)
        for muni_name in _SORTED_MUNI_NAMES:
            norm_muni = _normalize_name(muni_name)
            # Require ≥5 chars to avoid false positives on short names like "beja"
            if len(norm_muni) < 5:
                continue
            if norm_muni in norm_full or norm_full in norm_muni:
                code4 = self._caop_lookup.get(norm_muni)
                if not code4:
                    code4 = resolve_municipality(muni_name)
                if code4:
                    dist_code = code4[:2]
                    result["municipality"] = muni_name.title()
                    result["district"] = get_district_name(dist_code) or ""
                    result["ine_code"] = code4 + "00"
                    result["confidence"] = "fuzzy"
                    return result

        # Strategy 3: Split by comma and process parts
        parts = self._extract_parts(local_execucao)

        if len(parts) == 0:
            return result
        elif len(parts) == 1:
            # Single part — try as municipality or district
            muni_code = self._resolve_municipality(parts[0])
            if muni_code:
                dist_code = muni_code[:2]
                result["municipality"] = parts[0]
                result["district"] = get_district_name(dist_code) or ""
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "exact"
                return result

            dist_code = self._resolve_district(parts[0])
            if dist_code:
                result["district"] = parts[0]
                result["ine_code"] = dist_code + "0000"
                result["confidence"] = "partial"
                return result

        elif len(parts) == 2:
            # Try: District Municipality, Municipality Freguesia, etc.
            dist_code = self._resolve_district(parts[0])
            muni_code = self._resolve_municipality(parts[1])

            if muni_code:
                result["district"] = get_district_name(muni_code[:2]) or parts[0]
                result["municipality"] = parts[1]
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "exact"
                return result

            # Try reverse: Municipality, District
            muni_code = self._resolve_municipality(parts[0])
            if muni_code:
                result["municipality"] = parts[0]
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "exact"
                return result

            if dist_code:
                result["district"] = parts[0]
                result["municipality"] = parts[1]
                result["ine_code"] = dist_code + "0000"
                result["confidence"] = "partial"
                return result

        elif len(parts) >= 3:
            # District, Municipality, Freguesia (or more)
            # Try each consecutive pair as (district, municipality)
            for i in range(len(parts) - 1):
                dist_code = self._resolve_district(parts[i])
                muni_code = self._resolve_municipality(parts[i + 1])
                if muni_code:
                    result["district"] = get_district_name(muni_code[:2]) or parts[i]
                    result["municipality"] = parts[i + 1]
                    result["freguesia"] = parts[i + 2] if i + 2 < len(parts) else ""
                    result["ine_code"] = muni_code + "00"
                    result["confidence"] = "exact"
                    return result
                if dist_code:
                    # Try the next part as municipality
                    muni_code = self._resolve_municipality(parts[i + 1])
                    if muni_code:
                        result["district"] = parts[i]
                        result["municipality"] = parts[i + 1]
                        result["freguesia"] = parts[i + 2] if i + 2 < len(parts) else ""
                        result["ine_code"] = muni_code + "00"
                        result["confidence"] = "exact"
                        return result

            # If no district found, try any part as municipality
            for part in parts:
                muni_code = self._resolve_municipality(part)
                if muni_code:
                    dist_code = muni_code[:2]
                    result["municipality"] = part
                    result["district"] = get_district_name(dist_code) or ""
                    result["ine_code"] = muni_code + "00"
                    result["confidence"] = "fuzzy"
                    return result

        # Strategy 4: Fallback — try each part as municipality (reversed order)
        for part in reversed(parts):
            muni_code = self._resolve_municipality(part)
            if muni_code:
                dist_code = muni_code[:2]
                result["municipality"] = part
                result["district"] = get_district_name(dist_code) or ""
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "fuzzy"
                return result

        # Strategy 5: NIF database parish name lookup
        # Uses the official dados.gov.pt parish database to match parish names
        # found in LocalExecucao strings to their municipality
        for part in parts:
            parish_info = self.resolve_parish_to_municipality(part)
            if parish_info:
                muni = parish_info.get("municipality", "")
                if muni:
                    muni_code = self._try_resolve_name(muni)
                    if muni_code:
                        result["municipality"] = muni
                        result["freguesia"] = parish_info.get("name", "")
                        result["district"] = parish_info.get("district") or get_district_name(muni_code[:2]) or ""
                        result["ine_code"] = muni_code + "00"
                        result["parish_nif"] = parish_info.get("nif", "")
                        result["confidence"] = "nif_db"
                        return result

        # Strategy 6: Aggressive fallback — strip noise words and try again
        # Handles strings like "Edifício X, Rua Y, Z" or "Escritório, Bairro Z, Lisboa"
        aggressive_parts = []
        for part in parts:
            part_lower = part.lower().strip()
            # Remove noise words using word boundaries (not substring replace)
            for noise in NOISE_WORDS:
                part_lower = re.sub(r'\b' + re.escape(noise) + r'\b', '', part_lower)
            part_lower = re.sub(r'\b(de|do|da|dos|das|em|no|na|nos|nas)\b', '', part_lower)
            part_lower = re.sub(r'\s+', ' ', part_lower).strip()
            if part_lower and len(part_lower) > 2:
                aggressive_parts.append(part_lower)

        for part in reversed(aggressive_parts):
            muni_code = self._resolve_municipality(part)
            if muni_code:
                dist_code = muni_code[:2]
                result["municipality"] = part.title()
                result["district"] = get_district_name(dist_code) or ""
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "partial"
                return result

        return result

    def resolve_all(self, nif: str = None) -> dict:
        """Resolve all LocalExecucao values and return statistics."""
        if nif:
            rows = self.conn.execute(
                "SELECT DISTINCT LocalExecucao FROM contratos WHERE adjudicante_nif = ? AND LocalExecucao IS NOT NULL AND LocalExecucao != ''",
                (nif,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT DISTINCT LocalExecucao FROM contratos WHERE LocalExecucao IS NOT NULL AND LocalExecucao != ''"
            ).fetchall()

        results = {}
        confidence_counts = Counter()
        unresolved = []

        for r in rows:
            le = r["LocalExecucao"]
            if not le or le.strip() in ("", "Portugal", "PT"):
                continue
            resolved = self.resolve(le)
            results[le] = resolved
            confidence_counts[resolved["confidence"]] += 1
            if resolved["confidence"] == "none":
                unresolved.append(le)

        return {
            "total": len(results),
            "confidence": dict(confidence_counts),
            "unresolved": unresolved[:50],
            "results": results,
        }

    def get_stats(self) -> dict:
        """Get resolution statistics for all contracts."""
        total = self.conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
        with_le = self.conn.execute(
            "SELECT COUNT(*) FROM contratos WHERE LocalExecucao IS NOT NULL AND LocalExecucao != ''"
        ).fetchone()[0]

        result = self.resolve_all()

        resolved_munis = set()
        for v in result["results"].values():
            if v["ine_code"] and v["ine_code"] != "000000":
                resolved_munis.add(v["ine_code"][:4])

        return {
            "total_contracts": total,
            "with_localexecucao": with_le,
            "pct_with_localexecucao": with_le * 100 / total if total else 0,
            "unique_locations": result["total"],
            "confidence_breakdown": result["confidence"],
            "unresolved_count": len(result["unresolved"]),
            "resolved_municipalities": len(resolved_munis),
        }

    def export_mapping(self, output_path: str = None):
        """Export all resolved mappings to JSON."""
        result = self.resolve_all()
        output = output_path or str(MAPPING_PATH)

        mapping = {}
        for le, resolved in result["results"].items():
            mapping[le.lower().strip()] = {
                "ine_code": resolved["ine_code"],
                "district": resolved["district"],
                "municipality": resolved["municipality"],
                "freguesia": resolved["freguesia"],
                "confidence": resolved["confidence"],
            }

        with open(output, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

        print(f"Exported {len(mapping)} mappings to {output}")
        return mapping

    def update_contracts(self):
        """Update contratos table with resolved INE codes (adds columns if needed)."""
        try:
            self.conn.execute("ALTER TABLE contratos ADD COLUMN ine_district TEXT")
            self.conn.execute("ALTER TABLE contratos ADD COLUMN ine_municipality TEXT")
            self.conn.execute("ALTER TABLE contratos ADD COLUMN ine_freguesia TEXT")
            self.conn.execute("ALTER TABLE contratos ADD COLUMN ine_code TEXT")
        except sqlite3.OperationalError:
            pass  # Columns already exist

        rows = self.conn.execute(
            "SELECT idcontrato, LocalExecucao FROM contratos WHERE LocalExecucao IS NOT NULL AND LocalExecucao != ''"
        ).fetchall()

        updated = 0
        for r in rows:
            resolved = self.resolve(r["LocalExecucao"])
            if resolved["ine_code"]:
                self.conn.execute("""
                    UPDATE contratos SET ine_district=?, ine_municipality=?,
                    ine_freguesia=?, ine_code=? WHERE idcontrato=?
                """, (
                    resolved["district"],
                    resolved["municipality"],
                    resolved["freguesia"],
                    resolved["ine_code"],
                    r["idcontrato"],
                ))
                updated += 1

        self.conn.commit()
        print(f"Updated {updated:,} / {len(rows):,} contracts with INE codes")
        return updated

    def close(self):
        self.conn.close()


def cmd_resolve(args):
    """Resolve all LocalExecucao values."""
    resolver = FreguesiaResolver()
    result = resolver.resolve_all(nif=args.nif)

    print(f"\n{'='*70}")
    print(f"  FREGUESIA RESOLUTION RESULTS")
    print(f"{'='*70}")
    print(f"  Total unique locations: {result['total']}")
    print(f"\n  Confidence breakdown:")
    for conf, count in sorted(result["confidence"].items()):
        pct = count * 100 / result["total"] if result["total"] else 0
        print(f"    {conf:<12} {count:>6,} ({pct:.1f}%)")

    if result["unresolved"]:
        print(f"\n  Unresolved locations ({len(result['unresolved'])}):")
        for loc in result["unresolved"][:20]:
            print(f"    - {loc[:80]}")

    if args.json:
        print(json.dumps(result["results"], ensure_ascii=False, indent=2))

    resolver.close()


def cmd_stats(args):
    """Show resolution statistics."""
    resolver = FreguesiaResolver()
    stats = resolver.get_stats()

    print(f"\n{'='*70}")
    print(f"  FREGUESIA RESOLVER -- STATISTICS")
    print(f"{'='*70}")
    print(f"  Total contracts:          {stats['total_contracts']:>10,}")
    print(f"  With LocalExecucao:       {stats['with_localexecucao']:>10,} ({stats['pct_with_localexecucao']:.1f}%)")
    print(f"  Unique locations:         {stats['unique_locations']:>10,}")
    print(f"  Resolved municipalities:  {stats['resolved_municipalities']:>10,}")
    print(f"  Unresolved:               {stats['unresolved_count']:>10,}")
    print(f"\n  Confidence breakdown:")
    for conf, count in sorted(stats["confidence_breakdown"].items()):
        print(f"    {conf:<12} {count:>6,}")
    print(f"{'='*70}\n")

    resolver.close()


def cmd_unmapped(args):
    """Show unresolved LocalExecucao strings."""
    resolver = FreguesiaResolver()
    result = resolver.resolve_all()

    unmapped = [(le, r) for le, r in result["results"].items()
                if r["confidence"] == "none"]

    print(f"\n{'='*70}")
    print(f"  UNRESOLVED LOCALEXECUCAO STRINGS ({len(unmapped)})")
    print(f"{'='*70}")

    for le, r in sorted(unmapped, key=lambda x: x[0])[:50]:
        print(f"  - {le[:80]}")

    if len(unmapped) > 50:
        print(f"  ... and {len(unmapped) - 50} more")

    print(f"{'='*70}\n")
    resolver.close()


def cmd_export(args):
    """Export mapping to JSON."""
    resolver = FreguesiaResolver()
    resolver.export_mapping(args.output)
    resolver.close()


def cmd_nif(args):
    """Look up a parish by NIF or name."""
    resolver = FreguesiaResolver()
    query = args.query

    # Try as NIF first (9 digits)
    if query.isdigit() and len(query) == 9:
        result = resolver.resolve_nif(query)
        if result:
            print(f"\n  NIF: {result['nif']}")
            print(f"  Parish: {result['name']}")
            print(f"  Municipality: {result['municipality']}")
            print(f"  District: {result['district']}")
            print(f"  INE Code: {result['ine_code']}")
        else:
            print(f"  No parish found with NIF {query}")
    else:
        # Search by parish name
        result = resolver.resolve_parish_to_municipality(query)
        if result:
            print(f"\n  Matched parish: {result['name']}")
            print(f"  NIF: {result['nif']}")
            print(f"  Municipality: {result['municipality']}")
            print(f"  District: {result['district']}")
            print(f"  INE Code: {result['ine_code']}")
        else:
            print(f"  No parish found matching '{query}'")

    resolver.close()


def cmd_update(args):
    """Update contracts table with INE codes."""
    resolver = FreguesiaResolver()
    resolver.update_contracts()
    resolver.close()


def main():
    parser = argparse.ArgumentParser(
        description="Resolve LocalExecucao strings to INE freguesia codes",
    )
    sub = parser.add_subparsers(dest="command")

    resolve = sub.add_parser("resolve", help="Resolve all locations")
    resolve.add_argument("--nif", help="Filter by entity NIF")
    resolve.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("stats", help="Show resolution statistics")
    sub.add_parser("unmapped", help="Show unresolved strings")

    export = sub.add_parser("export", help="Export mapping to JSON")
    export.add_argument("--output", "-o", help="Output file path")

    sub.add_parser("update", help="Update contratos table with INE codes")

    nif_cmd = sub.add_parser("nif", help="Look up parish by NIF or name")
    nif_cmd.add_argument("query", help="NIF number or parish name to search")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "resolve": cmd_resolve,
        "stats": cmd_stats,
        "unmapped": cmd_unmapped,
        "export": cmd_export,
        "update": cmd_update,
        "nif": cmd_nif,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
