#!/usr/bin/env python3
"""Contract Modification Tracker — Detect post-award price changes via DRE.

Parses Diário da República (DRE) publications for contract amendments
(aditivos/modificações) and cross-references with the procurement database
to detect post-award price changes.

DRE publications contain official government announcements including:
- Contract amendments (aditivos)
- Price modifications (modificações contratuais)
- Supplementary agreements (acordos complementares)
- Contract extensions (prorrogações)

Usage:
    python modification_tracker.py scan           # Scan DRE for modifications
    python modification_tracker.py stats          # Show modification statistics
    python modification_tracker.py alerts         # Show high-value modifications
    python modification_tracker.py entity --nif X # Modifications for entity
    python modification_tracker.py export         # Export to JSON
"""

import sys
import json
import sqlite3
import argparse
import re
import time
from pathlib import Path
from collections import defaultdict, Counter
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from difflib import SequenceMatcher

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROC_DB = DATA_DIR / "procurement.db"
DRE_DB = SCRIPT_DIR / "dre_index.db"
MOD_DB = DATA_DIR / "modifications.db"
MOD_CACHE = DATA_DIR / "modifications_cache.json"

# DRE base URL for fetching publications
DRE_BASE = "https://dre.diariodarepublica.pt"

# Keywords indicating contract modifications
MODIFICATION_KEYWORDS = [
    "aditivo", "aditiva", "aditivos",
    "modificação", "modificações", "modificar",
    "alteração", "alterações", "alterar",
    "acordo complementar", "acordos complementares",
    "prorrogação", "prorrogações", "prorrogar",
    "suplementar", "complementar",
    "retificação", "retificar",
    "redução de prazo",
    "aumento de valor",
    "diminuição de valor",
    "cessão", "cedente", "cessionário",
]

# Keywords for value changes
VALUE_CHANGE_KEYWORDS = [
    "aumento de valor", "elevação de valor", "majoração",
    "diminuição de valor", "redução de valor", "minorac",
    "valor total", "valor inicial", "novo valor",
    "preço contratual", "preço global",
]


