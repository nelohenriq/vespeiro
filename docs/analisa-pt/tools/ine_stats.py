#!/usr/bin/env python3
"""INE Statistics Client — Download and analyze Portuguese social indicators.

Fetches indicators from INE (Instituto Nacional de Estatística) via their
public JSON API, stores in SQLite, and provides category-specific analysis.

Supported categories:
    - Pension: pensioners, pension amounts, retirement types
    - Crime: crime rates, offences by type, domestic violence
    - Immigration: foreign residents, nationality breakdowns

Usage:
    python ine_stats.py download                        # Download all indicators
    python ine_stats.py download --category pension     # Download pension only
    python ine_stats.py download --category crime       # Download crime only
    python ine_stats.py download --year 2023            # Download specific year
    python ine_stats.py index                           # Parse into SQLite
    python ine_stats.py status                          # Quick status
    python ine_stats.py stats                           # Summary statistics
    python ine_stats.py pension                         # Pension analysis
    python ine_stats.py crime                           # Crime analysis
    python ine_stats.py immigration                     # Immigration analysis
    python ine_stats.py compare                         # Cross-ref with procurement
    python ine_stats.py query "SELECT ..."              # Run SQL
    python ine_stats.py export --out X                  # Export JSON
"""

import sys
import json
import sqlite3
import argparse
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    import urllib.request
    import ssl
except ImportError:
    print("ERROR: urllib required (built-in)")
    sys.exit(1)

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "ine_stats.db"
RAW_DIR = DATA_DIR / "ine_raw"

