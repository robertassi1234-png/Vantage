import { useCallback, useEffect, useRef, useState } from "react";
import type { PricePoint } from "../types";

interface Props {
  points: PricePoint[];
  label: string;
  height?: number;
}

const PAD = { top: 16, right: 64, bottom: 28, left: 8 };
const Y_TICKS = 4;

/** Round a raw axis step up to a clean 1 / 2 / 5 × 10^n value. Exported for tests. */
export function niceStep(rawStep: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

/** Clean gridline values spanning [min, max]. Exported for tests. */
export function axisTicks(min: number, max: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const step = niceStep((max - min) / Y_TICKS);
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.001; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

const money = (v: number) =>
  v >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(2);

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

export function PriceChart({ points, label, height = 300 }: Props) {
  const [width, setWidth] = useState(720);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  // Render at true pixel size so strokes and text keep their intended weight
  // instead of being scaled by a viewBox. This is a callback ref rather than a
  // layout effect because the component returns early before the wrapper exists
  // while history is still loading -- an on-mount effect would attach to null
  // and the chart would stay stuck at its default width.
  const attachWrap = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;

    setWidth(node.clientWidth || 720);
    const observer = new ResizeObserver(([entry]) => {
      const next = entry.contentRect.width;
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  useEffect(() => () => observerRef.current?.disconnect(), []);

  useEffect(() => setHoverIndex(null), [points]);

  if (points.length < 2) {
    return (
      <div className="chart-empty" style={{ height }}>
        Not enough price history to draw a chart.
      </div>
    );
  }

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  // A little headroom so the line never touches the frame.
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;
  const ySpan = yMax - yMin;

  const plotW = Math.max(width - PAD.left - PAD.right, 10);
  const plotH = height - PAD.top - PAD.bottom;

  const xAt = (i: number) => PAD.left + (i / (points.length - 1)) * plotW;
  const yAt = (v: number) => PAD.top + (1 - (v - yMin) / ySpan) * plotH;

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(2)} ${yAt(p.close).toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L${xAt(points.length - 1).toFixed(2)} ${(PAD.top + plotH).toFixed(
    2,
  )} L${xAt(0).toFixed(2)} ${(PAD.top + plotH).toFixed(2)} Z`;

  const first = points[0].close;
  const last = points[points.length - 1].close;
  const rising = last >= first;
  const tone = rising ? "up" : "down";

  const ticks = axisTicks(min, max);
  const active = hoverIndex != null ? points[hoverIndex] : null;

  function handleMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left - PAD.left;
    const ratio = Math.min(Math.max(x / plotW, 0), 1);
    setHoverIndex(Math.round(ratio * (points.length - 1)));
  }

  // Roughly six evenly spaced date labels, always anchored by the first and
  // last point. Drop the penultimate tick when it would crowd the final label,
  // which otherwise renders as two overlapping dates at the right edge.
  const lastIndex = points.length - 1;
  const labelStep = Math.max(1, Math.floor(lastIndex / 5));
  const labelIndices: number[] = [];
  for (let i = 0; i <= lastIndex; i += labelStep) labelIndices.push(i);
  if (labelIndices[labelIndices.length - 1] !== lastIndex) {
    if (lastIndex - labelIndices[labelIndices.length - 1] < labelStep * 0.6) labelIndices.pop();
    labelIndices.push(lastIndex);
  }

  return (
    <div className="chart-wrap" ref={attachWrap}>
      <svg
        className={`price-chart tone-${tone}`}
        width={width}
        height={height}
        role="img"
        aria-label={`${label} closing price, ${longDate(points[0].date)} to ${longDate(
          points[points.length - 1].date,
        )}`}
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              className="chart-grid"
              x1={PAD.left}
              x2={PAD.left + plotW}
              y1={yAt(t)}
              y2={yAt(t)}
            />
            <text className="chart-axis-label" x={PAD.left + plotW + 8} y={yAt(t) + 4}>
              {money(t)}
            </text>
          </g>
        ))}

        {labelIndices.map((i) => (
          <text
            key={points[i].date}
            className="chart-axis-label chart-x-label"
            x={xAt(i)}
            y={height - 8}
            // Edge labels hug their edge so neither is clipped by the frame.
            textAnchor={i === 0 ? "start" : i === lastIndex ? "end" : "middle"}
          >
            {shortDate(points[i].date)}
          </text>
        ))}

        <path className="chart-area" d={areaPath} />
        <path
          className="chart-line"
          d={linePath}
          fill="none"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* End marker, ringed in the surface color so it stays legible. */}
        <circle
          className="chart-end-ring"
          cx={xAt(points.length - 1)}
          cy={yAt(last)}
          r={6}
          strokeWidth={2}
        />
        <circle className="chart-end-dot" cx={xAt(points.length - 1)} cy={yAt(last)} r={4} />

        {active && hoverIndex != null && (
          <g className="chart-hover">
            <line
              className="chart-crosshair"
              x1={xAt(hoverIndex)}
              x2={xAt(hoverIndex)}
              y1={PAD.top}
              y2={PAD.top + plotH}
            />
            <circle
              className="chart-end-ring"
              cx={xAt(hoverIndex)}
              cy={yAt(active.close)}
              r={6}
              strokeWidth={2}
            />
            <circle className="chart-end-dot" cx={xAt(hoverIndex)} cy={yAt(active.close)} r={4} />
          </g>
        )}
      </svg>

      {active && hoverIndex != null && (
        <div
          className="chart-tooltip"
          style={{
            left: Math.min(Math.max(xAt(hoverIndex), 60), width - 60),
            top: PAD.top,
          }}
        >
          <span className="tooltip-value">${money(active.close)}</span>
          <span className="tooltip-date">{longDate(active.date)}</span>
        </div>
      )}
    </div>
  );
}
