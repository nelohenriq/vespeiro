#!/usr/bin/env python3
"""Combined Multi-Panel Dashboard

Generates a single self-contained HTML file that combines:
  1. D3.js force-directed correlation network graph
  2. Sector-level overview charts (Chart.js)
  3. Entity profile detail panel (Chart.js)

All three panels are linked: clicking a node in the network updates
the detail panel, and clicking a sector in the overview highlights
the network.

Usage:
    python generate_combined_view.py -o combined.html
    python generate_combined_view.py --sector "Saúde" -o combined_saude.html
    python generate_combined_view.py --top 50 --open
"""

import sys
import json
import html as html_mod
import sqlite3
import argparse
import webbrowser
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_CACHE = SCRIPT_DIR / "data" / "contract_index.json"


def _esc(s):
    return html_mod.escape(str(s)) if s else ""


def _safe_int(val, default=0):
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_entities():
    if not BEP_DB.exists():
        return []
    conn = sqlite3.connect(str(BEP_DB))
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


def load_all_listings():
    if not BEP_DB.exists():
        return {}
    conn = sqlite3.connect(str(BEP_DB))
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


def load_listings_for_network():
    """Lighter load for the network graph (categories, dates, locations)."""
    if not BEP_DB.exists():
        return {}
    conn = sqlite3.connect(str(BEP_DB))
    rows = conn.execute(
        "SELECT entity_id, categoria, tipo_oferta, local_trabalho, data_publicacao "
        "FROM bep_listings"
    ).fetchall()
    conn.close()
    grouped = defaultdict(lambda: {"categories": defaultdict(int),
                                   "locations": defaultdict(int), "dates": []})
    for r in rows:
        eid = r[0]
        cat = r[1] or r[2] or "Outros"
        grouped[eid]["categories"][cat] += 1
        loc = r[3] or ""
        if loc:
            grouped[eid]["locations"][loc[:30]] += 1
        date = (r[4] or "")[:10]
        if date and len(date) >= 7:
            grouped[eid]["dates"].append(date)
    return dict(grouped)


