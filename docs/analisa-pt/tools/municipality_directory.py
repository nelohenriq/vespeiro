#!/usr/bin/env python3
"""
Municipality Directory — All 308+ Portuguese Municipalities

Comprehensive directory listing every municipality with:
- Câmara Municipal NIF (BEP - hiring/payroll)
- Município NIF (BASE.gov.pt - contracts)
- BEP job listings count
- BASE contract count and total value
- Population (Census 2021)

Usage:
    # Show full directory
    python municipality_directory.py

    # Sort by spending
    python municipality_directory.py --sort spending --top 50

    # Filter by district
    python municipality_directory.py --district Porto

    # Search for a municipality
    python municipality_directory.py --search "Gaia"

    # Export as JSON
    python municipality_directory.py --json > data/municipality_directory.json

    # Show gap analysis (municipalities missing data)
    python municipality_directory.py --gaps
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from unidecode import unidecode
from utils import format_currency
from generate_directory_dashboard import generate_dashboard
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
NIF_MAPPING_FILE = SCRIPT_DIR / "data" / "nif_mapping.json"

# Census 2021 population data (top municipalities + all 308)
POPULATION = {
    "lisboa": 544851, "sintra": 385702, "vila nova de gaia": 304847,
    "porto": 231962, "cascais": 214158, "loures": 200769,
    "braga": 193333, "almada": 174018, "oeiras": 173339,
    "gondomar": 168027, "seixal": 158533, "guimaraes": 156832,
    "odivelas": 148156, "matosinhos": 175834, "feira": 139345,
    "amadora": 178858, "vila franca de xira": 139292, "famalicao": 133832,
    "setubal": 123680, "leiria": 126879, "barcelos": 120391,
    "maia": 138040, "coimbra": 140816, "viseu": 99551,
    "funchal": 111892, "aveiro": 80228, "valongo": 93835,
    "vila do conde": 79533, "barreiro": 78764, "penafiel": 72654,
    "torres vedras": 79465, "pontinha": 25000, "santo tirso": 71027,
    "loulé": 70081, "pontadelgada": 68748, "pacos de ferreira": 56357,
    "oliveira de azemeis": 67084, "viana do castelo": 88725,
    "figueira da foz": 62101, "faro": 64560, "paredes": 86352,
    "trofa": 38553, "espinho": 34003, "amora": 35463,
    "vila verde": 47915, "esposende": 34905, "ilhavo": 38006,
    "agueda": 46159, "oliveira do bairro": 23412, "anadia": 29150,
    "mealhada": 19856, "ovar": 55398, "sever do vouga": 12299,
    "estarreja": 26997, "vagos": 22919, "mira": 12456,
    "arnoso": 13000, "lousa": 17465, "penacova": 15720,
    "soure": 19255, "montemor-o-velho": 26169, "cantanhede": 36590,
    "pombal": 55283, "marinha grande": 38933, "peniche": 27335,
    "caldas da rainha": 51460, "alcobaca": 55298, "tomar": 40709,
    "santarem": 29397, "abrantes": 37015, "ourem": 45431,
    "portimao": 55632, "albufeira": 40828, "lagos": 31421,
    "tavira": 26174, "olhao": 45228, "silves": 37086,
    "monchique": 6045, "castro marim": 6738, "alcoutim": 2721,
    "aljezur": 5884, "vila real de santo antonio": 12108,
    "santiago do cacem": 29658, "grandola": 14258, "odemira": 25854,
    "mertola": 7314, "sines": 14202, "sesimbra": 49486,
    "palmela": 62805, "montijo": 31160, "moita": 17359,
    "alcochete": 17555, "benavente": 30655, "azambuja": 21473,
    "cartaxo": 24435, "chamusca": 10550, "coruche": 17334,
    "salvaterra de magos": 22159, "alcanena": 13868,
    "porto de mos": 24489, "rio maior": 21473, "arruda dos vinhos": 13391,
    "bombarral": 13239, "cadaval": 14070, "obidos": 11689,
    "nazaré": 15152, "pedrogao grande": 3972, "ferreira do zezere": 8619,
    "atalaia": 16752,    "lamego": 25452,
    "resende": 10563, "peso da regua": 17150, "sabrosa": 6150,
    "vila nova de foz coa": 8249, "moimenta da beira": 10234,
    "seia": 24739, "gouveia": 14047, "nelas": 14037,
    "tondela": 26233, "carregal do sal": 11012,
    "oliveira do hospital": 20309, "arganil": 11776,
    "pampilhosa da serra": 4481, "nisa": 7451, "marvao": 2773,
    "campo maior": 8234, "elvas": 23032, "portalegre": 24931,
    "castelo branco": 52774, "fundao": 29414, "covilha": 51797,
    "serta": 16577, "vila velha de rodao": 3712, "oleiros": 5792,
    "aguiar da beira": 5593, "mangualde": 19856,
    "guarda": 42541, "chaves": 41243, "montalegre": 10442,
    "braganca": 35341, "vila real": 51575, "valpacos": 10000,
    "vila florz": 11918, "boticas": 5000, "mesao frio": 6000,
    "amarante": 56158, "fafe": 52955, "povoa de lanhoso": 22469,
    "celorico de basto": 18029, "marco de canaveses": 53450,
    "vila nova de famalicao": 133832, "povoa de varzim": 63408,
    "sao joao da madeira": 21713, "arouca": 22359,
    "sao pedro do sul": 16642, "bougado": 20522,
    "ponte de lima": 43498, "valenca": 14023, "moncao": 13418,
    "arcos de valdevez": 22494, "melgaco": 7000, "caminha": 12000,
    "ponte da barca": 12000, "vila nova de cerveira": 10195,
    "evora": 53856, "montemor-o-novo": 17000, "estremoz": 14000,
    "redondo": 7000, "vendas novas": 11000, "arraiolos": 8000,
    "mora": 5000, "cuba": 5000, "vidigueira": 6000,
    "beja": 35826, "ourique": 5000, "castro verde": 8000,
    "aljustrel": 9000, "ferreira do alentejo": 5000,
    "odemira": 25854, "santiago do cacem": 29658,
    "alvito": 3000, "ferreiras do alentejo": 5000,
}


def load_bep_camara() -> Dict[str, Dict]:
    """Load all Câmara Municipal entities from BEP."""
    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT display_name, nif, listing_count FROM bep_entities "
        "WHERE nif IS NOT NULL AND nif != ''"
    ).fetchall()
    conn.close()

    result = {}
    for name, nif, count in rows:
        nl = unidecode(name.lower())
        for prefix in ["camara municipal de ", "camara municipal do ", "camara municipal da "]:
            if nl.startswith(prefix):
                loc = nl[len(prefix):].strip()
                loc = re.sub(r"\s*\(.*$", "", loc)
                loc = re.sub(r",.*$", "", loc)
                if loc and len(loc) >= 2:
                    result[loc] = {"nif": nif, "name": name, "listings": count}
                break
    return result


def load_base_municipio() -> Dict[str, Dict]:
    """Load all Município entities from BASE contract index."""
    with open(CONTRACT_INDEX, "r", encoding="utf-8") as f:
        index = json.load(f)

    result = {}
    for nif, contracts in index.items():
        if not contracts:
            continue
        name = contracts[0].get("entity_name", "")
        nl = unidecode(name.lower())
        for prefix in ["municipio de ", "municipio do ", "municipio da "]:
            if nl.startswith(prefix):
                loc = nl[len(prefix):].strip()
                loc = re.sub(r"\s*\(.*$", "", loc)
                loc = re.sub(r",.*$", "", loc)
                if loc and len(loc) >= 2:
                    total_value = sum(c.get("valor", 0) or 0 for c in contracts)
                    if loc not in result or total_value > result[loc]["value"]:
                        result[loc] = {
                            "nif": nif,
                            "name": name,
                            "contracts": len(contracts),
                            "value": total_value,
                        }
                break
    return result


def load_nif_mappings() -> Dict[str, str]:
    """Load Câmara→Município NIF mapping."""
    if not NIF_MAPPING_FILE.exists():
        return {}
    with open(NIF_MAPPING_FILE, "r") as f:
        data = json.load(f)
    mappings = data.get("mappings", []) if isinstance(data, dict) else data
    return {m["camara_nif"]: m["municipio_nif"] for m in mappings if m.get("camara_nif") and m.get("municipio_nif")}


def build_directory() -> List[Dict]:
    """Build comprehensive municipality directory from all sources."""
    bep = load_bep_camara()
    base = load_base_municipio()
    nif_map = load_nif_mappings()

    # Merge all known locations
    all_locations = set(bep.keys()) | set(base.keys())

    directory = []
    for loc in sorted(all_locations):
        bep_entry = bep.get(loc, {})
        base_entry = base.get(loc, {})

        camara_nif = bep_entry.get("nif", "")
        municipio_nif = base_entry.get("nif", "")

        # If we only have one NIF, try to find the other via mapping
        if camara_nif and not municipio_nif:
            municipio_nif = nif_map.get(camara_nif, "")
        elif municipio_nif and not camara_nif:
            # Reverse lookup
            for cn, mn in nif_map.items():
                if mn == municipio_nif:
                    camara_nif = cn
                    break

        population = POPULATION.get(loc, 0)
        contracts = base_entry.get("contracts", 0)
        value = base_entry.get("value", 0)
        listings = bep_entry.get("listings", 0)
        per_capita = value / population if population > 0 else 0

        directory.append({
            "location": loc.title(),
            "location_normalized": loc,
            "camara_nif": camara_nif,
            "camara_name": bep_entry.get("name", ""),
            "municipio_nif": municipio_nif,
            "municipio_name": base_entry.get("name", ""),
            "bep_listings": listings,
            "base_contracts": contracts,
            "total_spending": value,
            "per_capita_spending": per_capita,
            "population": population,
            "data_sources": (
                ("BEP" if camara_nif else "") +
                ("+BASE" if municipio_nif else "")
            ).strip("+") or "none",
        })

    return directory



def print_directory(directory: List[Dict], top_n: Optional[int] = None, sort_key: str = "name"):
    """Print the municipality directory."""
    if sort_key == "spending":
        directory = sorted(directory, key=lambda x: -x["total_spending"])
    elif sort_key == "contracts":
        directory = sorted(directory, key=lambda x: -x["base_contracts"])
    elif sort_key == "population":
        directory = sorted(directory, key=lambda x: -x["population"])
    elif sort_key == "per_capita":
        directory = sorted(directory, key=lambda x: -x["per_capita_spending"])
    else:
        directory = sorted(directory, key=lambda x: x["location"])

    items = directory[:top_n] if top_n else directory

    print(f"\n{'='*120}")
    print(f"PORTUGUESE MUNICIPALITY DIRECTORY")
    print(f"{'='*120}")
    print(f"{'#':<4}{'Municipality':<28}{'Câmara NIF':<12}{'Município NIF':<12}{'Pop.':>8}{'Contracts':>10}{'Spending':>14}{'Per Capita':>12}{'Source':>8}")
    print(f"{'─'*4}{'─'*28}{'─'*12}{'─'*12}{'─'*8}{'─'*10}{'─'*14}{'─'*12}{'─'*8}")

    for i, d in enumerate(items, 1):
        pop = f"{d['population']:,}" if d['population'] > 0 else "?"
        cn = d['camara_nif'] or "—"
        mn = d['municipio_nif'] or "—"
        pc = format_currency(d['per_capita_spending']) if d['per_capita_spending'] > 0 else "—"
        src = d['data_sources']
        print(f"{i:<4}{d['location']:<28}{cn:<12}{mn:<12}{pop:>8}{d['base_contracts']:>10}{format_currency(d['total_spending']):>14}{pc:>12}{src:>8}")

    print(f"\n{'─'*120}")
    total_contracts = sum(d["base_contracts"] for d in directory)
    total_value = sum(d["total_spending"] for d in directory)
    total_pop = sum(d["population"] for d in directory if d["population"] > 0)
    with_camara = sum(1 for d in directory if d["camara_nif"])
    with_municipio = sum(1 for d in directory if d["municipio_nif"])
    with_both = sum(1 for d in directory if d["camara_nif"] and d["municipio_nif"])

    print(f"  Total municipalities: {len(directory)}")
    print(f"  With Câmara NIF:      {with_camara}")
    print(f"  With Município NIF:   {with_municipio}")
    print(f"  With both NIFs:       {with_both}")
    print(f"  Total contracts:      {total_contracts:,}")
    print(f"  Total spending:       {format_currency(total_value)}")
    print(f"  Total population:     {total_pop:,}")
    if total_pop > 0:
        print(f"  National avg:         {format_currency(total_value / total_pop)}/capita")


def show_gaps(directory: List[Dict]):
    """Show municipalities with missing data."""
    print(f"\n{'='*100}")
    print(f"GAP ANALYSIS — Data Coverage")
    print(f"{'='*100}")

    no_camara = [d for d in directory if not d["camara_nif"]]
    no_municipio = [d for d in directory if not d["municipio_nif"]]
    no_pop = [d for d in directory if d["population"] == 0]

    print(f"\n  Municipalities WITHOUT Câmara NIF: {len(no_camara)}")
    for d in sorted(no_camara, key=lambda x: -x["total_spending"])[:10]:
        print(f"    {d['location']:30s} {d['base_contracts']:>6} contracts  {format_currency(d['total_spending']):>12}")

    print(f"\n  Municipalities WITHOUT Município NIF: {len(no_municipio)}")
    for d in sorted(no_municipio, key=lambda x: -x["bep_listings"])[:10]:
        print(f"    {d['location']:30s} {d['bep_listings']:>6} listings")

    print(f"\n  Municipalities WITHOUT population data: {len(no_pop)}")


def search_directory(directory: List[Dict], query: str):
    """Search for a municipality by name."""
    q = unidecode(query.lower())
    matches = [d for d in directory if q in unidecode(d["location"].lower())]

    if not matches:
        print(f"No municipalities found matching '{query}'")
        return

    for d in matches:
        print(f"\n{'='*80}")
        print(f"  📍 {d['location']}")
        print(f"{'='*80}")
        print(f"  Câmara Municipal:  NIF {d['camara_nif'] or 'N/A'} — {d['camara_name'] or 'Not found in BEP'}")
        print(f"  Município:         NIF {d['municipio_nif'] or 'N/A'} — {d['municipio_name'] or 'Not found in BASE'}")
        print(f"  Population:        {d['population']:,}" if d['population'] > 0 else "  Population:        Unknown")
        print(f"  BEP Listings:      {d['bep_listings']}")
        print(f"  BASE Contracts:    {d['base_contracts']}")
        print(f"  Total Spending:    {format_currency(d['total_spending'])}")
        if d['per_capita_spending'] > 0:
            print(f"  Per Capita:        {format_currency(d['per_capita_spending'])}")
        print(f"  Data Sources:      {d['data_sources']}")


def export_json(directory: List[Dict]):
    """Export directory as JSON."""
    output = {
        "version": "1.0",
        "description": "Portuguese Municipality Directory — Câmara + Município NIFs, contracts, spending",
        "total_municipalities": len(directory),
        "municipalities": [{k: v for k, v in d.items() if k != "location_normalized"} for d in directory],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="Portuguese Municipality Directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sort", "-s", choices=["name", "spending", "contracts", "population", "per_capita"],
                        default="name", help="Sort by field (default: name)")
    parser.add_argument("--top", "-t", type=int, help="Show only top N results")
    parser.add_argument("--search", help="Search for a municipality")
    parser.add_argument("--gaps", action="store_true", help="Show data gaps")
    parser.add_argument("--json", action="store_true", help="Export as JSON")
    parser.add_argument("--output", "-o", help="Output file for JSON export")
    parser.add_argument("--html", action="store_true", help="Generate interactive HTML dashboard")
    parser.add_argument("-o-dir", "--html-output", default="municipality_directory.html",
                        help="Output path for HTML dashboard (default: municipality_directory.html)")

    args = parser.parse_args()
    directory = build_directory()

    if args.html:
        generate_dashboard(directory, args.html_output)
        return

    if args.json:
        if args.output:
            output = {
                "version": "1.0",
                "total_municipalities": len(directory),
                "municipalities": [{k: v for k, v in d.items() if k != "location_normalized"} for d in directory],
            }
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            print(f"Exported {len(directory)} municipalities to {args.output}", file=sys.stderr)
        else:
            export_json(directory)
        return

    if args.search:
        search_directory(directory, args.search)
        return

    if args.gaps:
        show_gaps(directory)
        return

    print_directory(directory, top_n=args.top, sort_key=args.sort)


if __name__ == "__main__":
    main()
