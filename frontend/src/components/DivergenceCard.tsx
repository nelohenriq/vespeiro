import type { StatsPayload } from "../types";
import { pct } from "../api";

interface DivergenceCardProps {
  stats: StatsPayload;
}

export default function DivergenceCard({ stats }: DivergenceCardProps) {
  const { divergence } = stats;
  const outlets = Object.entries(divergence.per_outlet);

  function divergenceColor(avg: number): string {
    if (avg < 0.2) return "#00d4aa";
    if (avg < 0.4) return "#f59e0b";
    if (avg < 0.6) return "#f97316";
    return "#ef4444";
  }

  function divergenceLabel(avg: number): string {
    if (avg < 0.2) return "Low";
    if (avg < 0.4) return "Moderate";
    if (avg < 0.6) return "High";
    return "Critical";
  }

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">🔄</span>
        Narrative Divergence
      </h2>

      {divergence.global_avg != null && (
        <div className="divergence-global">
          <div className="global-value-wrap">
            <div
              className="global-badge"
              style={{
                background: divergenceColor(divergence.global_avg),
                color: "#0a0e27",
              }}
            >
              {pct(divergence.global_avg, 0)}
            </div>
            <div>
              <div className="global-label">Global Average</div>
              <div className="global-sub">{divergenceLabel(divergence.global_avg)}</div>
            </div>
          </div>
        </div>
      )}

      {outlets.length > 0 && (
        <div className="outlet-divergence-list">
          <h3 className="subsection-title">Per Outlet</h3>
          {outlets
            .sort(([, a], [, b]) => b.avg - a.avg)
            .map(([id, outlet]) => {
              const color = divergenceColor(outlet.avg);
              return (
                <div key={id} className="outlet-row">
                  <div className="outlet-info">
                    <span className="outlet-name">{id}</span>
                    <span className="outlet-stories">{outlet.stories} stories</span>
                  </div>
                  <div className="outlet-score-wrap">
                    <div className="outlet-score-bar-bg">
                      <div
                        className="outlet-score-bar-fill"
                        style={{ width: `${outlet.avg * 100}%`, background: color }}
                      />
                    </div>
                    <span className="outlet-score" style={{ color }}>
                      {pct(outlet.avg, 0)}
                    </span>
                  </div>
                  <div className="outlet-sub-scores">
                    <span title="Omission">O: {pct(outlet.avg_omission)}</span>
                    <span title="Sentiment shift">S: {pct(outlet.avg_sentiment_shift)}</span>
                    <span title="Quote fidelity">Q: {pct(outlet.avg_quote_fidelity)}</span>
                    <span title="Headline divergence">H: {pct(outlet.avg_headline_divergence)}</span>
                  </div>
                </div>
              );
            })}
        </div>
      )}

      {divergence.top_omitted_facts.length > 0 && (
        <div className="omitted-facts">
          <h3 className="subsection-title">Top Omitted Facts</h3>
          <div className="facts-list">
            {divergence.top_omitted_facts.map((fact, i) => (
              <div key={i} className="fact-item">
                <span className="fact-rank">#{i + 1}</span>
                <span className="fact-text">{fact.text}</span>
                <div className="fact-meta">
                  <span className="fact-count">×{fact.count}</span>
                  {fact.category && <span className="fact-category">{fact.category}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {outlets.length === 0 && divergence.top_omitted_facts.length === 0 && (
        <div className="section-empty">No divergence data available</div>
      )}
    </section>
  );
}
