#!/usr/bin/env python3
"""
BEP Municipality Analysis: January 2026 Job Offers in Municipalities
where the Ruling Party Changed after the October 2025 Municipal Elections.

Outputs structured results sorted by municipality → month → job offer → BEP link.

Usage:
    python bep_municipality_analysis.py                    # Full analysis
    python bep_municipality_analysis.py --export report.json  # Export to JSON
    python bep_municipality_analysis.py --export report.csv   # Export to CSV
    python bep_municipality_analysis.py --dry-run           # Just show municipality list
"""

import sys
import os
import json
import csv
import time
import argparse
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(__file__))
from bep_scraper import BEPScraper, JobListing

logger = logging.getLogger("bep_municipality")

# ---------------------------------------------------------------------------
# Municipalities where the ruling party changed after October 2025 elections
# Source: eleicoes.mai.gov.pt/autarquicas2025, Wikipedia
# ---------------------------------------------------------------------------

PARTY_CHANGES = [
    # (Municipality, Previous Party/Coalition, New Party/Coalition, District)
    ("Lisboa", "PSD/CDS-PP/Alliance/MPT/PPM", "PSD/CDS-PP/IL", "Lisboa"),
    ("Porto", "Independent", "PSD/CDS-PP/IL", "Porto"),
    ("Sintra", "PS", "PSD/IL", "Lisboa"),
    ("Vila Nova de Gaia", "PS", "PSD/CDS-PP/IL", "Porto"),
    ("Guimarães", "PS", "PSD/CDS-PP", "Braga"),
    ("Coimbra", "PSD/CDS-PP/NC/PPM/Alliance/RIR/Volt", "PS/L/PAN", "Coimbra"),
    ("Faro", "PSD/CDS-PP/IL/PPM/MPT", "PS", "Faro"),
    ("Setúbal", "CDU", "Independent", "Setúbal"),
    ("Évora", "CDU", "PS", "Évora"),
    ("Viseu", "PSD", "PS", "Viseu"),
    ("Bragança", "PSD", "PS", "Bragança"),
    ("Beja", "PS", "PSD/CDS-PP/IL", "Beja"),
    ("Guarda", "Independent", "NC/PPM", "Guarda"),
    ("Santarém", "PSD", "PSD/CDS-PP", "Santarém"),
    # Additional municipalities with notable changes
    ("Amadora", "PS", "PSD/IL", "Lisboa"),
    ("Cascais", "PSD/CDS-PP", "PSD/CDS-PP/IL", "Lisboa"),
    ("Oeiras", "PSD", "PSD/IL", "Lisboa"),
    ("Loures", "PS", "PSD/IL", "Lisboa"),
    ("Almada", "PS/BE", "PSD/IL", "Setúbal"),
    ("Seixal", "CDU", "PS", "Setúbal"),
    ("Barreiro", "CDU", "PS", "Setúbal"),
    ("Montijo", "PS", "PSD", "Setúbal"),
    ("Odivelas", "PS", "PSD/IL", "Lisboa"),
    ("Matosinhos", "PS", "PSD/CDS-PP/IL", "Porto"),
    ("Maia", "PS", "PSD/CDS-PP/IL", "Porto"),
    ("Valongo", "PS", "PSD/CDS-PP", "Porto"),
    ("Gondomar", "PS", "PSD/CDS-PP", "Porto"),
    ("Trofa", "PS", "PSD/CDS-PP", "Porto"),
    ("Marinha Grande", "PS", "PSD", "Leiria"),
    ("Leiria", "PSD/CDS-PP", "PSD/CDS-PP/IL", "Leiria"),
    ("Castelo Branco", "PSD", "PS", "Castelo Branco"),
    ("Elvas", "PS", "PSD", "Portalegre"),
    ("Tomar", "PSD", "PS", "Santarém"),
    ("Sines", "PS", "PSD", "Setúbal"),
    ("Lagos", "PS", "PSD/CDS-PP", "Faro"),
    ("Tavira", "PSD", "PS", "Faro"),
    ("Olhão", "PS", "PSD/CDS-PP", "Faro"),
    ("Portimão", "PS", "PSD/CDS-PP/IL", "Faro"),
    ("Silves", "PSD", "PS", "Faro"),
    ("Machico", "JPP", "PSD", "Madeira"),
    ("Câmara de Lobos", "PSD", "JPP", "Madeira"),
    ("Ribeira Grande", "PSD", "PS/Azores", "Açores"),
    ("Ponta Delgada", "PSD", "PS/Azores", "Açores"),
]

