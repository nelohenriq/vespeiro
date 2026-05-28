import type { StatsPayload } from "../types";
import { formatDate } from "../api";

interface SystemHealthProps {
  stats: StatsPayload;
}

export default function SystemHealth({ stats }: SystemHealthProps) {
  const { system } = stats;

  const healthColor =
    system.uptime_pct >= 90
      ? "#00d4aa"
      : system.uptime_pct >= 50
        ? "#f59e0b"
        : "#ef4444";

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">⚙️</span>
        System Health
      </h2>

      <div className="health-grid">
        <div className="health-stat">
          <div className="health-ring" style={{ borderColor: healthColor }}>
            <div className="health-ring-value" style={{ color: healthColor }}>
              {system.uptime_pct.toFixed(0)}%
            </div>
          </div>
          <span className="health-label">Uptime</span>
        </div>

        <div className="health-details">
          <div className="health-row">
            <span className="health-row-label">Healthy sources</span>
            <span className="health-row-value" style={{ color: "#00d4aa" }}>
              {system.sources_healthy}
            </span>
          </div>
          <div className="health-row">
            <span className="health-row-label">Failing sources</span>
            <span className="health-row-value" style={{ color: system.sources_failing > 0 ? "#ef4444" : "#8892b0" }}>
              {system.sources_failing}
            </span>
          </div>
          {system.last_scrape && (
            <div className="health-row">
              <span className="health-row-label">Last scrape</span>
              <span className="health-row-value date">{formatDate(system.last_scrape)}</span>
            </div>
          )}
          {system.last_error && (
            <div className="health-row error">
              <span className="health-row-label">Last error</span>
              <span className="health-row-value error-text">{system.last_error}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
