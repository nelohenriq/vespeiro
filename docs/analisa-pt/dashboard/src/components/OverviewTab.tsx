import { useEffect, useMemo, useRef } from "react";
import { fmtNum, fmtEur, fmtPct, fmtYear } from "../api";
import type { OverviewResponse, ProcurementResponse } from "../types";
import SparkLine from "./SparkLine";

interface Props {
  data: OverviewResponse;
  loading: boolean;
  procurement?: ProcurementResponse | null;
}

// ── Contract-type donut (top 3 procedures + Other) ──────────────────────────

function DonutChart({ rows, total, size = 160 }: {
  rows: { label: string; value: number; color: string }[];
  total: number;
  size?: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || total <= 0) return;
    const svg = svgRef.current;
    const cx = size / 2;
    const cy = size / 2;
    const r = size / 2 - 6;
    const innerR = r * 0.6;
    let startAngle = -Math.PI / 2; // start at 12 o'clock

    const segments = rows
      .map(row => ({ ...row, frac: row.value / total }))
      .filter(s => s.frac > 0);

    let html = "";
    for (const seg of segments) {
      const angle = seg.frac * 2 * Math.PI;
      const endAngle = startAngle + angle;
      const largeArc = angle > Math.PI ? 1 : 0;

      // Outer arc endpoints
      const x1 = cx + r * Math.cos(startAngle);
      const y1 = cy + r * Math.sin(startAngle);
      const x2 = cx + r * Math.cos(endAngle);
      const y2 = cy + r * Math.sin(endAngle);

      // Inner arc endpoints (reverse direction to close the donut wedge)
      const x3 = cx + innerR * Math.cos(endAngle);
      const y3 = cy + innerR * Math.sin(endAngle);
      const x4 = cx + innerR * Math.cos(startAngle);
      const y4 = cy + innerR * Math.sin(startAngle);

      // M outerStart -> A outerArc -> L innerEnd -> A innerArc (reverse) -> Z
      html += `<path d="M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} L ${x3.toFixed(1)} ${y3.toFixed(1)} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4.toFixed(1)} ${y4.toFixed(1)} Z" fill="${seg.color}" opacity="0.85"><title>${seg.label}: ${(seg.frac * 100).toFixed(1)}% (${fmtNum(seg.value)})</title></path>`;

      startAngle = endAngle;
    }

    svg.innerHTML = html;
  }, [rows, total, size]);

  return <svg ref={svgRef} viewBox={`0 0 ${size} ${size}`} className="donut-chart" />;
}

// ── Main component ──────────────────────────────────────────────────────────