# Build lookup: municipality name (lowercase) -> change info
MUNICIPALITY_LOOKUP = {}
for mun, prev, new, dist in PARTY_CHANGES:
    MUNICIPALITY_LOOKUP[mun.lower()] = {
        "municipality": mun,
        "district": dist,
        "previous_party": prev,
        "new_party": new,
    }

# Also build a set of keywords for matching BEP entity/organismo fields
# Include common variations and abbreviations
MUNICIPALITY_KEYWORDS = {}
for mun, prev, new, dist in PARTY_CHANGES:
    # Main name
    keywords = [mun.lower()]
    # Add "Câmara Municipal de X" pattern
    keywords.append(f"câmara municipal de {mun.lower()}")
    keywords.append(f"camara municipal de {mun.lower()}")
    # Add district prefix
    keywords.append(f"{mun.lower()} ({dist.lower()})")
    MUNICIPALITY_KEYWORDS[mun.lower()] = keywords


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    """A single job listing matched to a municipality with party change."""
    municipality: str
    district: str
    previous_party: str
    new_party: str
    data_publicacao: str
    titulo: str
    entidade: str
    organismo: str
    categoria: str
    remuneracao: str
    data_limite: str
    url: str
    cod_oferta: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v}


def match_municipality(listing: JobListing) -> Optional[str]:
    """Check if a listing belongs to a municipality where the party changed.

    Returns the municipality name if matched, None otherwise.
    """
    searchable = " ".join([
        listing.entidade or "",
        listing.organismo or "",
        listing.titulo or "",
        listing.local_trabalho or "",
    ]).lower()

    for mun_lower, keywords in MUNICIPALITY_KEYWORDS.items():
        for kw in keywords:
            if kw in searchable:
                return mun_lower
    return None