def get_proc_db():
    conn = sqlite3.connect(str(PROC_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_mod_db():
    """Get or create modifications database."""
    conn = sqlite3.connect(str(MOD_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS modifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER,
            entity_nif TEXT,
            entity_name TEXT,
            publication_date TEXT,
            modification_type TEXT,
            description TEXT,
            original_value REAL,
            new_value REAL,
            value_change REAL,
            dre_url TEXT,
            dre_title TEXT,
            dre_serie TEXT,
            dre_numero TEXT,
            dre_year INTEGER,
            confidence REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mod_contract
        ON modifications(contract_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mod_entity
        ON modifications(entity_nif)
    """)
    conn.commit()
    return conn


def is_modification_candidate(title: str) -> bool:
    """Check if a DRE title suggests a contract modification."""
    if not title:
        return False
    title_lower = title.lower()
    return any(kw in title_lower for kw in MODIFICATION_KEYWORDS)


def classify_modification(title: str) -> str:
    """Classify the type of modification from the title."""
    if not title:
        return "unknown"

    title_lower = title.lower()

    if any(kw in title_lower for kw in ["aditivo", "aditiva", "aditivos"]):
        return "aditivo"
    if any(kw in title_lower for kw in ["prorrogação", "prorrogações", "prorrogar"]):
        return "prorrogação"
    if any(kw in title_lower for kw in ["cessão", "cedente", "cessionário"]):
        return "cessão"
    if any(kw in title_lower for kw in ["retificação", "retificar"]):
        return "retificação"
    if any(kw in title_lower for kw in ["modificação", "modificações"]):
        return "modificação"
    if any(kw in title_lower for kw in ["alteração", "alterações", "alterar"]):
        return "alteração"
    if any(kw in title_lower for kw in ["acordo complementar", "acordos complementares"]):
        return "acordo_complementar"
    if any(kw in title_lower for kw in ["suplementar", "complementar"]):
        return "complementar"
    return "other"


def extract_value_change(text: str) -> dict:
    """Try to extract value change information from text."""
    result = {"original": None, "new": None, "change": None}

    if not text:
        return result

    # Look for EUR values
    eur_pattern = r'(\d[\d\s.,]*)\s*(?:€|EUR|euros?)'
    values = re.findall(eur_pattern, text, re.IGNORECASE)

    # Clean and convert
    cleaned = []
    for v in values:
        v = v.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            val = float(v)
            if val > 0:
                cleaned.append(val)
        except ValueError:
            continue

    if len(cleaned) >= 2:
        result["original"] = cleaned[0]
        result["new"] = cleaned[1]
        result["change"] = cleaned[1] - cleaned[0]
    elif len(cleaned) == 1:
        # Check context
        if any(kw in text.lower() for kw in ["aumento", "elevação", "majoração", "novo valor"]):
            result["new"] = cleaned[0]
        elif any(kw in text.lower() for kw in ["redução", "diminuição", "minorac"]):
            result["original"] = cleaned[0]

    return result


def match_to_contract(mod_title: str, mod_description: str, proc_conn) -> dict | None:
    """Try to match a DRE modification to a procurement contract.

    Returns the matched contract record or None.
    """
    if not mod_title and not mod_description:
        return None

    search_text = f"{mod_title} {mod_description}".lower()

    # Extract potential NIFs from the modification text
    nif_matches = re.findall(r'\b(\d{9})\b', search_text)

    # Extract key terms for matching
    # Look for project/object descriptions
    object_terms = []
    for term in re.findall(r'(?:obra|reabilitação|construção|equipamento|infraestrutura|serviço)\s+(?:de\s+)?[\w\s]+', search_text):
        object_terms.append(term.strip())

    # Try to match by entity NIF
    if nif_matches:
        for nif in nif_matches:
            row = proc_conn.execute("""
                SELECT idcontrato, adjudicante_nome, objectoContrato,
                       precoContratual, precoBaseProcedimento
                FROM contratos
                WHERE adjudicante_nif = ?
                ORDER BY dataCelebracaoContrato DESC
                LIMIT 5
            """, (nif,)).fetchone()
            if row:
                return dict(row)

    # Try to match by object description similarity
    if object_terms:
        for term in object_terms[:3]:
            row = proc_conn.execute("""
                SELECT idcontrato, adjudicante_nome, objectoContrato,
                       precoContratual, precoBaseProcedimento
                FROM contratos
                WHERE objectoContrato LIKE ?
                ORDER BY precoContratual DESC
                LIMIT 5
            """, (f"%{term[:30]}%",)).fetchone()
            if row:
                return dict(row)

    return None


class ModificationTracker:
    """Track and analyze contract modifications."""

    def __init__(self):
        self.proc_conn = get_proc_db()
        self.mod_conn = get_mod_db()
        self.dre_available = DRE_DB.exists()

    def scan_dre(self, limit: int = 500, force: bool = False):
        """Scan DRE publications for contract modifications."""
        if not self.dre_available:
            print("  DRE database not found. Run dre_crawler.py first.")
            return

        dre_conn = sqlite3.connect(str(DRE_DB))
        dre_conn.row_factory = sqlite3.Row

        # Get existing modification publication IDs
        existing_ids = set()
        if not force:
            for r in self.mod_conn.execute(
                "SELECT DISTINCT dre_url FROM modifications WHERE dre_url IS NOT NULL"
            ).fetchall():
                existing_ids.add(r[0])

        # Scan DRE publications
        total_pubs = dre_conn.execute("SELECT COUNT(*) FROM dre_publications").fetchone()[0]
        print(f"\n  Scanning {total_pubs:,} DRE publications for modifications...")

        candidates = []
        for row in dre_conn.execute("""
            SELECT pub_id, title, serie, numero, year, eli_url, publication_date
            FROM dre_publications
            ORDER BY year DESC, numero DESC
            LIMIT ?
        """, (limit,)).fetchall():
            title = str(row["title"] or "")
            url = str(row["eli_url"] or "")

            if url in existing_ids:
                continue

            if is_modification_candidate(title):
                candidates.append(dict(row))

        print(f"  Found {len(candidates)} modification candidates")

        if not candidates:
            print("  No new modifications found.")
            dre_conn.close()
            return

        # Process candidates
        proc_conn = self.proc_conn
        stored = 0
        for i, cand in enumerate(candidates):
            title = cand.get("title", "")
            mod_type = classify_modification(title)
            value_info = extract_value_change(title)

            # Try to match to a contract
            matched = match_to_contract(title, title, proc_conn)

            entity_nif = matched["adjudicante_nif"] if matched else ""
            entity_name = matched["adjudicante_nome"] if matched else ""
            contract_id = matched["idcontrato"] if matched else None
            orig_value = matched["precoContratual"] if matched else None

            confidence = 0.3  # Base confidence
            if matched:
                confidence += 0.3
            if mod_type != "unknown":
                confidence += 0.2
            if value_info["change"] is not None:
                confidence += 0.2

            try:
                self.mod_conn.execute("""
                    INSERT INTO modifications
                    (contract_id, entity_nif, entity_name, publication_date,
                     modification_type, description, original_value, new_value,
                     value_change, dre_url, dre_title, dre_serie, dre_numero,
                     dre_year, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    contract_id,
                    entity_nif,
                    entity_name,
                    str(cand.get("publication_date", "")),
                    mod_type,
                    title,
                    orig_value,
                    value_info.get("new"),
                    value_info.get("change"),
                    cand.get("eli_url", ""),
                    title,
                    str(cand.get("serie", "")),
                    str(cand.get("numero", "")),
                    cand.get("year"),
                    confidence,
                ))
                stored += 1
            except sqlite3.IntegrityError:
                pass

            if (i + 1) % 50 == 0:
                self.mod_conn.commit()
                print(f"  Processed {i+1}/{len(candidates)}...")

        self.mod_conn.commit()

        print(f"\n  Stored {stored} modification records")
        dre_conn.close()

    def get_stats(self) -> dict:
        """Get modification statistics."""
        total = self.mod_conn.execute("SELECT COUNT(*) FROM modifications").fetchone()[0]

        if total == 0:
            return {"total": 0}

        # By type
        types = {}
        for r in self.mod_conn.execute(
            "SELECT modification_type, COUNT(*) as cnt FROM modifications GROUP BY modification_type ORDER BY cnt DESC"
        ).fetchall():
            types[r[0]] = r[1]

        # By year
        years = {}
        for r in self.mod_conn.execute(
            "SELECT dre_year, COUNT(*) as cnt FROM modifications WHERE dre_year IS NOT NULL GROUP BY dre_year ORDER BY dre_year"
        ).fetchall():
            years[r[0]] = r[1]

        # Value changes
        with_values = self.mod_conn.execute(
            "SELECT COUNT(*) FROM modifications WHERE value_change IS NOT NULL"
        ).fetchone()[0]

        total_increase = self.mod_conn.execute(
            "SELECT SUM(value_change) FROM modifications WHERE value_change > 0"
        ).fetchone()[0] or 0

        total_decrease = self.mod_conn.execute(
            "SELECT SUM(value_change) FROM modifications WHERE value_change < 0"
        ).fetchone()[0] or 0

        # Matched to contracts
        matched = self.mod_conn.execute(
            "SELECT COUNT(*) FROM modifications WHERE contract_id IS NOT NULL"
        ).fetchone()[0]

        # Top entities by modification count
        top_entities = []
        for r in self.mod_conn.execute("""
            SELECT entity_nif, entity_name, COUNT(*) as cnt,
                   SUM(ABS(COALESCE(value_change, 0))) as total_change
            FROM modifications
            WHERE entity_nif IS NOT NULL AND entity_nif != ''
            GROUP BY entity_nif
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall():
            top_entities.append({
                "nif": r[0], "name": r[1], "count": r[2], "total_change": r[3]
            })

        return {
            "total": total,
            "by_type": types,
            "by_year": years,
            "with_values": with_values,
            "total_increase": total_increase,
            "total_decrease": total_decrease,
            "matched_to_contracts": matched,
            "unmatched": total - matched,
            "top_entities": top_entities,
        }

    def get_alerts(self, min_value_change: float = 50000) -> list[dict]:
        """Get high-value modification alerts."""
        rows = self.mod_conn.execute("""
            SELECT * FROM modifications
            WHERE ABS(COALESCE(value_change, 0)) >= ?
            ORDER BY ABS(value_change) DESC
        """, (min_value_change,)).fetchall()

        return [dict(r) for r in rows]

    def get_entity_modifications(self, nif: str) -> list[dict]:
        """Get all modifications for a specific entity."""
        rows = self.mod_conn.execute("""
            SELECT * FROM modifications
            WHERE entity_nif = ?
            ORDER BY dre_year DESC, publication_date DESC
        """, (nif,)).fetchall()

        return [dict(r) for r in rows]

    def export_all(self, output_path: str = None):
        """Export all modifications to JSON."""
        rows = self.mod_conn.execute(
            "SELECT * FROM modifications ORDER BY dre_year DESC"
        ).fetchall()

        data = [dict(r) for r in rows]
        output = output_path or str(DATA_DIR / "modifications_export.json")

        with open(output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"  Exported {len(data)} modifications to {output}")
        return data

    def close(self):
        self.proc_conn.close()
        self.mod_conn.close()


def cmd_scan(args):
    """Scan DRE for modifications."""
    tracker = ModificationTracker()
    tracker.scan_dre(limit=args.limit, force=args.force)
    tracker.close()


def cmd_stats(args):
    """Show modification statistics."""
    tracker = ModificationTracker()
    stats = tracker.get_stats()

    print(f"\n{'='*70}")
    print(f"  CONTRACT MODIFICATION TRACKER — STATISTICS")
    print(f"{'='*70}")

    if stats["total"] == 0:
        print(f"  No modifications tracked yet. Run 'scan' first.")
        print(f"{'='*70}\n")
        tracker.close()
        return

    print(f"  Total modifications:     {stats['total']:>10,}")
    print(f"  Matched to contracts:    {stats['matched_to_contracts']:>10,}")
    print(f"  Unmatched:               {stats['unmatched']:>10,}")
    print(f"  With value data:         {stats['with_values']:>10,}")

    if stats["total_increase"] > 0:
        print(f"\n  Total value increases:   €{stats['total_increase']:>12,.0f}")
    if stats["total_decrease"] < 0:
        print(f"  Total value decreases:   €{stats['total_decrease']:>12,.0f}")

    if stats["by_type"]:
        print(f"\n  By modification type:")
        for t, c in stats["by_type"].items():
            print(f"    {t:<25} {c:>6,}")

    if stats["by_year"]:
        print(f"\n  By year:")
        for y, c in stats["by_year"].items():
            print(f"    {y}: {c:>6,}")

    if stats["top_entities"]:
        print(f"\n  Top entities by modification count:")
        for e in stats["top_entities"]:
            val = e["total_change"]
            val_str = f"€{val:,.0f}" if val > 0 else "N/A"
            print(f"    {e['nif'] or '???'} | {(e['name'] or 'Unknown')[:35]:<35} | {e['count']:>4} mods | Δ {val_str}")

    print(f"{'='*70}\n")
    tracker.close()


def cmd_alerts(args):
    """Show high-value modification alerts."""
    tracker = ModificationTracker()
    alerts = tracker.get_alerts(min_value_change=args.min_value)

    print(f"\n{'='*70}")
    print(f"  HIGH-VALUE MODIFICATION ALERTS (≥€{args.min_value:,.0f})")
    print(f"{'='*70}")

    if not alerts:
        print(f"  No high-value modifications found.")
        print(f"{'='*70}\n")
        tracker.close()
        return

    for a in alerts:
        change = a.get("value_change") or 0
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        print(f"\n  {arrow} {a['modification_type'] or 'Unknown'} — {a['dre_year'] or '?'}")
        print(f"     Entity: {a['entity_name'] or 'Unknown'} (NIF: {a['entity_nif'] or '???'})")
        print(f"     Description: {str(a['description'] or '')[:80]}")
        if a.get("dre_url"):
            print(f"     DRE: {a['dre_url'][:70]}")
        if change != 0:
            print(f"     Value change: €{change:>+12,.0f}")
        if a.get("original_value"):
            print(f"     Original: €{a['original_value']:>12,.0f}")
        if a.get("new_value"):
            print(f"     New:      €{a['new_value']:>12,.0f}")
        print(f"     Confidence: {a.get('confidence', 0):.0%}")

    print(f"\n{'='*70}\n")
    tracker.close()


def cmd_entity(args):
    """Show modifications for a specific entity."""
    tracker = ModificationTracker()
    mods = tracker.get_entity_modifications(args.nif)

    # Get entity name
    name_row = tracker.proc_conn.execute(
        "SELECT desigEntidade FROM entidades WHERE nifEntidade = ?",
        (args.nif,)
    ).fetchone()
    name = name_row["desigEntidade"] if name_row else "Unknown"

    print(f"\n{'='*70}")
    print(f"  MODIFICATIONS — {name} (NIF: {args.nif})")
    print(f"{'='*70}")

    if not mods:
        print(f"  No modifications found for this entity.")
        print(f"{'='*70}\n")
        tracker.close()
        return

    print(f"  Total modifications: {len(mods)}\n")

    for m in mods:
        change = m.get("value_change") or 0
        print(f"  [{m.get('dre_year', '?')}] {m['modification_type'] or 'Unknown'}")
        print(f"    {m['description'][:80]}")
        if change != 0:
            print(f"    Δ €{change:>+12,.0f}")
        print()

    print(f"{'='*70}\n")
    tracker.close()


def cmd_export(args):
    """Export modifications to JSON."""
    tracker = ModificationTracker()
    tracker.export_all(args.output)
    tracker.close()


def main():
    parser = argparse.ArgumentParser(
        description="Track contract modifications via DRE publications",
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="Scan DRE for modifications")
    scan.add_argument("--limit", type=int, default=500, help="Max publications to scan")
    scan.add_argument("--force", action="store_true", help="Re-scan all publications")

    sub.add_parser("stats", help="Show modification statistics")

    alerts = sub.add_parser("alerts", help="Show high-value modification alerts")
    alerts.add_argument("--min-value", type=float, default=50000,
                        help="Minimum value change threshold (EUR)")

    ent = sub.add_parser("entity", help="Modifications for an entity")
    ent.add_argument("--nif", required=True, help="Entity NIF")

    export = sub.add_parser("export", help="Export to JSON")
    export.add_argument("--output", "-o", help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "scan": cmd_scan,
        "stats": cmd_stats,
        "alerts": cmd_alerts,
        "entity": cmd_entity,
        "export": cmd_export,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
