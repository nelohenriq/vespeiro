import type { StatsPayload } from "../types";
import { formatDate, formatNumber, pct } from "../api";

interface Props {
  stats: StatsPayload;
}

export default function TransparencyMethodology({ stats }: Props) {
  return (
    <div className="transparency-page">
      {/* Hero */}
      <section className="transparency-hero">
        <h1>📖 Transparency &amp; Methodology</h1>
        <p className="transparency-subtitle">
          How Vespeiro works — and why you can trust the data.
        </p>
      </section>

      {/* Quick Stats */}
      <section className="transparency-stats">
        <div className="transparency-stat-card">
          <span className="transparency-stat-value">
            {formatNumber(stats.sources.articles_total)}
          </span>
          <span className="transparency-stat-label">Articles collected</span>
        </div>
        <div className="transparency-stat-card">
          <span className="transparency-stat-value">
            {stats.sources.active}/{stats.sources.total}
          </span>
          <span className="transparency-stat-label">Active sources</span>
        </div>
        <div className="transparency-stat-card">
          <span className="transparency-stat-value">
            {formatNumber(Object.keys(stats.divergence.per_outlet).length)}
          </span>
          <span className="transparency-stat-label">Outlets analyzed</span>
        </div>
        <div className="transparency-stat-card">
          <span className="transparency-stat-value">
            {pct(stats.lusa_dependency.global_pct ?? 0)}
          </span>
          <span className="transparency-stat-label">Lusa dependency</span>
        </div>
      </section>

      {/* Philosophy */}
      <section className="transparency-section">
        <h2>🎯 Our Philosophy</h2>
        <div className="transparency-grid">
          <div className="transparency-card">
            <h3>We don't claim truth</h3>
            <p>
              Vespeiro does not fact-check or decide what is "true." We
              measure <strong>divergence</strong> — the gap between what
              different sources report about the same event.
            </p>
          </div>
          <div className="transparency-card">
            <h3>We don't rely on any single source</h3>
            <p>
              Every finding is triangulated across 20+ sources in 5+
              languages. We compare, not judge.
            </p>
          </div>
          <div className="transparency-card">
            <h3>We don't hide methodology</h3>
            <p>
              All code is open source. All algorithms are documented. All data
              is available. Anyone can verify, critique, and replicate our
              findings.
            </p>
          </div>
          <div className="transparency-card">
            <h3>We measure patterns, not intentions</h3>
            <p>
              We quantify what is measurable — coverage volume, sentiment,
              source attribution, publication timing. We don't speculate about
              why.
            </p>
          </div>
        </div>
      </section>

      {/* Methodology */}
      <section className="transparency-section">
        <h2>🔬 Methodology</h2>

        <div className="methodology-item">
          <h3>1. Data Collection</h3>
          <p>
            Every 15–60 minutes, GitHub Actions workflows fetch articles from
            RSS feeds and public websites. All scrapers respect{' '}
            <code>robots.txt</code> and use rate limiting. We collect metadata
            (title, URL, date, summary) and extracted text. Embeddings are
            generated locally using{' '}
            <code>multilingual-e5-large</code> for cross-lingual semantic
            comparison.
          </p>
        </div>

        <div className="methodology-item">
          <h3>2. Story Matching</h3>
          <p>
            Articles are grouped into "story clusters" using cosine similarity
            on their embeddings, followed by DBSCAN clustering. Because
            embeddings are multilingual, the same event covered in Portuguese
            by Lusa and in English by Reuters will cluster together.
          </p>
          <div className="threshold-table">
            <h4>Similarity Thresholds</h4>
            <table>
              <thead>
                <tr>
                  <th>Threshold</th>
                  <th>Label</th>
                  <th>Meaning</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>&gt; 0.85</td>
                  <td>Exact match</td>
                  <td>Near-identical content (republished)</td>
                </tr>
                <tr>
                  <td>0.70 – 0.85</td>
                  <td>Paraphrase</td>
                  <td>Same story, different wording</td>
                </tr>
                <tr>
                  <td>0.55 – 0.70</td>
                  <td>Partial</td>
                  <td>Referenced or quoted</td>
                </tr>
                <tr>
                  <td>&lt; 0.55</td>
                  <td>Unrelated</td>
                  <td>Different topics</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="methodology-note">
            ⚠️ These thresholds were calibrated against a test set of ~100
            manually verified article pairs. They are periodically reviewed
            and adjusted based on community feedback.
          </p>
        </div>

        <div className="methodology-item">
          <h3>3. Lusa Dependency Analysis</h3>
          <p>
            For each non-Lusa Portuguese article published within ±3 days of a
            Lusa article, we compute the cosine similarity between their
            embeddings. The <strong>Lusa Dependency Score</strong> per outlet
            is the percentage of that outlet's articles that match a Lusa
            article above the paraphrase threshold (0.70).
          </p>
          <p>
            We also detect <strong>Topic Monopoly</strong>: topics where &gt;80%
            of all Portuguese coverage originates from a single Lusa article
            — indicating a gatekeeping bottleneck.
          </p>
        </div>

        <div className="methodology-item">
          <h3>4. Silence Detection</h3>
          <p>
            For each story cluster, we compute:
          </p>
          <ul>
            <li>
              <strong>International Coverage Score:</strong> percentage of
              international sources covering the story
            </li>
            <li>
              <strong>Portuguese Coverage Score:</strong> percentage of
              Portuguese sources covering it
            </li>
          </ul>
          <p>
            A <strong>"Black Hole" (silence)</strong> is flagged when
            international coverage exceeds 50% but Portuguese coverage is 0%.
            Stories are ranked by importance (derived from source prominence
            and volume).
          </p>
        </div>

        <div className="methodology-item">
          <h3>5. Narrative Divergence</h3>
          <p>
            For matched article pairs (Lusa → outlet, or international →
            Portuguese), we compute multi-dimensional divergence:
          </p>
          <ul>
            <li>
              <strong>Headline divergence:</strong> cosine similarity of title
              embeddings
            </li>
            <li>
              <strong>Quote fidelity:</strong> how quotes are preserved or
              altered
            </li>
            <li>
              <strong>Sentiment shift:</strong> sentiment score difference
              between source and outlet versions
            </li>
          </ul>
          <p>
            The composite <strong>Divergence Score</strong> (0–1) reflects how
            much an outlet's coverage differs from the source. Higher scores
            may indicate editorial reframing.
          </p>
        </div>

        <div className="methodology-item">
          <h3>6. Personnel Network</h3>
          <p>
            Appointments to media and communication roles are extracted from
            Diário da República (DRE) PDFs using regex patterns. The{' '}
            <strong>Personnel Graph</strong> connects individuals across their
            career transitions, highlighting "revolving door" patterns between
            government, regulatory bodies, and state-owned media.
          </p>
        </div>

        <div className="methodology-item">
          <h3>7. Advertising-Editorial Correlation</h3>
          <p>
            Using ERC institutional advertising reports, we compute the
            Pearson correlation coefficient between state advertising spend
            per outlet and that outlet's sentiment toward the government. A
            significant positive correlation (&gt;0.5) may indicate financial
            influence on editorial stance.
          </p>
        </div>
      </section>

      {/* Known Limitations */}
      <section className="transparency-section">
        <h2>⚠️ Known Limitations</h2>
        <div className="limitations-grid">
          <div className="limitation-card">
            <h3>RSS-only collection</h3>
            <p>
              We primarily collect from RSS feeds, which may miss articles
              behind paywalls or not syndicated. Paywalled content is captured
              as headline + summary only.
            </p>
          </div>
          <div className="limitation-card">
            <h3>Threshold sensitivity</h3>
            <p>
              Story matching thresholds (0.55–0.85) were calibrated once.
              Changes in source writing style or new topics may affect
              accuracy. Regular recalibration is planned.
            </p>
          </div>
          <div className="limitation-card">
            <h3>Language coverage</h3>
            <p>
              International sources are primarily in English, Spanish, and
              French. Key media in German, Chinese, Arabic, and Russian are not
              yet monitored — creating a Western-centric bias.
            </p>
          </div>
          <div className="limitation-card">
            <h3>Sentiment model bias</h3>
            <p>
              <code>pysentimiento</code> is trained on general-domain text.
              News articles with formal, neutral language may produce
              near-zero sentiment scores, reducing the signal for asymmetry
              detection.
            </p>
          </div>
          <div className="limitation-card">
            <h3>DRE extraction</h3>
            <p>
              Personnel appointments are extracted via regex from PDF text.
              OCR errors, inconsistent formatting, and non-standard naming
              may cause false negatives.
            </p>
          </div>
          <div className="limitation-card">
            <h3>No real-time data</h3>
            <p>
              Data is collected on a 15–60 minute schedule and analyzed daily.
              Breaking news events may not appear for up to 1 hour.
            </p>
          </div>
        </div>
      </section>

      {/* Data Sources */}
      <section className="transparency-section">
        <h2>📡 Data Sources</h2>
        <p>
          Vespeiro currently monitors {stats.sources.total} sources across
          multiple categories:
        </p>
        <div className="sources-table-wrapper">
          <table className="sources-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Sources</th>
                <th>Languages</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Agency</td>
                <td>Lusa</td>
                <td>PT</td>
              </tr>
              <tr>
                <td>Portuguese Media</td>
                <td>
                  RTP, Público, Expresso, Observador, Correio da Manhã, JN,
                  DN, SIC Notícias, TVI, Renascença, ECO, Notícias ao Minuto,
                  SAPO 24, Jornal de Negócios
                </td>
                <td>PT</td>
              </tr>
              <tr>
                <td>International</td>
                <td>
                  Reuters, Associated Press, BBC, The Guardian, El País, Le
                  Monde, DW, France24, NYT, Al Jazeera
                </td>
                <td>EN, ES, FR, DE, AR</td>
              </tr>
              <tr>
                <td>Government</td>
                <td>portugal.gov.pt, presidencia.pt</td>
                <td>PT</td>
              </tr>
              <tr>
                <td>Parliament</td>
                <td>debates.parlamento.pt</td>
                <td>PT</td>
              </tr>
              <tr>
                <td>Official Gazette</td>
                <td>Diário da República (dre.pt)</td>
                <td>PT</td>
              </tr>
              <tr>
                <td>Regulator</td>
                <td>ERC (reports)</td>
                <td>PT</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Open Source & API */}
      <section className="transparency-section">
        <h2>🔓 Open Source &amp; Public API</h2>
        <div className="transparency-grid">
          <div className="transparency-card cta-card">
            <h3>📂 Source Code</h3>
            <p>
              All code is available on GitHub under an open-source license.
              Contributions, bug reports, and feature requests are welcome.
            </p>
            <a
              href="https://github.com/nelohenriq/vespeiro"
              target="_blank"
              rel="noopener noreferrer"
              className="cta-link"
            >
              github.com/nelohenriq/vespeiro →
            </a>
          </div>
          <div className="transparency-card cta-card">
            <h3>🔌 Public API</h3>
            <p>
              Raw data is available via a free REST API (Supabase PostgREST).
              No API key required. Full documentation in the repository.
            </p>
            <a
              href="https://github.com/nelohenriq/vespeiro/blob/main/docs/api.md"
              target="_blank"
              rel="noopener noreferrer"
              className="cta-link"
            >
              API Documentation →
            </a>
          </div>
          <div className="transparency-card cta-card">
            <h3>📊 Raw Data</h3>
            <p>
              Pre-computed metrics are available as a static JSON file,
              regenerated daily. Use it for your own analysis or research.
            </p>
            <a
              href={`${import.meta.env.BASE_URL}stats.json`}
              target="_blank"
              rel="noopener noreferrer"
              className="cta-link"
            >
              stats.json →
            </a>
          </div>
          <div className="transparency-card cta-card">
            <h3>🐛 Report Issues</h3>
            <p>
              Found a bug? Data doesn't look right? Open an issue on GitHub.
              We track all corrections publicly.
            </p>
            <a
              href="https://github.com/nelohenriq/vespeiro/issues"
              target="_blank"
              rel="noopener noreferrer"
              className="cta-link"
            >
              Issue Tracker →
            </a>
          </div>
        </div>
      </section>

      {/* License */}
      <section className="transparency-section">
        <h2>📜 License &amp; Attribution</h2>
        <p>
          <strong>Vespeiro code:</strong> Open source (MIT License).
        </p>
        <p>
          <strong>Derived metrics:</strong> CC-BY 4.0 — free to use with
          attribution.
        </p>
        <p>
          <strong>Article metadata:</strong> Derived from publicly available
          RSS feeds and public government websites. Attribution to original
          publishers is included in all data.
        </p>
        <p>
          <strong>DRE appointments:</strong> Public government data from
          Diário da República Eletrónico — freely redistributable.
        </p>
        <p className="methodology-note">
          💰 Vespeiro operates at <strong>$0/month</strong>. No paid APIs, no
          servers. Everything runs on GitHub Actions (free tier for public
          repos), Supabase (free tier), and GitHub Pages (free hosting).
        </p>
      </section>

      {/* Footer */}
      <footer className="transparency-footer">
        <p>
          Data generated: {formatDate(stats.generated_at)} • Version: 1.0
        </p>
        <p>
          <strong>🐝 Vespeiro — Media Narrative Intelligence Platform</strong>
        </p>
      </footer>
    </div>
  );
}
