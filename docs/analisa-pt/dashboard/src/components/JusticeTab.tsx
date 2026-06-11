import { useMemo } from "react";
import SparkLine from "./SparkLine";
import { fmtNum } from "../api";
import type { JusticeResponse } from "../types";

interface Props {
  data: JusticeResponse | null;
  loading: boolean;
  error: string | null;
}



export default function JusticeTab({ data, loading, error }: Props) {
  if (loading && !data) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Loading justice data...</p></div></div>;
  if (error) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Error: {error}</p></div></div>;
  if (!data) return null;

  const corruptionValues = useMemo(() => data.corruption_trend.map(r => ({ x: r.year, y: r.corruption ?? 0 })), [data.corruption_trend]);
  const mlValues = useMemo(() => data.corruption_trend.map(r => ({ x: r.year, y: r.money_laundering ?? 0 })).filter(v => v.y > 0), [data.corruption_trend]);
  const pendingValues = useMemo(() => data.court_movements.map(r => ({ x: r.year, y: r.pending })), [data.court_movements]);
  const prisonValues = useMemo(() => data.prison_population.map(r => ({ x: r.year, y: r.count })), [data.prison_population]);

  return (
    <div className="tab-content fade-in">
      <div className="charts-grid">
        <div className="section-card">
          <h3 className="section-title">Corruption & Money Laundering</h3>
          {corruptionValues.length > 0 && (
            <SparkLine values={corruptionValues} color="#ef4444" label="Corruption cases (PJ)" height={120} />
          )}
          {mlValues.length > 0 && (
            <SparkLine values={mlValues} color="#f59e0b" label="Money laundering cases (PJ)" height={120} />
          )}
          <div className="data-table">
            <table>
              <thead>
                <tr><th>Year</th><th>Corruption</th><th>Money Laundering</th><th>Ratio</th></tr>
              </thead>
              <tbody>
                {data.corruption_trend.map(r => (
                  <tr key={r.year}>
                    <td>{r.year}</td>
                    <td className="num">{fmtNum(r.corruption)}</td>
                    <td className="num">{fmtNum(r.money_laundering)}</td>
                    <td className="num">{r.corruption && r.money_laundering ? (r.money_laundering / r.corruption).toFixed(1) + "x" : "\u2014"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="section-card">
          <h3 className="section-title">Court Case Flow</h3>
          {pendingValues.length > 0 && (
            <SparkLine values={pendingValues} color="#a78bfa" label="Pending cases" height={120} />
          )}
          <div className="data-table">
            <table>
              <thead>
                <tr><th>Year</th><th>Entered</th><th>Finalized</th><th>Pending</th><th>Resolution</th></tr>
              </thead>
              <tbody>
                {data.court_movements.map(r => (
                  <tr key={r.year}>
                    <td>{r.year}</td>
                    <td className="num">{fmtNum(r.entered)}</td>
                    <td className="num">{fmtNum(r.finalized)}</td>
                    <td className="num">{fmtNum(r.pending)}</td>
                    <td className="num">{(r.resolution_rate * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="charts-grid" style={{ marginTop: 16 }}>
        <div className="section-card">
          <h3 className="section-title">Prison Population</h3>
          {prisonValues.length > 0 && (
            <SparkLine values={prisonValues} color="#ec4899" label="Incarcerated population" height={120} />
          )}
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Population</th></tr></thead>
              <tbody>
                {data.prison_population.map(r => (
                  <tr key={r.year}>
                    <td>{r.year}</td>
                    <td className="num">{fmtNum(r.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="section-card">
          <h3 className="section-title">Data Sources</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Dataset</th><th>Category</th><th>Records</th><th>Years</th></tr></thead>
              <tbody>
                {data.datasets.map((d, i) => (
                  <tr key={i}>
                    <td>{d.dataset}</td>
                    <td>{d.category}</td>
                    <td className="num">{fmtNum(d.records)}</td>
                    <td>{d.year_min}\u2013{d.year_max}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
