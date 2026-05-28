import type { StatsPayload } from "../types";
import { formatNumber, pct } from "../api";

interface HeroMetricsProps {
  stats: StatsPayload;
}

export default function HeroMetrics({ stats }: HeroMetricsProps) {
  const { sources, divergence, lusa_dependency, silence } = stats;

  const items = [
    {
      label: "Articles Total",
      value: formatNumber(sources.articles_total),
      sub: `${formatNumber(sources.articles_today)} today`,
      accent: "#00d4aa",
      icon: "📄",
    },
    {
      label: "Active Sources",
      value: `${sources.active}`,
      sub: `of ${sources.total} total`,
      accent: "#60a5fa",
      icon: "📡",
    },
    {
      label: "Narrative Divergence",
      value: pct(divergence.global_avg, 0),
      sub: divergence.per_outlet
        ? `${Object.keys(divergence.per_outlet).length} outlets`
        : "No data",
      accent: "#f59e0b",
      icon: "🔄",
    },
    {
      label: "Lusa Dependency",
      value: pct(lusa_dependency.global_pct, 0),
      sub: lusa_dependency.per_outlet
        ? `${Object.keys(lusa_dependency.per_outlet).length} outlets`
        : "No data",
      accent: "#f97316",
      icon: "🔗",
    },
    {
      label: "Silence Today",
      value: `${silence.today}`,
      sub: `avg ${silence.avg_7d.toFixed(1)}/day`,
      accent: "#ef4444",
      icon: "🔇",
    },
    {
      label: "System Health",
      value: pct(stats.system.uptime_pct, 0),
      sub: `${stats.system.sources_healthy} healthy · ${stats.system.sources_failing} failing`,
      accent:
        stats.system.uptime_pct >= 90
          ? "#00d4aa"
          : stats.system.uptime_pct >= 50
            ? "#f59e0b"
            : "#ef4444",
      icon: "⚙️",
    },
  ];

  return (
    <section className="hero-metrics">
      <div className="hero-grid">
        {items.map((item) => (
          <div key={item.label} className="hero-card" style={{ "--accent": item.accent } as React.CSSProperties}>
            <div className="hero-card-header">
              <span className="hero-icon">{item.icon}</span>
              <span className="hero-label">{item.label}</span>
            </div>
            <div className="hero-value">{item.value}</div>
            <div className="hero-sub">{item.sub}</div>
            <div className="hero-accent-bar" style={{ background: item.accent }} />
          </div>
        ))}
      </div>
    </section>
  );
}
