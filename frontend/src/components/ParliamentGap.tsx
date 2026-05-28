import type { ParliamentGapMetrics } from "../types";
import { pct, formatNumber } from "../api";

interface ParliamentGapProps {
  gap: ParliamentGapMetrics;
}

export default function ParliamentGap({ gap }: ParliamentGapProps) {
  function gapColor(score: number): string {
    if (score < 0.3) return "#00d4aa";
    if (score < 0.6) return "#f59e0b";
    if (score < 0.8) return "#f97316";
    return "#ef4444";
  }

  function gapLabel(score: number): string {
    if (score < 0.3) return "Low Gap";
    if (score < 0.6) return "Moderate";
    if (score < 0.8) return "High Gap";
    return "Critical Gap";
  }

  const barMax = Math.max(
    ...gap.topics.map((t) => Math.max(t.parliament_mentions, t.media_mentions)),
    1
  );

  return (
    <section className="section-card">
      <h2 className="section-title">
        <span className="section-icon">🏛️</span>
        Parliament-Media Gap
      </h2>

      {gap.total_parliament_docs === 0 ? (
        <div className="section-empty">
          No parliament debate data available. Run the parliament spider to
          collect transcripts.
        </div>
      ) : (
        <>
          <div className="gap-global">
            <div className="global-value-wrap">
              <div
                className="global-badge"
                style={{
                  background: gapColor(gap.overall_gap_score),
                  color: "#0a0e27",
                }}
              >
                {pct(gap.overall_gap_score, 0)}
              </div>
              <div>
                <div className="global-label">Overall Gap Score</div>
                <div className="global-sub">{gapLabel(gap.overall_gap_score)}</div>
              </div>
            </div>
          </div>

          <div className="gap-summary">
            <div className="summary-stat">
              <span className="stat-value">{formatNumber(gap.total_parliament_docs)}</span>
              <span className="stat-label">Parliament Docs</span>
            </div>
            <div className="summary-stat">
              <span className="stat-value">{formatNumber(gap.total_media_articles)}</span>
              <span className="stat-label">Media Articles</span>
            </div>
          </div>

          {gap.topics.length > 0 && (
            <div className="gap-topics">
              <h3 className="subsection-title">Topic Coverage Comparison</h3>
              <div className="gap-topic-list">
                {gap.topics.slice(0, 15).map((t, i) => {
                  const parlWidth = (t.parliament_mentions / barMax) * 100;
                  const mediaWidth = (t.media_mentions / barMax) * 100;
                  const color = gapColor(t.gap_score);
                  return (
                    <div key={i} className="gap-topic-row">
                      <div className="gap-topic-header">
                        <span className="gap-topic-name" title={t.topic}>
                          {t.topic}
                        </span>
                        <span className="gap-topic-score" style={{ color }}>
                          {pct(t.gap_score, 0)}
                        </span>
                      </div>
                      <div className="gap-bars">
                        <div className="gap-bar-group">
                          <span className="gap-bar-label">Parl</span>
                          <div className="gap-bar-bg">
                            <div
                              className="gap-bar-fill parl"
                              style={{ width: `${parlWidth}%` }}
                            />
                          </div>
                          <span className="gap-bar-count">{t.parliament_mentions}</span>
                        </div>
                        <div className="gap-bar-group">
                          <span className="gap-bar-label">Media</span>
                          <div className="gap-bar-bg">
                            <div
                              className="gap-bar-fill media"
                              style={{
                                width: `${mediaWidth}%`,
                                background: color,
                              }}
                            />
                          </div>
                          <span className="gap-bar-count">{t.media_mentions}</span>
                        </div>
                      </div>
                      {t.top_media_outlets.length > 0 && (
                        <div className="gap-topic-outlets">
                          {t.top_media_outlets.map((o) => (
                            <span key={o} className="outlet-tag">
                              {o}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {gap.most_discussed_only_parliament.length > 0 && (
            <div className="gap-only-parliament">
              <h3 className="subsection-title">Discussed Only in Parliament</h3>
              <div className="topics-wrap">
                {gap.most_discussed_only_parliament.map((topic, i) => (
                  <div key={i} className="topic-chip" style={{ borderColor: "#ef4444" }}>
                    <span className="topic-name">{topic}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
