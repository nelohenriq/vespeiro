#!/usr/bin/env python3
"""Entity Network Visualization Generator

Generates a standalone HTML file with D3.js force-directed graph showing
buyer-seller relationships from procurement.db.

Usage:
    python generate_network_viz.py                    # Default: top 50 pairs
    python generate_network_viz.py --top 100          # Top 100 pairs
    python generate_network_viz.py --min-contracts 5  # Only pairs with 5+ contracts
    python generate_network_viz.py --entity "Fundão"  # Focus on specific entity
"""

import json
import sqlite3
import argparse
from pathlib import Path
from collections import defaultdict

from utils import fmt, parse_entity_field

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
PROCUREMENT_DB = DATA_DIR / "procurement.db"
DEFAULT_OUTPUT = DATA_DIR / "entity_network_viz.html"



def query_network(top_n: int = 50, min_contracts: int = 2, entity_filter: str = "") -> dict:
    """Query procurement.db for network relationship data."""
    conn = sqlite3.connect(str(PROCUREMENT_DB))
    conn.row_factory = sqlite3.Row

    # Aggregate in SQL first, then parse adjudicatarios only for top groups
    rows = conn.execute("""
        SELECT adjudicante_nif, adjudicante_nome, adjudicatarios,
               COUNT(*) as cnt, SUM(precoContratual) as total
        FROM contratos
        WHERE adjudicante_nif IS NOT NULL AND adjudicante_nif != ''
        AND adjudicatarios IS NOT NULL AND adjudicatarios != ''
        AND adjudicatarios LIKE '% - %'
        GROUP BY adjudicante_nif, adjudicatarios
        ORDER BY total DESC
        LIMIT 500
    """).fetchall()
    conn.close()

    # Build pair aggregation by parsing adjudicatarios from top groups
    pair_agg = {}
    for r in rows:
        buyer_nif = r["adjudicante_nif"]
        buyer_name = r["adjudicante_nome"] or buyer_nif
        cnt = r["cnt"]
        total = r["total"] or 0

        winners = parse_entity_field(r["adjudicatarios"])
        for seller_nif, seller_name in winners:
            if not seller_nif:
                continue
            key = (buyer_nif, seller_nif)
            if key not in pair_agg:
                pair_agg[key] = {
                    "buyer_nif": buyer_nif, "buyer_name": buyer_name,
                    "seller_nif": seller_nif, "seller_name": seller_name,
                    "count": 0, "total": 0,
                }
            pair_agg[key]["count"] += cnt
            pair_agg[key]["total"] += total

    # Filter and sort
    pairs = [p for p in pair_agg.values() if p["count"] >= min_contracts]
    if entity_filter:
        q = entity_filter.lower()
        pairs = [p for p in pairs if q in p["buyer_name"].lower() or q in p["seller_name"].lower()]
    pairs.sort(key=lambda x: -x["total"])
    pairs = pairs[:top_n]

    # Build nodes and edges
    nodes = {}
    edges = []

    for p in pairs:
        for nif, name, ntype in [(p["buyer_nif"], p["buyer_name"], "buyer"), (p["seller_nif"], p["seller_name"], "seller")]:
            if nif not in nodes:
                nodes[nif] = {"id": nif, "name": name, "type": ntype, "contracts": 0, "value": 0}
            nodes[nif]["contracts"] += p["count"]
            nodes[nif]["value"] += p["total"]

        edges.append({
            "source": p["buyer_nif"],
            "target": p["seller_nif"],
            "value": p["total"],
            "count": p["count"],
        })

    total_value = sum(e["value"] for e in edges)
    total_contracts = sum(e["count"] for e in edges)

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_value": total_value,
            "total_contracts": total_contracts,
        },
        "top_n": top_n,
        "min_contracts": min_contracts,
    }


