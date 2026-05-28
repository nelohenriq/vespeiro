import type { StatsPayload } from "../types";

interface SilenceCardProps {
  stats: StatsPayload;
}

export default function SilenceCard({ stats }: SilenceCardProps) {
  const { silence } = stats;

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">🔇</span>
        Silence Detection
      </h2>

      <div className="metrics-summary">
        <div className="summary-stat">
          <span className="stat-value" style={{ color: silence.today > 0 ? "#ef4444" : "#00d4aa" }}>
            {silence.today}
          </span>
          <span className="stat-label">Silenced Today</span>
        </div>
        <div className="summary-stat">
          <span className="stat-value">{silence.avg_7d.toFixed(1)}</span>
          <span className="stat-label">7-Day Avg</span>
        </div>
      </div>

      {silence.top_silenced.length > 0 && (
        <div className="silenced-list">
          <h3 className="subsection-title">Top Silenced Stories</h3>
          {silence.top_silenced.map((story, i) => (
            <div key={i} className="silenced-item">
              <span className="silenced-rank">#{i + 1}</span>
              <div className="silenced-content">
                <span className="silenced-title">{story.title}</span>
                <div className="silenced-meta">
                  <span className="silenced-gap" style={{ color: story.gap_pct > 0.5 ? "#ef4444" : "#f59e0b" }}>
                    {(story.gap_pct * 100).toFixed(0)}% coverage gap
                  </span>
                  <span className="silenced-sources">
                    {story.international_sources} intl · {story.pt_coverage} PT
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {silence.top_silenced.length === 0 && (
        <div className="section-empty">No silence data available</div>
      )}
    </section>
  );
}
