interface Props {
  values: number[];
  /** Direction the series closed in; drives the stroke color. */
  direction?: "up" | "down" | "flat";
  width?: number;
  height?: number;
}

/**
 * Trend line for a stat tile. Deliberately bare: no axes, no interaction —
 * the tile's value and delta carry the numbers, this only carries the shape.
 */
export function Sparkline({ values, direction = "flat", width = 120, height = 32 }: Props) {
  if (values.length < 2) {
    return <div className="sparkline-empty" style={{ width, height }} aria-hidden="true" />;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 2;

  const points = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  const path = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  const [lastX, lastY] = points[points.length - 1];

  return (
    <svg
      className={`sparkline sparkline-${direction}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Trend over the last ${values.length} sessions, ${direction}`}
    >
      <path d={path} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lastX} cy={lastY} r={2.5} className="sparkline-dot" />
    </svg>
  );
}
