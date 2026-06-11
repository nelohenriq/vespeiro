import { fmtNum, fmtEur, fmtPct, fmtYear } from "../api";
import type { OverviewResponse } from "../types";

interface Props {
  data: OverviewResponse;
  loading: boolean;
}

export default function OverviewTab({ data, loading }: Props) {
  const j = data.justice;
  const p = data.ine;
  const pr = data.procurement;

  const cards: { icon: string; value: string; label: string; sub: string; color: string }[] = [];

  if (j) {
    cards.push({
      icon: "\u2696",
      value: fmtNum(j.corruption_latest),
      label: `Corruption Cases (${fmtYear(j.corruption_latest_year)})`,
      sub: j.ml_latest ? `Money Laundering: ${fmtNum(j.ml_latest)}` : "",
      color: "var(--danger)",
    });
    cards.push({
      icon: "\u23F1",
      value: fmtNum(j.court_pending),
      label: `Court Backlog (${fmtYear(j.court_pending_year)})`,
      sub: "",
      color: "var(--warning)",
    });
    cards.push({
      icon: "\u25C9",
      value: fmtNum(j.prison_population),
      label: `Prison Population (${fmtYear(j.prison_year)})`,
      sub: "",
      color: "var(--purple)",
    });
  }

  if (p) {
    cards.push({
      icon: "\u2660",
      value: fmtNum(p.foreign_residents),
      label: `Foreign Residents (${fmtYear(p.foreign_year)})`,
      sub: p.crime_rate ? `Crime Rate: ${p.crime_rate.toFixed(1)}` : "",
      color: "var(--info)",
    });
    cards.push({
      icon: "\u2696",
      value: fmtNum(p.pensionistas),
      label: `Pensioners (${fmtYear(p.pensionistas_year)})`,
      sub: p.natural_growth != null ? `Natural Growth: ${p.natural_growth}` : "",
      color: "var(--accent)",
    });
  }

  if (pr && !("error" in pr)) {
    cards.push({
      icon: "\u269C",
      value: fmtNum(pr.total_contracts),
      label: pr.year_min && pr.year_max ? `Public Contracts (${pr.year_min}\u2013${pr.year_max})` : "Public Contracts",
      sub: pr.total_value ? `Total: ${fmtEur(pr.total_value)}` : "",
      color: "var(--orange)",
    });
  }

  return (
    <div className="hero-metrics">
      <div className="hero-grid">
        {cards.map((card, i) => (
          <div key={i} className="hero-card">
            <div className="hero-card-header">
              <span className="hero-icon">{card.icon}</span>
              <span className="hero-label">{card.label}</span>
            </div>
            <div className="hero-value" style={{ color: card.color }}>
              {loading ? "\u2014" : card.value}
            </div>
            {card.sub && <div className="hero-sub">{card.sub}</div>}
            <div className="hero-accent-bar" style={{ background: card.color, opacity: 0.3 }} />
          </div>
        ))}
      </div>
    </div>
  );
}