def generate_html(data: dict) -> str:
    """Generate standalone HTML with D3.js force-directed graph."""
    nodes_json = json.dumps(data["nodes"], ensure_ascii=False)
    edges_json = json.dumps(data["edges"], ensure_ascii=False)
    stats = data["stats"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Entity Network — Portuguese Procurement Relationships</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  :root {{
    --buyer: #2563eb;
    --seller: #059669;
    --bg: #0f172a;
    --card: #1e293b;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --border: #334155;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); overflow: hidden; }}
  #graph {{ width: 100vw; height: 100vh; }}
  .controls {{
    position: fixed; top: 16px; left: 16px; z-index: 10;
    background: var(--card); border-radius: 12px; padding: 16px;
    border: 1px solid var(--border); max-width: 320px;
  }}
  .controls h2 {{ font-size: 16px; margin-bottom: 8px; }}
  .controls .stat {{ font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
  .controls .stat span {{ color: var(--text); font-weight: 600; }}
  .legend {{
    position: fixed; bottom: 16px; left: 16px; z-index: 10;
    background: var(--card); border-radius: 8px; padding: 12px;
    border: 1px solid var(--border); font-size: 12px;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .tooltip {{
    position: fixed; z-index: 100; pointer-events: none;
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px; font-size: 12px;
    max-width: 300px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    display: none;
  }}
  .tooltip .name {{ font-weight: 700; font-size: 14px; margin-bottom: 4px; }}
  .tooltip .detail {{ color: var(--muted); margin-bottom: 2px; }}
  .tooltip .value {{ color: #f59e0b; font-weight: 600; }}
  .search {{
    position: fixed; top: 16px; right: 16px; z-index: 10;
    background: var(--card); border-radius: 8px; padding: 8px;
    border: 1px solid var(--border);
  }}
  .search input {{
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; color: var(--text); font-size: 13px; width: 200px;
  }}
  .search input:focus {{ outline: none; border-color: var(--buyer); }}
  .search input::placeholder {{ color: var(--muted); }}
</style>
</head>
<body>
<svg id="graph"></svg>

<div class="controls">
  <h2>🔗 Entity Network</h2>
  <div class="stat">Nodes: <span>{stats['total_nodes']}</span></div>
  <div class="stat">Relationships: <span>{stats['total_edges']}</span></div>
  <div class="stat">Total Value: <span>{fmt(stats['total_value'])}</span></div>
  <div class="stat">Total Contracts: <span>{stats['total_contracts']:,}</span></div>
</div>

<div class="legend">
  <div class="legend-item"><div class="legend-dot" style="background:var(--buyer)"></div> Buyer (Adjudicante)</div>
  <div class="legend-item"><div class="legend-dot" style="background:var(--seller)"></div> Winner (Adjudicatário)</div>
  <div class="legend-item"><div class="legend-dot" style="background:#f59e0b"></div> Self-referencing</div>
  <div style="margin-top:8px;color:var(--muted);font-size:11px">Edge thickness = contract value</div>
</div>

<div class="search">
  <input type="text" id="searchInput" placeholder="Search entity..." oninput="searchNode(this.value)">
</div>

<div class="tooltip" id="tooltip"></div>

<script>
const nodes = {nodes_json};
const edges = {edges_json};

const width = window.innerWidth;
const height = window.innerHeight;

const svg = d3.select("#graph")
  .attr("width", width)
  .attr("height", height);

const g = svg.append("g");

// Zoom
const zoom = d3.zoom()
  .scaleExtent([0.1, 5])
  .on("zoom", (event) => g.attr("transform", event.transform));
svg.call(zoom);

// Scale for edge width
const edgeScale = d3.scaleLinear()
  .domain([0, d3.max(edges, d => d.value) || 1])
  .range([1, 8]);

// Scale for node size
const nodeScale = d3.scaleSqrt()
  .domain([0, d3.max(nodes, d => d.value) || 1])
  .range([6, 25]);

// Simulation
const simulation = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(edges).id(d => d.id).distance(100).strength(0.3))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide().radius(d => nodeScale(d.value) + 5));

// Edges
const link = g.append("g")
  .selectAll("line")
  .data(edges)
  .join("line")
  .attr("stroke", "#475569")
  .attr("stroke-opacity", 0.5)
  .attr("stroke-width", d => edgeScale(d.value));

// Nodes
const node = g.append("g")
  .selectAll("circle")
  .data(nodes)
  .join("circle")
  .attr("r", d => nodeScale(d.value))
  .attr("fill", d => d.type === "buyer" ? "#2563eb" : "#059669")
  .attr("stroke", "#fff")
  .attr("stroke-width", 1.5)
  .attr("opacity", 0.9)
  .call(d3.drag()
    .on("start", dragstarted)
    .on("drag", dragged)
    .on("end", dragended));

// Labels for large nodes
const labels = g.append("g")
  .selectAll("text")
  .data(nodes.filter(d => d.value > d3.median(nodes, n => n.value)))
  .join("text")
  .text(d => d.name.length > 25 ? d.name.substring(0, 25) + "..." : d.name)
  .attr("font-size", 10)
  .attr("fill", "#94a3b8")
  .attr("dx", d => nodeScale(d.value) + 4)
  .attr("dy", 3);

// Tooltip
const tooltip = d3.select("#tooltip");

node.on("mouseover", (event, d) => {{
  tooltip.style("display", "block")
    .html(`
      <div class="name">${{d.name}}</div>
      <div class="detail">NIF: ${{d.id}}</div>
      <div class="detail">Type: ${{d.type === 'buyer' ? 'Adjudicante (Buyer)' : 'Adjudicatário (Winner)'}}</div>
      <div class="detail">Contracts: ${{d.contracts.toLocaleString()}}</div>
      <div class="value">Total Value: ${{formatValue(d.value)}}</div>
    `)
    .style("left", (event.pageX + 15) + "px")
    .style("top", (event.pageY - 10) + "px");

  // Highlight connected edges
  link.attr("stroke-opacity", e => (e.source.id === d.id || e.target.id === d.id) ? 1 : 0.1)
      .attr("stroke", e => (e.source.id === d.id || e.target.id === d.id) ? "#f59e0b" : "#475569");
  node.attr("opacity", n => {{
    if (n.id === d.id) return 1;
    const connected = edges.some(e =>
      (e.source.id === d.id && e.target.id === n.id) ||
      (e.target.id === d.id && e.source.id === n.id)
    );
    return connected ? 0.9 : 0.2;
  }});
}}).on("mouseout", () => {{
  tooltip.style("display", "none");
  link.attr("stroke-opacity", 0.5).attr("stroke", "#475569");
  node.attr("opacity", 0.9);
}});

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("cx", d => d.x).attr("cy", d => d.y);
  labels.attr("x", d => d.x).attr("y", d => d.y);
}});

function dragstarted(event) {{
  if (!event.active) simulation.alphaTarget(0.3).restart();
  event.subject.fx = event.subject.x;
  event.subject.fy = event.subject.y;
}}
function dragged(event) {{
  event.subject.fx = event.x;
  event.subject.fy = event.y;
}}
function dragended(event) {{
  if (!event.active) simulation.alphaTarget(0);
  event.subject.fx = null;
  event.subject.fy = null;
}}

function formatValue(v) {{
  if (v >= 1e9) return "€" + (v/1e9).toFixed(1) + "B";
  if (v >= 1e6) return "€" + (v/1e6).toFixed(1) + "M";
  if (v >= 1e3) return "€" + (v/1e3).toFixed(0) + "K";
  return "€" + v;
}}

function searchNode(query) {{
  if (!query) {{
    node.attr("opacity", 0.9);
    labels.attr("opacity", 1);
    link.attr("stroke-opacity", 0.5);
    return;
  }}
  query = query.toLowerCase();
  node.attr("opacity", d => d.name.toLowerCase().includes(query) || d.id.includes(query) ? 1 : 0.1);
  labels.attr("opacity", d => d.name.toLowerCase().includes(query) || d.id.includes(query) ? 1 : 0.1);
  link.attr("stroke-opacity", e => {{
    const src = typeof e.source === "object" ? e.source : nodes.find(n => n.id === e.source);
    const tgt = typeof e.target === "object" ? e.target : nodes.find(n => n.id === e.target);
    if (!src || !tgt) return 0.1;
    return (src.name.toLowerCase().includes(query) || tgt.name.toLowerCase().includes(query)) ? 0.8 : 0.05;
  }});
}}
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Entity Network Visualization Generator")
    parser.add_argument("--top", type=int, default=50, help="Top N relationships (default 50)")
    parser.add_argument("--min-contracts", type=int, default=2, help="Min contracts per pair (default 2)")
    parser.add_argument("--entity", default="", help="Focus on specific entity name")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT), help="Output HTML path")
    args = parser.parse_args()

    print(f"Querying procurement.db for top {args.top} relationships (min {args.min_contracts} contracts)...")
    data = query_network(args.top, args.min_contracts, args.entity)

    print(f"Generating network visualization...")
    html = generate_html(data)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Written to {out_path}")
    print(f"  Nodes: {data['stats']['total_nodes']}")
    print(f"  Edges: {data['stats']['total_edges']}")


if __name__ == "__main__":
    main()
