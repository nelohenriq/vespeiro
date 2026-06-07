#!/usr/bin/env python3
"""Unified Entity Transparency Profile

Shows a complete transparency profile for any Portuguese public entity,
cross-referencing data from BEP (jobs), BASE.gov.pt (contracts),
DRE (official gazette), and Law projects (parliament).

Usage:
    python entity_profile.py "Câmara Municipal de Gaia"
    python entity_profile.py --nif 500014872
    python entity_profile.py --nif 500014872 --export profile.json
    python entity_profile.py --list  # List top entities by listing count
    python entity_profile.py "Saúde" --section contracts  # Only show contracts
"""

import sys
import json
import re
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

# Paths
SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
DRE_DB = SCRIPT_DIR / "dre_index.db"
LAW_DB = SCRIPT_DIR / "law_index.db"
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"

NIF_MAPPING_FILE = SCRIPT_DIR / "data" / "nif_mapping.json"
BASE_DETAIL_URL = "https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id="


# =============================================================================
# NIF MAPPING (Câmara → Município bridge)
# =============================================================================

def _load_nif_mapping() -> dict:
    """Load the Câmara↔Município NIF mapping.

    Returns two dicts:
    - camara_to_municipio: maps Câmara NIF → Município NIF
    - municipio_to_camara: maps Município NIF → Câmara NIF
    """
    if not NIF_MAPPING_FILE.exists():
        return {}, {}
    try:
        with open(NIF_MAPPING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        mappings = data.get("mappings", []) if isinstance(data, dict) else data
        camara_to_muni = {}
        muni_to_camara = {}
        for m in mappings:
            cn = m.get("camara_nif", "")
            mn = m.get("municipio_nif", "")
            if cn and mn:
                camara_to_muni[cn] = mn
                muni_to_camara[mn] = cn
        return camara_to_muni, muni_to_camara
    except (json.JSONDecodeError, KeyError):
        return {}, {}


# Load once at module import
camara_to_municipio, municipio_to_camara = _load_nif_mapping()


def search_entities(query: str = "", nif: str = "", limit: int = 20) -> list[dict]:
    """Search BEP entities by name or NIF."""
    conn = sqlite3.connect(str(BEP_DB))
    if nif:
        rows = conn.execute(
            "SELECT id, display_name, entidade, organismo, nif, listing_count "
            "FROM bep_entities WHERE nif = ? ORDER BY listing_count DESC",
            (nif,),
        ).fetchall()
    elif query:
        rows = conn.execute(
            "SELECT id, display_name, entidade, organismo, nif, listing_count "
            "FROM bep_entities WHERE display_name LIKE ? OR entidade LIKE ? "
            "OR organismo LIKE ? ORDER BY listing_count DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, display_name, entidade, organismo, nif, listing_count "
            "FROM bep_entities ORDER BY listing_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "display_name": r[1], "entidade": r[2], "organismo": r[3],
         "nif": r[4], "listing_count": r[5]}
        for r in rows
    ]


def get_entity_listings(entity_id: str) -> list[dict]:
    """Get all BEP job listings for an entity."""
    conn = sqlite3.connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT cod_oferta, titulo, estado, categoria, tipo_oferta, "
        "remuneracao, total_postos, local_trabalho, data_publicacao, "
        "data_limite, url, funcoes "
        "FROM bep_listings WHERE entity_id = ? ORDER BY data_publicacao DESC",
        (entity_id,),
    ).fetchall()
    conn.close()
    return [
        {"cod_oferta": r[0], "titulo": r[1], "estado": r[2], "categoria": r[3],
         "tipo_oferta": r[4], "remuneracao": r[5], "total_postos": r[6],
         "local_trabalho": r[7], "data_publicacao": r[8], "data_limite": r[9],
         "url": r[10], "funcoes": r[11]}
        for r in rows
    ]


def get_entity_contracts(nif: str, entity_name: str = "", entidade: str = "") -> list[dict]:
    """Get BASE.gov.pt contracts for an entity by NIF.

    Uses the Câmara↔Município NIF mapping to bridge the data gap when the
    BEP NIF (Câmara) differs from the BASE NIF (Município). Falls back to
    name-based matching only as a last resort.
    """
    if not CONTRACT_CACHE.exists():
        return []
    with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
        index = json.load(f)

    # Strategy 1: Direct NIF lookup
    contracts = index.get(nif, []) if nif else []

    # Strategy 2: NIF mapping (Câmara → Município or vice versa)
    if not contracts and nif:
        mapped_nif = camara_to_municipio.get(nif) or municipio_to_camara.get(nif)
        if mapped_nif:
            contracts = index.get(mapped_nif, [])

    # Strategy 3: Name-based fallback (last resort)
    if not contracts and entity_name:
        contracts = _find_contracts_by_name(index, entity_name, nif)

    # Add detail page URLs
    for c in contracts:
        cid = c.get("contract_id")
        c["detail_url"] = f"{BASE_DETAIL_URL}{cid}" if cid else ""
    # Sort by date descending
    contracts.sort(key=lambda c: c.get("data", ""), reverse=True)
    return contracts


