interface Props {
  values: number[];
  /** Direction the series closed in; drives the stroke color. */
  direction?: "up" | "down" | "flat";
  width?: number;
  height?: number;
  /** Stretch to whatever width the container gives it, edge to edge. */
  bleed?: boolean;
}

/**
 * Trend line for a stat tile. Deliberately bare: no axes, no interaction —
 * the tile's value and delta carry the numbers, this only carries the shape.
 *
 * The end point is ringed in the surface colour so it stays legible where the
 * line doubles back under it, and a faint wash under the line gives the shape
 * some weight at this size without competing with the value above it.
 */
export function Sparkline({
  values,
  direction = "flat",
  width = 120,
  height = 32,
  bleed = false,
}: Props) {
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
  const [firstX] = points[0];
  const area = `${path} L${lastX.toFixed(2)} ${height} L${firstX.toFixed(2)} ${height} Z`;

  return (
    <svg
      className={`sparkline sparkline-${direction}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      // Letterboxing is the default, which leaves a stretched sparkline
      // floating in the middle of its card instead of meeting the edges.
      preserveAspectRatio={bleed ? "none" : undefined}
      role="img"
      aria-label={`Trend over the last ${values.length} sessions, ${direction}`}
    >
      <path className="sparkline-area" d={area} stroke="none" />
      <path
        d={path}
        fill="none"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        // Keeps the line 1.5px however far the viewBox is stretched.
        vectorEffect={bleed ? "non-scaling-stroke" : undefined}
      />
      {/* Ringed in the surface colour so the end point survives a line that
          doubles back beneath it. Dropped when stretched, where a circle
          would be squashed into an ellipse. */}
      {!bleed && (
        <circle cx={lastX} cy={lastY} r={3} className="sparkline-dot" strokeWidth={2} />
      )}
    </svg>
  );
}
