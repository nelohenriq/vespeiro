import type { StatsPayload } from "../types";
import { formatNumber } from "../api";

interface SourceMetricsProps {
  stats: StatsPayload;
}

const CATEGORY_LABELS: Record<string, string> = {
  news_agency: "News Agency",
  mainstream: "Mainstream Media",
  international: "International",
  parliament: "Parliament",
  official_gazette: "Official Gazette",
  regulatory: "Regulatory",
  government: "Government",
};

const CATEGORY_COLORS: Record<string, string> = {
  news_agency: "#60a5fa",
  mainstream: "#00d4aa",
  international: "#a78bfa",
  parliament: "#f59e0b",
  official_gazette: "#f97316",
  regulatory: "#ef4444",
  government: "#ec4899",
};

export default function SourceMetricsCard({ stats }: SourceMetricsProps) {
  const { sources } = stats;
  const categories = Object.entries(sources.per_category);

  const totalPerCat = categories.reduce((sum, [, c]) => sum + c.articles, 0);

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">📡</span>
        Source Metrics
      </h2>

      <div className="metrics-summary">
        <div className="summary-stat">
          <span className="stat-value">{sources.active}</span>
          <span className="stat-label">Active Sources</span>
        </div>
        <div className="summary-stat">
          <span className="stat-value">{sources.total}</span>
          <span className="stat-label">Total Sources</span>
        </div>
        <div className="summary-stat">
          <span className="stat-value">{formatNumber(sources.articles_total)}</span>
          <span className="stat-label">Total Articles</span>
        </div>
        <div className="summary-stat">
          <span className="stat-value">{formatNumber(sources.articles_today)}</span>
          <span className="stat-label">Today</span>
        </div>
      </div>

      {categories.length > 0 && (
        <div className="category-breakdown">
          <h3 className="subsection-title">Per Category</h3>
          <div className="category-grid">
            {categories.map(([catId, cat]) => {
              const pctVal = totalPerCat > 0 ? cat.articles / totalPerCat : 0;
              return (
                <div key={catId} className="category-card">
                  <div className="category-header">
                    <span
                      className="category-dot"
                      style={{ background: CATEGORY_COLORS[catId] || "#8892b0" }}
                    />
                    <span className="category-name">
                      {CATEGORY_LABELS[catId] || catId}
                    </span>
                  </div>
                  <div className="category-stats">
                    <span className="category-articles">{formatNumber(cat.articles)}</span>
                    <span className="category-sources">{cat.sources} sources</span>
                  </div>
                  <div className="category-bar-bg">
                    <div
                      className="category-bar-fill"
                      style={{
                        width: `${pctVal * 100}%`,
                        background: CATEGORY_COLORS[catId] || "#8892b0",
                      }}
                    />
                  </div>
                  <div className="category-today">
                    {cat.articles_today > 0 && (
                      <span className="today-badge">+{cat.articles_today} today</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {Object.keys(sources.articles_per_source).length > 0 && (
        <div className="top-sources">
          <h3 className="subsection-title">Top Sources</h3>
          <div className="sources-list">
            {Object.entries(sources.articles_per_source)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 10)
              .map(([src, count], i) => {
                const maxCount = Math.max(...Object.values(sources.articles_per_source), 1);
                return (
                  <div key={src} className="source-row">
                    <span className="source-rank">#{i + 1}</span>
                    <span className="source-name">{src}</span>
                    <div className="source-bar-bg">
                      <div
                        className="source-bar-fill"
                        style={{ width: `${(count / maxCount) * 100}%` }}
                      />
                    </div>
                    <span className="source-count">{formatNumber(count)}</span>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </section>
  );
}
