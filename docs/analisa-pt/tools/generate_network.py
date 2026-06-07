#!/usr/bin/env python3
"""Node-based Correlation Visualization

Generates a self-contained HTML file with a D3.js force-directed network graph
showing correlations between Portuguese public entities, sectors, and hiring
patterns. Nodes represent entities and sectors; edges represent shared
characteristics (same department, similar hiring profiles, contract overlap).

Features:
  - Leiden community detection for automatic clustering
  - Interactive cluster filtering and coloring
  - Temporal animation of network evolution
  - Search and type filtering
  - Click-to-copy CLI commands for entity/sector detail pages

Usage:
    python generate_network.py -o network.html
    python generate_network.py --sector "Saúde" -o saude_network.html
    python generate_network.py --min-connections 3 -o filtered_network.html
    python generate_network.py --no-clusters -o no_clusters.html
    python generate_network.py --open
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


def _esc(s: str) -> str:
    return html_mod.escape(str(s)) if s else ""


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
        {"id": r[0], "display_name": r[1], "entidade": r[2], "organismo": r[3],
         "nif": r[4], "listing_count": r[5]}
        for r in rows
    ]


def load_all_listings():
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


def build_graph(entities, listings, contracts, filter_sector="", min_connections=1):
    """Build nodes and edges for the network graph."""
    node_map = {}
    edges = []

    if filter_sector:
        entities = [e for e in entities if filter_sector.lower() in (e.get("entidade") or "").lower()]

    entity_categories = {}
    for e in entities:
        eid = e["id"]
        if eid in listings:
            entity_categories[eid] = set(listings[eid]["categories"].keys())

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
            "entities": sec_data["count"], "total_listings": sec_data["total_listings"],
            "first_date": "", "last_date": "",
            "cmd": "python generate_sector_dashboard.py --detail '" + _esc(sec_name) + "' -o sector_" + _esc(sec_name).replace(" ", "_")[:25] + ".html",
        }

    for e in entities:
        eid = e["id"]
        nif = e.get("nif", "") or ""
        contract_value = sum(c.get("valor", 0) for c in contracts.get(nif, []))
        ldata = listings.get(eid, {})
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
            "cmd": "python generate_html.py --nif " + _esc(nif) + " -o dashboard_" + _esc(nif) + ".html" if nif else "",
        }

    for e in entities:
        sec = e.get("entidade") or "Outros"
        sid = "sector-" + sec[:20]
        if sid in node_map:
            e_dates = sorted(listings.get(e["id"], {}).get("dates", []))
            edge_date = e_dates[0] if e_dates else ""
            edges.append({"source": sid, "target": e["id"], "label": "belongs to",
                          "strength": 1, "date": edge_date})

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
            d1 = sorted(listings.get(eid1, {}).get("dates", []))
            d2 = sorted(listings.get(eid2, {}).get("dates", []))
            edge_date = d1[0] if d1 else (d2[0] if d2 else "")
            edges.append({
                "source": eid1, "target": eid2,
                "label": str(count) + " shared categories",
                "strength": min(5, count), "date": edge_date,
            })

    return list(node_map.values()), edges


def build_network_html(nodes, edges, title="Entity Correlation Network",
                       enable_clusters=True):
    """Generate self-contained HTML with D3.js force-directed graph."""
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)
    esc_title = _esc(title)

    # Collect all dates for timeline range
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

    css = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; overflow: hidden; }
#header { position: fixed; top: 0; left: 0; right: 0; z-index: 10; background: linear-gradient(180deg, #0f172a 0%, rgba(15,23,42,0.9) 80%, transparent 100%); padding: 1rem 2rem 2rem; pointer-events: none; }
#header h1 { font-size: 1.4rem; color: #f8fafc; pointer-events: auto; }
#header .subtitle { color: #94a3b8; font-size: 0.85rem; margin-top: 0.3rem; }
#graph { width: 100vw; height: 100vh; }
#tooltip { position: fixed; display: none; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; max-width: 350px; pointer-events: none; z-index: 100; box-shadow: 0 8px 25px rgba(0,0,0,0.4); }
#tooltip h3 { color: #f8fafc; font-size: 0.95rem; margin-bottom: 0.4rem; }
#tooltip .type-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 9999px; font-size: 0.65rem; font-weight: 600; margin-bottom: 0.5rem; }
#tooltip .type-badge.sector { background: #3b82f6; color: white; }
#tooltip .type-badge.entity { background: #10b981; color: white; }
#tooltip .stat { font-size: 0.8rem; color: #94a3b8; margin: 0.15rem 0; }
#tooltip .stat strong { color: #cbd5e1; }
#search { position: fixed; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 20; pointer-events: auto; display: flex; gap: 0.5rem; align-items: center; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.4rem 0.8rem; flex-wrap: wrap; justify-content: center; }
#search input { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.85rem; width: 280px; max-width: 40vw; outline: none; transition: border-color 0.15s; }
#search input:focus { border-color: #3b82f6; }
#search input::placeholder { color: #475569; }
#search .count { font-size: 0.75rem; color: #64748b; white-space: nowrap; }
#search .filter-btns { display: flex; gap: 0.3rem; }
#search .filter-btns button { background: #0f172a; border: 1px solid #334155; color: #94a3b8; padding: 0.3rem 0.6rem; border-radius: 6px; cursor: pointer; font-size: 0.7rem; transition: all 0.15s; }
#search .filter-btns button:hover { background: #1e293b; color: #e2e8f0; }
#search .filter-btns button.active { background: #3b82f6; border-color: #3b82f6; color: white; }
#search .cluster-filters { display: flex; gap: 0.25rem; flex-wrap: wrap; max-width: 400px; }
#search .cluster-btn { display: flex; align-items: center; gap: 0.25rem; background: #0f172a; border: 1px solid #334155; color: #94a3b8; padding: 0.2rem 0.5rem; border-radius: 6px; cursor: pointer; font-size: 0.65rem; transition: all 0.15s; }
#search .cluster-btn:hover { background: #1e293b; color: #e2e8f0; }
#search .cluster-btn.active { border-color: #e2e8f0; color: white; }
#search .cluster-btn .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
#timeline { position: fixed; bottom: 4rem; left: 50%; transform: translateX(-50%); z-index: 20; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.6rem 1rem; display: flex; align-items: center; gap: 0.6rem; width: 80%; max-width: 900px; }
#timeline .date-label { color: #93c5fd; font-size: 0.8rem; font-weight: 600; min-width: 80px; text-align: center; }
#timeline .range-label { color: #64748b; font-size: 0.65rem; min-width: 60px; text-align: center; }
#timeline input[type="range"] { flex: 1; -webkit-appearance: none; height: 6px; background: #334155; border-radius: 3px; outline: none; }
#timeline input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: 2px solid #60a5fa; }
#timeline input[type="range"]::-moz-range-thumb { width: 16px; height: 16px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: 2px solid #60a5fa; }
#timeline .tl-btn { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; width: 30px; height: 30px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; justify-content: center; transition: background 0.15s; }
#timeline .tl-btn:hover { background: #334155; }
#timeline .tl-btn.playing { background: #3b82f6; border-color: #60a5fa; }
#timeline .tl-btn.disabled { opacity: 0.3; pointer-events: none; }
#legend { position: fixed; bottom: 1rem; left: 1rem; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.8rem 1rem; z-index: 10; max-height: 50vh; overflow-y: auto; }
#legend::-webkit-scrollbar { width: 4px; }
#legend::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
#legend h4 { color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem; }
.legend-item { display: flex; align-items: center; gap: 0.5rem; font-size: 0.75rem; margin: 0.2rem 0; color: #cbd5e1; cursor: pointer; padding: 0.15rem 0.3rem; border-radius: 4px; transition: background 0.15s; }
.legend-item:hover { background: #334155; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.legend-item .count { color: #64748b; font-size: 0.65rem; margin-left: auto; }
#controls { position: fixed; bottom: 1rem; right: 1rem; z-index: 10; display: flex; gap: 0.5rem; align-items: flex-end; }
#controls button { background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem 0.8rem; border-radius: 8px; cursor: pointer; font-size: 0.8rem; transition: background 0.15s; }
#controls button:hover { background: #334155; }
#export-menu { position: absolute; bottom: 100%; right: 0; margin-bottom: 0.5rem; background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 0.4rem; display: none; min-width: 180px; box-shadow: 0 4px 15px rgba(0,0,0,0.4); }
#export-menu.show { display: block; }
#export-menu button { width: 100%; text-align: left; border: none; border-radius: 6px; padding: 0.5rem 0.8rem; font-size: 0.78rem; margin: 0; }
#export-menu button:hover { background: #334155; }
#stats { position: fixed; top: 1rem; right: 1rem; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.8rem 1rem; z-index: 10; font-size: 0.8rem; }
#stats .stat { margin: 0.2rem 0; color: #94a3b8; }
#stats .stat strong { color: #f8fafc; }
#stats .stat strong { color: #f8fafc; }
#entity-panel { position: fixed; top: 4rem; left: 1rem; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0; z-index: 15; width: 320px; max-height: calc(100vh - 6rem); overflow-y: auto; font-size: 0.8rem; display: none; box-shadow: 0 8px 25px rgba(0,0,0,0.4); }
#entity-panel::-webkit-scrollbar { width: 4px; }
#entity-panel::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
#entity-panel .ep-header { background: #0f172a; border-bottom: 1px solid #334155; padding: 0.8rem 1rem; border-radius: 10px 10px 0 0; display: flex; justify-content: space-between; align-items: flex-start; }
#entity-panel .ep-header h3 { color: #f8fafc; font-size: 0.95rem; margin: 0; line-height: 1.3; }
#entity-panel .ep-close { background: none; border: none; color: #64748b; cursor: pointer; font-size: 1.1rem; padding: 0.2rem; line-height: 1; }
#entity-panel .ep-close:hover { color: #e2e8f0; }
#entity-panel .ep-body { padding: 0.8rem 1rem; }
#entity-panel .ep-meta { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
#entity-panel .ep-badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 9999px; font-size: 0.65rem; font-weight: 600; }
#entity-panel .ep-badge.sector { background: #3b82f6; color: white; }
#entity-panel .ep-badge.cluster { background: #8b5cf6; color: white; }
#entity-panel .ep-stat-row { display: flex; justify-content: space-between; padding: 0.3rem 0; border-bottom: 1px solid rgba(51,65,85,0.5); }
#entity-panel .ep-stat-label { color: #64748b; font-size: 0.75rem; }
#entity-panel .ep-stat-value { color: #f8fafc; font-weight: 600; font-size: 0.8rem; }
#entity-panel .ep-stat-value.money { color: #10b981; }
#entity-panel .ep-actions { margin-top: 0.6rem; padding-top: 0.5rem; border-top: 1px solid #334155; }
#entity-panel .ep-actions a { display: block; padding: 0.35rem 0.6rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #60a5fa; text-decoration: none; font-size: 0.75rem; margin-bottom: 0.3rem; transition: background 0.15s; }
#entity-panel .ep-actions a:hover { background: #334155; }
#cluster-panel { position: fixed; top: 4rem; right: 1rem; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 0.8rem 1rem; z-index: 10; width: 240px; max-height: 40vh; overflow-y: auto; font-size: 0.75rem; display: none; }
#cluster-panel::-webkit-scrollbar { width: 4px; }
#cluster-panel::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
#cluster-panel h4 { color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
.cluster-row { display: flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0.4rem; border-radius: 4px; cursor: pointer; transition: background 0.15s; }
.cluster-row:hover { background: #334155; }
.cluster-row.active { background: #1e3a5f; }
.cluster-row .cdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.cluster-row .cname { flex: 1; color: #cbd5e1; }
.cluster-row .ccount { color: #64748b; font-size: 0.65rem; }
#minimap { position: fixed; bottom: 4.5rem; right: 1rem; left: auto; z-index: 15; background: #1e293b; border: 1px solid #334155; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
#minimap svg { display: block; }
#minimap .mm-label { font-size: 0.6rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em; padding: 0.3rem 0.5rem 0.15rem; }
"""

    search_html = """
<div id="search">
<input type="text" id="searchInput" placeholder="Search entities, sectors, NIF..." oninput="filterNodes(this.value)">
<div class="filter-btns">
<button id="btnAll" class="active" onclick="setTypeFilter('all')">All</button>
<button id="btnSector" onclick="setTypeFilter('sector')">Sectors</button>
<button id="btnEntity" onclick="setTypeFilter('entity')">Entities</button>
""" + ('<button id="btnCluster" onclick="toggleClusterPanel()">Clusters</button>' if enable_clusters else '') + """
</div>
<span class="count" id="matchCount"></span>
</div>
"""

    # Leiden community detection algorithm
    louvain_js = """
// Leiden Community Detection Algorithm
// Improvement over Louvain: adds refinement phase guaranteeing well-connected communities
function detectCommunities(nodeList, edgeList) {
    var nodeIds = {}, nodeWeights = {}, adjacency = {};
    var totalWeight = 0;
    nodeList.forEach(function(n) {
        nodeIds[n.id] = true;
        nodeWeights[n.id] = 0;
        adjacency[n.id] = {};
    });
    edgeList.forEach(function(e) {
        var src = typeof e.source === 'object' ? e.source.id : e.source;
        var tgt = typeof e.target === 'object' ? e.target.id : e.target;
        var w = e.strength || 1;
        if (nodeIds[src] && nodeIds[tgt]) {
            adjacency[src][tgt] = (adjacency[src][tgt] || 0) + w;
            adjacency[tgt][src] = (adjacency[tgt][src] || 0) + w;
            nodeWeights[src] += w;
            nodeWeights[tgt] += w;
            totalWeight += w;
        }
    });
    if (totalWeight === 0) totalWeight = 1;

    // Each node starts in its own community
    var community = {};
    var communityDegreeSum = {};
    nodeList.forEach(function(n) {
        community[n.id] = n.id;
        communityDegreeSum[n.id] = nodeWeights[n.id] || 0;
    });

    var m2 = totalWeight * 2;
    var improved = true, iter = 0;

    while (improved && iter < 30) {
        improved = false;
        iter++;

        // === Phase 1: Local Moving ===
        var ids = Object.keys(nodeIds);
        for (var i = ids.length - 1; i > 0; i--) {
            var j = Math.floor(Math.random() * (i + 1));
            var t = ids[i]; ids[i] = ids[j]; ids[j] = t;
        }
        ids.forEach(function(nid) {
            var cur = community[nid];
            var best = cur, bestGain = 0, ki = nodeWeights[nid];
            var neighborComms = {};
            Object.keys(adjacency[nid]).forEach(function(nb) {
                var nc = community[nb];
                if (nc !== cur) neighborComms[nc] = (neighborComms[nc] || 0) + adjacency[nid][nb];
            });
            Object.keys(neighborComms).forEach(function(cand) {
                var gain = neighborComms[cand] / totalWeight;
                var sumDeg = communityDegreeSum[cand] || 0;
                gain -= (sumDeg * ki) / (m2 * totalWeight);
                if (gain > bestGain) { bestGain = gain; best = cand; }
            });
            if (best !== cur) {
                communityDegreeSum[cur] = (communityDegreeSum[cur] || 0) - ki;
                communityDegreeSum[best] = (communityDegreeSum[best] || 0) + ki;
                community[nid] = best;
                improved = true;
            }
        });

        // === Phase 2: Refinement (Leiden-specific) ===
        // For each community, try splitting into better-connected sub-parts
        var commGroups = {};
        Object.keys(nodeIds).forEach(function(nid) {
            var c = community[nid];
            if (!commGroups[c]) commGroups[c] = [];
            commGroups[c].push(nid);
        });

        Object.keys(commGroups).forEach(function(cid) {
            var members = commGroups[cid];
            if (members.length <= 2) return;

            // Sub-community assignment
            var sub = {};
            members.forEach(function(nid) { sub[nid] = nid; });
            var subImproved = true, subIter = 0;

            while (subImproved && subIter < 8) {
                subImproved = false;
                subIter++;
                members.forEach(function(nid) {
                    var cur = sub[nid];
                    var bestSub = cur, bestGain = 0;
                    var subNeighbors = {};
                    Object.keys(adjacency[nid]).forEach(function(nb) {
                        if (community[nb] === cid && sub[nb] !== cur) {
                            subNeighbors[sub[nb]] = (subNeighbors[sub[nb]] || 0) + adjacency[nid][nb];
                        }
                    });
                    Object.keys(subNeighbors).forEach(function(sc) {
                        var subDeg = 0;
                        members.forEach(function(m) { if (sub[m] === sc) subDeg += nodeWeights[m] || 0; });
                        var gain = subNeighbors[sc] / totalWeight - (subDeg * ki) / (m2 * totalWeight);
                        if (gain > bestGain) { bestGain = gain; bestSub = sc; }
                    });
                    if (bestSub !== cur) { sub[nid] = bestSub; subImproved = true; }
                });
            }

            // Apply refinement: if multiple sub-communities exist, split
            var uniqueSubs = {};
            members.forEach(function(nid) { uniqueSubs[sub[nid]] = true; });
            if (Object.keys(uniqueSubs).length > 1) {
                Object.keys(uniqueSubs).forEach(function(sid) {
                    members.forEach(function(nid) {
                        if (sub[nid] === sid) community[nid] = cid + '_' + sid;
                    });
                });
            }
        });
    }

    // Compact to sequential IDs
    var map = {}, nextId = 0;
    Object.keys(nodeIds).forEach(function(nid) {
        var c = community[nid];
        if (map[c] === undefined) map[c] = nextId++;
    });
    var result = {};
    Object.keys(nodeIds).forEach(function(nid) { result[nid] = map[community[nid]]; });
    return { assignments: result, count: nextId };
}

// Run Leiden community detection
var communityResult = detectCommunities(nodes, links);
var communityAssignments = communityResult.assignments;
var communityCount = communityResult.count;

// Assign community to nodes
nodes.forEach(function(n) {
    n.community = communityAssignments[n.id] !== undefined ? communityAssignments[n.id] : 0;
});

// Cluster color palette (15 distinct colors)
var clusterColors = [
    '#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6',
    '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#22d3ee',
    '#84cc16', '#f43f5e', '#06b6d4', '#a855f7', '#eab308',
    '#fb923c', '#4ade80', '#818cf8', '#c084fc', '#38bdf8'
];

// Build cluster metadata
var clusterMeta = {};
var totalWeightSum = totalWeight;
nodes.forEach(function(n) {
    var c = n.community;
    if (!clusterMeta[c]) clusterMeta[c] = { id: c, nodes: 0, totalListings: 0, sectors: {} };
    clusterMeta[c].nodes++;
    clusterMeta[c].totalListings += n.listings || n.total_listings || 0;
    if (n.type === 'sector') {
        clusterMeta[c].sectors[n.label] = (clusterMeta[c].sectors[n.label] || 0) + 1;
    }
});

var sortedClusters = Object.keys(clusterMeta).sort(function(a, b) {
    return clusterMeta[b].nodes - clusterMeta[a].nodes;
});

// Build cluster legend HTML
var clusterLegendHtml = '';
if (communityCount > 0) {
    clusterLegendHtml = '<h4>Clusters (' + communityCount + ')</h4>';
    sortedClusters.forEach(function(cid) {
        var meta = clusterMeta[cid];
        var color = clusterColors[parseInt(cid) % clusterColors.length];
        var topSectors = Object.keys(meta.sectors).sort(function(a, b) { return meta.sectors[b] - meta.sectors[a]; }).slice(0, 2).join(', ');
        clusterLegendHtml += '<div class="legend-item" onclick="toggleClusterFilter(' + cid + ')" title="' + (topSectors || meta.nodes + ' entities') + '">';
        clusterLegendHtml += '<div class="legend-dot" style="background:' + color + '"></div>';
        clusterLegendHtml += '<span>Cluster ' + cid + '</span>';
        clusterLegendHtml += '<span class="count">' + meta.nodes + '</span>';
        clusterLegendHtml += '</div>';
    });
}

// Update stats
document.getElementById('clusterCount').textContent = communityCount;
"""

    js = """
const nodes = """ + nodes_json + """;
const links = """ + edges_json + """;
const allMonths = """ + months_json + """;

document.getElementById('nodeCount').textContent = nodes.length;
document.getElementById('edgeCount').textContent = links.length;
document.getElementById('sectorCount').textContent = nodes.filter(n => n.type === 'sector').length;

const width = window.innerWidth;
const height = window.innerHeight;

const svg = d3.select('#graph')
    .attr('width', width)
    .attr('height', height);

const g = svg.append('g');

const zoom = d3.zoom()
    .scaleExtent([0.1, 8])
    .on('zoom', (event) => { g.attr('transform', event.transform); if (typeof updateMinimap === 'function') updateMinimap(); });

svg.call(zoom);

const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(d => 80 / (d.strength || 1)))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(d => d.size + 5))
    .force('x', d3.forceX(width / 2).strength(0.05))
    .force('y', d3.forceY(height / 2).strength(0.05));

const link = g.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', '#334155')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', d => Math.min(4, 0.5 + (d.strength || 1) * 0.5));

const node = g.append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .call(d3.drag()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended));

node.append('circle')
    .attr('r', d => d.size)
    .attr('fill', d => """ + ('d.type === "sector" ? "#3b82f6" : clusterColors[d.community % clusterColors.length]' if enable_clusters else 'd.type === "sector" ? "#3b82f6" : "#10b981"') + """)
    .attr('stroke', d => """ + ('d.type === "sector" ? "#60a5fa" : clusterColors[(d.community + 5) % clusterColors.length]' if enable_clusters else 'd.type === "sector" ? "#60a5fa" : "#34d399"') + """)
    .attr('stroke-width', 2)
    .attr('opacity', 0.85)
    .style('cursor', 'pointer');

let showLabels = true;
const labels = node.append('text')
    .text(d => d.label)
    .attr('dx', d => d.size + 4)
    .attr('dy', 4)
    .attr('font-size', d => d.type === 'sector' ? '11px' : '9px')
    .attr('fill', d => d.type === 'sector' ? '#93c5fd' : '#86efac')
    .attr('font-weight', d => d.type === 'sector' ? '600' : '400')
    .style('pointer-events', 'none');

// Tooltip
var tooltip = document.getElementById('tooltip');

node.on('mouseover', function(event, d) {
    tooltip.style.display = 'block';
    var html = '<h3>' + d.label + '</h3>';
    html += '<span class="type-badge ' + d.type + '">' + d.type + '</span>';
    """ + ('html += \'<span class="type-badge" style="background:\' + clusterColors[d.community % clusterColors.length] + \';color:white;margin-left:0.3rem">Cluster \' + d.community + \'</span>\';' if enable_clusters else '') + """
    if (d.type === 'entity') {
        html += '<div class="stat">Department: <strong>' + (d.entidade || 'N/A') + '</strong></div>';
        html += '<div class="stat">Listings: <strong>' + d.listings + '</strong></div>';
        html += '<div class="stat">Contracts: <strong>' + d.contracts + '</strong></div>';
        if (d.contract_value > 0) html += '<div class="stat">Contract Value: <strong>\\u20ac' + d.contract_value.toLocaleString() + '</strong></div>';
        if (d.nif) html += '<div class="stat">NIF: <strong>' + d.nif + '</strong></div>';
        if (d.first_date) html += '<div class="stat">First listing: <strong>' + d.first_date + '</strong></div>';
    } else {
        html += '<div class="stat">Entities: <strong>' + d.entities + '</strong></div>';
        html += '<div class="stat">Total Listings: <strong>' + d.total_listings + '</strong></div>';
    }
    var conns = links.filter(function(l) { return (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id; });
    html += '<div class="stat">Connections: <strong>' + conns.length + '</strong></div>';
    if (d.cmd && d.cmd.length > 0) {
        html += '<div class="stat" style="margin-top:0.5rem;padding-top:0.4rem;border-top:1px solid #334155;font-size:0.7rem;color:#64748b">CLI: <code style="background:#0f172a;padding:0.15rem 0.4rem;border-radius:4px;font-size:0.65rem;color:#93c5fd;word-break:break-all">' + d.cmd + '</code></div>';
    }
    tooltip.innerHTML = html;
    tooltip.style.left = (event.pageX + 15) + 'px';
    tooltip.style.top = (event.pageY - 10) + 'px';

    var connected = new Set();
    conns.forEach(function(l) {
        connected.add(l.source.id || l.source);
        connected.add(l.target.id || l.target);
    });
    node.select('circle').attr('opacity', function(n) { return connected.has(n.id) || n.id === d.id ? 1 : 0.15; });
    link.attr('stroke-opacity', function(l) { return (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id ? 1 : 0.1; });
}).on('mouseout', function() {
    tooltip.style.display = 'none';
    applyFilters();
});

// Click handler: entity -> clipboard, sector -> clipboard
var dragStartPos = null;
node.on('mousedown', function(event, d) { dragStartPos = [event.pageX, event.pageY]; })
    .on('mouseup', function(event, d) {
        if (!dragStartPos) return;
        var dx = event.pageX - dragStartPos[0];
        var dy = event.pageY - dragStartPos[1];
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) {
            showEntityPanel(d);
        }
        dragStartPos = null;
    });

// Search and filter
var currentTypeFilter = 'all';
var searchTerm = '';
var currentClusterFilter = -1; // -1 = no cluster filter
var filterTimer = null;
function filterNodes(term) {
    searchTerm = term.toLowerCase().trim();
    clearTimeout(filterTimer);
    filterTimer = setTimeout(applyFilters, 150);
}
function setTypeFilter(type) {
    currentTypeFilter = type;
    document.getElementById('btnAll').className = type === 'all' ? 'active' : '';
    document.getElementById('btnSector').className = type === 'sector' ? 'active' : '';
    document.getElementById('btnEntity').className = type === 'entity' ? 'active' : '';
    applyFilters();
}

""" + ("""
function toggleClusterFilter(cid) {
    currentClusterFilter = (currentClusterFilter === cid) ? -1 : cid;
    // Update cluster button states
    document.querySelectorAll('#search .cluster-btn').forEach(function(b) {
        b.className = 'cluster-btn' + (currentClusterFilter === parseInt(b.dataset.cid)) ? ' active' : '';
    });
    // Update legend highlight
    document.querySelectorAll('#legend .legend-item').forEach(function(li, idx) {
        li.style.fontWeight = (currentClusterFilter === idx) ? 'bold' : '';
    });
    applyFilters();
}
function toggleClusterPanel() {
    var panel = document.getElementById('cluster-panel');
    panel.style.display = panel.style.display === 'none' ? '' : 'none';
}
""" if enable_clusters else '') + """

// Timeline / temporal filter
var currentMonthIdx = allMonths.length - 1;
var currentMonth = allMonths[currentMonthIdx];
var timelineSlider = document.getElementById('timelineSlider');
var dateLabel = document.getElementById('dateLabel');
var dateRangeStart = document.getElementById('dateRangeStart');
var dateRangeEnd = document.getElementById('dateRangeEnd');
if (timelineSlider) {
    timelineSlider.max = allMonths.length - 1;
    timelineSlider.value = currentMonthIdx;
    dateLabel.textContent = currentMonth;
    dateRangeStart.textContent = allMonths[0];
    dateRangeEnd.textContent = allMonths[allMonths.length - 1];
}

function setTimelineMonth(idx) {
    currentMonthIdx = Math.max(0, Math.min(allMonths.length - 1, idx));
    currentMonth = allMonths[currentMonthIdx];
    if (timelineSlider) timelineSlider.value = currentMonthIdx;
    if (dateLabel) dateLabel.textContent = currentMonth;
    applyFilters();
}
function onTimelineInput(val) { setTimelineMonth(parseInt(val)); }

// Animation
var animTimer = null;
var animSpeed = 800;
var animPlaying = false;
function toggleAnimation() { animPlaying ? stopAnimation() : startAnimation(); }
function startAnimation() {
    animPlaying = true;
    var btn = document.getElementById('playBtn');
    if (btn) { btn.textContent = '\\u23f8'; btn.className = 'tl-btn playing'; }
    if (currentMonthIdx >= allMonths.length - 1) setTimelineMonth(0);
    animTimer = setInterval(function() {
        if (currentMonthIdx < allMonths.length - 1) setTimelineMonth(currentMonthIdx + 1);
        else stopAnimation();
    }, animSpeed);
}
function stopAnimation() {
    animPlaying = false;
    if (animTimer) { clearInterval(animTimer); animTimer = null; }
    var btn = document.getElementById('playBtn');
    if (btn) { btn.textContent = '\\u25b6'; btn.className = 'tl-btn'; }
}
function changeSpeed() {
    var speeds = [1200, 800, 400, 200];
    var labels = ['0.5x', '1x', '2x', '4x'];
    var si = speeds.indexOf(animSpeed);
    var ni = (si + 1) % speeds.length;
    animSpeed = speeds[ni];
    document.getElementById('speedLabel').textContent = labels[ni];
    if (animPlaying) { stopAnimation(); startAnimation(); }
}
function skipToEnd() { stopAnimation(); setTimelineMonth(allMonths.length - 1); }
function skipToStart() { stopAnimation(); setTimelineMonth(0); }

// Combined filter (search + type + temporal + cluster)
function applyFilters() {
    var matchCount = 0;
    var matchIds = new Set();

    node.each(function(d) {
        var matches = true;
        // Type filter
        if (currentTypeFilter !== 'all' && d.type !== currentTypeFilter) matches = false;
        // Search filter
        if (searchTerm) {
            var searchable = (d.label + ' ' + (d.entidade || '') + ' ' + (d.nif || '') + ' ' + d.type).toLowerCase();
            if (searchable.indexOf(searchTerm) === -1) matches = false;
        }
        // Cluster filter
        """ + ('if (currentClusterFilter >= 0 && d.community !== currentClusterFilter) matches = false;' if enable_clusters else '') + """
        // Temporal filter
        if (d.type === 'entity' && d.first_date) {
            if (d.first_date.substring(0, 7) > currentMonth) matches = false;
        }
        if (matches) { matchCount++; matchIds.add(d.id); }
    });

    var countEl = document.getElementById('matchCount');
    if (searchTerm || currentTypeFilter !== 'all' || currentClusterFilter >= 0) {
        countEl.textContent = matchCount + ' / ' + nodes.length;
    } else {
        countEl.textContent = '';
    }

    node.select('circle')
        .attr('opacity', function(d) {
            if (!matchIds.has(d.id)) return (searchTerm || currentTypeFilter !== 'all' || currentClusterFilter >= 0) ? 0.1 : 0.15;
            return 0.85;
        })
        .attr('stroke-width', function(d) { return matchIds.has(d.id) && (searchTerm || currentTypeFilter !== 'all' || currentClusterFilter >= 0) ? 3 : 2; });

    labels.style('opacity', function(d) { return matchIds.has(d.id) ? 1 : (searchTerm || currentTypeFilter !== 'all' || currentClusterFilter >= 0) ? 0.15 : 1; });

    link.attr('stroke-opacity', function(l) {
        var src = l.source.id || l.source;
        var tgt = l.target.id || l.target;
        var edgeDate = l.date || '';
        if (edgeDate && edgeDate.substring(0, 7) > currentMonth) return 0.03;
        if (searchTerm || currentTypeFilter !== 'all' || currentClusterFilter >= 0) {
            return matchIds.has(src) && matchIds.has(tgt) ? 0.8 : 0.05;
        }
        return 0.6;
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

simulation.on('tick', function() {
    link
        .attr('x1', function(d) { return d.source.x; })
        .attr('y1', function(d) { return d.source.y; })
        .attr('x2', function(d) { return d.target.x; })
        .attr('y2', function(d) { return d.target.y; });
    node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
    if (typeof updateMinimap === 'function') updateMinimap();
});

function dragstarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x; d.fy = d.y;
}
function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null; d.fy = null;
}

function resetZoom() {
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
}
function toggleLabels() {
    showLabels = !showLabels;
    labels.style('display', showLabels ? 'block' : 'none');
}
var physicsRunning = true;
function togglePhysics() {
    physicsRunning = !physicsRunning;
    if (physicsRunning) simulation.alpha(0.3).restart();
    else simulation.stop();
}

// Export functionality
function toggleExportMenu() {
    var menu = document.getElementById('export-menu');
    menu.classList.toggle('show');
}

document.addEventListener('click', function(e) {
    var menu = document.getElementById('export-menu');
    if (menu && !e.target.closest('#controls')) menu.classList.remove('show');
});

function nodeMatchesFilters(d) {
    if (currentTypeFilter !== 'all' && d.type !== currentTypeFilter) return false;
    if (searchTerm) {
        var s = (d.label + ' ' + (d.entidade || '') + ' ' + (d.nif || '') + ' ' + d.type).toLowerCase();
        if (s.indexOf(searchTerm) === -1) return false;
    }
    if (currentClusterFilter >= 0 && d.community !== currentClusterFilter) return false;
    if (d.type === 'entity' && d.first_date && d.first_date.substring(0, 7) > currentMonth) return false;
    return true;
}
function getVisibleNodes() {
    var visible = [];
    node.each(function(d) { if (nodeMatchesFilters(d)) visible.push(d); });
    return visible;
}

function getVisibleEdges(visibleIds) {
    var idSet = new Set(visibleIds);
    return links.filter(function(l) {
        var src = l.source.id || l.source;
        var tgt = l.target.id || l.target;
        var edgeDate = l.date || '';
        if (edgeDate && edgeDate.substring(0, 7) > currentMonth) return false;
        return idSet.has(src) && idSet.has(tgt);
    });
}

function downloadFile(content, filename, mimeType) {
    var blob = new Blob([content], { type: mimeType });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(function() { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
}

function exportCSV(type) {
    document.getElementById('export-menu').classList.remove('show');
    if (type === 'nodes') {
        var vis = getVisibleNodes();
        var header = 'id,label,type,entidade,nif,listings,contracts,contract_value,community,first_date,last_date';
        var rows = vis.map(function(d) {
            return [d.id, '"' + (d.label||'').replace(/"/g,'""') + '"', d.type,
                '"' + (d.entidade||'').replace(/"/g,'""') + '"', d.nif || '',
                d.listings || d.total_listings || 0, d.contracts || 0,
                d.contract_value || 0, d.community || 0,
                d.first_date || '', d.last_date || ''].join(',');
        });
        downloadFile(header + '\n' + rows.join('\n'), 'network_nodes.csv', 'text/csv');
    } else {
        var vis = getVisibleNodes();
        var visIds = new Set(vis.map(function(d) { return d.id; }));
        var edges = getVisibleEdges(Array.from(visIds));
        var header = 'source,target,label,strength,date';
        var rows = edges.map(function(l) {
            var src = l.source.id || l.source;
            var tgt = l.target.id || l.target;
            return [src, tgt, '"' + (l.label||'').replace(/"/g,'""') + '"',
                l.strength || 1, l.date || ''].join(',');
        });
        downloadFile(header + '\n' + rows.join('\n'), 'network_edges.csv', 'text/csv');
    }
}

function exportJSON() {
    document.getElementById('export-menu').classList.remove('show');
    var vis = getVisibleNodes();
    var visIds = new Set(vis.map(function(d) { return d.id; }));
    var edges = getVisibleEdges(Array.from(visIds));
    var cleanEdges = edges.map(function(l) {
        return { source: l.source.id || l.source, target: l.target.id || l.target,
            label: l.label, strength: l.strength, date: l.date };
    });
    var exportData = {
        metadata: { title: 'Entity Correlation Network', exported: new Date().toISOString(),
            filters: { search: searchTerm, type: currentTypeFilter, cluster: currentClusterFilter,
            month: currentMonth },
            counts: { nodes: vis.length, edges: cleanEdges.length } },
        nodes: vis.map(function(d) {
            var clean = { id: d.id, label: d.label, type: d.type, entidade: d.entidade || '',
                nif: d.nif || '', community: d.community || 0 };
            if (d.type === 'entity') { clean.listings = d.listings; clean.contracts = d.contracts;
                clean.contract_value = d.contract_value; clean.first_date = d.first_date; }
            if (d.type === 'sector') { clean.entities = d.entities; clean.total_listings = d.total_listings; }
            return clean;
        }),
        edges: cleanEdges
    };
    downloadFile(JSON.stringify(exportData, null, 2), 'network_export.json', 'application/json');
}

window.addEventListener('resize', function() {
    svg.attr('width', window.innerWidth).attr('height', window.innerHeight);
    simulation.force('center', d3.forceCenter(window.innerWidth / 2, window.innerHeight / 2));
    simulation.alpha(0.3).restart();
});


// --- Entity Profile Panel ---
var selectedEntityId = null;
function showEntityPanel(d) {
    selectedEntityId = d.id;
    var panel = document.getElementById('entity-panel');
    document.getElementById('epTitle').textContent = d.label;
    // Meta badges
    var meta = '';
    if (d.type === 'entity' && d.nif) meta += '<span class="ep-badge sector">NIF: ' + d.nif + '</span>';
    if (d.type === 'entity' && d.entidade) meta += '<span class="ep-badge sector" title="' + d.entidade + '">' + (d.entidade.length > 30 ? d.entidade.substring(0,30) + '...' : d.entidade) + '</span>';
    meta += '<span class="ep-badge cluster">Cluster ' + (d.community || 0) + '</span>';
    document.getElementById('epMeta').innerHTML = meta;
    // Stats
    var stats = '';
    if (d.type === 'entity') {
        stats += '<div class="ep-stat-row"><span class="ep-stat-label">BEP Listings</span><span class="ep-stat-value">' + (d.listings || 0) + '</span></div>';
        stats += '<div class="ep-stat-row"><span class="ep-stat-label">BASE Contracts</span><span class="ep-stat-value">' + (d.contracts || 0) + '</span></div>';
        if (d.contract_value > 0) stats += '<div class="ep-stat-row"><span class="ep-stat-label">Contract Value</span><span class="ep-stat-value money">€' + d.contract_value.toLocaleString() + '</span></div>';
        if (d.first_date) stats += '<div class="ep-stat-row"><span class="ep-stat-label">First Listing</span><span class="ep-stat-value">' + d.first_date + '</span></div>';
        if (d.last_date) stats += '<div class="ep-stat-row"><span class="ep-stat-label">Last Listing</span><span class="ep-stat-value">' + d.last_date + '</span></div>';
    } else {
        stats += '<div class="ep-stat-row"><span class="ep-stat-label">Entities</span><span class="ep-stat-value">' + (d.entities || 0) + '</span></div>';
        stats += '<div class="ep-stat-row"><span class="ep-stat-label">Total Listings</span><span class="ep-stat-value">' + (d.total_listings || 0) + '</span></div>';
    }
    var conns = links.filter(function(l) { return (l.source.id || l.source) === d.id || (l.target.id || l.target) === d.id; });
    stats += '<div class="ep-stat-row"><span class="ep-stat-label">Connections</span><span class="ep-stat-value">' + conns.length + '</span></div>';
    document.getElementById('epStats').innerHTML = stats;
    // Actions
    var actions = '';
    if (d.cmd) actions += '<a href="#" onclick="copyCmd('' + d.cmd.replace(/'/g, "\'") + ''); return false;">📜 Copy CLI Command</a>';
    if (d.type === 'entity' && d.nif) {
        actions += '<a href="https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id=' + d.nif + '" target="_blank">🔗 View on BASE.gov.pt</a>';
        actions += '<a href="#" onclick="window.open('dashboard_' + d.nif + '.html', '_blank'); return false;">📊 Open Full Dashboard</a>';
    }
    document.getElementById('epActions').innerHTML = actions;
    panel.style.display = 'block';
    var legend = document.getElementById('legend');
    if (legend) legend.style.display = 'none';
    // Highlight selected node
    node.select('circle').attr('stroke-width', function(n) { return n.id === d.id ? 4 : 2; });
}
function closeEntityPanel() {
    document.getElementById('entity-panel').style.display = 'none';
    var legend = document.getElementById('legend');
    if (legend) legend.style.display = '';
    selectedEntityId = null;
    node.select('circle').attr('stroke-width', 2);
}
function copyCmd(cmd) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmd).then(function() {
            var badge = document.createElement('div');
            badge.textContent = 'Copied!';
            badge.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#10b981;color:white;padding:0.5rem 1rem;border-radius:8px;font-size:0.85rem;z-index:200;pointer-events:none;transition:opacity 0.5s';
            document.body.appendChild(badge);
            setTimeout(function() { badge.style.opacity = '0'; }, 800);
            setTimeout(function() { badge.remove(); }, 1300);
        }).catch(function() { window.prompt('Copy this command:', cmd); });
    } else {
        window.prompt('Copy this command:', cmd);
    }
}

// --- Minimap ---
var mmWidth = 180, mmHeight = 130;
var mmSvg = d3.select('#minimapSvg').attr('width', mmWidth).attr('height', mmHeight);
var mmG = mmSvg.append('g');
var mmViewport = mmSvg.append('rect')
    .attr('fill', 'rgba(59,130,246,0.15)')
    .attr('stroke', '#3b82f6')
    .attr('stroke-width', 1.5)
    .attr('rx', 2);

function updateMinimap() {
    if (nodes.length === 0) return;
    // Compute bounds of all nodes
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach(function(n) {
        if (n.x < x0) x0 = n.x;
        if (n.y < y0) y0 = n.y;
        if (n.x > x1) x1 = n.x;
        if (n.y > y1) y1 = n.y;
    });
    var pad = 40;
    x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
    var dataW = x1 - x0 || 1;
    var dataH = y1 - y0 || 1;
    var scale = Math.min(mmWidth / dataW, mmHeight / dataH);
    var offsetX = (mmWidth - dataW * scale) / 2;
    var offsetY = (mmHeight - dataH * scale) / 2;

    // Transform: data coords -> minimap coords
    function mmX(d) { return (d - x0) * scale + offsetX; }
    function mmY(d) { return (d - y0) * scale + offsetY; }

    // Draw mini edges
    mmG.selectAll('.mm-edge').remove();
    mmG.selectAll('.mm-edge').data(links).join('line')
        .attr('class', 'mm-edge')
        .attr('x1', function(l) { return mmX(l.source.x || 0); })
        .attr('y1', function(l) { return mmY(l.source.y || 0); })
        .attr('x2', function(l) { return mmX(l.target.x || 0); })
        .attr('y2', function(l) { return mmY(l.target.y || 0); })
        .attr('stroke', '#334155').attr('stroke-opacity', 0.4).attr('stroke-width', 0.5);

    // Draw mini nodes
    mmG.selectAll('.mm-node').remove();
    mmG.selectAll('.mm-node').data(nodes).join('circle')
        .attr('class', 'mm-node')
        .attr('cx', function(d) { return mmX(d.x || 0); })
        .attr('cy', function(d) { return mmY(d.y || 0); })
        .attr('r', 2)
        .attr('fill', function(d) { return d.type === 'sector' ? '#3b82f6' : '#10b981'; })
        .attr('opacity', 0.8);

    // Compute viewport rectangle in data coords
    var t = d3.zoomTransform(svg.node());
    var vw = width / t.k;
    var vh = height / t.k;
    var vx = -t.x / t.k;
    var vy = -t.y / t.k;

    mmViewport
        .attr('x', mmX(vx))
        .attr('y', mmY(vy))
        .attr('width', vw * scale)
        .attr('height', vh * scale);
}

// Sync minimap on zoom
svg.on('zoom.minimap', function() { updateMinimap(); });

// Drag on minimap to pan main view
var mmDragging = false;
mmSvg.on('mousedown', function(event) {
    mmDragging = true;
    event.preventDefault();
});
d3.select(window).on('mousemove.minimap', function(event) {
    if (!mmDragging) return;
    var bounds = mmSvg.node().getBoundingClientRect();
    var mx = event.clientX - bounds.left;
    var my = event.clientY - bounds.top;

    // Recompute data bounds
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach(function(n) {
        if (n.x < x0) x0 = n.x;
        if (n.y < y0) y0 = n.y;
        if (n.x > x1) x1 = n.x;
        if (n.y > y1) y1 = n.y;
    });
    var pad = 40;
    x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
    var dataW = x1 - x0 || 1;
    var dataH = y1 - y0 || 1;
    var scale = Math.min(mmWidth / dataW, mmHeight / dataH);
    var offsetX = (mmWidth - dataW * scale) / 2;
    var offsetY = (mmHeight - dataH * scale) / 2;

    // Convert minimap click to data coords, then center main view
    var dataX = (mx - offsetX) / scale + x0;
    var dataY = (my - offsetY) / scale + y0;
    var t = d3.zoomTransform(svg.node());
    var newTx = -(dataX * t.k) + width / 2;
    var newTy = -(dataY * t.k) + height / 2;
    svg.call(zoom.transform, d3.zoomIdentity.translate(newTx, newTy).scale(t.k));
}).on('mouseup.minimap', function() { mmDragging = false; })
.on('mouseleave.minimap', function() { mmDragging = false; });

// Initial draw and periodic refresh
updateMinimap();
setInterval(updateMinimap, 500);

"""

    # Assemble HTML
    parts = []
    parts.append("<!DOCTYPE html>\n<html lang=\"pt\">\n<head>\n")
    parts.append("<meta charset=\"UTF-8\">\n")
    parts.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n")
    parts.append("<title>" + esc_title + "</title>\n")
    parts.append("<style>\n" + css + "</style>\n")
    parts.append("</head>\n<body>\n")
    parts.append("<div id=\"header\">\n")
    parts.append("<h1>&#x1f517; " + esc_title + "</h1>\n")
    parts.append("<div class=\"subtitle\">Node-based Correlation Visualization &mdash; Analisa.pt</div>\n")
    parts.append("</div>\n")
    parts.append(search_html)
    # Timeline slider
    parts.append("<div id=\"timeline\">\n")
    parts.append("<button class=\"tl-btn\" id=\"skipStartBtn\" onclick=\"skipToStart()\" title=\"Skip to start\">&#x23ee;</button>\n")
    parts.append("<button class=\"tl-btn\" id=\"playBtn\" onclick=\"toggleAnimation()\" title=\"Play/Pause\">&#x25b6;</button>\n")
    parts.append("<button class=\"tl-btn\" id=\"skipEndBtn\" onclick=\"skipToEnd()\" title=\"Skip to end\">&#x23ed;</button>\n")
    parts.append("<span class=\"range-label\" id=\"dateRangeStart\"></span>\n")
    parts.append("<input type=\"range\" id=\"timelineSlider\" min=\"0\" max=\"0\" value=\"0\" oninput=\"onTimelineInput(this.value)\">\n")
    parts.append("<span class=\"range-label\" id=\"dateRangeEnd\"></span>\n")
    parts.append("<span class=\"date-label\" id=\"dateLabel\">\u2014</span>\n")
    parts.append("<button class=\"tl-btn\" onclick=\"changeSpeed()\" title=\"Change speed\"><span id=\"speedLabel\">1x</span></button>\n")
    parts.append("</div>\n")
    parts.append("<div id=\"tooltip\"></div>\n")

    # Legend with cluster info
    parts.append("<div id=\"legend\">\n")
    parts.append("<h4>Legend</h4>\n")
    parts.append("<div class=\"legend-item\"><div class=\"legend-dot\" style=\"background:#3b82f6\"></div>Sector (department)</div>\n")
    if enable_clusters:
        parts.append("<div class=\"legend-item\"><div class=\"legend-dot\" style=\"background:linear-gradient(135deg, #10b981, #3b82f6)\"></div>Entity (colored by cluster)</div>\n")
    else:
        parts.append("<div class=\"legend-item\"><div class=\"legend-dot\" style=\"background:#10b981\"></div>Entity (agency)</div>\n")
    parts.append("<div class=\"legend-item\" style=\"font-size:0.65rem;color:#64748b\">Node size = listing count</div>\n")
    parts.append("<div class=\"legend-item\" style=\"font-size:0.65rem;color:#64748b\">Edge thickness = connection strength</div>\n")
    if enable_clusters:
        parts.append("<div id=\"clusterLegend\"></div>\n")
    parts.append("</div>\n")
    parts.append("<div id=\"entity-panel\">\n")
    parts.append("<div class=\"ep-header\"><h3 id=\"epTitle\"></h3><button class=\"ep-close\" onclick=\"closeEntityPanel()\">✕</button></div>\n")
    parts.append("<div class=\"ep-body\">\n")
    parts.append("<div class=\"ep-meta\" id=\"epMeta\"></div>\n")
    parts.append("<div id=\"epStats\"></div>\n")
    parts.append("<div class=\"ep-actions\" id=\"epActions\"></div>\n")
    parts.append("</div>\n")
    parts.append("</div>\n")

    # Stats panel
    parts.append("<div id=\"stats\">\n")
    parts.append("<div class=\"stat\">Visible: <strong id=\"nodeCount\">0</strong> nodes</div>\n")
    parts.append("<div class=\"stat\">Visible: <strong id=\"edgeCount\">0</strong> edges</div>\n")
    parts.append("<div class=\"stat\">Sectors: <strong id=\"sectorCount\">0</strong></div>\n")
    if enable_clusters:
        parts.append("<div class=\"stat\">Clusters: <strong id=\"clusterCount\">0</strong></div>\n")
    parts.append("</div>\n")

    # Cluster panel (collapsible)
    if enable_clusters:
        parts.append("<div id=\"cluster-panel\">\n")
        parts.append("<h4>Leiden Clusters</h4>\n")
        parts.append("<div id=\"clusterList\"></div>\n")
        parts.append("</div>\n")

    # Controls
    parts.append("<div id=\"controls\">\n")
    parts.append("<button onclick=\"resetZoom()\">Reset Zoom</button>\n")
    parts.append("<button onclick=\"toggleLabels()\">Labels</button>\n")
    parts.append("<button onclick=\"togglePhysics()\">Physics</button>\n")
    parts.append("<div style=\"position:relative\">\n")
    parts.append("<button onclick=\"toggleExportMenu()\">Export</button>\n")
    parts.append("<div id=\"export-menu\">\n")
    parts.append("<button onclick=\"exportCSV('nodes')\">CSV — Visible Nodes</button>\n")
    parts.append("<button onclick=\"exportCSV('edges')\">CSV — Visible Edges</button>\n")
    parts.append("<button onclick=\"exportJSON()\">JSON — Full Graph</button>\n")
    parts.append("</div>\n")
    parts.append("</div>\n")
    parts.append("</div>\n")

    parts.append("<svg id=\"graph\"></svg>\n")
    parts.append("<div id=\"minimap\"><div class=\"mm-label\">Overview</div><svg id=\"minimapSvg\"></svg></div>\n")
    parts.append("<script src=\"https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js\"></script>\n")
    parts.append("<script>\n")

    if enable_clusters:
        parts.append(louvain_js)

    parts.append(js)
    parts.append("</script>\n</body>\n</html>")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Generate Node-based Correlation Network")
    parser.add_argument("-o", "--output", default="", help="Output HTML file")
    parser.add_argument("--sector", default="", help="Filter by sector name")
    parser.add_argument("--min-connections", type=int, default=1,
                        help="Minimum shared categories for entity-entity edges")
    parser.add_argument("--top", type=int, default=0, help="Show only top N entities by listing count")
    parser.add_argument("--no-clusters", action="store_true", help="Disable community detection clustering")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")

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
    listings = load_all_listings()
    print(f"  {len(listings)} entities with listings")

    print("Loading contracts...")
    contracts = load_contracts()
    print(f"  {sum(len(v) for v in contracts.values())} total contracts")

    title = "Entity Correlation Network"
    if args.sector:
        title = f"{args.sector} \u2014 Correlation Network"

    print("Building graph...")
    nodes, edges = build_graph(entities, listings, contracts,
                               filter_sector=args.sector,
                               min_connections=args.min_connections)
    print(f"  {len(nodes)} nodes, {len(edges)} edges")

    enable_clusters = not args.no_clusters

    print("Generating visualization...")
    html = build_network_html(nodes, edges, title, enable_clusters=enable_clusters)
    output = args.output or "network.html"
    Path(output).write_text(html, encoding="utf-8")
    print(f"  \u2705 Saved to {output}")

    if args.open:
        webbrowser.open(Path(output).resolve().as_uri())


if __name__ == "__main__":
    main()
