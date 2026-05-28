import { useEffect, useRef } from "react";
import * as d3 from "d3";
import type { CorrelationMetrics } from "../types";
import { formatNumber } from "../api";

interface AdCorrelationProps {
  correlation: CorrelationMetrics;
}

export default function AdCorrelation({ correlation }: AdCorrelationProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (
      !svgRef.current ||
      correlation.outlets.length < 3 ||
      !correlation.r_spend_vs_gov_coverage
    )
      return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = 560;
    const height = 340;
    const margin = { top: 20, right: 20, bottom: 50, left: 60 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const g = svg
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const data = correlation.outlets.filter(
      (o) => o.estimated_ad_spend_eur > 0 || o.gov_coverage_pct > 0
    );

    const xExtent = d3.extent(data, (d) => d.estimated_ad_spend_eur) as [number, number];
    const yExtent = d3.extent(data, (d) => d.gov_coverage_pct) as [number, number];

    const xScale = d3
      .scaleLinear()
      .domain([0, Math.max(xExtent[1], 1)])
      .range([0, innerW])
      .nice();

    const yScale = d3
      .scaleLinear()
      .domain([0, Math.max(yExtent[1], 1)])
      .range([innerH, 0])
      .nice();

    // Axes
    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(xScale).ticks(5))
      .selectAll("text")
      .attr("fill", "#556080")
      .attr("font-size", "10px");

    g.append("g")
      .call(d3.axisLeft(yScale).ticks(5).tickFormat(d3.format(".0%")))
      .selectAll("text")
      .attr("fill", "#556080")
      .attr("font-size", "10px");

    // Grid lines
    g.append("g")
      .selectAll("line.grid")
      .data(yScale.ticks(5))
      .join("line")
      .attr("x1", 0)
      .attr("x2", innerW)
      .attr("y1", (d) => yScale(d))
      .attr("y2", (d) => yScale(d))
      .attr("stroke", "#1a2450")
      .attr("stroke-width", 0.5);

    // Dots
    const colorMap: Record<string, string> = {
      "Setor Público Estatal": "#f59e0b",
      "Grupo Impresa": "#60a5fa",
      "Grupo Media Capital": "#a78bfa",
      "Grupo Sonae": "#00d4aa",
      "Grupo Cofina": "#f97316",
      "Grupo Observador": "#ec4899",
      "Global Media Group": "#ef4444",
      "Igreja Católica em Portugal": "#a78bfa",
    };

    g.selectAll("circle")
      .data(data)
      .join("circle")
      .attr("cx", (d) => xScale(d.estimated_ad_spend_eur))
      .attr("cy", (d) => yScale(d.gov_coverage_pct))
      .attr("r", 8)
      .attr("fill", (d) => colorMap[d.owner_group] || "#556080")
      .attr("stroke", "#070b1a")
      .attr("stroke-width", 1.5)
      .attr("opacity", 0.85);

    // Labels
    g.selectAll("text.label")
      .data(data)
      .join("text")
      .attr("x", (d) => xScale(d.estimated_ad_spend_eur) + 10)
      .attr("y", (d) => yScale(d.gov_coverage_pct) + 3)
      .text((d) => d.outlet_name.substring(0, 14))
      .attr("fill", "#8892b0")
      .attr("font-size", "9px")
      .attr("font-family", "Inter, sans-serif");

    // Axis labels
    svg
      .append("text")
      .attr("x", width / 2)
      .attr("y", height - 8)
      .attr("text-anchor", "middle")
      .attr("fill", "#556080")
      .attr("font-size", "11px")
      .text("Est. Ad Spend (EUR)");

    svg
      .append("text")
      .attr("x", -height / 2)
      .attr("y", 14)
      .attr("text-anchor", "middle")
      .attr("transform", "rotate(-90)")
      .attr("fill", "#556080")
      .attr("font-size", "11px")
      .text("Gov Coverage %");
  }, [correlation]);

  function rColor(r: number | null): string {
    if (r == null) return "#556080";
    const abs = Math.abs(r);
    if (abs > 0.7) return "#ef4444";
    if (abs > 0.4) return "#f97316";
    if (abs > 0.2) return "#f59e0b";
    return "#00d4aa";
  }

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">💰</span>
        Ad-Editorial Correlation
      </h2>

      {correlation.outlets.length === 0 ? (
        <div className="section-empty">
          No correlation data available. Run the ERC advertising spider to
          collect spending data.
        </div>
      ) : (
        <>
          <div className="correlation-stats">
            <div className="correlation-r">
              <div className="r-pair">
                <span className="r-label">Spend vs Gov Coverage</span>
                <span
                  className="r-value"
                  style={{ color: rColor(correlation.r_spend_vs_gov_coverage) }}
                >
                  {correlation.r_spend_vs_gov_coverage != null
                    ? `r = ${correlation.r_spend_vs_gov_coverage.toFixed(3)}`
                    : "—"}
                </span>
              </div>
              <div className="r-pair">
                <span className="r-label">Spend vs Articles</span>
                <span
                  className="r-value"
                  style={{ color: rColor(correlation.r_spend_vs_articles) }}
                >
                  {correlation.r_spend_vs_articles != null
                    ? `r = ${correlation.r_spend_vs_articles.toFixed(3)}`
                    : "—"}
                </span>
              </div>
            </div>
            <div className="correlation-totals">
              <span className="r-label">
                Total Est. Spend: €{formatNumber(correlation.total_ad_spend_estimated)}
              </span>
            </div>
          </div>

          <div className="scatter-wrap">
            <svg ref={svgRef} className="scatter-plot" />
          </div>

          <div className="correlation-outlets">
            <h3 className="subsection-title">Outlet Breakdown</h3>
            <div className="correlation-table">
              {correlation.outlets
                .filter((o) => o.estimated_ad_spend_eur > 0 || o.articles_count > 0)
                .sort((a, b) => b.estimated_ad_spend_eur - a.estimated_ad_spend_eur)
                .map((o) => (
                  <div key={o.outlet_id} className="correlation-row">
                    <div className="correlation-row-name">
                      <span className="outlet-name">{o.outlet_name}</span>
                      <span className="outlet-owner">{o.owner_group}</span>
                    </div>
                    <div className="correlation-row-metrics">
                      <span className="metric">
                        €{formatNumber(o.estimated_ad_spend_eur)}
                      </span>
                      <span className="metric-sep">·</span>
                      <span className="metric">{o.articles_count} articles</span>
                      <span className="metric-sep">·</span>
                      <span className="metric">
                        {(o.gov_coverage_pct * 100).toFixed(1)}% gov
                      </span>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