from utils import extract_location as _extract_location


def _find_contracts_by_name(index: dict, entity_name: str,
                           skip_nif: str = "") -> list[dict]:
    """Find contracts by fuzzy name matching against the contract index.

    Builds a temporary name→NIF lookup and matches on location names.
    """
    location = _extract_location(entity_name)
    if len(location) < 4:  # too short to match reliably
        return []

    from unidecode import unidecode

    candidates = []
    for nif_key, contracts in index.items():
        if nif_key == skip_nif:
            continue
        if not contracts:
            continue
        # Get the entity name from the first contract
        first_name = contracts[0].get("entity_name", "")
        if not first_name:
            continue
        normalized = unidecode(first_name.lower().strip())
        # Match if location name appears in the contract entity name
        if location in normalized or normalized.endswith(location):
            candidates.append((nif_key, first_name, len(contracts)))

    # Deduplicate and sort by contract count (most contracts = most likely match)
    seen = set()
    matched_contracts = []
    for nif_key, name, count in sorted(candidates, key=lambda x: -x[2]):
        if nif_key not in seen:
            seen.add(nif_key)
            matched_contracts.extend(index[nif_key])
    return matched_contracts


def get_entity_dre(entity_name: str) -> list[dict]:
    """Search DRE publications for mentions of the entity name."""
    if not DRE_DB.exists():
        return []
    conn = sqlite3.connect(str(DRE_DB))
    # Search in publication titles and document titles
    rows = conn.execute(
        "SELECT pub_id, serie, numero, year, title, eli_url, redirect_url "
        "FROM dre_publications WHERE title LIKE ? OR eli_url LIKE ? "
        "ORDER BY year DESC, serie DESC, numero DESC LIMIT 20",
        (f"%{entity_name}%", f"%{entity_name}%"),
    ).fetchall()
    conn.close()
    return [
        {"pub_id": r[0], "serie": r[1], "numero": r[2], "year": r[3],
         "title": r[4], "eli_url": r[5], "redirect_url": r[6]}
        for r in rows
    ]


def get_entity_laws(entity_name: str) -> list[dict]:
    """Search law projects for mentions of the entity name."""
    if not LAW_DB.exists():
        return []
    conn = sqlite3.connect(str(LAW_DB))
    rows = conn.execute(
        "SELECT ini_id, ini_nr, legislatura, ini_desc_tipo, ini_titulo, "
        "autor_gp, latest_fase, latest_fase_date, vote_result "
        "FROM law_projects WHERE ini_titulo LIKE ? OR autor_gp LIKE ? "
        "ORDER BY latest_fase_date DESC LIMIT 20",
        (f"%{entity_name}%", f"%{entity_name}%"),
    ).fetchall()
    conn.close()
    return [
        {"ini_id": r[0], "ini_nr": r[1], "legislatura": r[2],
         "ini_desc_tipo": r[3], "ini_titulo": r[4], "autor_gp": r[5],
         "latest_fase": r[6], "latest_fase_date": r[7], "vote_result": r[8]}
        for r in rows
    ]


def compute_contract_trends(contracts: list[dict]) -> dict:
    """Aggregate contract values by month."""
    by_month = defaultdict(lambda: {"count": 0, "value": 0.0})
    for c in contracts:
        date = c.get("data", "")
        if date and len(date) >= 7:
            month = date[:7]  # YYYY-MM
            by_month[month]["count"] += 1
            by_month[month]["value"] += c.get("valor", 0)
    return dict(sorted(by_month.items()))


def compute_hiring_trends(listings: list[dict]) -> dict:
    """Aggregate BEP hiring by month based on data_publicacao."""
    by_month = defaultdict(lambda: {"count": 0, "positions": 0})
    for l in listings:
        pub = l.get("data_publicacao", "")
        if pub and len(pub) >= 7:
            month = pub[:7]
            by_month[month]["count"] += 1
            try:
                by_month[month]["positions"] += int(l.get("total_postos", 1) or 1)
            except (ValueError, TypeError):
                by_month[month]["positions"] += 1
    return dict(sorted(by_month.items()))


def render_ascii_chart(data: dict, value_key: str, width: int = 50, currency: bool = True) -> str:
    """Render a simple ASCII bar chart from a dict of {period: {value_key: N}}."""
    if not data:
        return ""
    values = [d.get(value_key, 0) for d in data.values()]
    max_val = max(values) if values else 1
    if max_val == 0:
        return ""
    lines = []
    for period, d in data.items():
        val = d.get(value_key, 0)
        bar_len = int((val / max_val) * width) if max_val > 0 else 0
        bar = "█" * bar_len
        if currency and isinstance(val, float) and val >= 1000:
            val_str = f"€{val:,.0f}"
        elif currency and isinstance(val, float):
            val_str = f"€{val:,.2f}"
        else:
            val_str = str(val)
        lines.append(f"  {period}  {bar} {val_str}")
    return "\n".join(lines)


