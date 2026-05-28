import type { StatsPayload } from "../types";
import { formatDate } from "../api";

interface HeaderProps {
  stats: StatsPayload | null;
}

export default function Header({ stats }: HeaderProps) {
  return (
    <header className="dashboard-header">
      <div className="header-brand">
        <div className="header-logo">
          <span className="logo-icon">🏛️</span>
          <div>
            <h1 className="header-title">Vespeiro</h1>
            <span className="header-subtitle">Media Narrative Intelligence</span>
          </div>
        </div>
      </div>
      <div className="header-meta">
        {stats && (
          <div className="header-stats-bar">
            <span className="meta-chip">
              <span className="chip-dot" /> v{stats.version}
            </span>
            <span className="meta-chip">
              <span className="chip-icon">🕐</span>
              {formatDate(stats.generated_at)}
            </span>
          </div>
        )}
        <button className="refresh-btn" onClick={() => window.location.reload()} title="Refresh data">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M1 8a7 7 0 0 1 13.2-3.2M15 8a7 7 0 0 1-13.2 3.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M14.5 1.5v3.5H11M1.5 14.5V11H5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </div>
    </header>
  );
}
