import { useCallback, useEffect, useRef, useState } from "react";
import type { PricePoint } from "../types";

export interface ChartSeries {
  symbol: string;
  points: PricePoint[];
}

interface Props {
  series: ChartSeries[];
  height?: number;
}

const PAD = { top: 16, right: 58, bottom: 28, left: 8 };
const Y_TICKS = 4;

/** Categorical slots 1-5, validated for both surfaces (see dataviz palette). */
export const SERIES_COLORS = 5;

function niceStep(raw: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const n = raw / magnitude;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * magnitude;
}

function axisTicks(min: number, max: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  const step = niceStep((max - min) / Y_TICKS);
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 0.001; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;

const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/**
 * Several stocks on one axis, each indexed to 0% at the start of the range.
 *
 * Plotting raw prices would make this unreadable — a $12 stock and a $500 one
 * share no useful scale, and the usual fix (a second y-axis) invites false
 * conclusions from where two lines happen to cross. Percentage change from a
 * common baseline puts every series on one honest axis.
 */
export function ComparisonChart({ series, height = 320 }: Props) {
  const [width, setWidth] = useState(720);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  const attachWrap = useCallback((node: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;
    setWidth(node.clientWidth || 720);
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width);
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  useEffect(() => () => observerRef.current?.disconnect(), []);
  useEffect(() => setHoverIndex(null), [series]);

  const usable = series.filter((s) => s.points.length >= 2).slice(0, SERIES_COLORS);

  if (usable.length === 0) {
    return (
      <div className="chart-empty" style={{ height }}>
        Add at least one company with price history to compare.
      </div>
    );
  }

  // Series can start on different days (a recent listing, a data gap), so the
  // x-axis is the union of every date present.
  const allDates = [...new Set(usable.flatMap((s) => s.points.map((p) => p.date)))].sort();

  const normalised = usable.map((s) => {
    const base = s.points[0].close;
    const byDate = new Map<string, number>();
    for (const point of s.points) {
      if (base) byDate.set(point.date, ((point.close - base) / base) * 100);
    }
    return { symbol: s.symbol, byDate };
  });

  const values = normalised.flatMap((s) => [...s.byDate.values()]);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;

  const plotW = Math.max(width - PAD.left - PAD.right, 10);
  const plotH = height - PAD.top - PAD.bottom;

  const xAt = (i: number) =>
    PAD.left + (allDates.length === 1 ? plotW / 2 : (i / (allDates.length - 1)) * plotW);
  const yAt = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * plotH;

  const ticks = axisTicks(min, max);
  const lastIndex = allDates.length - 1;
  const labelStep = Math.max(1, Math.floor(lastIndex / 5));
  const labelIndices: number[] = [];
  for (let i = 0; i <= lastIndex; i += labelStep) labelIndices.push(i);
  if (labelIndices[labelIndices.length - 1] !== lastIndex) {
    if (lastIndex - labelIndices[labelIndices.length - 1] < labelStep * 0.6) labelIndices.pop();
    labelIndices.push(lastIndex);
  }

  function handleMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.min(Math.max((e.clientX - rect.left - PAD.left) / plotW, 0), 1);
    setHoverIndex(Math.round(ratio * lastIndex));
  }

  const hoverDate = hoverIndex != null ? allDates[hoverIndex] : null;

  return (
    <div className="comparison-chart">
      {/* A legend is the dependable identity channel; colour alone never is. */}
      <ul className="chart-legend">
        {normalised.map((s, i) => {
          // The last value is the change over the whole selected period, which
          // is the number most readers actually want from a comparison.
          const values = [...s.byDate.values()];
          const change = values.length ? values[values.length - 1] : null;
          return (
            <li key={s.symbol} className={`legend-item-inline series-${i + 1}`}>
              <span className="legend-key" aria-hidden="true" />
              <span className="legend-name">{s.symbol}</span>
              {change !== null && (
                <span className={`legend-change ${change >= 0 ? "is-up" : "is-down"}`}>
                  {pct(change)}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="chart-wrap" ref={attachWrap}>
        <svg
          className="price-chart"
          width={width}
          height={height}
          role="img"
          aria-label={`Percentage change since the start of the range for ${usable
            .map((s) => s.symbol)
            .join(", ")}`}
          onPointerMove={handleMove}
          onPointerLeave={() => setHoverIndex(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line
                className={t === 0 ? "chart-baseline" : "chart-grid"}
                x1={PAD.left}
                x2={PAD.left + plotW}
                y1={yAt(t)}
                y2={yAt(t)}
              />
              <text className="chart-axis-label" x={PAD.left + plotW + 8} y={yAt(t) + 4}>
                {pct(t)}
              </text>
            </g>
          ))}

          {labelIndices.map((i) => (
            <text
              key={allDates[i]}
              className="chart-axis-label chart-x-label"
              x={xAt(i)}
              y={height - 8}
              textAnchor={i === 0 ? "start" : i === lastIndex ? "end" : "middle"}
            >
              {shortDate(allDates[i])}
            </text>
          ))}

          {normalised.map((s, seriesIndex) => {
            let path = "";
            let penDown = false;
            allDates.forEach((date, i) => {
              const value = s.byDate.get(date);
              if (value === undefined) {
                penDown = false; // lift the pen across a gap rather than bridging it
                return;
              }
              path += `${penDown ? "L" : "M"}${xAt(i).toFixed(2)} ${yAt(value).toFixed(2)}`;
              penDown = true;
            });

            return (
              <path
                key={s.symbol}
                className={`chart-line series-${seriesIndex + 1}`}
                d={path}
                fill="none"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          })}

          {hoverDate && hoverIndex != null && (
            <>
              <line
                className="chart-crosshair"
                x1={xAt(hoverIndex)}
                x2={xAt(hoverIndex)}
                y1={PAD.top}
                y2={PAD.top + plotH}
              />
              {normalised.map((s, i) => {
                const value = s.byDate.get(hoverDate);
                if (value === undefined) return null;
                return (
                  <circle
                    key={s.symbol}
                    className={`chart-end-dot series-${i + 1}`}
                    cx={xAt(hoverIndex)}
                    cy={yAt(value)}
                    r={4}
                  />
                );
              })}
            </>
          )}
        </svg>

        {hoverDate && hoverIndex != null && (
          <div
            className="chart-tooltip chart-tooltip-multi"
            style={{ left: Math.min(Math.max(xAt(hoverIndex), 80), width - 80), top: PAD.top }}
          >
            <span className="tooltip-date">{longDate(hoverDate)}</span>
            {/* One tooltip lists every series, so the pointer never has to
                land on a particular line to read its value. */}
            {normalised.map((s, i) => {
              const value = s.byDate.get(hoverDate);
              return (
                <span key={s.symbol} className={`tooltip-row series-${i + 1}`}>
                  <span className="legend-key" aria-hidden="true" />
                  <span className="tooltip-symbol">{s.symbol}</span>
                  <span className="tooltip-value">{value === undefined ? "—" : pct(value)}</span>
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