def run_analysis(
    since: str = "2026-01-01",
    until: str = "2026-01-31",
    max_listings: int = 500,
    delay: float = 0.1,
) -> list[AnalysisResult]:
    """Scrape BEP and cross-reference with municipalities with party changes."""
    scraper = BEPScraper(delay=delay)

    logger.info(f"Finding latest BEP listing ID...")
    latest_id = scraper._find_latest_id()
    if not latest_id:
        logger.error("Could not find latest BEP listing ID")
        return []

    # January 2026 is approximately IDs 143300-144350
    # Based on probing: ID 143000=2025-12-10, ID 143500=2026-01-05,
    # ID 144200=2026-01-29, ID 144400=2026-02-04
    start_id = 143300
    end_id = 144400
    logger.info(f"Scanning BEP IDs {start_id}-{end_id} for {since} to {until}")

    since_dt = datetime.strptime(since, "%Y-%m-%d")
    until_dt = datetime.strptime(until, "%Y-%m-%d")

    results: list[AnalysisResult] = []
    matched_municipalities: set[str] = set()
    consecutive_empty = 0
    total_scanned = 0

    for cod in range(end_id, start_id - 1, -1):
        total_scanned += 1
        listing = scraper.fetch_listing(cod)
        if not listing:
            consecutive_empty += 1
            if consecutive_empty > 30:
                logger.info(f"Too many consecutive empty IDs at {cod}, stopping")
                break
            continue

        consecutive_empty = 0

        # Filter by date
        if listing.data_publicacao:
            try:
                pub_date = datetime.strptime(listing.data_publicacao, "%Y-%m-%d")
                if pub_date < since_dt:
                    logger.info(f"  Reached listings before {since}, stopping at {cod}")
                    break
                if pub_date > until_dt:
                    continue
            except ValueError:
                pass

        # Match against municipalities
        mun_lower = match_municipality(listing)
        if mun_lower:
            info = MUNICIPALITY_LOOKUP[mun_lower]
            result = AnalysisResult(
                municipality=info["municipality"],
                district=info["district"],
                previous_party=info["previous_party"],
                new_party=info["new_party"],
                data_publicacao=listing.data_publicacao,
                titulo=listing.titulo,
                entidade=listing.entidade,
                organismo=listing.organismo,
                categoria=listing.categoria,
                remuneracao=listing.remuneracao,
                data_limite=listing.data_limite,
                url=f"https://www.bep.gov.pt/pages/oferta/Oferta_Detalhes.aspx?CodOferta={cod}",
                cod_oferta=listing.cod_oferta,
            )
            results.append(result)
            matched_municipalities.add(info["municipality"])
            logger.info(f"  MATCH: {info['municipality']} - {listing.titulo}")

        if total_scanned % 50 == 0:
            logger.info(f"  Scanned {total_scanned} IDs, found {len(results)} matches...")

        if max_listings and len(results) >= max_listings:
            logger.info(f"  Reached max_listings limit ({max_listings})")
            break

        time.sleep(delay)

    # Sort by municipality → publication date → title
    results.sort(key=lambda r: (r.municipality, r.data_publicacao, r.titulo))

    logger.info(f"\n{'='*60}")
    logger.info(f"Analysis complete!")
    logger.info(f"  Total IDs scanned: {total_scanned}")
    logger.info(f"  Total matches: {len(results)}")
    logger.info(f"  Municipalities with matches: {len(matched_municipalities)}")
    logger.info(f"  Municipalities without matches: {len(MUNICIPALITY_LOOKUP) - len(matched_municipalities)}")
    logger.info(f"{'='*60}")

    return results


def export_json(results: list[AnalysisResult], path: str):
    """Export results to a structured JSON file."""
    # Group by municipality
    by_municipality: dict[str, list[dict]] = {}
    for r in results:
        mun = r.municipality
        if mun not in by_municipality:
            info = MUNICIPALITY_LOOKUP[mun.lower()]
            by_municipality[mun] = {
                "municipality": mun,
                "district": r.district,
                "previous_party": r.previous_party,
                "new_party": r.new_party,
                "job_count": 0,
                "listings": [],
            }
        by_municipality[mun]["listings"].append({
            "cod_oferta": r.cod_oferta,
            "data_publicacao": r.data_publicacao,
            "titulo": r.titulo,
            "entidade": r.entidade,
            "organismo": r.organismo,
            "categoria": r.categoria,
            "remuneracao": r.remuneracao,
            "data_limite": r.data_limite,
            "url": r.url,
        })
        by_municipality[mun]["job_count"] = len(by_municipality[mun]["listings"])

    output = {
        "title": "BEP Job Offers in Municipalities with Party Changes (January 2026)",
        "description": "Public sector job listings from municipalities where the ruling party changed after the October 2025 municipal elections.",
        "period": "2026-01-01 to 2026-01-31",
        "source": "BEP - Bolsa de Emprego Público (bep.gov.pt)",
        "election_date": "2025-10-12",
        "total_matches": len(results),
        "municipalities_with_matches": len(by_municipality),
        "municipalities_total": len(MUNICIPALITY_LOOKUP),
        "generated_at": datetime.now().isoformat(),
        "municipalities": list(by_municipality.values()),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(results)} listings to {path}", file=sys.stderr)


