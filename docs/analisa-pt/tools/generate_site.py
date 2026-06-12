#!/usr/bin/env python3
"""Generate a linked static site from all Analisa.pt dashboard generators.

Produces a self-contained static site under a single output directory with:
  - index.html          (navigation hub with stats)
  - combined.html       (multi-panel combined dashboard)
  - network.html        (D3.js correlation network)
  - sectors.html        (sector overview dashboard)
  - entity_<NIF>.html   (individual entity profiles for top entities)
  - contracts.json      (companion file for lazy-loading)

Usage:
    python generate_site.py -o site/
    python generate_site.py -o site/ --top 20
    python generate_site.py -o site/ --top 10 --entities 5
"""

import sys
import json
import argparse
import webbrowser
import importlib.util
from pathlib import Path
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"


import html as html_mod
from utils_db import connect as db_connect


def _esc(s):
    return html_mod.escape(str(s)) if s else ""


# ---------------------------------------------------------------------------
# Data loading (shared with other generators)
# ---------------------------------------------------------------------------

def load_all_entities():
    if not BEP_DB.exists():
        return []
    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT id, display_name, entidade, organismo, nif, listing_count "
        "FROM bep_entities WHERE listing_count > 0 ORDER BY listing_count DESC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "display_name": r[1], "entidade": r[2],
         "organismo": r[3], "nif": r[4], "listing_count": r[5]}
        for r in rows
    ]


def load_contracts():
    if not CONTRACT_CACHE.exists():
        return {}
    try:
        with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def load_all_listings():
    if not BEP_DB.exists():
        return {}
    conn = db_connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT entity_id, titulo, estado, categoria, tipo_oferta, "
        "remuneracao, total_postos, data_publicacao, local_trabalho "
        "FROM bep_listings ORDER BY data_publicacao DESC"
    ).fetchall()
    conn.close()
    grouped = defaultdict(list)
    for r in rows:
        grouped[r[0]].append({
            "titulo": r[1], "estado": r[2], "categoria": r[3],
            "tipo_oferta": r[4], "remuneracao": r[5],
            "total_postos": r[6], "data_publicacao": r[7],
            "local_trabalho": r[8] or "",
        })
    return dict(grouped)


# ---------------------------------------------------------------------------
# Module loader — imports sibling generators at runtime
# ---------------------------------------------------------------------------

def _load_generator(name):
    """Import a sibling generate_*.py module by name (without .py)."""
    path = SCRIPT_DIR / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Index page builder
# ---------------------------------------------------------------------------

