import { useState } from "react";
import { useOverview, useJustice, useProcurement, useSocial, useCrossRef, useHealth, useHealthPoll } from "./api";
import OverviewTab from "./components/OverviewTab";
import JusticeTab from "./components/JusticeTab";
import ProcurementTab from "./components/ProcurementTab";
import SocialTab from "./components/SocialTab";
import CrossRefTab from "./components/CrossRefTab";
import HealthTab from "./components/HealthTab";

type Tab = "overview" | "justice" | "procurement" | "social" | "crossref" | "health";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "\u25B3" },
  { id: "justice", label: "Justice", icon: "\u2696" },
  { id: "procurement", label: "Procurement", icon: "\u269C" },
  { id: "social", label: "Social", icon: "\u2660" },
  { id: "crossref", label: "Cross-Reference", icon: "\u21C4" },
  { id: "health", label: "Health", icon: "\u2699" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  // The 5s health poll drives connectivity. Domain endpoints are skipped
  // whenever the API is known to be offline — this prevents 6 concurrent
  // ECONNREFUSED errors every 5s when the backend is dead.
  const healthPoll = useHealthPoll();
  const apiOnline = !!healthPoll.data && !healthPoll.error;

  const overview = useOverview(!apiOnline);
  const justice = useJustice(!apiOnline);
  const procurement = useProcurement(!apiOnline);
  const social = useSocial(!apiOnline);
  const crossref = useCrossRef(!apiOnline);
  const health = useHealth(!apiOnline);

  // Live connectivity status — driven by the 5s /api/health probe
  const isOnline = !!healthPoll.data && !healthPoll.error;
  const isProbing = healthPoll.loading && !healthPoll.data;

  const anyLoading = overview.loading && justice.loading && procurement.loading;

  // Aggregate errors from any tab — if the API server is down, surface it.
  // Include healthPoll.error (5s) so the error screen stays in sync with the banner.
  const aggregateError =
    healthPoll.error ||
    overview.error || justice.error || procurement.error ||
    social.error || crossref.error || health.error;

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="header-brand">
          <div className="header-logo">
            <span className="logo-icon">AP</span>
            <div>
              <h1 className="header-title">Analisa.pt</h1>
              <span className="header-subtitle">Intelligence Dashboard</span>
            </div>
          </div>
        </div>
        <div className="header-meta">
          {/* Live API connectivity — polls /api/health every 5s */}
          <span
            className={`api-status ${isOnline ? "online" : isProbing ? "probing" : "offline"}`}
            title={
              isOnline
                ? `API server online \u2014 last checked ${healthPoll.lastUpdated ?? ""}`
                : isProbing
                ? "Checking API server..."
                : `API server offline: ${healthPoll.error ?? "unreachable"}`
            }
          >
            <span className="api-dot" />
            <span className="api-label">
              {isOnline ? "API Online" : isProbing ? "Checking..." : "API Offline"}
            </span>
          </span>
          {overview.lastUpdated && (
            <span className="meta-chip">
              <span className="chip-dot" />
              Updated {overview.lastUpdated}
            </span>
          )}
          {overview.data && (
            <span className="meta-chip">
              <span className="chip-icon">DB</span>
              {Object.values(overview.data.databases).filter(d => d.exists).length} databases
            </span>
          )}
          <button className="refresh-btn" onClick={overview.refetch} title="Refresh all data">
            &#x21BB;
          </button>
        </div>
      </header>

      {/* Loading state */}
      {anyLoading && !overview.data && (
        <div className="app-loading">
          <div className="loading-content">
            <div className="loading-spinner" />
            <h2>Loading Analisa.pt Dashboard</h2>
            <p>Querying databases...</p>
          </div>
        </div>
      )}

      {/* Error state — shows when any endpoint is unreachable and no data has loaded yet */}
      {aggregateError && !overview.data && (
        <div className="app-error">
          <div className="error-content">
            <span className="error-icon">!</span>
            <h2>API Server Not Running</h2>
            <p>{aggregateError}</p>
            <p className="error-hint" style={{ marginTop: 16 }}>
              Start the API server in a separate terminal:
            </p>
            <p className="error-hint" style={{ marginTop: 8 }}>
              <code>cd docs/analisa-pt/tools &amp;&amp; python api_server.py --port 8080</code>
            </p>
            <p className="error-hint" style={{ marginTop: 8 }}>
              Or use the batch file: <code>docs\analisa-pt\dashboard\start.bat</code>
            </p>
          </div>
        </div>
      )}

      {/* Hero metrics + headline finding tiles (donut + sparkline) */}
      {overview.data && (
        <OverviewTab
          data={overview.data}
          loading={overview.loading}
          procurement={procurement.data}
        />
      )}

      {/* Tab navigation */}
      <nav className="tab-nav">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="tab-icon">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      <main className="dashboard-main">
        {activeTab === "overview" && overview.data && (
          <div className="tab-content fade-in">
            <div className="quick-grid">
              <div className="section-card">
                <h3 className="section-title">Database Status</h3>
                <div className="db-grid">
                  {Object.entries(overview.data.databases).map(([name, db]) => (
                    <div key={name} className={`db-card ${db.exists ? "online" : "offline"}`}>
                      <div className="db-name">{name}</div>
                      <div className="db-size">{db.exists ? `${db.size_mb} MB` : "missing"}</div>
                      <div className={`db-dot ${db.exists ? "green" : "red"}`} />
                    </div>
                  ))}
                </div>
              </div>
              <div className="section-card">
                <h3 className="section-title">Risk Signals</h3>
                <div className="signals-list">
                  {crossref.data?.risk_signals?.map((sig, i) => (
                    <div key={i} className={`signal-item severity-${sig.severity}`}>
                      <span className="signal-severity">{sig.severity.toUpperCase()}</span>
                      <span className="signal-detail">{sig.detail}</span>
                    </div>
                  )) || <p className="section-empty">Loading cross-reference data...</p>}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === "justice" && (
          <JusticeTab data={justice.data} loading={justice.loading} error={justice.error} />
        )}
        {activeTab === "procurement" && (
          <ProcurementTab data={procurement.data} loading={procurement.loading} error={procurement.error} />
        )}
        {activeTab === "social" && (
          <SocialTab data={social.data} loading={social.loading} error={social.error} />
        )}
        {activeTab === "crossref" && (
          <CrossRefTab data={crossref.data} loading={crossref.loading} error={crossref.error} />
        )}
        {activeTab === "health" && (
          <HealthTab data={health.data} loading={health.loading} error={health.error} />
        )}
      </main>
    </div>
  );
}
