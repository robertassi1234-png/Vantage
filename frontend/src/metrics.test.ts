import { describe, expect, it } from "vitest";
import { GROUPS, METRICS, PRIMARY_METRICS } from "./metrics";

const byKey = (key: string) => METRICS.find((m) => m.key === key)!;

describe("metric definitions", () => {
  it("has no duplicate keys", () => {
    const keys = METRICS.map((m) => m.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("assigns every metric to a declared group", () => {
    const groupIds = new Set(GROUPS.map((g) => g.id));
    for (const metric of METRICS) expect(groupIds.has(metric.group)).toBe(true);
  });

  it("gives every metric a plain-language label and explanation", () => {
    for (const metric of METRICS) {
      expect(metric.plainLabel.length).toBeGreaterThan(0);
      expect(metric.explanation.length).toBeGreaterThan(0);
    }
  });

  it("explains every analytical metric properly, not just in a few words", () => {
    // Identity fields ("the company's name") are self-evident; a ratio is not,
    // and a stub explanation there defeats the glossary.
    for (const metric of METRICS.filter((m) => m.band)) {
      expect(metric.explanation.length, `${metric.key}`).toBeGreaterThan(60);
    }
  });

  it("keeps the default view a readable subset", () => {
    expect(PRIMARY_METRICS.length).toBeGreaterThan(0);
    expect(PRIMARY_METRICS.length).toBeLessThan(METRICS.length);
  });
});

describe("formatters", () => {
  it("renders missing values as an em dash rather than NaN", () => {
    for (const metric of METRICS) {
      expect(metric.format(null)).toBe("—");
      expect(metric.format(undefined)).toBe("—");
      expect(metric.format(Number.NaN)).toBe("—");
    }
  });

  it("scales large market caps to T/B/M", () => {
    const marketCap = byKey("marketCap").format;
    expect(marketCap(4_551_611_624_400)).toBe("$4.55T");
    expect(marketCap(51_200_000_000)).toBe("$51.2B");
    expect(marketCap(250_000_000)).toBe("$250.0M");
  });

  it("renders ratios as percentages", () => {
    expect(byKey("netProfitMargin").format(0.2761)).toBe("27.6%");
    expect(byKey("epsGrowth").format(-0.084)).toBe("-8.4%");
  });

  it("formats share price as money", () => {
    expect(byKey("price").format(309.9)).toBe("$309.90");
  });
});

describe("range bands", () => {
  it("marks values inside the norm as typical", () => {
    expect(byKey("peRatio").band!(20)).toBe("mid");
    expect(byKey("debtToEquity").band!(1)).toBe("mid");
  });

  it("flags outliers on both sides", () => {
    expect(byKey("peRatio").band!(5)).toBe("low");
    expect(byKey("peRatio").band!(80)).toBe("high");
  });

  it("is positional, not a judgement: a strong margin reads high", () => {
    // Regression guard. An earlier `invert` flag made a 27% net margin
    // report as the *low* band, which inverted the shading in the table.
    expect(byKey("netProfitMargin").band!(0.276)).toBe("high");
    expect(byKey("netProfitMargin").band!(0.021)).toBe("low");
    expect(byKey("returnOnEquity").band!(1.37)).toBe("high");
    expect(byKey("revenueGrowth").band!(-0.05)).toBe("low");
  });

  it("returns null for non-finite input rather than shading it", () => {
    expect(byKey("peRatio").band!(Number.NaN)).toBeNull();
    expect(byKey("peRatio").band!(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("uses ranges wide enough that typical values stay unshaded", () => {
    // If almost everything is tinted the shading stops meaning anything.
    const typical: Record<string, number> = {
      peRatio: 25,
      evToEbitda: 15,
      netProfitMargin: 0.12,
      returnOnEquity: 0.15,
      debtToEquity: 0.9,
      currentRatio: 1.5,
    };
    for (const [key, value] of Object.entries(typical)) {
      expect(byKey(key).band!(value), `${key} at ${value}`).toBe("mid");
    }
  });
});