def build_index_html(site_dir, stats, top_entities):
    """Build the index.html navigation hub."""
    entity_rows = ""
    for e in top_entities:
        nif = e.get("nif", "")
        fname = f"entity_{nif}.html" if nif else "#"
        entity_rows += (
            f'<tr><td><a href="{fname}">{_esc(e["display_name"][:40])}</a></td>'
            f'<td>{_esc((e.get("entidade") or "N/A")[:30])}</td>'
            f'<td class="num">{e.get("listing_count", 0)}</td>'
            f'<td><a href="{fname}" class="btn btn-sm">View</a></td></tr>\n'
        )

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f'''<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Analisa.pt — Static Site</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0f172a; color: #e2e8f0; min-height: 100vh; }}

.header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
           border-bottom: 1px solid #334155; padding: 2rem 3rem; }}
.header h1 {{ font-size: 1.8rem; color: #f8fafc; margin-bottom: 0.3rem; }}
.header .sub {{ color: #94a3b8; font-size: 0.9rem; }}
.header .date {{ color: #64748b; font-size: 0.75rem; margin-top: 0.4rem; }}

.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem 3rem; }}

/* Stats row */
.stats {{ display: flex; gap: 1.5rem; margin-bottom: 2rem; flex-wrap: wrap; }}
.stat {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px;
         padding: 1.2rem 1.5rem; min-width: 160px; flex: 1; }}
.stat .val {{ font-size: 1.6rem; font-weight: 700; color: #f8fafc; }}
.stat .lbl {{ font-size: 0.7rem; color: #94a3b8; text-transform: uppercase;
              letter-spacing: 0.05em; margin-top: 0.2rem; }}

/* View cards */
.views {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 1.2rem; margin-bottom: 2.5rem; }}
.view-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px;
              padding: 1.5rem; transition: border-color 0.2s, transform 0.15s; }}
.view-card:hover {{ border-color: #3b82f6; transform: translateY(-2px); }}
.view-card h3 {{ color: #f8fafc; font-size: 1rem; margin-bottom: 0.4rem; }}
.view-card p {{ color: #94a3b8; font-size: 0.8rem; line-height: 1.5; margin-bottom: 1rem; }}
.view-card .tag {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px;
                   font-size: 0.65rem; font-weight: 600; margin-right: 0.3rem; }}
.view-card .tag.d3 {{ background: #10b981; color: white; }}
.view-card .tag.chart {{ background: #3b82f6; color: white; }}
.view-card .tag.interactive {{ background: #f59e0b; color: #0f172a; }}
.btn {{ display: inline-block; padding: 0.5rem 1.2rem; border-radius: 8px;
        text-decoration: none; font-size: 0.85rem; font-weight: 600;
        transition: background 0.15s; }}
.btn-primary {{ background: #3b82f6; color: white; }}
.btn-primary:hover {{ background: #2563eb; }}
.btn-sm {{ background: #334155; color: #e2e8f0; padding: 0.3rem 0.7rem;
           font-size: 0.75rem; border-radius: 6px; }}
.btn-sm:hover {{ background: #3b82f6; }}

/* Entity table */
.section {{ margin-bottom: 2.5rem; }}
.section h2 {{ font-size: 1.1rem; color: #f8fafc; margin-bottom: 0.8rem;
               padding-bottom: 0.5rem; border-bottom: 1px solid #334155; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ text-align: left; color: #94a3b8; font-size: 0.7rem; text-transform: uppercase;
      letter-spacing: 0.04em; padding: 0.5rem 0.8rem; border-bottom: 1px solid #334155; }}
td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e293b; font-size: 0.82rem; }}
td a {{ color: #60a5fa; text-decoration: none; }}
td a:hover {{ text-decoration: underline; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; color: #cbd5e1; }}
tr:hover {{ background: rgba(59,130,246,0.05); }}

.footer {{ text-align: center; color: #475569; font-size: 0.7rem; padding: 2rem;
           border-top: 1px solid #334155; }}
</style>
</head>
<body>
<div class="header">
  <h1>&#x1f3d7; Analisa.pt — Static Dashboard Site</h1>
  <div class="sub">Linked views of Portuguese public procurement and transparency data</div>
  <div class="date">Generated: {date_str}</div>
</div>
<div class="container">

  <div class="stats">
    <div class="stat"><div class="val">{stats['entities']}</div><div class="lbl">Entities</div></div>
    <div class="stat"><div class="val">{stats['listings']}</div><div class="lbl">Listings</div></div>
    <div class="stat"><div class="val">{stats['contracts']}</div><div class="lbl">Contracts</div></div>
    <div class="stat"><div class="val">{stats['sectors']}</div><div class="lbl">Sectors</div></div>
  </div>

  <div class="views">
    <div class="view-card">
      <h3>&#x1f4ca; Combined Dashboard</h3>
      <p>Multi-panel view: D3.js correlation network + sector overview charts + entity detail panel. All three panels are linked.</p>
      <span class="tag d3">D3.js</span>
      <span class="tag chart">Chart.js</span>
      <span class="tag interactive">Interactive</span>
      <br><br>
      <a href="combined.html" class="btn btn-primary">Open Dashboard</a>
    </div>
    <div class="view-card">
      <h3>&#x1f310; Correlation Network</h3>
      <p>Force-directed network graph showing entity relationships by shared hiring categories. Includes Louvain community detection clustering.</p>
      <span class="tag d3">D3.js</span>
      <span class="tag interactive">Draggable</span>
      <br><br>
      <a href="network.html" class="btn btn-primary">Open Network</a>
    </div>
    <div class="view-card">
      <h3>&#x1f4cb; Sector Overview</h3>
      <p>Overview of all sectors: hiring trends, category breakdowns, and per-sector entity lists.</p>
      <span class="tag chart">Chart.js</span>
      <span class="tag interactive">Filterable</span>
      <br><br>
      <a href="sectors.html" class="btn btn-primary">Open Sectors</a>
    </div>
  </div>

  <div class="section">
    <h2>&#x1f464; Entity Profiles ({len(top_entities)} top entities)</h2>
    <table>
      <thead><tr><th>Entity</th><th>Sector</th><th style="text-align:right">Listings</th><th></th></tr></thead>
      <tbody>{entity_rows}</tbody>
    </table>
  </div>

</div>
<div class="footer">
  Analisa.pt Static Site &mdash; Generated by <code>generate_site.py</code> &mdash; {date_str}
</div>
</body>
</html>'''


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a linked static site from all Analisa.pt dashboards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-o", "--output-dir", default="site",
                        help="Output directory for the static site (default: site)")
    parser.add_argument("--top", type=int, default=50,
                        help="Show only top N entities by listing count (default: 50)")
    parser.add_argument("--entities", type=int, default=10,
                        help="Number of individual entity profiles to generate (default: 10)")
    parser.add_argument("--sector", default="",
                        help="Filter all views to a specific sector")
    parser.add_argument("--min-connections", type=int, default=1,
                        help="Minimum shared categories for entity-entity edges")
    parser.add_argument("--open", action="store_true",
                        help="Open index.html in browser after generation")
    parser.add_argument("--skip-entities", action="store_true",
                        help="Skip generating individual entity profiles")

    args = parser.parse_args()
    site_dir = Path(args.output_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {site_dir.resolve()}")

    # --- Load data ---
    print("\nLoading data...")
    entities = load_all_entities()
    if not entities:
        print("No entities found in database.")
        sys.exit(1)

    if args.top:
        entities = entities[:args.top]
    print(f"  {len(entities)} entities")

    contracts = load_contracts()
    total_contracts = sum(len(v) for v in contracts.values())
    print(f"  {total_contracts} contracts")

    all_listings = load_all_listings()
    print(f"  {sum(len(v) for v in all_listings.values())} total listings")

    # Count sectors
    sectors = defaultdict(int)
    for e in entities:
        sectors[e.get("entidade") or "Outros"] += 1

    # --- 1. Combined Dashboard ---
    print("\n[1/4] Generating combined dashboard...")
    combined_mod = _load_generator("generate_combined_view")
    if combined_mod:
        combined_out = site_dir / "combined.html"
        sys.argv = ["generate_combined_view.py",
                     "-o", str(combined_out),
                     "--top", str(args.top),
                     "--min-connections", str(args.min_connections)]
        if args.sector:
            sys.argv.extend(["--sector", args.sector])
        try:
            combined_mod.main()
            print(f"  ✅ {combined_out}")
        except SystemExit:
            print(f"  ⚠️  Combined dashboard generation failed (non-fatal)")
        finally:
            sys.argv = ["generate_site.py"]
    else:
        print("  ⚠️  generate_combined_view.py not found, skipping")

    # --- 2. Network Graph ---
    print("\n[2/4] Generating network graph...")
    network_mod = _load_generator("generate_network")
    if network_mod:
        network_out = site_dir / "network.html"
        sys.argv = ["generate_network.py",
                     "-o", str(network_out),
                     "--top", str(args.top),
                     "--min-connections", str(args.min_connections)]
        if args.sector:
            sys.argv.extend(["--sector", args.sector])
        try:
            network_mod.main()
            print(f"  ✅ {network_out}")
        except SystemExit:
            print(f"  ⚠️  Network generation failed (non-fatal)")
        finally:
            sys.argv = ["generate_site.py"]
    else:
        print("  ⚠️  generate_network.py not found, skipping")

    # --- 3. Sector Dashboard ---
    print("\n[3/4] Generating sector dashboard...")
    sector_mod = _load_generator("generate_sector_dashboard")
    if sector_mod:
        sector_out = site_dir / "sectors.html"
        sys.argv = ["generate_sector_dashboard.py",
                     "-o", str(sector_out),
                     "--top", str(args.top)]
        if args.sector:
            sys.argv.extend(["--sector", args.sector])
        try:
            sector_mod.main()
            print(f"  ✅ {sector_out}")
        except SystemExit:
            print(f"  ⚠️  Sector dashboard generation failed (non-fatal)")
        finally:
            sys.argv = ["generate_site.py"]
    else:
        print("  ⚠️  generate_sector_dashboard.py not found, skipping")

    # --- 4. Entity Profiles ---
    entity_files = []
    if not args.skip_entities:
        n_entities = min(args.entities, len(entities))
        print(f"\n[4/4] Generating {n_entities} entity profiles...")
        html_mod = _load_generator("generate_html")
        if html_mod:
            for i, e in enumerate(entities[:n_entities]):
                nif = e.get("nif", "")
                if not nif:
                    continue
                entity_out = site_dir / f"entity_{nif}.html"
                sys.argv = ["generate_html.py",
                             e["display_name"],
                             "--nif", nif,
                             "-o", str(entity_out)]
                try:
                    html_mod.main()
                    entity_files.append({"display_name": e["display_name"], "nif": nif,
                                         "entidade": e.get("entidade", ""),
                                         "listings": e.get("listing_count", 0)})
                    print(f"  ✅ [{i+1}/{n_entities}] {e['display_name'][:40]}")
                except SystemExit:
                    print(f"  ⚠️  Entity profile failed for {e['display_name'][:30]}")
                finally:
                    sys.argv = ["generate_site.py"]
        else:
            print("  ⚠️  generate_html.py not found, skipping")
    else:
        print("\n[4/4] Skipping entity profiles (--skip-entities)")

    # --- Copy companion JSON if present ---
    combined_json = site_dir / "combined_contracts.json"
    if combined_json.exists():
        print(f"  ✅ Companion JSON: {combined_json}")

    # --- Build index ---
    print("\nBuilding index.html...")
    stats = {
        "entities": len(entities),
        "listings": sum(e.get("listing_count", 0) for e in entities),
        "contracts": total_contracts,
        "sectors": len(sectors),
    }
    index_html = build_index_html(site_dir, stats, entity_files)
    index_path = site_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    print(f"  ✅ {index_path}")

    # --- Summary ---
    total_files = len(list(site_dir.glob("*.html"))) + len(list(site_dir.glob("*.json")))
    total_size = sum(f.stat().st_size for f in site_dir.iterdir() if f.is_file())
    print(f"\n{'='*50}")
    print(f"✅ Static site generated: {site_dir.resolve()}")
    print(f"   {total_files} files, {total_size / 1024:.0f} KB total")
    print(f"   Open: {index_path.resolve()}")
    print(f"{'='*50}")

    if args.open:
        webbrowser.open(index_path.resolve().as_uri())


if __name__ == "__main__":
    main()
