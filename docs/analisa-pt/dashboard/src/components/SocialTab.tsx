import { useMemo } from "react";
import SparkLine from "./SparkLine";
import { fmtNum, fmtPct } from "../api";
import type { SocialResponse } from "../types";

interface Props {
  data: SocialResponse | null;
  loading: boolean;
  error: string | null;
}



export default function SocialTab({ data, loading, error }: Props) {
  if (loading && !data) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Loading social data...</p></div></div>;
  if (error) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Error: {error}</p></div></div>;
  if (!data) return null;

  const immigValues = useMemo(() => data.immigration.map(r => ({ x: r.year, y: r.total })), [data.immigration]);
  const pensionValues = useMemo(() => data.pensionistas.map(r => ({ x: r.year, y: r.total })), [data.pensionistas]);
  const crimeValues = useMemo(() => data.crime_rate.map(r => ({ x: r.year, y: r.rate })), [data.crime_rate]);
  const growthValues = useMemo(() => data.natural_growth.map(r => ({ x: r.year, y: r.total })), [data.natural_growth]);

  // Compute latest stats
  const latestImmig = data.immigration.length > 0 ? data.immigration[data.immigration.length - 1]! : null;
  const prevImmig = data.immigration.length > 1 ? data.immigration[data.immigration.length - 2]! : null;
  const immigGrowth = latestImmig && prevImmig && prevImmig.total > 0
    ? ((latestImmig.total - prevImmig.total) / prevImmig.total * 100)
    : null;

  return (
    <div className="tab-content fade-in">
      {/* Summary cards */}
      <div className="hero-metrics">
        <div className="hero-grid">
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Foreign Residents</span></div>
            <div className="hero-value" style={{ color: "var(--info)" }}>{latestImmig ? fmtNum(latestImmig.total) : "\u2014"}</div>
            <div className="hero-sub">{latestImmig?.year} {immigGrowth != null ? `(${immigGrowth >= 0 ? "+" : ""}${immigGrowth.toFixed(1)}% YoY)` : ""}</div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Pensioners</span></div>
            <div className="hero-value" style={{ color: "var(--accent)" }}>
              {data.pensionistas.length > 0 ? fmtNum(data.pensionistas[data.pensionistas.length - 1]!.total) : "\u2014"}
            </div>
            <div className="hero-sub">{data.pensionistas.length > 0 ? data.pensionistas[data.pensionistas.length - 1]!.year : ""}</div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Crime Rate</span></div>
            <div className="hero-value" style={{ color: "var(--warning)" }}>
              {data.crime_rate.length > 0 ? data.crime_rate[data.crime_rate.length - 1]!.rate.toFixed(1) : "\u2014"}
            </div>
            <div className="hero-sub">per 100K residents ({data.crime_rate.length > 0 ? data.crime_rate[data.crime_rate.length - 1]!.year : ""})</div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Natural Growth</span></div>
            <div className="hero-value" style={{ color: growthValues.length > 0 && growthValues[growthValues.length - 1]!.y < 0 ? "var(--danger)" : "var(--accent)" }}>
              {growthValues.length > 0 ? fmtNum(growthValues[growthValues.length - 1]!.y) : "\u2014"}
            </div>
            <div className="hero-sub">{growthValues.length > 0 ? growthValues[growthValues.length - 1]!.x : ""} (births - deaths)</div>
          </div>
        </div>
      </div>

      <div className="charts-grid">
        <div className="section-card">
          <h3 className="section-title">Immigration Trend</h3>
          {immigValues.length > 0 && <SparkLine values={immigValues} color="var(--info)" label="Foreign residents (total)" />}
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Residents</th><th>YoY</th></tr></thead>
              <tbody>
                {data.immigration.slice(-10).map((r, i, arr) => {
                  const prev = i > 0 ? arr[i - 1] : null;
                  const growth = prev && prev.total > 0 ? ((r.total - prev.total) / prev.total * 100) : null;
                  return (
                    <tr key={r.year}>
                      <td>{r.year}</td>
                      <td className="num">{fmtNum(r.total)}</td>
                      <td className="num" style={{ color: growth != null && growth < 0 ? "var(--danger)" : growth != null && growth > 10 ? "var(--warning)" : undefined }}>
                        {growth != null ? `${growth >= 0 ? "+" : ""}${growth.toFixed(1)}%` : "\u2014"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="section-card">
          <h3 className="section-title">Pensioners Trend</h3>
          {pensionValues.length > 0 && <SparkLine values={pensionValues} color="var(--accent)" label="SS Pensionistas (total)" />}
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Pensioners</th><th>YoY</th></tr></thead>
              <tbody>
                {data.pensionistas.slice(-10).map((r, i, arr) => {
                  const prev = i > 0 ? arr[i - 1] : null;
                  const growth = prev && prev.total > 0 ? ((r.total - prev.total) / prev.total * 100) : null;
                  return (
                    <tr key={r.year}>
                      <td>{r.year}</td>
                      <td className="num">{fmtNum(r.total)}</td>
                      <td className="num">{growth != null ? `${growth >= 0 ? "+" : ""}${growth.toFixed(1)}%` : "\u2014"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="charts-grid" style={{ marginTop: 16 }}>
        <div className="section-card">
          <h3 className="section-title">Crime Rate</h3>
          {crimeValues.length > 0 && <SparkLine values={crimeValues} color="var(--warning)" label="Criminality rate (per 100K)" />}
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Rate</th></tr></thead>
              <tbody>
                {data.crime_rate.map(r => (
                  <tr key={r.year}><td>{r.year}</td><td className="num">{r.rate.toFixed(1)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="section-card">
          <h3 className="section-title">Natural Population Growth</h3>
          {growthValues.length > 0 && <SparkLine values={growthValues} color="var(--danger)" label="Births minus Deaths" />}
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Growth</th></tr></thead>
              <tbody>
                {data.natural_growth.slice(-10).map(r => (
                  <tr key={r.year}>
                    <td>{r.year}</td>
                    <td className="num" style={{ color: r.total < 0 ? "var(--danger)" : undefined }}>{fmtNum(r.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {data.immigration_by_region.length > 0 && (
        <div className="section-card" style={{ marginTop: 16 }}>
          <h3 className="section-title">Immigration by Region (Latest Year)</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Region</th><th>Residents</th><th>Share</th></tr></thead>
              <tbody>
                {data.immigration_by_region.map((r, i) => {
                  const totalImmig = data.immigration_by_region.reduce((s, x) => s + x.value, 0);
                  return (
                    <tr key={i}>
                      <td>{r.region}</td>
                      <td className="num">{fmtNum(r.value)}</td>
                      <td className="num">{fmtPct(totalImmig > 0 ? (r.value / totalImmig) * 100 : 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