export default function OverviewTab({ data, loading, procurement }: Props) {
  const j = data.justice;
  const p = data.ine;
  const pr = data.procurement;

  // ── Derived headline numbers from the procurement cache ──
  // Top 3 procedures + "Other" for the donut. The by_procedure cache
  // returns 10 rows ordered by contract count; we use the top 3 and
  // group the rest as "Other" to keep the donut readable.
  const proc = procurement;
  const procRows = proc?.by_procedure ?? [];
  const procTotal = procRows.reduce((s, r) => s + (r.contracts || 0), 0);
  const directAwardPct = procTotal > 0
    ? (procRows[0]?.contracts ?? 0) / procTotal * 100
    : 0;

  // YoY sparkline: 12 years, contracts per year
  const yearValues = (proc?.by_year ?? []).map(r => ({ x: r.year, y: r.contracts }));
  const yoyFirst = yearValues[0]?.y ?? 0;
  const yoyLast = yearValues[yearValues.length - 1]?.y ?? 0;
  const yoyGrowth = yoyFirst > 0 ? yoyLast / yoyFirst : 0;

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

  // Donut palette: danger for the dominant direct-award share, then
  // warning/info/accent for the secondary procedures, muted for "Other".
  // Memoized on the STABLE upstream values (procRows + procTotal) so
  // DonutChart's useEffect doesn't re-run on every parent re-render.
  // Deriving procTop3 + procOtherCount INSIDE the memo (rather than
  // passing them as deps) keeps the dep array stable: the parent
  // otherwise re-creates those arrays on every render and the memo
  // would be a no-op.
  const donutColors = useMemo(
    () => ["var(--danger)", "var(--warning)", "var(--info)", "#3a4256"] as const,
    []
  );
  const donutRows = useMemo(() => {
    const top3 = procRows.slice(0, 3);
    const otherCount = Math.max(
      0,
      procTotal - top3.reduce((s, r) => s + (r.contracts || 0), 0)
    );
    return [
      ...top3.map((r, i) => ({
        label: r.tipoprocedimento,
        value: r.contracts,
        color: donutColors[i] ?? "#3a4256",
      })),
      ...(otherCount > 0
        ? [{ label: "Other procedures", value: otherCount, color: donutColors[3] ?? "#3a4256" }]
        : []),
    ];
  }, [procRows, procTotal, donutColors]);

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

      {/* Headline finding tiles: direct-award share + YoY growth */}
      {proc && procRows.length > 0 && (
        <div className="charts-grid" style={{ marginTop: 16 }}>
          <div className="section-card">
            <h3 className="section-title">
              Direct-Award Share
              <span style={{ marginLeft: 12, fontSize: 14, color: directAwardPct > 50 ? "var(--danger)" : "var(--warning)" }}>
                {directAwardPct.toFixed(1)}% of contracts
              </span>
            </h3>
            <p className="section-empty" style={{ fontSize: 12, margin: "4px 0 12px", lineHeight: 1.4 }}>
              Share of public contracts awarded via procedures that bypass or limit competition.
              OECD benchmarks put well-functioning systems at 15&ndash;25% direct awards &mdash;
              Portugal sits at <strong>{directAwardPct.toFixed(0)}%</strong> for the dominant
              procedure type alone. Top 3 procedures shown; the rest are grouped as
              &quot;Other procedures&quot;.
            </p>
            <div className="donut-layout">
              <DonutChart rows={donutRows} total={procTotal} />
              <div className="donut-legend">
                {donutRows.map((row) => (
                  <div key={row.label} className="donut-legend-item">
                    <span className="donut-legend-swatch" style={{ background: row.color }} />
                    <span className="donut-legend-label">{(row.label ?? "").slice(0, 40)}</span>
                    <span className="donut-legend-value">
                      {fmtPct((row.value / procTotal) * 100)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="section-card">
            <h3 className="section-title">
              Contracts per Year
              <span style={{ marginLeft: 12, fontSize: 14, color: yoyGrowth > 2 ? "var(--warning)" : "var(--accent)" }}>
                {yoyGrowth.toFixed(1)}&times; growth since {yearValues[0]?.x}
              </span>
            </h3>
            <p className="section-empty" style={{ fontSize: 12, margin: "4px 0 12px", lineHeight: 1.4 }}>
              Total public contracts per year. From {fmtNum(yoyFirst)} in
              {" "}{yearValues[0]?.x} to {fmtNum(yoyLast)} in {yearValues[yearValues.length - 1]?.x}
              &mdash; a {yoyGrowth.toFixed(1)}&times; expansion in procurement activity
              over {yearValues.length} years.
            </p>
            {yearValues.length >= 2 && (
              <div
                role="img"
                aria-label={`Contracts per year, ${yearValues[0]?.x} to ${yearValues[yearValues.length - 1]?.x}: ${fmtNum(yoyFirst)} to ${fmtNum(yoyLast)}, ${yoyGrowth.toFixed(1)} times growth`}
              >
                <SparkLine
                  values={yearValues}
                  color="var(--orange)"
                  label={`Contracts per year, ${yearValues[0]?.x}\u2013${yearValues[yearValues.length - 1]?.x}`}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
