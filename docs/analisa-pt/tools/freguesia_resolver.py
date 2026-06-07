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
from collections import Counter, defaultdict
from difflib import get_close_matches
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




class FreguesiaResolver:
    """Resolves LocalExecucao location strings to INE codes."""

    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.muni_map = self._load_municipality_map()
        self.local_exec_map = self._load_existing_mapping()

    def _load_municipality_map(self) -> dict:
        """Load municipality directory and build name → code lookup."""
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
                            if name and len(code) >= 4:
                                muni_map[name] = code[:4]
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            name = item.get("name", item.get("municipality", "")).lower().strip()
                            code = item.get("code", item.get("codigo", ""))
                            if name and len(code) >= 4:
                                muni_map[name] = code[:4]
            except (json.JSONDecodeError, KeyError):
                pass

        # Also build from procurement data — extract unique adjudicante_nome
        # with known NUTs codes to build name → code mapping
        try:
            rows = self.conn.execute("""
                SELECT DISTINCT adjudicante_nome, NUTs
                FROM contratos
                WHERE adjudicante_nome IS NOT NULL AND adjudicante_nome != ''
                AND NUTs IS NOT NULL AND NUTs != ''
                AND tipoContrato LIKE '%Serv%'
                LIMIT 5000
            """).fetchall()
            for r in rows:
                name = r["adjudicante_nome"].lower().strip()
                nuts = str(r["NUTs"] or "")
                # Extract district from NUTs
                if " - " in nuts:
                    nuts_code = nuts.split(" - ")[0].strip()
                else:
                    nuts_code = nuts.strip()
                # Try to extract municipality from name patterns like
                # "Município de X" or "Câmara Municipal de X"
                for prefix in ["município de ", "câmara municipal de ", "cm ", "municipal de "]:
                    if prefix in name:
                        muni_name = name.split(prefix)[-1].strip()
                        # Remove trailing common words
                        for suffix in [" e ", " -", " (", ","]:
                            if suffix in muni_name:
                                muni_name = muni_name[:muni_name.index(suffix)].strip()
                        if len(muni_name) > 2:
                            muni_map[muni_name] = nuts_code[:4] if len(nuts_code) >= 4 else ""
                            break
        except Exception:
            pass

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

    def _normalize(self, s: str) -> str:
        """Normalize a string for comparison."""
        return _normalize_name(s)

    def _extract_parts(self, local_execucao: str) -> list[str]:
        """Extract location parts from LocalExecucao string."""
        if not local_execucao:
            return []

        # Split by comma, newline, or semicolon
        parts = re.split(r'[,;\n]', local_execucao)
        parts = [p.strip() for p in parts if p.strip()]

        # Remove "Portugal" if first element
        if parts and parts[0].lower() in ("portugal", "pt"):
            parts = parts[1:]

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
        # Use the official CAOP codes first
        code4 = resolve_municipality(name)
        if code4:
            return code4
        # Fallback to municipality directory
        norm = self._normalize(name)
        if norm in self.muni_map:
            return self.muni_map[norm]
        matches = get_close_matches(norm, list(self.muni_map.keys()), n=1, cutoff=0.6)
        if matches:
            return self.muni_map[matches[0]]
        return None

    def resolve(self, local_execucao: str) -> dict:
        """Resolve a LocalExecucao string to an INE code and metadata.

        Returns dict with:
            - ine_code: 6-digit INE code (or prefix if freguesia unknown)
            - district: district name
            - municipality: municipality name
            - freguesia: freguesia name (if available)
            - confidence: "exact", "fuzzy", "partial", "nuts", "none"
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

        parts = self._extract_parts(local_execucao)

        if len(parts) == 0:
            return result
        elif len(parts) == 1:
            # Single part — might be a city/municipality name
            muni_code = self._resolve_municipality(parts[0])
            if muni_code:
                result["municipality"] = parts[0]
                result["ine_code"] = muni_code + "00"  # No freguesia
                result["confidence"] = "partial"
                return result

            dist_code = self._resolve_district(parts[0])
            if dist_code:
                result["district"] = parts[0]
                result["ine_code"] = dist_code + "0000"
                result["confidence"] = "partial"
                return result

        elif len(parts) == 2:
            # District, Municipality
            dist_code = self._resolve_district(parts[0])
            muni_code = self._resolve_municipality(parts[1])

            if muni_code:
                result["district"] = parts[0]
                result["municipality"] = parts[1]
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "exact"
                return result
            elif dist_code:
                result["district"] = parts[0]
                result["municipality"] = parts[1]
                result["ine_code"] = dist_code + "0000"
                result["confidence"] = "partial"
                return result

        elif len(parts) >= 3:
            # District, Municipality, Freguesia (or more)
            dist_code = self._resolve_district(parts[0])
            muni_code = self._resolve_municipality(parts[1])

            result["district"] = parts[0]
            result["municipality"] = parts[1]
            result["freguesia"] = parts[2] if len(parts) > 2 else ""

            if muni_code:
                result["ine_code"] = muni_code + "00"  # Freguesia code unknown
                result["confidence"] = "exact"
                return result
            elif dist_code:
                result["ine_code"] = dist_code + "0000"
                result["confidence"] = "partial"
                return result

        # Fallback: try to match any part as municipality
        for part in reversed(parts):
            muni_code = self._resolve_municipality(part)
            if muni_code:
                result["municipality"] = part
                result["ine_code"] = muni_code + "00"
                result["confidence"] = "fuzzy"
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

        # Sample and resolve
        result = self.resolve_all()

        # Count unique resolved municipalities
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

        # Save mapping
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
            print(f"    • {loc[:80]}")

    if args.json:
        print(json.dumps(result["results"], ensure_ascii=False, indent=2))

    resolver.close()


def cmd_stats(args):
    """Show resolution statistics."""
    resolver = FreguesiaResolver()
    stats = resolver.get_stats()

    print(f"\n{'='*70}")
    print(f"  FREGUESIA RESOLVER — STATISTICS")
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
        print(f"  • {le[:80]}")

    if len(unmapped) > 50:
        print(f"  ... and {len(unmapped) - 50} more")

    print(f"{'='*70}\n")
    resolver.close()


def cmd_export(args):
    """Export mapping to JSON."""
    resolver = FreguesiaResolver()
    resolver.export_mapping(args.output)
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
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
