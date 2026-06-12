#!/usr/bin/env python3
"""INE Pension Data Client — Download and analyze Portuguese pension statistics.

Fetches pension indicators from INE (Instituto Nacional de Estatística) via
their public JSON API, stores in SQLite, and provides analysis commands.

Sources:
    - INE JSON API: https://www.ine.pt/ine/json_indicador/pindica.jsp
    - Metadata: https://www.ine.pt/bddXplorer/htdocs/minfo.jsp

Usage:
    python pension_ine.py download              # Download all pension indicators
    python pension_ine.py download --year 2023  # Download specific year
    python pension_ine.py index                # Parse downloaded data into SQLite
    python pension_ine.py status               # Quick status overview
    python pension_ine.py stats                # Summary statistics
    python pension_ine.py query "SELECT ..."   # Run arbitrary SQL
    python pension_ine.py export --out X       # Export to JSON
    python pension_ine.py compare              # Cross-reference with procurement data
"""

import sys
import json
import sqlite3
import argparse
import time
from pathlib import Path
from datetime import datetime, timezone
from utils_db import connect as db_connect

try:
    import urllib.request
    import ssl
except ImportError:
    print("ERROR: urllib required (built-in)")
    sys.exit(1)

# Paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DB_PATH = DATA_DIR / "pension_ine.db"
RAW_DIR = DATA_DIR / "ine_pension"