def print_entity_profile(entity: dict, listings: list, contracts: list,
                         dre: list, laws: list, sections: list[str] | None = None):
    """Print the full entity transparency profile."""
    show_all = sections is None or "all" in sections
    show_jobs = show_all or "jobs" in sections
    show_contracts = show_all or "contracts" in sections
    show_dre = show_all or "dre" in sections
    show_laws = show_all or "laws" in sections

    nif = entity.get("nif", "")
    total_value = sum(c.get("valor", 0) for c in contracts)

    print(f"\n{'='*80}")
    print(f"  🔍 TRANSPARENCY PROFILE: {entity['display_name']}")
    print(f"{'='*80}")
    # Show paired NIF if available
    paired_nif = camara_to_municipio.get(nif) or municipio_to_camara.get(nif)
    paired_label = "Município NIF" if nif in camara_to_municipio else "Câmara NIF"
    if paired_nif:
        print(f"  NIF:        {nif or 'N/A'} → {paired_label}: {paired_nif}")
        print(f"  BASE.gov:   https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={paired_nif}")
    else:
        print(f"  NIF:        {nif or 'N/A'}")
        if nif:
            print(f"  BASE.gov:   https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={nif}")
    print(f"  Department: {entity['entidade'][:70]}")
    print(f"  Org:        {entity['organismo'][:70]}")
    print(f"  BEP Jobs:   {entity['listing_count']} listings")
    print(f"  Contracts:  {len(contracts)} | Value: €{total_value:,.2f}")
    print(f"  DRE:        {len(dre)} publications")
    print(f"  Laws:       {len(laws)} projects")
    print(f"{'='*80}\n")

    # --- BEP Job Listings ---
    if show_jobs and listings:
        print(f"  📋 BEP JOB LISTINGS ({len(listings)})")
        print(f"  {'-'*70}")
        for i, l in enumerate(listings[:20]):
            status_icon = "🟢" if "aberta" in (l["estado"] or "").lower() else "⚪"
            print(f"  {status_icon} {l['titulo'][:65]}")
            detail = []
            if l["categoria"]:
                detail.append(l["categoria"])
            if l["remuneracao"]:
                detail.append(f"€{l['remuneracao']}")
            if l["total_postos"] and l["total_postos"] != "1":
                detail.append(f"{l['total_postos']} positions")
            if l["data_limite"]:
                detail.append(f"deadline: {l['data_limite'][:10]}")
            if detail:
                print(f"     {' | '.join(detail)}")
            if l["url"]:
                print(f"     🔗 {l['url']}")
            print()
        if len(listings) > 20:
            print(f"  ... and {len(listings) - 20} more listings\n")

    # --- BASE Contracts ---
    if show_contracts and contracts:
        print(f"  📦 BASE.GOV.PT CONTRACTS ({len(contracts)}, €{total_value:,.2f} total)")
        print(f"  {'-'*70}")
        for c in contracts[:15]:
            valor = f"€{c.get('valor', 0):,.2f}" if c.get("valor") else "N/A"
            print(f"  [{c.get('data', '?')}] {valor}  {c.get('tipo', '')}")
            if c.get("objeto"):
                print(f"     {c['objeto'][:70]}")
            if c.get("detail_url"):
                print(f"     📋 {c['detail_url']}")
            if c.get("link_pecas_proc"):
                print(f"     📎 {c['link_pecas_proc'][:90]}")
            print()
        if len(contracts) > 15:
            print(f"  ... and {len(contracts) - 15} more contracts\n")

    # --- DRE Publications ---
    if show_dre and dre:
        print(f"  📰 DRE PUBLICATIONS ({len(dre)})")
        print(f"  {'-'*70}")
        for d in dre[:10]:
            print(f"  Serie {d['serie']} #{d['numero']}/{d['year']}")
            if d.get("title"):
                print(f"     {d['title'][:70]}")
            if d.get("redirect_url"):
                print(f"     🔗 {d['redirect_url']}")
            print()
        if len(dre) > 10:
            print(f"  ... and {len(dre) - 10} more publications\n")

    # --- Law Projects ---
    if show_laws and laws:
        print(f"  ⚖️  LAW PROJECTS ({len(laws)})")
        print(f"  {'-'*70}")
        for l in laws[:10]:
            fase = l.get("latest_fase", "?")
            date = l.get("latest_fase_date", "?")
            print(f"  [{l.get('ini_desc_tipo', '?')}] {l.get('ini_titulo', '?')[:60]}")
            print(f"     Phase: {fase} ({date})")
            if l.get("vote_result"):
                print(f"     Vote: {l['vote_result']}")
            print()

    # --- Temporal Trends ---
    show_trends = show_all or "trends" in sections
    if show_trends:
        contract_trends = compute_contract_trends(contracts)
        hiring_trends = compute_hiring_trends(listings)

        if contract_trends or hiring_trends:
            print(f"  📈 TEMPORAL TRENDS")
            print(f"  {'-'*70}")

            if contract_trends:
                total_months = len(contract_trends)
                total_value = sum(d["value"] for d in contract_trends.values())
                total_contracts = sum(d["count"] for d in contract_trends.values())
                avg_monthly = total_value / total_months if total_months else 0
                print(f"\n  Contract Value by Month ({total_contracts} contracts, €{total_value:,.0f} total):")
                print(f"  Average: €{avg_monthly:,.0f}/month")
                chart = render_ascii_chart(contract_trends, "value")
                if chart:
                    print(chart)
                print()

            if hiring_trends:
                total_months = len(hiring_trends)
                total_listings = sum(d["count"] for d in hiring_trends.values())
                total_positions = sum(d["positions"] for d in hiring_trends.values())
                avg_monthly = total_listings / total_months if total_months else 0
                print(f"  BEP Hiring by Month ({total_listings} listings, {total_positions} positions):")
                print(f"  Average: {avg_monthly:.1f} listings/month")
                chart = render_ascii_chart(hiring_trends, "count", currency=False)
                if chart:
                    print(chart)
                print()

    # --- Summary ---
    if not any([show_jobs and listings, show_contracts and contracts,
                show_dre and dre, show_laws and laws]):
        print("  No cross-referenced data found for this entity.\n")


