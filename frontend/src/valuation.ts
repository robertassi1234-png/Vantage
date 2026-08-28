import type { MetricStat, ValuationCompany, ValuationMetricDef } from "./types";

/**
 * Reading a metric against the company's own record.
 *
 * A P/E of 30 is not a fact about expense, it is a fact about a number. The
 * only thing that makes it mean anything is where it sits against the same
 * company's own last five years -- so everything here is about turning a raw
 * value into a position within that range.
 */

const dash = "—";

/** Where the marker goes on the bar, 0-1, or null if it cannot be placed. */
export function markerPosition(stat: MetricStat): number | null {
  const { value, low, high } = stat;
  if (value == null || low == null || high == null) return null;

  const span = high - low;
  // A metric that has not moved in five years has no range to place anything
  // in. Parking the marker in the middle says "typical", which is true.
  if (span <= 0) return 0.5;
  return Math.min(Math.max((value - low) / span, 0), 1);
}

export function medianPosition(stat: MetricStat): number | null {
  const { median, low, high } = stat;
  if (median == null || low == null || high == null) return null;

  const span = high - low;
  if (span <= 0) return 0.5;
  return Math.min(Math.max((median - low) / span, 0), 1);
}

/** Whether the bar is worth drawing: one quarter is not a range. */
export function hasContext(stat: MetricStat): boolean {
  return stat.samples >= 4 && stat.low != null && stat.high != null;
}

export function formatMetric(value: number | null, def: ValuationMetricDef): string {
  if (value == null || !Number.isFinite(value)) return dash;
  if (def.percent) return `${(value * 100).toFixed(1)}%`;
  // Multiples past a hundred are noise dressed as precision.
  if (Math.abs(value) >= 100) return value.toFixed(0);
  return value.toFixed(1);
}

/**
 * How today compares to the company's own history, in words.
 *
 * The bar shows it; this is what a screen reader gets, and what the tooltip
 * says. Percentile is unintuitive on its own, so it is phrased as the thing
 * it actually means.
 */
export function describePercentile(stat: MetricStat, def: ValuationMetricDef): string | null {
  if (stat.percentile == null || stat.samples < 4) return null;

  const pct = Math.round(stat.percentile * 100);
  const median = formatMetric(stat.median, def);

  if (pct >= 90) return `Near its five-year high — typically ${median}`;
  if (pct >= 70) return `Above its five-year normal of ${median}`;
  if (pct <= 10) return `Near its five-year low — typically ${median}`;
  if (pct <= 30) return `Below its five-year normal of ${median}`;
  return `About its five-year normal of ${median}`;
}

/**
 * The company that leads a row, where leading means anything.
 *
 * Deliberately empty for every valuation multiple. The lowest P/E in a group
 * is as often the most troubled company as the best value, and marking it as
 * the winner would be a judgement the data does not support. Margins, growth
 * and dilution are the three where more (or less) is simply better.
 */
export function bestInRow(
  companies: ValuationCompany[],
  def: ValuationMetricDef,
): string | null {
  if (!def.better) return null;

  const scored = companies
    .map((c) => ({ ticker: c.ticker, value: c.metrics[def.key]?.value }))
    .filter((c): c is { ticker: string; value: number } => typeof c.value === "number");

  // Nothing to compare against means nothing to lead.
  if (scored.length < 2) return null;

  const winner = scored.reduce((best, candidate) =>
    def.better === "high"
      ? candidate.value > best.value
        ? candidate
        : best
      : candidate.value < best.value
        ? candidate
        : best,
  );

  // A tie has no winner: highlighting the first one would be arbitrary.
  const tied = scored.filter((c) => c.value === winner.value).length > 1;
  return tied ? null : winner.ticker;
}
