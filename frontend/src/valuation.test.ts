import { describe, expect, it } from "vitest";
import {
  bestInRow,
  describePercentile,
  formatMetric,
  hasContext,
  markerPosition,
  medianPosition,
} from "./valuation";
import type { MetricStat, ValuationCompany, ValuationMetricDef } from "./types";

const stat = (over: Partial<MetricStat> = {}): MetricStat => ({
  value: 30,
  median: 24,
  low: 18,
  high: 34,
  percentile: 0.9,
  samples: 20,
  ...over,
});

const def = (over: Partial<ValuationMetricDef> = {}): ValuationMetricDef => ({
  key: "peRatio",
  label: "P/E (trailing)",
  better: null,
  percent: false,
  ...over,
});

const company = (ticker: string, value: number | null, key = "grossMargin"): ValuationCompany => ({
  ticker,
  companyName: ticker,
  sector: null,
  price: null,
  metrics: { [key]: stat({ value }) },
  stale: false,
  error: null,
});

describe("placing today inside the company's own range", () => {
  it("puts a value at the top of its range near the right", () => {
    expect(markerPosition(stat({ value: 34 }))).toBe(1);
  });

  it("puts a value at the bottom near the left", () => {
    expect(markerPosition(stat({ value: 18 }))).toBe(0);
  });

  it("clamps a value past the trimmed range to the end of the bar", () => {
    // The bar is drawn between the 5th and 95th percentiles, so a genuine
    // extreme sits outside it. Better pinned to the end than off the bar.
    expect(markerPosition(stat({ value: 400 }))).toBe(1);
  });

  it("centres a metric that has not moved in five years", () => {
    // No range to place anything in, and the middle says "typical", which
    // is true.
    expect(markerPosition(stat({ value: 15, low: 15, high: 15 }))).toBe(0.5);
  });

  it("cannot place a value it does not have", () => {
    expect(markerPosition(stat({ value: null }))).toBeNull();
    expect(medianPosition(stat({ median: null }))).toBeNull();
  });

  it("places the median tick the same way", () => {
    expect(medianPosition(stat({ median: 26, low: 18, high: 34 }))).toBe(0.5);
  });
});

describe("whether a range is worth drawing", () => {
  it("needs more than a quarter or two", () => {
    // One observation is not a range, and a bar over it implies a history
    // that isn't there.
    expect(hasContext(stat({ samples: 2 }))).toBe(false);
    expect(hasContext(stat({ samples: 20 }))).toBe(true);
  });

  it("is false when the endpoint reported nothing", () => {
    expect(hasContext(stat({ low: null, high: null, samples: 0 }))).toBe(false);
  });
});

describe("formatting", () => {
  it("shows a margin as a percentage", () => {
    expect(formatMetric(0.464, def({ percent: true }))).toBe("46.4%");
  });

  it("shows a multiple to one decimal", () => {
    expect(formatMetric(32.44, def())).toBe("32.4");
  });

  it("drops the decimals past a hundred, where they are noise", () => {
    expect(formatMetric(432.7, def())).toBe("433");
  });

  it("shows a dash rather than a zero for a missing number", () => {
    expect(formatMetric(null, def())).toBe("—");
    expect(formatMetric(Number.NaN, def())).toBe("—");
  });
});

describe("saying what the percentile means", () => {
  it.each([
    [0.95, /Near its five-year high/],
    [0.75, /Above its five-year normal/],
    [0.5, /About its five-year normal/],
    [0.2, /Below its five-year normal/],
    [0.02, /Near its five-year low/],
  ])("describes a percentile of %s", (percentile, expected) => {
    expect(describePercentile(stat({ percentile }), def())).toMatch(expected);
  });

  it("names the median, since a percentile alone means little", () => {
    expect(describePercentile(stat({ percentile: 0.95, median: 24 }), def())).toContain("24.0");
  });

  it("says nothing when there is not enough history to say it", () => {
    expect(describePercentile(stat({ samples: 2 }), def())).toBeNull();
    expect(describePercentile(stat({ percentile: null }), def())).toBeNull();
  });
});

describe("marking the leader of a row", () => {
  it("picks the highest margin", () => {
    const companies = [company("A", 0.3), company("B", 0.5)];
    expect(bestInRow(companies, def({ key: "grossMargin", better: "high" }))).toBe("B");
  });

  it("picks the least dilution, which can be a buyback", () => {
    const companies = [company("A", 0.04, "shareChange"), company("B", -0.02, "shareChange")];
    expect(bestInRow(companies, def({ key: "shareChange", better: "low" }))).toBe("B");
  });

  it("marks no leader on a valuation multiple", () => {
    // The lowest P/E in a group is as often the most troubled company as the
    // best value. Calling it the winner is a judgement the data cannot make.
    const companies = [company("A", 12, "peRatio"), company("B", 40, "peRatio")];
    expect(bestInRow(companies, def({ key: "peRatio", better: null }))).toBeNull();
  });

  it("marks no leader when only one company reported the figure", () => {
    const companies = [company("A", 0.3), company("B", null)];
    expect(bestInRow(companies, def({ key: "grossMargin", better: "high" }))).toBeNull();
  });

  it("marks no leader on a tie, rather than picking whichever came first", () => {
    const companies = [company("A", 0.4), company("B", 0.4)];
    expect(bestInRow(companies, def({ key: "grossMargin", better: "high" }))).toBeNull();
  });
});