def export_profile(entity: dict, listings: list, contracts: list,
                   dre: list, laws: list, output_path: str):
    """Export the full profile to JSON."""
    total_value = sum(c.get("valor", 0) for c in contracts)
    profile = {
        "entity": entity,
        "summary": {
            "bep_listings": len(listings),
            "base_contracts": len(contracts),
            "base_total_value": total_value,
            "dre_publications": len(dre),
            "law_projects": len(laws),
        },
        "contract_trends": compute_contract_trends(contracts),
        "hiring_trends": compute_hiring_trends(listings),
        "listings": listings,
        "contracts": contracts,
        "dre_publications": dre,
        "law_projects": laws,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"\nExported to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Unified Entity Transparency Profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", default="", help="Entity name to search for")
    parser.add_argument("--nif", default="", help="Filter by NIF number")
    parser.add_argument("--export", help="Export to JSON file")
    parser.add_argument("--list", action="store_true", help="List top entities")
    parser.add_argument("--section", default="",
                        help="Show specific section(s): jobs,contracts,dre,laws,trends (comma-separated)")

    args = parser.parse_args()

    if args.list:
        entities = search_entities(limit=20)
        print(f"\n  Top 20 BEP Entities by Listing Count:")
        print(f"  {'-'*60}")
        for e in entities:
            print(f"  {e['listing_count']:4d} listings  {e['nif'] or 'N/A':>10s}  {e['display_name'][:50]}")
        print()
        return

    if not args.query and not args.nif:
        parser.print_help()
        sys.exit(1)

    # Search for entities
    entities = search_entities(query=args.query, nif=args.nif, limit=10)
    if not entities:
        print(f"No entities found matching '{args.query or args.nif}'")
        sys.exit(1)

    if len(entities) > 1:
        print(f"\n  Found {len(entities)} matching entities:")
        for i, e in enumerate(entities):
            print(f"  [{i+1}] {e['display_name']} (NIF: {e['nif'] or 'N/A'}, {e['listing_count']} listings)")
        print(f"\n  Showing first match. Use --nif for exact match.\n")

    entity = entities[0]
    sections = [s.strip() for s in args.section.split(",")] if args.section else None

    print(f"\nLoading data for {entity['display_name']}...")

    listings = get_entity_listings(entity["id"])
    print(f"  BEP listings: {len(listings)}")

    contracts = get_entity_contracts(
        entity.get("nif", ""),
        entity_name=entity.get("display_name", ""),
        entidade=entity.get("entidade", ""),
    )
    print(f"  BASE contracts: {len(contracts)}")

    dre = get_entity_dre(entity["display_name"])
    print(f"  DRE publications: {len(dre)}")

    laws = get_entity_laws(entity["display_name"])
    print(f"  Law projects: {len(laws)}")

    print_entity_profile(entity, listings, contracts, dre, laws, sections)

    if args.export:
        export_profile(entity, listings, contracts, dre, laws, args.export)


if __name__ == "__main__":
    main()
