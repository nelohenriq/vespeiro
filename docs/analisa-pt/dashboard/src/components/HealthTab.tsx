import type { HealthResponse } from "../types";

interface Props {
  data: HealthResponse | null;
  loading: boolean;
  error: string | null;
}

export default function HealthTab({ data, loading, error }: Props) {
  if (loading && !data) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Loading health data...</p></div></div>;
  if (error) return <div className="tab-content fade-in"><div className="section-card"><p className="section-empty">Error: {error}</p></div></div>;
  if (!data) return null;

  const dbEntries = Object.entries(data.databases);
  const online = dbEntries.filter(([, d]) => d.exists && d.connectable !== false).length;
  const total = dbEntries.length;

  return (
    <div className="tab-content fade-in">
      <div className="hero-metrics">
        <div className="hero-grid">
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Databases Online</span></div>
            <div className="hero-value" style={{ color: online === total ? "var(--accent)" : "var(--warning)" }}>
              {online}/{total}
            </div>
          </div>
          <div className="hero-card">
            <div className="hero-card-header"><span className="hero-label">Last Check</span></div>
            <div className="hero-value" style={{ color: "var(--text)", fontSize: "1.2rem" }}>
              {new Date(data.timestamp).toLocaleString("pt-PT")}
            </div>
          </div>
        </div>
      </div>

      <div className="section-card" style={{ marginTop: 16 }}>
        <h3 className="section-title">Database Status</h3>
        <div className="data-table">
          <table>
            <thead>
              <tr>
                <th>Database</th>
                <th>Status</th>
                <th>Size</th>
                <th>Tables</th>
                <th>Last Modified</th>
              </tr>
            </thead>
            <tbody>
              {dbEntries.map(([name, db]) => (
                <tr key={name} className={!db.exists ? "row-error" : ""}>
                  <td className="mono">{name}</td>
                  <td>
                    <span className={`status-dot ${db.exists ? "green" : "red"}`} />
                    {db.exists
                      ? db.connectable === false ? "locked" : "online"
                      : "missing"}
                  </td>
                  <td className="num">{db.exists ? `${db.size_mb} MB` : "\u2014"}</td>
                  <td className="num">{db.tables ? db.tables.length : "\u2014"}</td>
                  <td className="text-muted">{db.mtime ? new Date(db.mtime).toLocaleDateString("pt-PT") : "\u2014"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section-card" style={{ marginTop: 16 }}>
        <h3 className="section-title">Table Inventory</h3>
        <div className="data-table">
          <table>
            <thead><tr><th>Database</th><th>Table</th></tr></thead>
            <tbody>
              {dbEntries.map(([name, db]) =>
                db.tables?.map((t) => (
                  <tr key={`${name}-${t}`}>
                    <td className="mono">{name}</td>
                    <td>{t}</td>
                  </tr>
                ))
              )}
              {dbEntries.every(([, db]) => !db.tables || db.tables.length === 0) && (
                <tr><td colSpan={2} className="text-muted">No tables found. Check database connectivity.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