def load_contracts():
    if not CONTRACT_CACHE.exists():
        return {}
    try:
        with open(CONTRACT_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


# ---------------------------------------------------------------------------
# Graph builder (from generate_network.py)
# ---------------------------------------------------------------------------

def build_graph(entities, net_listings, contracts, filter_sector="", min_connections=1):
    node_map = {}
    edges = []
    if filter_sector:
        entities = [e for e in entities
                    if filter_sector.lower() in (e.get("entidade") or "").lower()]

    entity_categories = {}
    for e in entities:
        eid = e["id"]
        if eid in net_listings:
            entity_categories[eid] = set(net_listings[eid]["categories"].keys())

    sectors = defaultdict(lambda: {"count": 0, "total_listings": 0})
    for e in entities:
        sec = e.get("entidade") or "Outros"
        sectors[sec]["count"] += 1
        sectors[sec]["total_listings"] += e.get("listing_count", 0)

    for sec_name, sec_data in sectors.items():
        sid = "sector-" + sec_name[:20]
        node_map[sid] = {
            "id": sid, "label": sec_name[:30], "type": "sector",
            "size": min(40, 10 + sec_data["total_listings"] // 50),
            "entities": sec_data["count"],
            "total_listings": sec_data["total_listings"],
            "first_date": "", "last_date": "",
        }

    for e in entities:
        eid = e["id"]
        nif = e.get("nif", "") or ""
        contract_value = sum(c.get("valor", 0) for c in contracts.get(nif, []))
        ldata = net_listings.get(eid, {})
        dates = sorted(ldata.get("dates", []))
        first_date = dates[0] if dates else ""
        last_date = dates[-1] if dates else ""
        monthly = defaultdict(int)
        for d in dates:
            monthly[d[:7]] += 1
        node_map[eid] = {
            "id": eid, "label": e["display_name"][:30], "type": "entity",
            "size": min(30, 5 + e.get("listing_count", 0) // 20),
            "entidade": e.get("entidade", ""), "nif": nif,
            "listings": e.get("listing_count", 0),
            "contracts": len(contracts.get(nif, [])),
            "contract_value": round(contract_value, 2),
            "first_date": first_date, "last_date": last_date,
            "monthly": dict(monthly),
            "name": e.get("display_name", ""),
        }

    for e in entities:
        sec = e.get("entidade") or "Outros"
        sid = "sector-" + sec[:20]
        if sid in node_map:
            e_dates = sorted(net_listings.get(e["id"], {}).get("dates", []))
            edge_date = e_dates[0] if e_dates else ""
            edges.append({"source": sid, "target": e["id"],
                          "label": "belongs to", "strength": 1, "date": edge_date})

    cat_entities = defaultdict(list)
    for eid, cats in entity_categories.items():
        for cat in cats:
            cat_entities[cat].append(eid)

    edge_counts = defaultdict(int)
    for cat, eids in cat_entities.items():
        if 1 < len(eids) < 50:
            for i in range(len(eids)):
                for j in range(i + 1, min(i + 10, len(eids))):
                    key = tuple(sorted([eids[i], eids[j]]))
                    edge_counts[key] += 1

    for (eid1, eid2), count in sorted(edge_counts.items(), key=lambda x: -x[1])[:200]:
        if count >= min_connections:
            d1 = sorted(net_listings.get(eid1, {}).get("dates", []))
            d2 = sorted(net_listings.get(eid2, {}).get("dates", []))
            edge_date = d1[0] if d1 else (d2[0] if d2 else "")
            edges.append({
                "source": eid1, "target": eid2,
                "label": str(count) + " shared categories",
                "strength": min(5, count), "date": edge_date,
            })

    return list(node_map.values()), edges


# ---------------------------------------------------------------------------
# Sector aggregation (from generate_sector_dashboard.py)
# ---------------------------------------------------------------------------

def aggregate_sectors(entities, all_listings):
    sectors = defaultdict(lambda: {
        "total_listings": 0, "total_positions": 0,
        "total_contracts": 0, "total_contract_value": 0.0,
        "hiring_by_month": defaultdict(lambda: {"count": 0, "positions": 0}),
        "categories": defaultdict(int),
        "entity_ids": [],
    })
    for entity in entities:
        entidade = entity.get("entidade") or "Outros"
        if not entidade.strip():
            entidade = "Outros"
        sec = sectors[entidade]
        sec["entity_ids"].append(entity["id"])
        sec["total_listings"] += entity.get("listing_count", 0)
        for l in all_listings.get(entity["id"], []):
            pub = l.get("data_publicacao", "")
            if pub and len(pub) >= 7:
                month = pub[:7]
                sec["hiring_by_month"][month]["count"] += 1
                pos = _safe_int(l.get("total_postos"), 1)
                sec["hiring_by_month"][month]["positions"] += pos
                sec["total_positions"] += pos
            cat = l.get("tipo_oferta") or l.get("categoria") or "Outros"
            sec["categories"][cat] += 1
    return dict(sectors)


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_combined_html(nodes, edges, sectors, entities, all_listings, contracts,
                         filter_sector="", top_n=0, output="combined_dashboard.html"):
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)

    # Timeline months
    all_dates = set()
    for n in nodes:
        fd = n.get("first_date", "")
        if fd and len(fd) >= 7:
            all_dates.add(fd[:7])
    for e in edges:
        d = e.get("date", "")
        if d and len(d) >= 7:
            all_dates.add(d[:7])
    sorted_months = sorted(all_dates) if all_dates else ["2024-01"]
    months_json = json.dumps(sorted_months)

    # Sector chart data
    sorted_sectors = sorted(sectors.items(), key=lambda x: x[1]["total_listings"], reverse=True)
    if top_n > 0:
        sorted_sectors = sorted_sectors[:top_n]
    if filter_sector:
        sorted_sectors = [(k, v) for k, v in sorted_sectors
                          if filter_sector.lower() in k.lower()]

    sector_chart_names = json.dumps([s[0][:25] for s in sorted_sectors[:10]])
    sector_chart_listings = json.dumps([s[1]["total_listings"] for s in sorted_sectors[:10]])

    # Merge months for sector trends
    all_months_set = set()
    for _, s in sorted_sectors:
        all_months_set.update(s["hiring_by_month"].keys())
    trend_months = sorted(all_months_set)

    top5 = sorted_sectors[:5]
    colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]
    hiring_datasets = []
    for i, (name, s) in enumerate(top5):
        data = [s["hiring_by_month"].get(m, {}).get("count", 0) for m in trend_months]
        hiring_datasets.append({
            "label": name[:20], "data": data,
            "borderColor": colors[i], "tension": 0.3, "fill": False,
            "pointRadius": 3,
        })

    # Category breakdown
    all_cats = defaultdict(int)
    for _, s in sorted_sectors:
        for cat, cnt in s["categories"].items():
            all_cats[cat] += cnt
    top_cats = sorted(all_cats.items(), key=lambda x: x[1], reverse=True)[:8]
    cat_labels = json.dumps([c[0][:20] for c in top_cats])
    cat_values = json.dumps([c[1] for c in top_cats])

    # Build per-entity listing summaries for the profile panel
    entity_listings_json = {}
    for eid, llist in all_listings.items():
        cats = defaultdict(int)
        months = defaultdict(int)
        for l in llist:
            cat = l.get("tipo_oferta") or l.get("categoria") or "Outros"
            cats[cat] += 1
            pub = l.get("data_publicacao", "")
            if pub and len(pub) >= 7:
                months[pub[:7]] += 1
        entity_listings_json[eid] = {
            "count": len(llist),
            "categories": dict(cats),
            "months": dict(months),
            "recent": [l.get("titulo", "")[:60] for l in llist[:5]],
        }

    elj = json.dumps(entity_listings_json, ensure_ascii=False)

    total_entities = sum(len(s.get("entity_ids", [])) for s in sectors.values())
    total_listings = sum(s["total_listings"] for s in sectors.values())
    total_positions = sum(s["total_positions"] for s in sectors.values())

    esc_title = _esc("Combined Dashboard" if not filter_sector
                     else filter_sector + " — Combined Dashboard")

    # --- Build HTML ---
    parts = []
    parts.append("<!DOCTYPE html>\n<html lang=\"pt\">\n<head>\n")
    parts.append("<meta charset=\"UTF-8\">\n")
    parts.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n")
    parts.append("<title>" + esc_title + "</title>\n")
    parts.append("<script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js\"></script>\n")
    parts.append("<style>\n")

    # --- CSS ---
    parts.append("""* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; overflow: hidden; height: 100vh; }

/* Top bar */
#topbar { position: fixed; top: 0; left: 0; right: 0; z-index: 30; background: #1e293b; border-bottom: 1px solid #334155; padding: 0.6rem 1.5rem; display: flex; align-items: center; gap: 1.5rem; height: 48px; }
#topbar h1 { font-size: 1.1rem; color: #f8fafc; white-space: nowrap; }
#topbar .subtitle { color: #94a3b8; font-size: 0.8rem; white-space: nowrap; }
#topbar .stats { display: flex; gap: 1rem; margin-left: auto; font-size: 0.75rem; color: #94a3b8; }
#topbar .stats strong { color: #f8fafc; }
#topbar .search-wrap { position: relative; }
#topbar input { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 0.35rem 0.7rem; border-radius: 6px; font-size: 0.8rem; width: 200px; outline: none; }
#topbar input:focus { border-color: #3b82f6; }
#topbar input::placeholder { color: #475569; }

/* Main layout */
#main { position: fixed; top: 48px; left: 0; right: 0; bottom: 0; display: flex; }
#network-panel { flex: 1; min-width: 0; position: relative; border-right: 1px solid #334155; }
#right-panel { width: 480px; min-width: 360px; display: flex; flex-direction: column; background: #0f172a; overflow: hidden; }

/* Tabs */
.tab-bar { display: flex; background: #1e293b; border-bottom: 1px solid #334155; }
.tab-bar button { flex: 1; padding: 0.5rem; background: none; border: none; border-bottom: 2px solid transparent; color: #94a3b8; font-size: 0.75rem; font-weight: 600; cursor: pointer; transition: all 0.15s; text-transform: uppercase; letter-spacing: 0.04em; }
.tab-bar button:hover { color: #e2e8f0; }
.tab-bar button.active { color: #3b82f6; border-bottom-color: #3b82f6; }
.tab-content { flex: 1; overflow-y: auto; padding: 1rem; }
.tab-content::-webkit-scrollbar { width: 6px; }
.tab-content::-webkit-scrollbar-track { background: #0f172a; }
.tab-content::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }

/* Sector tab */
.sec-card { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin-bottom: 0.8rem; }
.sec-card h3 { color: #f8fafc; font-size: 0.9rem; margin-bottom: 0.6rem; }
.sec-card canvas { max-height: 200px; }
.sec-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.6rem; border-radius: 6px; cursor: pointer; transition: background 0.15s; font-size: 0.8rem; }
.sec-row:hover { background: #334155; }
.sec-row.active { background: #1e3a5f; border-left: 3px solid #3b82f6; }
.sec-row .name { flex: 1; color: #e2e8f0; font-weight: 500; }
.sec-row .count { color: #94a3b8; font-size: 0.7rem; }

/* Entity tab */
.entity-empty { text-align: center; padding: 3rem 1rem; color: #64748b; }
.entity-empty .icon { font-size: 3rem; margin-bottom: 1rem; }
.entity-header { margin-bottom: 1rem; }
.entity-header h2 { color: #f8fafc; font-size: 1.1rem; margin-bottom: 0.3rem; }
.entity-header .meta { color: #94a3b8; font-size: 0.8rem; }
.entity-header .meta strong { color: #cbd5e1; }
.metric-row { display: flex; gap: 0.6rem; margin-bottom: 1rem; }
.metric-box { flex: 1; background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 0.7rem; text-align: center; }
.metric-box .val { font-size: 1.2rem; font-weight: 700; color: #f8fafc; }
.metric-box .lbl { font-size: 0.65rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 0.2rem; }
.entity-chart { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; margin-bottom: 0.8rem; }
.entity-chart h3 { color: #f8fafc; font-size: 0.85rem; margin-bottom: 0.6rem; }
.entity-chart canvas { max-height: 180px; }
.entity-list { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.8rem; }
.entity-list h3 { color: #f8fafc; font-size: 0.85rem; margin-bottom: 0.5rem; }
.entity-list .item { padding: 0.3rem 0; border-bottom: 1px solid #334155; color: #cbd5e1; font-size: 0.78rem; }
.entity-list .item:last-child { border-bottom: none; }
.base-link { display: inline-block; margin-top: 0.8rem; padding: 0.4rem 0.8rem; background: #3b82f6; color: white; border-radius: 6px; text-decoration: none; font-size: 0.8rem; transition: background 0.15s; }
.base-link:hover { background: #2563eb; }

/* Network overlay controls */
#net-controls { position: absolute; bottom: 0.8rem; left: 0.8rem; z-index: 10; display: flex; gap: 0.4rem; }
#net-controls button { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.4rem 0.7rem; border-radius: 6px; cursor: pointer; font-size: 0.75rem; transition: background 0.15s; }
#net-controls button:hover { background: #334155; }
#net-stats { position: absolute; top: 0.8rem; right: 0.8rem; z-index: 10; background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 0.6rem 0.8rem; font-size: 0.75rem; }
#net-stats .s { color: #94a3b8; margin: 0.15rem 0; }
#net-stats .s strong { color: #f8fafc; }
#legend { position: absolute; bottom: 0.8rem; right: 0.8rem; z-index: 10; background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 0.6rem 0.8rem; }
#legend .li { display: flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; color: #cbd5e1; margin: 0.15rem 0; }
#legend .dot { width: 10px; height: 10px; border-radius: 50%; }

/* Timeline */
#timeline { position: absolute; bottom: 0; left: 0; right: 0; z-index: 10; background: linear-gradient(0deg, #0f172a 0%, rgba(15,23,42,0.95) 80%, transparent 100%); padding: 1.5rem 1rem 0.6rem; }
#tl-inner { display: flex; align-items: center; gap: 0.5rem; }
#tl-inner .tl-btn { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; display: flex; align-items: center; justify-content: center; }
#tl-inner .tl-btn:hover { background: #334155; }
#tl-inner .tl-btn.playing { background: #3b82f6; border-color: #60a5fa; }
#tl-inner .date-label { color: #93c5fd; font-size: 0.8rem; font-weight: 600; min-width: 70px; text-align: center; }
#tl-inner .range-label { color: #64748b; font-size: 0.65rem; min-width: 50px; text-align: center; }
#tl-inner input[type="range"] { flex: 1; -webkit-appearance: none; height: 5px; background: #334155; border-radius: 3px; outline: none; }
#tl-inner input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: 2px solid #60a5fa; }
#tl-inner input[type="range"]::-moz-range-thumb { width: 14px; height: 14px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: 2px solid #60a5fa; }
#tl-inner .speed-btn { background: #0f172a; border: 1px solid #334155; color: #64748b; padding: 0.2rem 0.5rem; border-radius: 4px; cursor: pointer; font-size: 0.65rem; }
#tl-inner .speed-btn:hover { color: #e2e8f0; background: #334155; }

/* Tooltip */
#tooltip { position: fixed; display: none; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.8rem; max-width: 300px; pointer-events: none; z-index: 100; box-shadow: 0 8px 25px rgba(0,0,0,0.4); font-size: 0.8rem; }
#tooltip h3 { color: #f8fafc; font-size: 0.9rem; margin-bottom: 0.3rem; }
#tooltip .badge { display: inline-block; padding: 0.1rem 0.4rem; border-radius: 9999px; font-size: 0.6rem; font-weight: 600; margin-bottom: 0.4rem; }
#tooltip .badge.sector { background: #3b82f6; color: white; }
#tooltip .badge.entity { background: #10b981; color: white; }
#tooltip .s { color: #94a3b8; margin: 0.1rem 0; }
#tooltip .s strong { color: #cbd5e1; }
""")

    parts.append("</style>\n</head>\n<body>\n")

    # --- Top bar ---
    parts.append("<div id=\"topbar\">\n")
    parts.append("<h1>&#x1f3d7; " + esc_title + "</h1>\n")
    parts.append("<div class=\"subtitle\">Analisa.pt</div>\n")
    parts.append("<div class=\"search-wrap\"><input type=\"text\" id=\"globalSearch\" placeholder=\"Search entities...\" oninput=\"onGlobalSearch(this.value)\"></div>\n")
    parts.append("<div class=\"stats\">\n")
    parts.append("<span>Entities: <strong id=\"statEntities\">" + str(total_entities) + "</strong></span>\n")
    parts.append("<span>Listings: <strong id=\"statListings\">" + str(total_listings) + "</strong></span>\n")
    parts.append("<span>Positions: <strong id=\"statPositions\">" + str(total_positions) + "</strong></span>\n")
    parts.append("</div>\n")
    parts.append("</div>\n")

    # --- Main layout ---
    parts.append("<div id=\"main\">\n")

    # Network panel
    parts.append("<div id=\"network-panel\">\n")
    parts.append("<svg id=\"graph\" style=\"width:100%;height:100%\"></svg>\n")
    parts.append("<div id=\"net-stats\">\n")
    parts.append("<div class=\"s\">Nodes: <strong id=\"nodeCount\">0</strong></div>\n")
    parts.append("<div class=\"s\">Edges: <strong id=\"edgeCount\">0</strong></div>\n")
    parts.append("<div class=\"s\">Sectors: <strong id=\"sectorCount\">0</strong></div>\n")
    parts.append("</div>\n")
    parts.append("<div id=\"legend\">\n")
    parts.append("<div class=\"li\"><div class=\"dot\" style=\"background:#3b82f6\"></div>Sector</div>\n")
    parts.append("<div class=\"li\"><div class=\"dot\" style=\"background:#10b981\"></div>Entity</div>\n")
    parts.append("<div class=\"li\" style=\"font-size:0.65rem;color:#64748b\">Click node for details</div>\n")
    parts.append("</div>\n")
    parts.append("<div id=\"net-controls\">\n")
    parts.append("<button onclick=\"resetZoom()\">Reset Zoom</button>\n")
    parts.append("<button onclick=\"toggleLabels()\">Labels</button>\n")
    parts.append("<button onclick=\"togglePhysics()\">Physics</button>\n")
    parts.append("</div>\n")

    # Timeline
    parts.append("<div id=\"timeline\"><div id=\"tl-inner\">\n")
    parts.append("<button class=\"tl-btn\" onclick=\"skipToStart()\" title=\"Start\">&#x23ee;</button>\n")
    parts.append("<button class=\"tl-btn\" id=\"playBtn\" onclick=\"toggleAnimation()\" title=\"Play\">&#x25b6;</button>\n")
    parts.append("<button class=\"tl-btn\" onclick=\"skipToEnd()\" title=\"End\">&#x23ed;</button>\n")
    parts.append("<span class=\"range-label\" id=\"tlStart\"></span>\n")
    parts.append("<input type=\"range\" id=\"tlSlider\" min=\"0\" max=\"0\" value=\"0\" oninput=\"onTlInput(this.value)\">\n")
    parts.append("<span class=\"range-label\" id=\"tlEnd\"></span>\n")
    parts.append("<span class=\"date-label\" id=\"tlDate\">—</span>\n")
    parts.append("<button class=\"speed-btn\" onclick=\"changeSpeed()\"><span id=\"speedLabel\">1x</span></button>\n")
    parts.append("</div></div>\n")

    parts.append("</div>\n")  # /network-panel

    # Right panel
    parts.append("<div id=\"right-panel\">\n")
    parts.append("<div class=\"tab-bar\">\n")
    parts.append("<button class=\"active\" onclick=\"switchTab('sectors')\" id=\"tabSectors\">Sectors</button>\n")
    parts.append("<button onclick=\"switchTab('entity')\" id=\"tabEntity\">Entity Profile</button>\n")
    parts.append("</div>\n")
    parts.append("<div id=\"tabSectorsContent\" class=\"tab-content\">\n")

    # Sector list
    parts.append("<div class=\"sec-card\">\n")
    parts.append("<h3>Sectors (" + str(len(sorted_sectors)) + ")</h3>\n")
    parts.append("<div id=\"sectorList\" style=\"max-height:250px;overflow-y:auto\">\n")
    for i, (name, s) in enumerate(sorted_sectors[:30]):
        parts.append("<div class=\"sec-row\" onclick=\"selectSector('" + _esc(name) + "')\" id=\"sec-" + str(i) + "\">")
        parts.append("<span class=\"name\">" + _esc(name[:30]) + "</span>")
        parts.append("<span class=\"count\">" + str(s["total_listings"]) + " listings</span>")
        parts.append("</div>\n")
    parts.append("</div>\n</div>\n")

    # Sector charts
    parts.append("<div class=\"sec-card\"><h3>Listings by Sector</h3><canvas id=\"secBarChart\"></canvas></div>\n")
    parts.append("<div class=\"sec-card\"><h3>Hiring Trends — Top 5</h3><canvas id=\"secTrendChart\"></canvas></div>\n")
    parts.append("<div class=\"sec-card\"><h3>Categories</h3><canvas id=\"secCatChart\"></canvas></div>\n")

    parts.append("</div>\n")  # /tabSectorsContent

    # Entity tab
    parts.append("<div id=\"tabEntityContent\" class=\"tab-content\" style=\"display:none\">\n")
    parts.append("<div class=\"entity-empty\" id=\"entityEmpty\">\n")
    parts.append("<div class=\"icon\">🔍</div>\n")
    parts.append("<p>Click an entity node in the network<br>to view its profile here.</p>\n")
    parts.append("</div>\n")
    parts.append("<div id=\"entityProfile\" style=\"display:none\">\n")
    parts.append("<div class=\"entity-header\">\n")
    parts.append("<h2 id=\"epName\"></h2>\n")
    parts.append("<div class=\"meta\">NIF: <strong id=\"epNif\"></strong> | Sector: <strong id=\"epSector\"></strong></div>\n")
    parts.append("</div>\n")
    parts.append("<div class=\"metric-row\">\n")
    parts.append("<div class=\"metric-box\"><div class=\"val\" id=\"epListings\">0</div><div class=\"lbl\">Listings</div></div>\n")
    parts.append("<div class=\"metric-box\"><div class=\"val\" id=\"epContracts\">0</div><div class=\"lbl\">Contracts</div></div>\n")
    parts.append("<div class=\"metric-box\"><div class=\"val\" id=\"epValue\">€0</div><div class=\"lbl\">Value</div></div>\n")
    parts.append("</div>\n")
    parts.append("<div class=\"entity-chart\"><h3>Hiring Trend</h3><canvas id=\"epHiringChart\"></canvas></div>\n")
    parts.append("<div class=\"entity-chart\"><h3>Contract Trend</h3><canvas id=\"epContractChart\"></canvas></div>\n")
    parts.append("<div class=\"entity-chart\"><h3>Categories</h3><canvas id=\"epCatChart\"></canvas></div>\n")
    parts.append("<div class=\"entity-list\"><h3>Recent Listings</h3><div id=\"epRecent\"></div></div>\n")
    parts.append("<a class=\"base-link\" id=\"epBaseLink\" href=\"#\" target=\"_blank\">Open on BASE.gov.pt</a>\n")
    parts.append("</div>\n")  # /entityProfile
    parts.append("</div>\n")  # /tabEntityContent

    parts.append("</div>\n")  # /right-panel
    parts.append("</div>\n")  # /main

    parts.append("<div id=\"tooltip\"></div>\n")

    # --- JavaScript ---
    parts.append("<script src=\"https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js\"></script>\n")
    parts.append("<script>\n")

    parts.append("var allNodes = " + nodes_json + ";\n")
    parts.append("var allLinks = " + edges_json + ";\n")
    parts.append("var allMonths = " + months_json + ";\n")
    parts.append("var entityListings = " + elj + ";\n")
    parts.append("var contractsJsonUrl = '" + Path(output).stem + "_contracts.json';\n")
    parts.append("var _contractCache = {};\n")
    parts.append("var sectorNames = " + sector_chart_names + ";\n")
    parts.append("var sectorListings = " + sector_chart_listings + ";\n")
    parts.append("var trendMonths = " + json.dumps(trend_months) + ";\n")
    parts.append("var hiringDatasets = " + json.dumps(hiring_datasets) + ";\n")
    parts.append("var catLabels = " + cat_labels + ";\n")
    parts.append("var catValues = " + cat_values + ";\n")

    parts.append("""
// --- State ---
var currentMonthIdx = allMonths.length - 1;
var currentMonth = allMonths[currentMonthIdx];
var animTimer = null;
var animSpeed = 800;
var animPlaying = false;
var showLabels = true;
var physicsRunning = true;
var selectedSector = '';
var selectedEntityId = '';
var searchFilter = '';

// --- Sector Charts ---
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

var secBarChart = new Chart(document.getElementById('secBarChart'), {
    type: 'bar', data: { labels: sectorNames, datasets: [{ label: 'Listings', data: sectorListings,
        backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }] },
    options: { responsive: true, indexAxis: 'y', plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true } } }
});

var secTrendChart = new Chart(document.getElementById('secTrendChart'), {
    type: 'line', data: { labels: trendMonths, datasets: hiringDatasets },
    options: { responsive: true, interaction: { mode: 'index', intersect: false },
        scales: { y: { beginAtZero: true } },
        plugins: { legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } } }
});

var secCatChart = new Chart(document.getElementById('secCatChart'), {
    type: 'doughnut', data: { labels: catLabels, datasets: [{ data: catValues,
        backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316'], borderWidth: 0 }] },
    options: { responsive: true, plugins: { legend: { position: 'right', labels: { padding: 8, usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } } }
});

// --- D3 Network ---
var width = document.getElementById('network-panel').clientWidth;
var height = document.getElementById('network-panel').clientHeight;

var svg = d3.select('#graph').attr('width', width).attr('height', height);
var g = svg.append('g');

var zoom = d3.zoom().scaleExtent([0.1, 8])
    .on('zoom', function(e) { g.attr('transform', e.transform); });
svg.call(zoom);

var simulation = d3.forceSimulation(allNodes)
    .force('link', d3.forceLink(allLinks).id(function(d) { return d.id; }).distance(function(d) { return 80 / (d.strength || 1); }))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(function(d) { return d.size + 5; }))
    .force('x', d3.forceX(width / 2).strength(0.05))
    .force('y', d3.forceY(height / 2).strength(0.05));

var link = g.append('g').selectAll('line').data(allLinks).join('line')
    .attr('stroke', '#334155').attr('stroke-opacity', 0.5)
    .attr('stroke-width', function(d) { return Math.min(4, 0.5 + (d.strength || 1) * 0.5); });

var node = g.append('g').selectAll('g').data(allNodes).join('g')
    .call(d3.drag().on('start', dragstarted).on('drag', dragged).on('end', dragended));

node.append('circle')
    .attr('r', function(d) { return d.size; })
    .attr('fill', function(d) { return d.type === 'sector' ? '#3b82f6' : '#10b981'; })
    .attr('stroke', function(d) { return d.type === 'sector' ? '#60a5fa' : '#34d399'; })
    .attr('stroke-width', 2).attr('opacity', 0.85).style('cursor', 'pointer');

var labels = node.append('text')
    .text(function(d) { return d.label; })
    .attr('dx', function(d) { return d.size + 4; }).attr('dy', 4)
    .attr('font-size', function(d) { return d.type === 'sector' ? '10px' : '8px'; })
    .attr('fill', function(d) { return d.type === 'sector' ? '#93c5fd' : '#86efac'; })
    .attr('font-weight', function(d) { return d.type === 'sector' ? '600' : '400'; })
    .style('pointer-events', 'none');

document.getElementById('nodeCount').textContent = allNodes.length;
document.getElementById('edgeCount').textContent = allLinks.length;
document.getElementById('sectorCount').textContent = allNodes.filter(function(n) { return n.type === 'sector'; }).length;

// --- Tooltip ---
var tooltip = document.getElementById('tooltip');
node.on('mouseover', function(event, d) {
    tooltip.style.display = 'block';
    var html = '<h3>' + d.label + '</h3>';
    html += '<span class="badge ' + d.type + '">' + d.type + '</span>';
    if (d.type === 'entity') {
        html += '<div class="s">Sector: <strong>' + (d.entidade || 'N/A') + '</strong></div>';
        html += '<div class="s">Listings: <strong>' + d.listings + '</strong></div>';
        html += '<div class="s">Contracts: <strong>' + d.contracts + '</strong></div>';
        if (d.contract_value > 0) html += '<div class="s">Value: <strong>\\u20ac' + d.contract_value.toLocaleString() + '</strong></div>';
    } else {
        html += '<div class="s">Entities: <strong>' + d.entities + '</strong></div>';
        html += '<div class="s">Listings: <strong>' + d.total_listings + '</strong></div>';
    }
    html += '<div class="s" style="margin-top:0.3rem;font-size:0.7rem;color:#60a5fa\">Click to select</div>';
    tooltip.innerHTML = html;
    tooltip.style.left = (event.pageX + 15) + 'px';
    tooltip.style.top = (event.pageY - 10) + 'px';

    var conns = allLinks.filter(function(l) { return (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id; });
    var connected = new Set();
    connected.add(d.id);
    conns.forEach(function(l) { connected.add(l.source.id || l.source); connected.add(l.target.id || l.target); });
    node.select('circle').attr('opacity', function(n) { return connected.has(n.id) ? 1 : 0.12; });
    link.attr('stroke-opacity', function(l) { return (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id ? 1 : 0.05; });
}).on('mouseout', function() {
    tooltip.style.display = 'none';
    applyFilters();
});

// Click handler: entity -> profile, sector -> highlight
var dragStartPos = null;
node.on('mousedown', function(event, d) { dragStartPos = [event.pageX, event.pageY]; })
    .on('mouseup', function(event, d) {
        if (!dragStartPos) return;
        var dx = event.pageX - dragStartPos[0];
        var dy = event.pageY - dragStartPos[1];
        if (Math.abs(dx) < 5 && Math.abs(dy) < 5) {
            if (d.type === 'entity') {
                selectEntity(d.id, d.name || d.label, d.nif || '', d.entidade || '', d.listings || 0, d.contracts || 0, d.contract_value || 0);
            } else if (d.type === 'sector') {
                selectSector(d.label);
            }
        }
        dragStartPos = null;
    });

function dragstarted(event, d) { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
function dragended(event, d) { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }

function resetZoom() { svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity); }
function toggleLabels() { showLabels = !showLabels; labels.style('display', showLabels ? 'block' : 'none'); }
function togglePhysics() { physicsRunning = !physicsRunning; if (physicsRunning) simulation.alpha(0.3).restart(); else simulation.stop(); }

// --- Search ---
function onGlobalSearch(term) {
    searchFilter = term.toLowerCase().trim();
    applyFilters();
}

// --- Filters ---
function applyFilters() {
    var matchIds = new Set();
    node.each(function(d) {
        var show = true;
        if (searchFilter) {
            var s = (d.label + ' ' + (d.entidade || '') + ' ' + (d.nif || '') + ' ' + (d.name || '')).toLowerCase();
            if (s.indexOf(searchFilter) === -1) show = false;
        }
        if (d.type === 'entity' && d.first_date) {
            if (d.first_date.substring(0, 7) > currentMonth) show = false;
        }
        if (selectedSector && d.type === 'entity' && d.entidade !== selectedSector) show = false;
        if (show) matchIds.add(d.id);
    });

    node.select('circle')
        .attr('opacity', function(d) { return matchIds.has(d.id) ? 0.85 : 0.08; })
        .attr('stroke-width', function(d) { return d.id === selectedEntityId ? 4 : 2; });

    labels.style('opacity', function(d) { return matchIds.has(d.id) ? 1 : 0.08; });

    link.attr('stroke-opacity', function(l) {
        var edgeDate = l.date || '';
        if (edgeDate && edgeDate.substring(0, 7) > currentMonth) return 0.02;
        var src = l.source.id || l.source;
        var tgt = l.target.id || l.target;
        return matchIds.has(src) && matchIds.has(tgt) ? 0.5 : 0.03;
    }).attr('display', function(l) {
        var edgeDate = l.date || '';
        if (edgeDate && edgeDate.substring(0, 7) > currentMonth) return 'none';
        return 'inline';
    });

    var visN = 0, visE = 0;
    node.each(function(d) { if (matchIds.has(d.id)) visN++; });
    link.each(function(l) { var ed = l.date || ''; if (ed && ed.substring(0,7) > currentMonth) return; visE++; });
    document.getElementById('nodeCount').textContent = visN;
    document.getElementById('edgeCount').textContent = visE;
}

// --- Timeline ---
var tlSlider = document.getElementById('tlSlider');
var tlDate = document.getElementById('tlDate');
if (tlSlider) {
    tlSlider.max = allMonths.length - 1;
    tlSlider.value = currentMonthIdx;
    tlDate.textContent = currentMonth;
    document.getElementById('tlStart').textContent = allMonths[0];
    document.getElementById('tlEnd').textContent = allMonths[allMonths.length - 1];
}
function setTlMonth(idx) {
    currentMonthIdx = Math.max(0, Math.min(allMonths.length - 1, idx));
    currentMonth = allMonths[currentMonthIdx];
    if (tlSlider) tlSlider.value = currentMonthIdx;
    if (tlDate) tlDate.textContent = currentMonth;
    applyFilters();
}
function onTlInput(val) { setTlMonth(parseInt(val)); }

function toggleAnimation() { animPlaying ? stopAnim() : startAnim(); }
function startAnim() {
    animPlaying = true;
    var btn = document.getElementById('playBtn');
    if (btn) { btn.innerHTML = '&#x23f8;'; btn.className = 'tl-btn playing'; }
    if (currentMonthIdx >= allMonths.length - 1) setTlMonth(0);
    animTimer = setInterval(function() {
        if (currentMonthIdx < allMonths.length - 1) setTlMonth(currentMonthIdx + 1);
        else stopAnim();
    }, animSpeed);
}
function stopAnim() {
    animPlaying = false;
    if (animTimer) { clearInterval(animTimer); animTimer = null; }
    var btn = document.getElementById('playBtn');
    if (btn) { btn.innerHTML = '&#x25b6;'; btn.className = 'tl-btn'; }
}
function changeSpeed() {
    var speeds = [1200, 800, 400, 200];
    var labels = ['0.5x', '1x', '2x', '4x'];
    var si = speeds.indexOf(animSpeed);
    var ni = (si + 1) % speeds.length;
    animSpeed = speeds[ni];
    document.getElementById('speedLabel').textContent = labels[ni];
    if (animPlaying) { stopAnim(); startAnim(); }
}
function skipToEnd() { stopAnim(); setTlMonth(allMonths.length - 1); }
function skipToStart() { stopAnim(); setTlMonth(0); }

// --- Tabs ---
function switchTab(tab) {
    document.getElementById('tabSectors').className = tab === 'sectors' ? 'active' : '';
    document.getElementById('tabEntity').className = tab === 'entity' ? 'active' : '';
    document.getElementById('tabSectorsContent').style.display = tab === 'sectors' ? '' : 'none';
    document.getElementById('tabEntityContent').style.display = tab === 'entity' ? '' : 'none';
}

// --- Sector selection ---
function selectSector(name) {
    selectedSector = (selectedSector === name) ? '' : name;
    // Update sector list UI
    var rows = document.querySelectorAll('.sec-row');
    rows.forEach(function(r) { r.className = 'sec-row'; });
    if (selectedSector) {
        rows.forEach(function(r) {
            if (r.querySelector('.name').textContent === selectedSector.substring(0, 30)) r.className = 'sec-row active';
        });
    }
    applyFilters();
}

// --- Entity profile ---
var epCharts = {};
function selectEntity(eid, name, nif, entidade, listings, contracts, contractValue) {
    selectedEntityId = eid;
    switchTab('entity');
    document.getElementById('entityEmpty').style.display = 'none';
    document.getElementById('entityProfile').style.display = '';
    document.getElementById('epName').textContent = name;
    document.getElementById('epNif').textContent = nif || 'N/A';
    document.getElementById('epSector').textContent = entidade || 'N/A';
    document.getElementById('epListings').textContent = listings;
    document.getElementById('epContracts').textContent = contracts;
    document.getElementById('epValue').textContent = '\\u20ac' + contractValue.toLocaleString();

    var baseLink = document.getElementById('epBaseLink');
    if (nif) {
        baseLink.href = 'https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id=' + nif;
        baseLink.style.display = '';
    } else {
        baseLink.style.display = 'none';
    }

    // Destroy old charts
    Object.keys(epCharts).forEach(function(k) { epCharts[k].destroy(); epCharts[k] = null; });

    var eData = entityListings[eid] || { count: 0, categories: {}, months: {}, recent: [] };
    // Hiring chart
    var hMonths = Object.keys(eData.months).sort();
    if (hMonths.length > 0) {
        epCharts.hiring = new Chart(document.getElementById('epHiringChart'), {
            type: 'bar', data: { labels: hMonths, datasets: [{ label: 'Listings', data: hMonths.map(function(m) { return eData.months[m]; }),
                backgroundColor: 'rgba(16,185,129,0.7)', borderRadius: 4 }] },
            options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
        });
    }

    function renderContractChart(cd) {
        if (!cd || !cd.months) return;
        var cMonths = Object.keys(cd.months).sort();
        if (cMonths.length > 0) {
            epCharts.contract = new Chart(document.getElementById('epContractChart'), {
                type: 'bar', data: { labels: cMonths, datasets: [{ label: 'Value (€)', data: cMonths.map(function(m) { return cd.months[m]; }),
                    backgroundColor: 'rgba(59,130,246,0.7)', borderRadius: 4 }] },
                options: { responsive: true, plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, ticks: { callback: function(v) { return '€' + v.toLocaleString(); } } } } }
            });
        }
    }
    // Lazy-load contract data from separate JSON file
    if (nif && contractsJsonUrl) {
        if (_contractCache[nif]) { renderContractChart(_contractCache[nif]); }
        else {
            fetch(contractsJsonUrl)
                .then(function(r) { return r.json(); })
                .then(function(data) { _contractCache = data; var cd = data[nif]; if (cd) renderContractChart(cd); })
                .catch(function(e) { console.warn('Contract data not available:', e); });
        }
    }

    // Categories chart
    var cats = eData.categories;
    var catKeys = Object.keys(cats);
    if (catKeys.length > 0) {
        epCharts.cat = new Chart(document.getElementById('epCatChart'), {
            type: 'doughnut', data: { labels: catKeys.map(function(k) { return k.substring(0, 20); }),
                datasets: [{ data: catKeys.map(function(k) { return cats[k]; }),
                    backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316'], borderWidth: 0 }] },
            options: { responsive: true, plugins: { legend: { position: 'right', labels: { padding: 6, usePointStyle: true, pointStyle: 'circle', font: { size: 9 } } } } }
        });
    }

    // Recent listings
    var recentDiv = document.getElementById('epRecent');
    recentDiv.innerHTML = '';
    if (eData.recent.length === 0) {
        recentDiv.innerHTML = '<div class="item" style="color:#64748b">No recent listings</div>';
    } else {
        eData.recent.forEach(function(t) {
            var div = document.createElement('div');
            div.className = 'item';
            div.textContent = t || '(untitled)';
            recentDiv.appendChild(div);
        });
    }

    applyFilters();
}

// --- Resize ---
window.addEventListener('resize', function() {
    var w = document.getElementById('network-panel').clientWidth;
    var h = document.getElementById('network-panel').clientHeight;
    svg.attr('width', w).attr('height', h);
    simulation.force('center', d3.forceCenter(w / 2, h / 2));
    simulation.alpha(0.3).restart();
});

// --- Timeline tick ---
simulation.on('tick', function() {
    link.attr('x1', function(d) { return d.source.x; }).attr('y1', function(d) { return d.source.y; })
        .attr('x2', function(d) { return d.target.x; }).attr('y2', function(d) { return d.target.y; });
    node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
});

applyFilters();
""")

    parts.append("</script>\n</body>\n</html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Combined Multi-Panel Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-o", "--output", default="", help="Output HTML file")
    parser.add_argument("--sector", default="", help="Filter by sector name")
    parser.add_argument("--top", type=int, default=0, help="Show only top N entities")
    parser.add_argument("--min-connections", type=int, default=1,
                        help="Minimum shared categories for entity-entity edges")
    parser.add_argument("--open", action="store_true", help="Open in browser")

    args = parser.parse_args()

    print("Loading entities...")
    entities = load_all_entities()
    if not entities:
        print("No entities found.")
        sys.exit(1)

    if args.top:
        entities = entities[:args.top]
    print(f"  {len(entities)} entities")

    print("Loading listings...")
    all_listings = load_all_listings()
    net_listings = load_listings_for_network()
    print(f"  {len(all_listings)} entities with listings")

    print("Loading contracts...")
    contracts = load_contracts()
    total_contracts = sum(len(v) for v in contracts.values())
    print(f"  {total_contracts} total contracts")

    print("Building network graph...")
    nodes, edges = build_graph(entities, net_listings, contracts,
                               filter_sector=args.sector,
                               min_connections=args.min_connections)
    print(f"  {len(nodes)} nodes, {len(edges)} edges")

    print("Aggregating sector data...")
    sectors = aggregate_sectors(entities, all_listings)
    print(f"  {len(sectors)} sectors")

    print("Generating combined dashboard...")
    output = args.output or "combined_dashboard.html"
    html = build_combined_html(nodes, edges, sectors, entities, all_listings, contracts,
                               filter_sector=args.sector, top_n=args.top, output=output)
    Path(output).write_text(html, encoding="utf-8")
    # Write companion contracts JSON for lazy-loading
    contracts_output = Path(output).parent / (Path(output).stem + "_contracts.json")
    full_contracts = {}
    for nif, clist in contracts.items():
        total_val = sum(c.get("valor", 0) for c in clist)
        types = defaultdict(int)
        months = defaultdict(int)
        for c in clist:
            tipo = c.get("tipo") or "Outros"
            types[tipo] += 1
            date = c.get("data", "")
            if date and len(date) >= 7:
                months[date[:7]] += c.get("valor", 0)
        full_contracts[nif] = {
            "count": len(clist),
            "total_value": round(total_val, 2),
            "types": dict(types),
            "months": {k: round(v, 2) for k, v in months.items()},
        }
    contracts_output.write_text(json.dumps(full_contracts, ensure_ascii=False), encoding="utf-8")
    print(f"  ✅ Companion JSON saved to {contracts_output}")
    print(f"  \u2705 Saved to {output}")

    if args.open:
        webbrowser.open(Path(output).resolve().as_uri())


if __name__ == "__main__":
    main()
