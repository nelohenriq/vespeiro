import { useEffect, useRef, memo } from "react";
import { fmtNum } from "../api";

interface SparkLineProps {
  values: { x: number; y: number }[];
  color: string;
  label: string;
  width?: number;
  height?: number;
}

function SparkLineInner({ values, color, label, width = 400, height = 100 }: SparkLineProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || values.length < 2) return;
    const svg = svgRef.current;
    const pad = 30;
    const minY = Math.min(...values.map(v => v.y)) * 0.9;
    const maxY = Math.max(...values.map(v => v.y)) * 1.1;
    const minX = values[0]!.x;
    const maxX = values[values.length - 1]!.x;

    const x = (v: number) => pad + ((v - minX) / (maxX - minX || 1)) * (width - pad * 2);
    const y = (v: number) => height - pad - ((v - minY) / (maxY - minY || 1)) * (height - pad * 2);

    let d = "";
    for (const v of values) {
      const px = x(v.x), py = y(v.y);
      d += d ? ` L${px},${py}` : `M${px},${py}`;
    }

    const last = values[values.length - 1]!;
    svg.innerHTML = `
      <text x="${pad}" y="14" fill="#8892b0" font-size="11" font-family="Inter">${label}</text>
      <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="${x(last.x)}" cy="${y(last.y)}" r="3" fill="${color}"/>
      <text x="${x(last.x) + 6}" y="${y(last.y) + 3}" fill="#e0e6ed" font-size="10" font-family="Inter" font-weight="600">${fmtNum(last.y)}</text>
    `;
  }, [values, color, label, width, height]);

  return <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="mini-chart" />;
}

const SparkLine = memo(SparkLineInner);
export default SparkLine;
