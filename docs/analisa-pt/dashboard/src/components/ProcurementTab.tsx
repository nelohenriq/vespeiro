import { useEffect, useRef, useMemo } from "react";
import { fmtNum, fmtEur, fmtPct } from "../api";
import type { ProcurementResponse } from "../types";

interface Props {
  data: ProcurementResponse | null;
  loading: boolean;
  error: string | null;
}

function BarChart({ values, color, label }: { values: { label: string; value: number }[]; color: string; label: string }) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || values.length === 0) return;
    const svg = svgRef.current;
    const w = 440, h = 160, pad = 40;
    const maxVal = Math.max(...values.map(v => v.value)) * 1.1 || 1;
    const barW = Math.min(30, (w - pad * 2) / values.length - 4);

    let html = `<text x="${pad}" y="14" fill="#8892b0" font-size="11" font-family="Inter">${label}</text>`;
    values.forEach((v, i) => {
      const x = pad + i * ((w - pad * 2) / values.length) + 2;
      const barH = (v.value / maxVal) * (h - pad * 2);
      const y = h - pad - barH;
      html += `<rect x="${x}" y="${y}" width="${barW}" height="${barH}" fill="${color}" rx="3" opacity="0.7"/>`;
      if (i % Math.ceil(values.length / 10) === 0 || i === values.length - 1) {
        html += `<text x="${x + barW / 2}" y="${h - pad + 14}" fill="#8892b0" font-size="9" font-family="Inter" text-anchor="middle">${v.label.slice(-2)}</text>`;
      }
    });

    svg.innerHTML = html;
  }, [values, color, label]);

  return <svg ref={svgRef} viewBox="0 0 440 160" className="mini-chart" />;
}

export default function ProcurementTab({ data, loading, error }: Props) {
  if (loading && !data) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Loading procurement data... (1.9GB DB, may take a moment)</p></div></div>;
  if (error) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Error: {error}</p></div></div>;
  if (!data) return null;

  const yearValues = useMemo(() => data.by_year.map(r => ({ label: String(r.year), value: r.contracts })), [data.by_year]);
  const stats = data.stats;

  return (
    <div className="tab-content fade-in">
      {/* Summary cards */}
      <div className="hero-metrics">
        <div className="hero-grid">
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Total Contracts</span></div>
            <div className="hero-value" style={{ color: "var(--orange)" }}>{fmtNum(stats.total)}</div>
            <div className="hero-sub">{fmtYear(stats.year_min)} \u2013 {fmtYear(stats.year_max)}</div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Total Value</span></div>
            <div className="hero-value" style={{ color: "var(--accent)" }}>{fmtEur(stats.total_value)}</div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Direct Awards</span></div>
            <div className="hero-value" style={{ color: data.direct_awards.pct > 50 ? "var(--danger)" : "var(--warning)" }}>
              {fmtPct(data.direct_awards.pct)}
            </div>
            <div className="hero-sub">{fmtNum(data.direct_awards.count)} contracts (ajuste direto)</div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Price Inflation</span></div>
            <div className="hero-value" style={{ color: "var(--warning)" }}>
              {data.price_inflation.with_base_price ? fmtPct((data.price_inflation.count / data.price_inflation.with_base_price) * 100) : "\u2014"}
            </div>
            <div className="hero-sub">{fmtNum(data.price_inflation.count)} of {fmtNum(data.price_inflation.with_base_price)} with base price</div>
          </div>
        </div>
      </div>

      <div className="charts-grid">
        <div className="section-card">
          <h3 className="section-title">Contracts by Year</h3>
          {yearValues.length > 0 && <BarChart values={yearValues} color="var(--orange)" label="Contracts per year" />}
        </div>

        <div className="section-card">
          <h3 className="section-title">By Procedure Type</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Type</th><th>Contracts</th><th>Value</th></tr></thead>
              <tbody>
                {data.by_procedure.map((r, i) => (
                  <tr key={i}>
                    <td>{r.tipoprocedimento}</td>
                    <td className="num">{fmtNum(r.contracts)}</td>
                    <td className="num">{fmtEur(r.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="charts-grid" style={{ marginTop: 16 }}>
        <div className="section-card">
          <h3 className="section-title">Self-Referencing Check</h3>
          <div className="metrics-summary">
            <div className="summary-stat">
              <span className="stat-value">{fmtNum(data.self_referencing.count)}</span>
              <span className="stat-label">Suspected</span>
            </div>
            <div className="summary-stat">
              <span className="stat-value">{fmtNum(data.self_referencing.sample_size)}</span>
              <span className="stat-label">Sampled</span>
            </div>
            <div className="summary-stat">
              <span className="stat-value">{data.self_referencing.sample_size > 0 ? fmtPct((data.self_referencing.count / data.self_referencing.sample_size) * 100) : "\u2014"}</span>
              <span className="stat-label">Rate</span>
            </div>
          </div>
        </div>

        <div className="section-card">
          <h3 className="section-title">Top Buyers by Value</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Entity</th><th>NIF</th><th>Contracts</th><th>Value</th></tr></thead>
              <tbody>
                {data.top_buyers.slice(0, 10).map((r, i) => (
                  <tr key={i}>
                    <td>{(r.name ?? "").slice(0, 45)}</td>
                    <td className="mono">{r.nif}</td>
                    <td className="num">{fmtNum(r.contracts)}</td>
                    <td className="num">{fmtEur(r.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {data.by_municipality.length > 0 && (
        <div className="section-card" style={{ marginTop: 16 }}>
          <h3 className="section-title">By Municipality (Top 20)</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Municipality</th><th>Contracts</th><th>Value</th></tr></thead>
              <tbody>
                {data.by_municipality.map((r, i) => (
                  <tr key={i}>
                    <td>{r.municipality}</td>
                    <td className="num">{fmtNum(r.contracts)}</td>
                    <td className="num">{fmtEur(r.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