def export_csv(results: list[AnalysisResult], path: str):
    """Export results to a CSV file sorted by municipality → date → title."""
    fieldnames = [
        "Município", "Distrito", "Partido Anterior", "Novo Partido",
        "Data Publicação", "Título", "Entidade", "Organismo",
        "Categoria", "Remuneração", "Data Limite", "Código BEP", "URL BEP",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "Município": r.municipality,
                "Distrito": r.district,
                "Partido Anterior": r.previous_party,
                "Novo Partido": r.new_party,
                "Data Publicação": r.data_publicacao,
                "Título": r.titulo,
                "Entidade": r.entidade,
                "Organismo": r.organismo,
                "Categoria": r.categoria,
                "Remuneração": r.remuneracao,
                "Data Limite": r.data_limite,
                "Código BEP": r.cod_oferta,
                "URL BEP": r.url,
            })

    print(f"Exported {len(results)} listings to {path}", file=sys.stderr)


def print_summary(results: list[AnalysisResult]):
    """Print a human-readable summary to stdout."""
    # Group by municipality
    by_mun: dict[str, list[AnalysisResult]] = {}
    for r in results:
        by_mun.setdefault(r.municipality, []).append(r)

    print(f"\n{'='*80}")
    print(f"BEP Job Offers — Municipalities with Party Changes (January 2026)")
    print(f"{'='*80}")
    print(f"Total listings found: {len(results)}")
    print(f"Municipalities with matches: {len(by_mun)} / {len(MUNICIPALITY_LOOKUP)}")
    print(f"{'='*80}\n")

    for mun in sorted(by_mun.keys()):
        listings = by_mun[mun]
        info = MUNICIPALITY_LOOKUP[mun.lower()]
        print(f"📍 {mun} ({info['district']})")
        print(f"   {info['previous_party']} → {info['new_party']}")
        print(f"   {len(listings)} job offer(s)")
        print(f"   {'-'*70}")

        for r in sorted(listings, key=lambda x: x.data_publicacao):
            print(f"   [{r.data_publicacao}] {r.titulo}")
            if r.categoria:
                print(f"     Categoria: {r.categoria}")
            if r.remuneracao:
                print(f"     Remuneração: {r.remuneracao}")
            print(f"     {r.url}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="BEP Job Offers in Municipalities with Party Changes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Municipalities covered (40+ with party changes after Oct 2025 elections):
  Lisboa, Porto, Sintra, Guimarães, Coimbra, Faro, Setúbal, Évora,
  Viseu, Bragança, Beja, Guarda, Amadora, Cascais, Oeiras, Loures,
  Almada, Odivelas, Matosinhos, Maia, Valongo, Gondomar, and more.

Examples:
  %(prog)s                         # Full analysis (scrape + cross-ref)
  %(prog)s --dry-run               # Show municipality list only
  %(prog)s --export results.json   # Export structured JSON
  %(prog)s --export results.csv    # Export CSV for spreadsheets
  %(prog)s --delay 0.05            # Faster scraping (use responsibly)
        """
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--since", default="2026-01-01", help="Start date (default: 2026-01-01)")
    parser.add_argument("--until", default="2026-01-31", help="End date (default: 2026-01-31)")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between requests (default: 0.1s)")
    parser.add_argument("--max", type=int, default=500, help="Max listings to scan (default: 500)")
    parser.add_argument("--export", help="Export to file (.json or .csv)")
    parser.add_argument("--dry-run", action="store_true", help="Show municipality list only, don't scrape")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.dry_run:
        print(f"\nMunicipalities with party changes (October 2025 elections):\n")
        print(f"{'Municipality':<25} {'District':<15} {'Previous':<35} {'New'}")
        print(f"{'-'*25} {'-'*15} {'-'*35} {'-'*35}")
        for mun, prev, new, dist in sorted(PARTY_CHANGES, key=lambda x: x[0]):
            print(f"{mun:<25} {dist:<15} {prev:<35} {new}")
        print(f"\nTotal: {len(PARTY_CHANGES)} municipalities")
        return

    results = run_analysis(
        since=args.since,
        until=args.until,
        max_listings=args.max,
        delay=args.delay,
    )

    if args.export:
        if args.export.endswith(".csv"):
            export_csv(results, args.export)
        else:
            export_json(results, args.export)
    else:
        print_summary(results)


if __name__ == "__main__":
    main()
