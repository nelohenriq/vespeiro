import { fmtNum, fmtPct } from "../api";
import type { CrossRefResponse } from "../types";

interface Props {
  data: CrossRefResponse | null;
  loading: boolean;
  error: string | null;
}

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    high: "var(--danger)",
    medium: "var(--warning)",
    low: "var(--info)",
    info: "var(--text-muted)",
  };
  return (
    <span
      className="severity-badge"
      style={{ background: colors[severity] ?? "var(--text-muted)", color: "#fff" }}
    >
      {severity.toUpperCase()}
    </span>
  );
}

export default function CrossRefTab({ data, loading, error }: Props) {
  if (loading && !data) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Loading cross-reference data...</p></div></div>;
  if (error) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Error: {error}</p></div></div>;
  if (!data) return null;

  const icCorr = data.immigration_crime_correlation;
  const ps = data.procurement_signals;

  return (
    <div className="tab-content fade-in">
      {/* Risk signals */}
      <div className="section-card">
        <h3 className="section-title">Risk Signals</h3>
        <div className="signals-list">
          {data.risk_signals.length === 0 && <p className="section-empty">No risk signals detected</p>}
          {data.risk_signals.map((sig, i) => (
            <div key={i} className="signal-item">
              <SeverityBadge severity={sig.severity} />
              <span className="signal-signal">{sig.signal.replace(/_/g, " ")}</span>
              <span className="signal-detail">{sig.detail}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="charts-grid" style={{ marginTop: 16 }}>
        {/* Immigration vs Crime correlation */}
        <div className="section-card">
          <h3 className="section-title">Immigration x Crime Correlation</h3>
          {icCorr && "pearson_r" in icCorr ? (
            <div>
              <div className="metrics-summary">
                <div className="summary-stat">
                  <span className="stat-value">{icCorr.pearson_r.toFixed(3)}</span>
                  <span className="stat-label">Pearson r</span>
                </div>
                <div className="summary-stat">
                  <span className="stat-value">{icCorr.r_squared.toFixed(3)}</span>
                  <span className="stat-label">R-squared</span>
                </div>
                <div className="summary-stat">
                  <span className="stat-value">{icCorr.n}</span>
                  <span className="stat-label">Years</span>
                </div>
              </div>
              <div className="insight-box">
                <strong>Interpretation:</strong> {icCorr.interpretation} correlation.
                {"pearson_r" in icCorr && Math.abs(icCorr.pearson_r) < 0.3
                  ? " No meaningful statistical relationship between immigration levels and crime rate."
                  : ""}
                <br />
                <span className="text-muted">
                  Overlap years: {icCorr.overlap_years.join(", ")}
                </span>
              </div>
            </div>
          ) : (
            <p className="section-empty">Insufficient data for correlation analysis</p>
          )}
        </div>

        {/* Procurement signals */}
        <div className="section-card">
          <h3 className="section-title">Procurement Signals</h3>
          <div className="metrics-summary">
            <div className="summary-stat">
              <span className="stat-value" style={{ color: ps.direct_award_pct > 50 ? "var(--danger)" : "var(--warning)" }}>
                {fmtPct(ps.direct_award_pct)}
              </span>
              <span className="stat-label">Direct Awards</span>
            </div>
            <div className="summary-stat">
              <span className="stat-value">{fmtNum(ps.total_contracts)}</span>
              <span className="stat-label">Total Contracts</span>
            </div>
          </div>
          <div className="insight-box">
            {ps.direct_award_pct > 60
              ? "CRITICAL: Over 60% of contracts are direct awards (ajuste direto), bypassing competitive bidding."
              : ps.direct_award_pct > 50
                ? "WARNING: Over 50% of contracts are direct awards. Competitive bidding rates are low."
                : "Direct award rate is within normal range."}
          </div>
        </div>
      </div>

      <div className="charts-grid" style={{ marginTop: 16 }}>
        {/* Corruption vs Money Laundering trend */}
        <div className="section-card">
          <h3 className="section-title">Corruption vs Money Laundering Trend</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Corruption</th><th>Money Laundering</th><th>ML/Corr Ratio</th></tr></thead>
              <tbody>
                {data.corruption_trend.map((ct) => {
                  const ml = data.ml_trend.find(m => m.year === ct.year);
                  const ratio = ct.value && ml?.value ? (ml.value / ct.value) : null;
                  return (
                    <tr key={ct.year}>
                      <td>{ct.year}</td>
                      <td className="num">{fmtNum(ct.value)}</td>
                      <td className="num">{fmtNum(ml?.value ?? null)}</td>
                      <td className="num" style={{ color: ratio != null && ratio > 2 ? "var(--danger)" : undefined }}>
                        {ratio != null ? ratio.toFixed(1) + "x" : "\u2014"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Court backlog trend */}
        <div className="section-card">
          <h3 className="section-title">Court Pending Cases Trend</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Pending</th><th>Change</th></tr></thead>
              <tbody>
                {data.court_pending_trend.map((cp, i) => {
                  const prev = i > 0 ? data.court_pending_trend[i - 1] : null;
                  const change = prev?.value ? ((cp.value - prev.value) / prev.value * 100) : null;
                  return (
                    <tr key={cp.year}>
                      <td>{cp.year}</td>
                      <td className="num">{fmtNum(cp.value)}</td>
                      <td className="num" style={{ color: change != null && change > 0 ? "var(--danger)" : change != null && change < 0 ? "var(--accent)" : undefined }}>
                        {change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(1)}%` : "\u2014"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Immigration vs Crime dual trend */}
      {data.immigration_trend.length > 0 && data.crime_trend.length > 0 && (
        <div className="section-card" style={{ marginTop: 16 }}>
          <h3 className="section-title">Immigration vs Crime Rate (Dual Trend)</h3>
          <div className="data-table">
            <table>
              <thead><tr><th>Year</th><th>Immigration</th><th>Crime Rate</th><th>Immig YoY</th></tr></thead>
              <tbody>
                {data.immigration_trend.map((im, i) => {
                  const cr = data.crime_trend.find(c => c.year === im.year);
                  const prev = i > 0 ? data.immigration_trend[i - 1] : null;
                  const igrowth = prev?.total ? ((im.total - prev.total) / prev.total * 100) : null;
                  return (
                    <tr key={im.year}>
                      <td>{im.year}</td>
                      <td className="num">{fmtNum(im.total)}</td>
                      <td className="num">{cr?.rate?.toFixed(1) ?? "\u2014"}</td>
                      <td className="num">{igrowth != null ? `${igrowth >= 0 ? "+" : ""}${igrowth.toFixed(1)}%` : "\u2014"}</td>
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