# SSL context
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,*/*",
}

# ---------------------------------------------------------------------------
# INE API Configuration
# ---------------------------------------------------------------------------
# Pension indicator codes (varcd) confirmed working via research
PENSION_INDICATORS = {
    "0004325": {
        "name": "Pensionistas da Segurança Social",
        "description": "Social Security pensioners at 31 Dec, by type",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
    "0004347": {
        "name": "Valor médio das pensões SS",
        "description": "Average value of Social Security pensions, by type",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
    "0006712": {
        "name": "Pensionistas com reforma antecipada",
        "description": "Social Security pensioners with early retirement",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
    # CGA indicators (Caixa Geral de Aposentações) — public sector pensions
    "0008263": {
        "name": "Pensionistas da CGA",
        "description": "CGA pensioners by type",
        "dimensions": ["Período", "Local de residência", "Tipo de pensão"],
    },
}

# INE API base URL
INE_API_BASE = "https://www.ine.pt/ine/json_indicador/pindica.jsp"

# Time dimension codes (Dim1) — format: S7AYYYY
def _dim1_all_periods():
    """Request all periods."""
    return "T"

def _dim1_year(year: int):
    """Request a specific year."""
    return f"S7A{year}"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(force: bool = False) -> sqlite3.Connection:
    """Initialize the pension database."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if force and DB_PATH.exists():
        DB_PATH.unlink()
        print("  Deleted existing database.")

    conn = db_connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Pension observations — one row per (indicator, year, period, geography, type)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pension_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator_code TEXT NOT NULL,
            indicator_name TEXT,
            period TEXT,
            year INTEGER,
            geographic_level TEXT,
            geographic_code TEXT,
            geographic_name TEXT,
            pension_type TEXT,
            value REAL,
            unit TEXT,
            UNIQUE(indicator_code, period, geographic_code, pension_type)
        )
    """)

    # Indicator metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            code TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            source TEXT,
            first_period TEXT,
            last_period TEXT,
            last_updated TEXT,
            dimensions TEXT,
            downloaded_at TEXT,
            row_count INTEGER DEFAULT 0
        )
    """)

    # Download log
    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_log (
            indicator_code TEXT,
            year TEXT,
            response_size INTEGER,
            downloaded_at TEXT,
            success INTEGER DEFAULT 1,
            UNIQUE(indicator_code, year)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pd_code ON pension_data(indicator_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pd_year ON pension_data(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pd_geo ON pension_data(geographic_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pd_type ON pension_data(pension_type)")

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# INE API Client
# ---------------------------------------------------------------------------

def ine_api_fetch(varcd: str, dim1: str = "T", extra_dims: dict = None) -> dict:
    """Fetch an indicator from the INE JSON API.

    Args:
        varcd: Indicator code (e.g., "0004325")
        dim1: Time dimension ("T" for all, "S7A2023" for specific year)
        extra_dims: Additional dimension filters {"Dim2": "...", ...}

    Returns:
        Parsed JSON response dict.

    Raises:
        RuntimeError: If the API returns an error or empty response.
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
        # Check for API-level error messages
        msg = item.get("Msg", "")
        if msg and "no válido" in msg.lower():
            raise RuntimeError(f"INE API error for varcd={varcd}: {msg}")
        return item
    return {}


def parse_indicator_response(resp: dict) -> list[dict]:
    """Parse INE API response into flat rows.

    Returns list of dicts with keys:
        indicator_code, indicator_name, period, year, geographic_level,
        geographic_code, geographic_name, pension_type, value, unit
    """
    code = resp.get("IndicadorCod", "")
    name = resp.get("IndicadorDsg", "")
    dados = resp.get("Dados", {})

    rows = []
    for period_key, period_data in dados.items():
        # period_key format: "S7A2023" or similar
        year_match = period_key.replace("S7A", "") if "S7A" in period_key else period_key
        try:
            year = int(year_match)
        except ValueError:
            year = 0

        # period_data can be a dict or list depending on dimensions
        if isinstance(period_data, dict):
            for entry_key, entry_val in period_data.items():
                row = _parse_entry(code, name, period_key, year, entry_key, entry_val)
                if row:
                    rows.append(row)
        elif isinstance(period_data, list):
            for entry in period_data:
                if isinstance(entry, dict):
                    row = _parse_dict_entry(code, name, period_key, year, entry)
                    if row:
                        rows.append(row)

    return rows


def _parse_entry(code, name, period, year, entry_key, entry_val):
    """Parse a single data entry from the API response.

    Returns a row dict or None if the entry has no usable data.
    """
    if isinstance(entry_val, dict):
        # Nested structure — extract value from the dict
        value = None
        geo_code = ""
        geo_name = ""
        pension_type = ""
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
                pension_type = str(v)
            elif k == "unidade":
                unit = str(v)

        # Skip entries with no value and no meaningful geographic info
        if value is None and not geo_code:
            return None

        # Fallback: use entry_key as geographic info
        if not geo_name:
            geo_name = str(entry_key)

        return {
            "indicator_code": code,
            "indicator_name": name,
            "period": period,
            "year": year,
            "geographic_level": _classify_geographic_level(geo_code),
            "geographic_code": geo_code,
            "geographic_name": geo_name,
            "pension_type": pension_type,
            "value": value,
            "unit": unit,
        }

    elif isinstance(entry_val, (int, float)):
        return {
            "indicator_code": code,
            "indicator_name": name,
            "period": period,
            "year": year,
            "geographic_level": "national",
            "geographic_code": "PT",
            "geographic_name": str(entry_key),
            "pension_type": "",
            "value": float(entry_val),
            "unit": "",
        }

    return None


def _parse_dict_entry(code, name, period, year, entry):
    """Parse a dict entry from a list-type response."""
    value = entry.get("valor")
    try:
        value = float(value) if value is not None else None
    except (ValueError, TypeError):
        value = None

    return {
        "indicator_code": code,
        "indicator_name": name,
        "period": period,
        "year": year,
        "geographic_level": _classify_geographic_level(str(entry.get("geoCod", ""))),
        "geographic_code": str(entry.get("geoCod", "")),
        "geographic_name": str(entry.get("geoDsg", "")),
        "pension_type": str(entry.get("dim_3_t", entry.get("dim_3", ""))),
        "value": value,
        "unit": str(entry.get("unidade", "")),
    }


def _classify_geographic_level(geo_code: str) -> str:
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
# Download
# ---------------------------------------------------------------------------

def cmd_download(args):
    """Download pension indicators from INE API."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    target_year = getattr(args, "year", None)
    target_indicators = getattr(args, "indicator", None)

    indicators = PENSION_INDICATORS
    if target_indicators:
        indicators = {k: v for k, v in indicators.items() if k in target_indicators}

    print(f"\n  Downloading pension indicators from INE API...")
    print(f"  Indicators: {len(indicators)}")

    total_downloaded = 0
    total_size = 0

    for varcd, info in indicators.items():
        print(f"\n  [{varcd}] {info['name']}")

        # Determine time range
        if target_year:
            periods = [_dim1_year(target_year)]
        else:
            periods = [_dim1_all_periods()]

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

            time.sleep(0.5)  # Rate limiting

    print(f"\n  Total: {total_downloaded} files, {total_size:,} bytes")
    if total_downloaded > 0:
        print(f"  Run 'python pension_ine.py index' to build the database")
    print()


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def cmd_index(args):
    """Parse downloaded JSON files into SQLite."""
    conn = init_db(force=getattr(args, "force", False))

    if getattr(args, "force", False):
        conn.execute("DELETE FROM pension_data")
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

        rows = parse_indicator_response(resp)
        if not rows:
            print("0 rows")
            continue

        # Insert into database
        changes_before = conn.total_changes
        for row in rows:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO pension_data
                    (indicator_code, indicator_name, period, year,
                     geographic_level, geographic_code, geographic_name,
                     pension_type, value, unit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["indicator_code"], row["indicator_name"], row["period"],
                    row["year"], row["geographic_level"], row["geographic_code"],
                    row["geographic_name"], row["pension_type"], row["value"],
                    row["unit"],
                ))
            except sqlite3.Error as e:
                print(f"DB error: {e}")
                break

        new_count = conn.total_changes - changes_before
        total_rows += new_count
        print(f"{len(rows):,} rows ({new_count:,} new)")
        conn.commit()

        # Update indicator metadata
        code = resp.get("IndicadorCod", "")
        if code:
            dados = resp.get("Dados", {})
            years = sorted(dados.keys()) if dados else []
            conn.execute("""
                INSERT OR REPLACE INTO indicators
                (code, name, description, source, first_period, last_period,
                 last_updated, dimensions, downloaded_at, row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code,
                resp.get("IndicadorDsg", ""),
                PENSION_INDICATORS.get(code, {}).get("description", ""),
                "INE",
                years[0] if years else "",
                years[-1] if years else "",
                resp.get("DataUltimoAtualizacao", ""),
                json.dumps(PENSION_INDICATORS.get(code, {}).get("dimensions", [])),
                datetime.now(timezone.utc).isoformat(),
                new_count,
            ))
            conn.commit()

    # Summary
    count = conn.execute("SELECT COUNT(*) FROM pension_data").fetchone()[0]
    indicators_count = conn.execute("SELECT COUNT(DISTINCT indicator_code) FROM pension_data").fetchone()[0]
    years_count = conn.execute("SELECT COUNT(DISTINCT year) FROM pension_data WHERE year > 0").fetchone()[0]
    geo_count = conn.execute("SELECT COUNT(DISTINCT geographic_code) FROM pension_data").fetchone()[0]

    print(f"\n  Index totals:")
    print(f"    pension_data:   {count:,}")
    print(f"    indicators:     {indicators_count}")
    print(f"    years:          {years_count}")
    print(f"    geographies:    {geo_count}")
    print(f"    New rows:       {total_rows:,}")

    conn.close()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def cmd_status(args):
    """Quick one-glance status overview."""
    if not DB_PATH.exists():
        print(f"  pension_ine.db: NOT FOUND")
        print(f"  Run 'python pension_ine.py download' then 'index'")
        return

    db_size = DB_PATH.stat().st_size / (1024 * 1024)
    mtime = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
    age_days = (datetime.now() - mtime).days

    conn = db_connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM pension_data").fetchone()[0]
    indicators = conn.execute("SELECT COUNT(DISTINCT indicator_code) FROM pension_data").fetchone()[0]
    years = conn.execute("SELECT MIN(year), MAX(year) FROM pension_data WHERE year > 0").fetchone()
    geos = conn.execute("SELECT COUNT(DISTINCT geographic_code) FROM pension_data").fetchone()[0]
    geo_levels = conn.execute(
        "SELECT geographic_level, COUNT(DISTINCT geographic_code) FROM pension_data GROUP BY geographic_level"
    ).fetchall()
    conn.close()

    yr_range = f"{years[0]}-{years[1]}" if years and years[0] else "empty"
    print(f"  pension_ine.db  {db_size:.1f} MB  ({age_days}d old)")
    print(f"    observations:   {total:>10,}  ({yr_range})")
    print(f"    indicators:     {indicators:>10}")
    print(f"    geographies:    {geos:>10}")
    for level, count in geo_levels:
        print(f"      {level:<20} {count:>8,}")
    print()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def cmd_stats(args):
    """Show summary statistics."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = db_connect(str(DB_PATH))

    print(f"\n{'='*70}")
    print(f"  Pension INE Data — Statistics")
    print(f"{'='*70}")

    # By indicator
    print(f"\n  By Indicator:")
    for code, name, count, yr_min, yr_max in conn.execute("""
        SELECT indicator_code, indicator_name, COUNT(*),
               MIN(year), MAX(year)
        FROM pension_data WHERE year > 0
        GROUP BY indicator_code ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"    [{code}] {name[:50]}")
        print(f"      {count:,} rows, {yr_min}-{yr_max}")

    # By geographic level
    print(f"\n  By Geographic Level:")
    for level, count, geos in conn.execute("""
        SELECT geographic_level, COUNT(*), COUNT(DISTINCT geographic_code)
        FROM pension_data GROUP BY geographic_level ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"    {level:<20} {count:>8,} rows  ({geos:,} geographies)")

    # By pension type
    print(f"\n  By Pension Type:")
    for ptype, count in conn.execute("""
        SELECT pension_type, COUNT(*) FROM pension_data
        WHERE pension_type != ''
        GROUP BY pension_type ORDER BY COUNT(*) DESC LIMIT 10
    """).fetchall():
        print(f"    {ptype:<40} {count:>8,}")

    # Latest values (national level)
    print(f"\n  Latest National Values:")
    for code, name, year, ptype, value in conn.execute("""
        SELECT p.indicator_code, p.indicator_name, p.year, p.pension_type, p.value
        FROM pension_data p
        INNER JOIN (
            SELECT indicator_code, pension_type, MAX(year) as max_year
            FROM pension_data WHERE geographic_level = 'national' AND value IS NOT NULL
            GROUP BY indicator_code, pension_type
        ) latest ON p.indicator_code = latest.indicator_code
            AND p.pension_type = latest.pension_type
            AND p.year = latest.max_year
        WHERE p.geographic_level = 'national' AND p.value IS NOT NULL
        ORDER BY p.indicator_code, p.pension_type
    """).fetchall():
        val_str = f"{value:,.0f}" if value else "N/A"
        print(f"    [{code}] {ptype or 'Total':<25} {year}: {val_str}")

    print(f"\n{'='*70}\n")
    conn.close()


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def cmd_query(args):
    """Run arbitrary SQL query."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = db_connect(str(DB_PATH))

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


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def cmd_export(args):
    """Export pension data to JSON."""
    if not DB_PATH.exists():
        print("  Database not found. Run 'download' then 'index' first.")
        return

    conn = db_connect(str(DB_PATH))

    data = {}
    rows = conn.execute("""
        SELECT indicator_code, indicator_name, year, geographic_level,
               geographic_code, geographic_name, pension_type, value, unit
        FROM pension_data ORDER BY indicator_code, year, geographic_code
    """).fetchall()

    for code, name, year, geo_level, geo_code, geo_name, ptype, value, unit in rows:
        if code not in data:
            data[code] = {"name": name, "observations": []}
        data[code]["observations"].append({
            "year": year,
            "geographic_level": geo_level,
            "geographic_code": geo_code,
            "geographic_name": geo_name,
            "pension_type": ptype,
            "value": value,
            "unit": unit,
        })

    out_path = Path(args.out) if args.out else DATA_DIR / "pension_ine_export.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"  Exported {len(rows):,} observations across {len(data)} indicators")
    print(f"  To: {out_path}")

    conn.close()


# ---------------------------------------------------------------------------
# Compare — cross-reference with procurement data
# ---------------------------------------------------------------------------

def cmd_compare(args):
    """Cross-reference pension data with procurement patterns."""
    if not DB_PATH.exists():
        print("  pension_ine.db not found. Run 'download' then 'index' first.")
        return

    procurement_db = SCRIPT_DIR / "data" / "procurement.db"
    if not procurement_db.exists():
        print(f"  procurement.db not found at {procurement_db}")
        return

    conn = db_connect(str(DB_PATH))
    proc_conn = db_connect(str(procurement_db))

    print(f"\n{'='*70}")
    print(f"  Pension × Procurement Cross-Reference")
    print(f"{'='*70}")

    # --- Pension data overview ---
    latest_year = conn.execute(
        "SELECT MAX(year) FROM pension_data WHERE indicator_code = '0004325'"
    ).fetchone()[0]

    if not latest_year:
        print("\n  No pension data available. Run 'download' then 'index' first.")
        conn.close()
        proc_conn.close()
        return

    # Get latest pension data by district
    pension_by_district = {}
    for geo_code, geo_name, value in conn.execute("""
        SELECT geographic_code, geographic_name, value
        FROM pension_data
        WHERE geographic_level = 'district' AND value IS NOT NULL
        AND indicator_code = '0004325' AND year = ?
        AND pension_type = ''
    """, (latest_year,)).fetchall():
        pension_by_district[geo_code] = {"name": geo_name, "pensioners": value}

    if pension_by_district:
        print(f"\n  District-level pension data ({latest_year}): {len(pension_by_district)} districts")
        print(f"\n  Top districts by pensioner count:")
        sorted_districts = sorted(pension_by_district.values(), key=lambda x: -x["pensioners"])
        for d in sorted_districts[:10]:
            print(f"    {d['name']:<30} {d['pensioners']:>10,.0f} pensioners")
    else:
        print(f"\n  No district-level pension data for {latest_year}.")
        print(f"  The INE API may not support geographic breakdown for these indicators.")

    # --- National pension summary ---
    print(f"\n  National pension summary:")
    for code, year, ptype, value in conn.execute("""
        SELECT indicator_code, year, pension_type, value
        FROM pension_data
        WHERE geographic_level = 'national' AND value IS NOT NULL
        AND year = (SELECT MAX(year) FROM pension_data WHERE indicator_code = pension_data.indicator_code)
        ORDER BY indicator_code, pension_type
    """).fetchall():
        val_str = f"{value:,.0f}" if value else "N/A"
        print(f"    [{code}] {ptype or 'Total':<25} {year}: {val_str}")

    # --- Procurement overview ---
    print(f"\n  Procurement data overview:")
    try:
        total_contracts = proc_conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0]
        total_value = proc_conn.execute(
            "SELECT SUM(precoContratual) FROM contratos WHERE precoContratual > 0"
        ).fetchone()[0] or 0
        n_districts = proc_conn.execute(
            "SELECT COUNT(DISTINCT ine_district) FROM contratos WHERE ine_district != ''"
        ).fetchone()[0]
        print(f"    Contracts:  {total_contracts:>12,}")
        print(f"    Total value: €{total_value:>14,.0f}")
        print(f"    Districts:  {n_districts:>12,}")

        # Top districts by contract value
        if n_districts > 0:
            print(f"\n  Top districts by contract value:")
            for district, value in proc_conn.execute("""
                SELECT ine_district, SUM(precoContratual) as total
                FROM contratos WHERE ine_district != '' AND precoContratual > 0
                GROUP BY ine_district ORDER BY total DESC LIMIT 10
            """).fetchall():
                print(f"    {district or '?':<30} €{value:>14,.0f}")
    except Exception as e:
        print(f"    Error reading procurement data: {e}")

    print(f"\n{'='*70}")
    conn.close()
    proc_conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="INE Pension Data Client — Portuguese pension statistics via INE API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command")

    # Download
    dl = sub.add_parser("download", help="Download pension indicators from INE")
    dl.add_argument("--year", type=int, help="Specific year to download")
    dl.add_argument("--indicator", nargs="+", help="Specific indicator code(s)")

    # Index
    idx = sub.add_parser("index", help="Parse downloaded JSON into SQLite")
    idx.add_argument("--force", action="store_true", help="Re-index from scratch")

    # Status
    sub.add_parser("status", help="Quick one-glance status overview")

    # Stats
    sub.add_parser("stats", help="Summary statistics")

    # Query
    qr = sub.add_parser("query", help="Run arbitrary SQL")
    qr.add_argument("sql", help="SQL query to execute")

    # Export
    exp = sub.add_parser("export", help="Export to JSON")
    exp.add_argument("--out", help="Output file path")

    # Compare
    sub.add_parser("compare", help="Cross-reference with procurement data")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "download": cmd_download,
        "index": cmd_index,
        "status": cmd_status,
        "stats": cmd_stats,
        "query": cmd_query,
        "export": cmd_export,
        "compare": cmd_compare,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
