import { useEffect, useRef } from "react";
import * as d3 from "d3";
import type { PersonnelNetworkMetrics } from "../types";

interface PersonnelGraphProps {
  personnel: PersonnelNetworkMetrics;
}

export default function PersonnelGraph({ personnel }: PersonnelGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || personnel.nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = 700;
    const height = 500;

    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const colorMap: Record<string, string> = {
      media: "#00d4aa",
      state: "#f59e0b",
      regulator: "#a78bfa",
      other: "#556080",
    };

    const nodesData = personnel.nodes.map((n) => ({ ...n }));
    const edgesData = personnel.edges.map((e) => ({ ...e }));

    const simulation = d3
      .forceSimulation(nodesData as any)
      .force(
        "link",
        d3
          .forceLink(edgesData)
          .id((d: any) => d.id)
          .distance(100)
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(30));

    const defs = svg.append("defs");
    defs
      .append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "#253060");

    const link = svg
      .append("g")
      .selectAll("line")
      .data(edgesData)
      .join("line")
      .attr("stroke", "#253060")
      .attr("stroke-width", (d) => Math.min(d.value * 2, 4))
      .attr("stroke-opacity", 0.4);

    const node = svg
      .append("g")
      .selectAll("g")
      .data(nodesData)
      .join("g")
      .call(
        d3
          .drag<SVGGElement, any>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }) as any
      );

    node
      .append("circle")
      .attr("r", (d) => (d.type === "person" ? 12 : 16))
      .attr("fill", (d) => colorMap[d.group] || "#556080")
      .attr("stroke", "#070b1a")
      .attr("stroke-width", 2)
      .attr("opacity", 0.9);

    node
      .append("text")
      .text((d) => d.label.substring(0, 20))
      .attr("x", 18)
      .attr("y", 4)
      .attr("font-size", "9px")
      .attr("fill", "#8892b0")
      .attr("font-family", "Inter, sans-serif");

    node.append("title").text((d) => `${d.label} (${d.type})`);

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);

      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
      simulation.on("tick", null);
    };
  }, [personnel]);

  if (personnel.nodes.length === 0) {
    return (
      <section className="section-card">
        <h2 className="section-title">
          <span className="section-icon">🕸️</span>
          Personnel Network
        </h2>
        <div className="section-empty">
          No personnel network data available. Run the DRE spider to collect
          appointment data.
        </div>
      </section>
    );
  }

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">🕸️</span>
        Personnel Network — Revolving Door
      </h2>
      <div className="personnel-summary">
        <div className="summary-stat">
          <span className="stat-value">{personnel.total_people}</span>
          <span className="stat-label">People</span>
        </div>
        <div className="summary-stat">
          <span className="stat-value">{personnel.total_appointments}</span>
          <span className="stat-label">Appointments</span>
        </div>
        <div className="summary-stat">
          <span className="stat-value">{personnel.edges.length}</span>
          <span className="stat-label">Connections</span>
        </div>
      </div>
      <div className="personnel-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: "#00d4aa" }} />
          Media
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: "#f59e0b" }} />
          State
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: "#a78bfa" }} />
          Regulator
        </span>
      </div>
      <div className="personnel-graph-wrap">
        <svg ref={svgRef} className="personnel-graph" />
      </div>
    </section>
  );
}
