import type { StatsPayload } from "../types";
import PersonnelGraph from "./PersonnelGraph";
import ParliamentGap from "./ParliamentGap";
import AdCorrelation from "./AdCorrelation";
import { pct } from "../api";

interface InfluenceMapProps {
  stats: StatsPayload;
}

export default function InfluenceMap({ stats }: InfluenceMapProps) {
  const { influence, personnel, parliament_gap, ad_correlation } = stats;

  function captureColor(score: number): string {
    if (score > 0.7) return "#ef4444";
    if (score > 0.4) return "#f97316";
    if (score > 0.2) return "#f59e0b";
    return "#00d4aa";
  }

  function captureLabel(score: number): string {
    if (score > 0.7) return "Critical Capture";
    if (score > 0.4) return "Significant Capture";
    if (score > 0.2) return "Moderate Capture";
    return "Low Capture Risk";
  }

  return (
    <div className="influence-map">
      {/* Capture Score Hero */}
      <section className="capture-hero">
        <div className="capture-hero-content">
          <div className="capture-score-ring" style={{ borderColor: captureColor(influence.capture_score) }}>
            <span
              className="capture-score-value"
              style={{ color: captureColor(influence.capture_score) }}
            >
              {pct(influence.capture_score, 0)}
            </span>
          </div>
          <div className="capture-hero-text">
            <h2 className="capture-title">Media Capture Score</h2>
            <p className="capture-subtitle">
              {captureLabel(influence.capture_score)}
            </p>
            <p className="capture-summary">{influence.summary}</p>
          </div>
        </div>

        <div className="capture-sub-scores">
          <div className="capture-sub-score">
            <div className="sub-score-bar-bg">
              <div
                className="sub-score-bar-fill"
                style={{
                  width: `${influence.personnel_density * 100}%`,
                  background: "#00d4aa",
                }}
              />
            </div>
            <div className="sub-score-label">
              <span>🕸️ Personnel Density</span>
              <span>{pct(influence.personnel_density)}</span>
            </div>
          </div>
          <div className="capture-sub-score">
            <div className="sub-score-bar-bg">
              <div
                className="sub-score-bar-fill"
                style={{
                  width: `${influence.parliament_gap * 100}%`,
                  background: "#f59e0b",
                }}
              />
            </div>
            <div className="sub-score-label">
              <span>🏛️ Parliament Gap</span>
              <span>{pct(influence.parliament_gap)}</span>
            </div>
          </div>
          <div className="capture-sub-score">
            <div className="sub-score-bar-bg">
              <div
                className="sub-score-bar-fill"
                style={{
                  width: `${influence.ad_correlation_strength * 100}%`,
                  background: "#a78bfa",
                }}
              />
            </div>
            <div className="sub-score-label">
              <span>💰 Ad Correlation</span>
              <span>{pct(influence.ad_correlation_strength)}</span>
            </div>
          </div>
        </div>
      </section>

      {/* Detail sections */}
      <div className="influence-grid">
        <PersonnelGraph personnel={personnel} />
        <ParliamentGap gap={parliament_gap} />
        <AdCorrelation correlation={ad_correlation} />
      </div>
    </div>
  );
}
