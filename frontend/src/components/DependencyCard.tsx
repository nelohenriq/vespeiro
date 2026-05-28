import type { StatsPayload } from "../types";
import { pct } from "../api";

interface DependencyCardProps {
  stats: StatsPayload;
}

export default function DependencyCard({ stats }: DependencyCardProps) {
  const { lusa_dependency } = stats;
  const outlets = Object.entries(lusa_dependency.per_outlet);

  function depColor(pctVal: number): string {
    if (pctVal < 0.3) return "#00d4aa";
    if (pctVal < 0.5) return "#f59e0b";
    if (pctVal < 0.7) return "#f97316";
    return "#ef4444";
  }

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">🔗</span>
        Lusa Dependency
      </h2>

      {lusa_dependency.global_pct != null && (
        <div className="dep-global">
          <div className="dep-global-value" style={{ color: depColor(lusa_dependency.global_pct) }}>
            {pct(lusa_dependency.global_pct, 0)}
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
                      style={{ width: `${outlet.pct * 100}%`, background: color }}
                    />
                  </div>
                  <span className="dep-pct" style={{ color }}>
                    {pct(outlet.pct, 0)}
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
                    {pct(pctVal, 0)}
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
