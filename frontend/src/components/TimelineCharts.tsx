import type { Timelines } from "../types";

interface TimelineChartsProps {
  timelines: Timelines;
}

function BarChart({
  data,
  dates,
  label,
  color,
  unit,
}: {
  data: number[];
  dates: string[];
  label: string;
  color: string;
  unit: string;
}) {
  if (!data.length || data.every((v) => v === 0)) {
    return (
      <div className="chart-card">
        <h3 className="chart-title">{label}</h3>
        <div className="chart-empty">No data available</div>
      </div>
    );
  }

  const max = Math.max(...data, 1);
  const barWidth = 36;
  const gap = 12;
  const chartHeight = 160;
  const labelHeight = 20;

  return (
    <div className="chart-card">
      <h3 className="chart-title">{label}</h3>
      <div className="chart-container">
        <svg
          width={data.length * (barWidth + gap) + gap}
          height={chartHeight + labelHeight + 10}
          viewBox={`0 0 ${data.length * (barWidth + gap) + gap} ${chartHeight + labelHeight + 10}`}
        >
          {data.map((value, i) => {
            const barH = (value / max) * (chartHeight - 20);
            const x = gap + i * (barWidth + gap);
            const y = chartHeight - barH - 5;
            return (
              <g key={i}>
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={barH}
                  rx={4}
                  fill={color}
                  opacity={0.85}
                >
                  <title>{`${dates[i]}: ${value}${unit}`}</title>
                </rect>
                <text
                  x={x + barWidth / 2}
                  y={chartHeight + labelHeight - 5}
                  textAnchor="middle"
                  fill="#8892b0"
                  fontSize="10"
                >
                  {dates[i].slice(5)}
                </text>
                {value > 0 && (
                  <text
                    x={x + barWidth / 2}
                    y={y - 6}
                    textAnchor="middle"
                    fill={color}
                    fontSize="11"
                    fontWeight="600"
                  >
                    {value}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function LineChart({
  data,
  dates,
  label,
  color,
}: {
  data: number[];
  dates: string[];
  label: string;
  color: string;
}) {
  if (!data.length || data.every((v) => v === 0)) {
    return (
      <div className="chart-card">
        <h3 className="chart-title">{label}</h3>
        <div className="chart-empty">No data available</div>
      </div>
    );
  }

  const max = Math.max(...data, 0.01);
  const padding = { top: 20, right: 16, bottom: 28, left: 40 };
  const chartW = 400;
  const chartH = 160;
  const innerW = chartW - padding.left - padding.right;
  const innerH = chartH - padding.top - padding.bottom;

  const points = data.map((value, i) => {
    const x = padding.left + (i / Math.max(data.length - 1, 1)) * innerW;
    const y = padding.top + innerH - (value / max) * innerH;
    return { x, y, value, date: dates[i] };
  });

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  const areaD =
    pathD +
    ` L ${points[points.length - 1].x.toFixed(1)} ${padding.top + innerH}` +
    ` L ${points[0].x.toFixed(1)} ${padding.top + innerH} Z`;

  // Y-axis ticks
  const yTicks = [0, 0.25, 0.5, 0.75, 1].filter((t) => t <= max);

  return (
    <div className="chart-card">
      <h3 className="chart-title">{label}</h3>
      <div className="chart-container">
        <svg width={chartW} height={chartH + 10} viewBox={`0 0 ${chartW} ${chartH + 10}`}>
          {/* Grid lines */}
          {yTicks.map((tick) => {
            const y = padding.top + innerH - (tick / max) * innerH;
            return (
              <g key={tick}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={chartW - padding.right}
                  y2={y}
                  stroke="#1e2844"
                  strokeWidth={1}
                />
                <text x={padding.left - 8} y={y + 4} textAnchor="end" fill="#556080" fontSize="10">
                  {(tick * 100).toFixed(0)}%
                </text>
              </g>
            );
          })}

          {/* Area fill */}
          <path d={areaD} fill={color} opacity={0.1} />

          {/* Line */}
          <path d={pathD} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />

          {/* Dots */}
          {points.map((p, i) => (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r={4} fill={color} stroke="#0a0e27" strokeWidth={2}>
                <title>{`${p.date}: ${(p.value * 100).toFixed(1)}%`}</title>
              </circle>
            </g>
          ))}

          {/* X-axis labels */}
          {points.map((p, i) => (
            <text
              key={i}
              x={p.x}
              y={chartH - 5}
              textAnchor="middle"
              fill="#8892b0"
              fontSize="10"
            >
              {p.date.slice(5)}
            </text>
          ))}
        </svg>
      </div>
    </div>
  );
}

export default function TimelineCharts({ timelines }: TimelineChartsProps) {
  return (
    <section className="timeline-section">
      <h2 className="section-title">
        <span className="section-icon">📈</span>
        7-Day Trends
      </h2>
      <div className="charts-grid">
        <BarChart
          data={timelines.articles_daily_7d}
          dates={timelines.dates_7d}
          label="Articles per Day"
          color="#00d4aa"
          unit=" articles"
        />
        <LineChart
          data={timelines.divergence_avg_7d}
          dates={timelines.dates_7d}
          label="Divergence avg"
          color="#f59e0b"
        />
        <LineChart
          data={timelines.lusa_dependency_7d}
          dates={timelines.dates_7d}
          label="Lusa Dependency"
          color="#f97316"
        />
        <BarChart
          data={timelines.silence_daily_7d}
          dates={timelines.dates_7d}
          label="Silenced Stories"
          color="#ef4444"
          unit=" stories"
        />
      </div>
    </section>
  );
}