# SSL context
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,*/*",
}

# ---------------------------------------------------------------------------
# INE API Configuration — indicator catalog by category
# ---------------------------------------------------------------------------
INDICATORS = {
    # === PENSION ===
    "0004325": {
        "name": "Pensionistas da Segurança Social",
        "description": "Social Security pensioners at 31 Dec, by type",
        "category": "pension",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
    "0004347": {
        "name": "Valor médio das pensões SS",
        "description": "Average value of Social Security pensions, by type",
        "category": "pension",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
    "0006712": {
        "name": "Pensionistas com reforma antecipada",
        "description": "Social Security pensioners with early retirement",
        "category": "pension",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
    "0008263": {
        "name": "Pensionistas da CGA",
        "description": "CGA (public sector) pensioners by type",
        "category": "pension",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },

    # === CRIME ===
    "0008074": {
        "name": "Taxa de criminalidade",
        "description": "Crime rate by NUTS 2013 and crime category",
        "category": "crime",
        "dimensions": ["Período", "NUTS 2013", "Tipo de crime"],
    },

    # === IMMIGRATION ===
    "0001236": {
        "name": "População estrangeira residente",
        "description": "Foreign resident population by country of citizenship",
        "category": "immigration",
        "dimensions": ["Período", "País de cidadania"],
    },
}

INE_API_BASE = "https://www.ine.pt/ine/json_indicador/pindica.jsp"


def _dim1_year(year: int) -> str:
    """INE time dimension code for a specific year."""
    return f"S7A{year}"


def get_indicators(category: str = None) -> dict:
    """Return indicators filtered by category."""
    if category:
        return {k: v for k, v in INDICATORS.items() if v.get("category") == category}
    return dict(INDICATORS)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(force: bool = False) -> sqlite3.Connection:
    """Initialize the INE statistics database."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if force and DB_PATH.exists():
        DB_PATH.unlink()
        print("  Deleted existing database.")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Main observations table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ine_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator_code TEXT NOT NULL,
            indicator_name TEXT,
            category TEXT,
            period TEXT,
            year INTEGER,
            geographic_level TEXT,
            geographic_code TEXT,
            geographic_name TEXT,
            dimension_3 TEXT,
            value REAL,
            unit TEXT,
            UNIQUE(indicator_code, period, geographic_code, dimension_3)
        )
    """)

    # Indicator metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            code TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            category TEXT,
            source TEXT,
            first_period TEXT,
            last_period TEXT,
            last_updated TEXT,
            dimensions TEXT,
            downloaded_at TEXT,
            row_count INTEGER DEFAULT 0
        )
    """)

    # Metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)

    # Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_io_code ON ine_observations(indicator_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_io_year ON ine_observations(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_io_geo ON ine_observations(geographic_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_io_cat ON ine_observations(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_io_dim3 ON ine_observations(dimension_3)")

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# INE API Client
# ---------------------------------------------------------------------------

def ine_api_fetch(varcd: str, dim1: str = "T", extra_dims: dict = None) -> dict:
    """Fetch an indicator from the INE JSON API.

    Raises RuntimeError on HTTP errors or API-level failures.
    """
    params = f"op=2&varcd={varcd}&Dim1={dim1}&lang=PT"
    if extra_dims:
        for key, val in extra_dims.items():
            params += f"&{key}={val}"

    url = f"{INE_API_BASE}?{params}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=30, context=SSL_CTX)
        data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"INE API HTTP {e.code} for varcd={varcd}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"INE API connection error for varcd={varcd}: {e.reason}")
    except json.JSONDecodeError:
        raise RuntimeError(f"INE API returned invalid JSON for varcd={varcd}")

    if isinstance(data, list) and data:
        item = data[0]
        msg = item.get("Msg", "")
        if msg and "no válido" in msg.lower():
            raise RuntimeError(f"INE API error for varcd={varcd}: {msg}")
        return item
    return {}


def parse_indicator_response(resp: dict, category: str = "") -> list[dict]:
    """Parse INE API response into flat row dicts."""
    code = resp.get("IndicadorCod", "")
    name = resp.get("IndicadorDsg", "")
    dados = resp.get("Dados", {})

    rows = []
    for period_key, period_data in dados.items():
        year_match = period_key.replace("S7A", "") if "S7A" in period_key else period_key
        try:
            year = int(year_match)
        except ValueError:
            year = 0

        if isinstance(period_data, dict):
            for entry_key, entry_val in period_data.items():
                row = _parse_entry(code, name, category, period_key, year, entry_key, entry_val)
                if row:
                    rows.append(row)
        elif isinstance(period_data, list):
            for entry in period_data:
                if isinstance(entry, dict):
                    row = _parse_dict_entry(code, name, category, period_key, year, entry)
                    if row:
                        rows.append(row)

    return rows


def _parse_entry(code, name, category, period, year, entry_key, entry_val):
    """Parse a single nested dict entry. Returns row dict or None."""
    if isinstance(entry_val, dict):
        value = None
        geo_code = ""
        geo_name = ""
        dim3 = ""
        unit = ""

        for k, v in entry_val.items():
            if k == "valor":
                try:
                    value = float(v)
                except (ValueError, TypeError):
                    value = None
            elif k == "geoCod":
                geo_code = str(v)
            elif k == "geoDsg":
                geo_name = str(v)
            elif k.startswith("dim_3") or k == "dim_3_t":
                dim3 = str(v)
            elif k == "unidade":
                unit = str(v)

        if value is None and not geo_code:
            return None

        if not geo_name:
            geo_name = str(entry_key)

        return {
            "indicator_code": code,
            "indicator_name": name,
            "category": category,
            "period": period,
            "year": year,
            "geographic_level": _classify_geo(geo_code),
            "geographic_code": geo_code,
            "geographic_name": geo_name,
            "dimension_3": dim3,
            "value": value,
            "unit": unit,
        }

    elif isinstance(entry_val, (int, float)):
        return {
            "indicator_code": code,
            "indicator_name": name,
            "category": category,
            "period": period,
            "year": year,
            "geographic_level": "national",
            "geographic_code": "PT",
            "geographic_name": str(entry_key),
            "dimension_3": "",
            "value": float(entry_val),
            "unit": "",
        }

    return None


def _parse_dict_entry(code, name, category, period, year, entry):
    """Parse a dict entry from a list-type response."""
    value = entry.get("valor")
    try:
        value = float(value) if value is not None else None
    except (ValueError, TypeError):
        value = None

    return {
        "indicator_code": code,
        "indicator_name": name,
        "category": category,
        "period": period,
        "year": year,
        "geographic_level": _classify_geo(str(entry.get("geoCod", ""))),
        "geographic_code": str(entry.get("geoCod", "")),
        "geographic_name": str(entry.get("geoDsg", "")),
        "dimension_3": str(entry.get("dim_3_t", entry.get("dim_3", ""))),
        "value": value,
        "unit": str(entry.get("unidade", "")),
    }


def _classify_geo(geo_code: str) -> str:
    """Classify geographic code into a level."""
    if not geo_code or geo_code in ("PT", ""):
        return "national"
    code = str(geo_code).strip()
    if len(code) <= 2:
        return "nuts2"
    elif len(code) <= 4:
        return "district"
    elif len(code) <= 7:
        return "municipality"
    else:
        return "parish"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_download(args):
    """Download indicators from INE API."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    target_year = getattr(args, "year", None)
    target_category = getattr(args, "category", None)
    target_indicators = getattr(args, "indicator", None)

    indicators = get_indicators(target_category)
    if target_indicators:
        indicators = {k: v for k, v in indicators.items() if k in target_indicators}

    print(f"\n  Downloading INE indicators...")
    print(f"  Category: {target_category or 'all'}")
    print(f"  Indicators: {len(indicators)}")

    total_downloaded = 0
    total_size = 0

    for varcd, info in indicators.items():
        cat = info.get("category", "")
        print(f"\n  [{varcd}] {info['name']} ({cat})")

        if target_year:
            periods = [_dim1_year(target_year)]
        else:
            periods = ["T"]

        for dim1 in periods:
            label = dim1 if dim1 != "T" else "all-periods"
            local_path = RAW_DIR / f"ine_{varcd}_{label}.json"

            if local_path.exists() and local_path.stat().st_size > 100:
                size = local_path.stat().st_size
                print(f"    {label}: already exists ({size:,} bytes)")
                continue

            print(f"    {label}: fetching...", end=" ", flush=True)
            try:
                resp = ine_api_fetch(varcd, dim1=dim1)
                data = json.dumps(resp, ensure_ascii=False)
                local_path.write_text(data, encoding="utf-8")
                size = len(data.encode("utf-8"))
                total_downloaded += 1
                total_size += size
                print(f"done ({size:,} bytes)")
            except Exception as e:
                print(f"FAILED: {e}")
                continue

            time.sleep(0.5)

    print(f"\n  Total: {total_downloaded} files, {total_size:,} bytes")
    if total_downloaded > 0:
        print(f"  Run 'python ine_stats.py index' to build the database")
    print()


def cmd_index(args):
    """Parse downloaded JSON files into SQLite."""
    conn = init_db(force=getattr(args, "force", False))

    if getattr(args, "force", False):
        conn.execute("DELETE FROM ine_observations")
        conn.execute("DELETE FROM indicators")
        conn.commit()
        print("  Cleared existing data.\n")

    total_rows = 0

    for json_file in sorted(RAW_DIR.glob("ine_*.json")):
        print(f"  {json_file.name}: parsing...", end=" ", flush=True)
        try:
            resp = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        # Determine category from indicator code
        code = resp.get("IndicadorCod", "")
        cat = INDICATORS.get(code, {}).get("category", "")

        rows = parse_indicator_response(resp, category=cat)
        if not rows:
            print("0 rows")
            continue

        changes_before = conn.total_changes
        for row in rows:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO ine_observations
                    (indicator_code, indicator_name, category, period, year,
                     geographic_level, geographic_code, geographic_name,
                     dimension_3, value, unit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["indicator_code"], row["indicator_name"], row["category"],
                    row["period"], row["year"], row["geographic_level"],
                    row["geographic_code"], row["geographic_name"],
                    row["dimension_3"], row["value"], row["unit"],
                ))
            except sqlite3.Error as e:
                print(f"DB error: {e}")
                break

        new_count = conn.total_changes - changes_before
        total_rows += new_count
        print(f"{len(rows):,} rows ({new_count:,} new)")
        conn.commit()

        # Update indicator metadata
        if code:
            dados = resp.get("Dados", {})
            years = sorted(dados.keys()) if dados else []
            conn.execute("""
                INSERT OR REPLACE INTO indicators
                (code, name, description, category, source, first_period,
                 last_period, last_updated, dimensions, downloaded_at, row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code,
                resp.get("IndicadorDsg", ""),
                INDICATORS.get(code, {}).get("description", ""),
                cat,
                "INE",
                years[0] if years else "",
                years[-1] if years else "",
                resp.get("DataUltimoAtualizacao", ""),
                json.dumps(INDICATORS.get(code, {}).get("dimensions", [])),
                datetime.now(timezone.utc).isoformat(),
                new_count,
            ))
            conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM ine_observations").fetchone()[0]
    n_ind = conn.execute("SELECT COUNT(DISTINCT indicator_code) FROM ine_observations").fetchone()[0]
    n_yr = conn.execute("SELECT COUNT(DISTINCT year) FROM ine_observations WHERE year > 0").fetchone()[0]
    n_geo = conn.execute("SELECT COUNT(DISTINCT geographic_code) FROM ine_observations").fetchone()[0]

    print(f"\n  Index totals:")
    print(f"    observations:   {count:,}")
    print(f"    indicators:     {n_ind}")
    print(f"    years:          {n_yr}")
    print(f"    geographies:    {n_geo}")
    print(f"    New rows:       {total_rows:,}")

    conn.close()


def cmd_status(args):
    """Quick one-glance status overview."""
    if not DB_PATH.exists():
        print(f"  ine_stats.db: NOT FOUND")
        print(f"  Run 'python ine_stats.py download' then 'index'")
        return

    db_size = DB_PATH.stat().st_size / (1024 * 1024)
    mtime = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
    age_days = (datetime.now() - mtime).days

    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM ine_observations").fetchone()[0]
    indicators = conn.execute("SELECT COUNT(DISTINCT indicator_code) FROM ine_observations").fetchone()[0]
    years = conn.execute("SELECT MIN(year), MAX(year) FROM ine_observations WHERE year > 0").fetchone()
    geos = conn.execute("SELECT COUNT(DISTINCT geographic_code) FROM ine_observations").fetchone()[0]

    # Per-category breakdown
    cats = conn.execute(
        "SELECT category, COUNT(*), COUNT(DISTINCT indicator_code) FROM ine_observations GROUP BY category"
    ).fetchall()
    conn.close()

    yr_range = f"{years[0]}-{years[1]}" if years and years[0] else "empty"
    print(f"  ine_stats.db  {db_size:.1f} MB  ({age_days}d old)")
    print(f"    observations:   {total:>10,}  ({yr_range})")
    print(f"    indicators:     {indicators:>10}")
    print(f"    geographies:    {geos:>10}")
    for cat, count, n_ind in cats:
        label = cat or "(uncategorized)"
        print(f"      {label:<20} {count:>8,} rows  ({n_ind} indicators)")
    print()


def cmd_stats(args):
    """Show summary statistics."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = sqlite3.connect(str(DB_PATH))

    print(f"\n{'='*70}")
    print(f"  INE Statistics — Overview")
    print(f"{'='*70}")

    # By category
    print(f"\n  By Category:")
    for cat, count, n_ind, yr_min, yr_max in conn.execute("""
        SELECT category, COUNT(*), COUNT(DISTINCT indicator_code),
               MIN(year), MAX(year)
        FROM ine_observations WHERE year > 0
        GROUP BY category ORDER BY COUNT(*) DESC
    """).fetchall():
        label = cat or "(uncategorized)"
        print(f"    {label:<20} {count:>8,} rows  ({n_ind} indicators, {yr_min}-{yr_max})")

    # By indicator
    print(f"\n  By Indicator:")
    for code, name, cat, count, yr_min, yr_max in conn.execute("""
        SELECT indicator_code, indicator_name, category, COUNT(*),
               MIN(year), MAX(year)
        FROM ine_observations WHERE year > 0
        GROUP BY indicator_code ORDER BY category, COUNT(*) DESC
    """).fetchall():
        print(f"    [{code}] {name[:45]} ({cat})")
        print(f"      {count:,} rows, {yr_min}-{yr_max}")

    # By geographic level
    print(f"\n  By Geographic Level:")
    for level, count, geos in conn.execute("""
        SELECT geographic_level, COUNT(*), COUNT(DISTINCT geographic_code)
        FROM ine_observations GROUP BY geographic_level ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"    {level:<20} {count:>8,} rows  ({geos:,} geographies)")

    # Latest values per category (national)
    for cat in ["pension", "crime", "immigration"]:
        cat_rows = conn.execute("""
            SELECT p.indicator_code, p.indicator_name, p.year, p.dimension_3, p.value
            FROM ine_observations p
            INNER JOIN (
                SELECT indicator_code, dimension_3, MAX(year) as max_year
                FROM ine_observations WHERE geographic_level = 'national'
                    AND value IS NOT NULL AND category = ?
                GROUP BY indicator_code, dimension_3
            ) latest ON p.indicator_code = latest.indicator_code
                AND p.dimension_3 = latest.dimension_3
                AND p.year = latest.max_year
            WHERE p.geographic_level = 'national' AND p.value IS NOT NULL
                AND p.category = ?
            ORDER BY p.indicator_code, p.dimension_3
        """, (cat, cat)).fetchall()

        if cat_rows:
            print(f"\n  Latest National ({cat}):")
            for code, name, year, dim3, value in cat_rows:
                val_str = f"{value:,.0f}" if value else "N/A"
                print(f"    [{code}] {dim3 or 'Total':<25} {year}: {val_str}")

    print(f"\n{'='*70}\n")
    conn.close()


def cmd_pension(args):
    """Pension-specific analysis."""
    _cmd_category_analysis(args, "pension", "PENSION")


def cmd_crime(args):
    """Crime-specific analysis."""
    _cmd_category_analysis(args, "crime", "CRIME")


def cmd_immigration(args):
    """Immigration-specific analysis."""
    _cmd_category_analysis(args, "immigration", "IMMIGRATION")


def _cmd_category_analysis(args, category, label):
    """Generic category analysis command."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    top_n = getattr(args, "top", 10)

    print(f"\n{'='*70}")
    print(f"  {label} — INE Data Analysis")
    print(f"{'='*70}")

    # Overview
    total = conn.execute(
        "SELECT COUNT(*) FROM ine_observations WHERE category = ?", (category,)
    ).fetchone()[0]
    indicators = conn.execute(
        "SELECT COUNT(DISTINCT indicator_code) FROM ine_observations WHERE category = ?",
        (category,),
    ).fetchone()[0]
    years = conn.execute(
        "SELECT MIN(year), MAX(year) FROM ine_observations WHERE category = ? AND year > 0",
        (category,),
    ).fetchone()

    if total == 0:
        print(f"\n  No {label.lower()} data found. Run 'python ine_stats.py download --category {category}' first.")
        conn.close()
        return

    yr_range = f"{years[0]}-{years[1]}" if years and years[0] else "N/A"
    print(f"\n  Observations: {total:,}  |  Indicators: {indicators}  |  Years: {yr_range}")

    # Latest national values
    print(f"\n  Latest National Values:")
    for code, name, year, dim3, value in conn.execute("""
        SELECT p.indicator_code, p.indicator_name, p.year, p.dimension_3, p.value
        FROM ine_observations p
        INNER JOIN (
            SELECT indicator_code, dimension_3, MAX(year) as max_year
            FROM ine_observations WHERE geographic_level = 'national'
                AND value IS NOT NULL AND category = ?
            GROUP BY indicator_code, dimension_3
        ) latest ON p.indicator_code = latest.indicator_code
            AND p.dimension_3 = latest.dimension_3
            AND p.year = latest.max_year
        WHERE p.geographic_level = 'national' AND p.value IS NOT NULL
            AND p.category = ?
        ORDER BY p.indicator_code, p.dimension_3
    """, (category, category)).fetchall():
        val_str = f"{value:,.0f}" if value else "N/A"
        print(f"    [{code}] {dim3 or 'Total':<25} {year}: {val_str}")

    # Trend (last 5 years, national, total)
    print(f"\n  Trend (national, last 5 years):")
    for code, name in conn.execute("""
        SELECT DISTINCT indicator_code, indicator_name
        FROM ine_observations WHERE category = ? AND geographic_level = 'national'
        ORDER BY indicator_code
    """, (category,)).fetchall():
        trend = conn.execute("""
            SELECT year, dimension_3, value FROM ine_observations
            WHERE indicator_code = ? AND geographic_level = 'national'
                AND value IS NOT NULL AND dimension_3 = ''
            ORDER BY year DESC LIMIT 5
        """, (code,)).fetchall()
        if trend:
            print(f"    [{code}] {name[:50]}")
            for year, _, value in reversed(trend):
                print(f"      {year}: {value:,.0f}")

    # Geographic breakdown (if available)
    print(f"\n  Geographic Breakdown (latest year, top {top_n}):")
    for code, name in conn.execute("""
        SELECT DISTINCT indicator_code, indicator_name
        FROM ine_observations WHERE category = ? AND geographic_level != 'national'
        ORDER BY indicator_code
    """, (category,)).fetchall():
        geo_data = conn.execute("""
            SELECT geographic_name, year, value FROM ine_observations
            WHERE indicator_code = ? AND geographic_level != 'national'
                AND value IS NOT NULL
                AND year = (SELECT MAX(year) FROM ine_observations
                            WHERE indicator_code = ? AND value IS NOT NULL)
            ORDER BY value DESC LIMIT ?
        """, (code, code, top_n)).fetchall()
        if geo_data:
            print(f"    [{code}] {name[:50]}")
            for geo_name, year, value in geo_data:
                print(f"      {geo_name[:35]:<35} {year}: {value:,.0f}")

    print(f"\n{'='*70}")
    conn.close()


def cmd_compare(args):
    """Cross-reference INE data with procurement patterns."""
    if not DB_PATH.exists():
        print("  ine_stats.db not found. Run 'download' then 'index' first.")
        return

    procurement_db = SCRIPT_DIR / "data" / "procurement.db"
    conn = sqlite3.connect(str(DB_PATH))
    has_procurement = procurement_db.exists()
    proc_conn = None
    if has_procurement:
        proc_conn = sqlite3.connect(str(procurement_db))

    print(f"\n{'='*70}")
    print(f"  INE Statistics × Procurement Cross-Reference")
    print(f"{'='*70}")

    # Show latest national values per category
    for cat in ["pension", "crime", "immigration"]:
        rows = conn.execute("""
            SELECT indicator_code, dimension_3, year, value
            FROM ine_observations
            WHERE category = ? AND geographic_level = 'national' AND value IS NOT NULL
            AND year = (SELECT MAX(year) FROM ine_observations
                        WHERE indicator_code = ine_observations.indicator_code)
            ORDER BY indicator_code, dimension_3
        """, (cat,)).fetchall()
        if rows:
            print(f"\n  {cat.upper()}:")
            for code, dim3, year, value in rows:
                print(f"    [{code}] {dim3 or 'Total':<25} {year}: {value:,.0f}")

    # Procurement overview
    if proc_conn:
        print(f"\n  Procurement:")
        try:
            total = proc_conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
            val = proc_conn.execute(
                "SELECT SUM(precoContratual) FROM contratos WHERE precoContratual > 0"
            ).fetchone()[0] or 0
            print(f"    Contracts: {total:,}  |  Value: €{val:,.0f}")
        except Exception as e:
            print(f"    Error: {e}")
        proc_conn.close()
    else:
        print(f"\n  procurement.db not found — procurement data skipped.")

    print(f"\n{'='*70}")
    conn.close()


def cmd_query(args):
    """Run arbitrary SQL query."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(args.sql).fetchall()
        if rows:
            headers = rows[0].keys()
            widths = [max(len(str(h)), max(len(str(r[h])) for r in rows[:50])) for h in headers]
            header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
            print(header_line)
            print("-" * len(header_line))
            for row in rows[:100]:
                print(" | ".join(f"{str(row[h]):<{w}}" for h, w in zip(headers, widths)))
            if len(rows) > 100:
                print(f"... ({len(rows) - 100} more rows)")
        else:
            print("  (no results)")
    except Exception as e:
        print(f"  SQL Error: {e}")

    conn.close()


def cmd_export(args):
    """Export all data to JSON."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = sqlite3.connect(str(DB_PATH))

    data = {}
    rows = conn.execute("""
        SELECT indicator_code, indicator_name, category, year, geographic_level,
               geographic_code, geographic_name, dimension_3, value, unit
        FROM ine_observations ORDER BY category, indicator_code, year, geographic_code
    """).fetchall()

    for code, name, cat, year, geo_level, geo_code, geo_name, dim3, value, unit in rows:
        if code not in data:
            data[code] = {"name": name, "category": cat, "observations": []}
        data[code]["observations"].append({
            "year": year,
            "geographic_level": geo_level,
            "geographic_code": geo_code,
            "geographic_name": geo_name,
            "dimension_3": dim3,
            "value": value,
            "unit": unit,
        })

    out_path = Path(args.out) if args.out else DATA_DIR / "ine_stats_export.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"  Exported {len(rows):,} observations across {len(data)} indicators")
    print(f"  To: {out_path}")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="INE Statistics Client — Portuguese social indicators via INE API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command")

    # Download
    dl = sub.add_parser("download", help="Download indicators from INE")
    dl.add_argument("--year", type=int, help="Specific year to download")
    dl.add_argument("--category", choices=["pension", "crime", "immigration"],
                    help="Download only this category")
    dl.add_argument("--indicator", nargs="+", help="Specific indicator code(s)")

    # Index
    idx = sub.add_parser("index", help="Parse downloaded JSON into SQLite")
    idx.add_argument("--force", action="store_true", help="Re-index from scratch")

    # Status
    sub.add_parser("status", help="Quick one-glance status overview")

    # Stats
    sub.add_parser("stats", help="Summary statistics")

    # Category analysis
    pen = sub.add_parser("pension", help="Pension analysis")
    pen.add_argument("--top", type=int, default=10)

    crm = sub.add_parser("crime", help="Crime analysis")
    crm.add_argument("--top", type=int, default=10)

    imm = sub.add_parser("immigration", help="Immigration analysis")
    imm.add_argument("--top", type=int, default=10)

    # Compare
    sub.add_parser("compare", help="Cross-reference with procurement data")

    # Query
    qr = sub.add_parser("query", help="Run arbitrary SQL")
    qr.add_argument("sql", help="SQL query to execute")

    # Export
    exp = sub.add_parser("export", help="Export to JSON")
    exp.add_argument("--out", help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "download": cmd_download,
        "index": cmd_index,
        "status": cmd_status,
        "stats": cmd_stats,
        "pension": cmd_pension,
        "crime": cmd_crime,
        "immigration": cmd_immigration,
        "compare": cmd_compare,
        "query": cmd_query,
        "export": cmd_export,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
