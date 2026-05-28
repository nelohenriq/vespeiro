import type { StatsPayload } from "../types";

interface DependencyCardProps {
  stats: StatsPayload;
}

/** Format a percentage value that the backend stores as 0-100 (not 0-1). */
function fmtPct(pctVal: number, decimals = 1): string {
  return pctVal.toFixed(decimals) + "%";
}

/** Backend stores percentages on 0-100 scale; depColor expects 0-1. */
function depColor(pctVal: number): string {
  const fraction = pctVal / 100;
  if (fraction < 0.3) return "#00d4aa";
  if (fraction < 0.5) return "#f59e0b";
  if (fraction < 0.7) return "#f97316";
  return "#ef4444";
}

export default function DependencyCard({ stats }: DependencyCardProps) {
  const { lusa_dependency } = stats;
  const outlets = Object.entries(lusa_dependency.per_outlet);

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">🔗</span>
        Lusa Dependency
      </h2>

      {lusa_dependency.global_pct != null && (
        <div className="dep-global">
          <div className="dep-global-value" style={{ color: depColor(lusa_dependency.global_pct) }}>
            {fmtPct(lusa_dependency.global_pct)}
          </div>
          <div className="dep-global-label">of Portuguese media content derives from Lusa</div>
        </div>
      )}

      {outlets.length > 0 && (
        <div className="dep-outlet-list">
          <h3 className="subsection-title">Per Outlet</h3>
          {outlets
            .sort(([, a], [, b]) => b.pct - a.pct)
            .map(([id, outlet]) => {
              const color = depColor(outlet.pct);
              return (
                <div key={id} className="dep-row">
                  <div className="dep-row-info">
                    <span className="dep-outlet-name">{id}</span>
                    <span className="dep-outlet-stories">
                      {outlet.lusa_derived}/{outlet.stories} stories
                    </span>
                  </div>
                  <div className="dep-bar-bg">
                    <div
                      className="dep-bar-fill"
                      style={{ width: `${outlet.pct}%`, background: color }}
                    />
                  </div>
                  <span className="dep-pct" style={{ color }}>
                    {fmtPct(outlet.pct)}
                  </span>
                </div>
              );
            })}
        </div>
      )}

      {Object.keys(lusa_dependency.per_topic).length > 0 && (
        <div className="dep-topics">
          <h3 className="subsection-title">Per Topic</h3>
          <div className="topics-wrap">
            {Object.entries(lusa_dependency.per_topic)
              .sort(([, a], [, b]) => b - a)
              .map(([topic, pctVal]) => (
                <div key={topic} className="topic-chip" style={{ borderColor: depColor(pctVal) }}>
                  <span className="topic-name">{topic}</span>
                  <span className="topic-pct" style={{ color: depColor(pctVal) }}>
                    {fmtPct(pctVal)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {outlets.length === 0 && lusa_dependency.global_pct == null && (
        <div className="section-empty">No dependency data available</div>
      )}
    </section>
  );
}
