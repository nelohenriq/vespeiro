import { useState } from "react";
import { useStats } from "./api";
import Header from "./components/Header";
import HeroMetrics from "./components/HeroMetrics";
import SourceMetricsCard from "./components/SourceMetrics";
import TimelineCharts from "./components/TimelineCharts";
import DivergenceCard from "./components/DivergenceCard";
import DependencyCard from "./components/DependencyCard";
import SilenceCard from "./components/SilenceCard";
import SystemHealth from "./components/SystemHealth";
import InfluenceMap from "./components/InfluenceMap";

type Tab = "overview" | "sources" | "narrative" | "influence" | "system";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "📊" },
  { id: "sources", label: "Sources", icon: "📡" },
  { id: "narrative", label: "Narrative", icon: "🔄" },
  { id: "influence", label: "Influence", icon: "🕸️" },
  { id: "system", label: "System", icon: "⚙️" },
];

export default function App() {
  const { stats, loading, error } = useStats();
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  if (loading) {
    return (
      <div className="app-loading">
        <div className="loading-content">
          <div className="loading-spinner" />
          <h2>Loading Vespeiro Dashboard</h2>
          <p>Fetching latest metrics…</p>
        </div>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="app-error">
        <div className="error-content">
          <span className="error-icon">⚠️</span>
          <h2>Dashboard Unavailable</h2>
          <p>{error || "No stats data available"}</p>
          <p className="error-hint">
            Run <code>python run_stats.py</code> from the backend directory to generate stats.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <Header stats={stats} />
      <HeroMetrics stats={stats} />

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

      <main className="dashboard-main">
        {activeTab === "overview" && (
          <div className="tab-content fade-in">
            <TimelineCharts timelines={stats.timelines} />
            <div className="quick-grid">
              <DivergenceCard stats={stats} />
              <DependencyCard stats={stats} />
              <SilenceCard stats={stats} />
              <SystemHealth stats={stats} />
            </div>
          </div>
        )}

        {activeTab === "sources" && (
          <div className="tab-content fade-in">
            <SourceMetricsCard stats={stats} />
          </div>
        )}

        {activeTab === "narrative" && (
          <div className="tab-content fade-in">
            <div className="narrative-grid">
              <DivergenceCard stats={stats} />
              <DependencyCard stats={stats} />
              <SilenceCard stats={stats} />
            </div>
          </div>
        )}

        {activeTab === "influence" && (
          <div className="tab-content fade-in">
            <InfluenceMap stats={stats} />
          </div>
        )}

        {activeTab === "system" && (
          <div className="tab-content fade-in">
            <SystemHealth stats={stats} />
          </div>
        )}
      </main>
    </div>
  );
}
