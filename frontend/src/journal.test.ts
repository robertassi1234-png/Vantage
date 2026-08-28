import { describe, expect, it } from "vitest";
import { describeElapsed, filterByTags, formatWritten, gradeEntry, tagCounts } from "./journal";
import type { JournalEntry, Quote } from "./types";

const entry = (over: Partial<JournalEntry> = {}): JournalEntry => ({
  id: "e1",
  ticker: "AAPL",
  body: "Services margin keeps expanding.",
  priceAtWrite: 142.3,
  dateWritten: "2025-03-04T00:00:00+00:00",
  tags: [],
  reviewedAt: null,
  ...over,
});

const quote = (price: number | null): Quote => ({
  symbol: "AAPL",
  name: "Apple Inc.",
  price,
  change: null,
  changePercent: null,
  dayLow: null,
  dayHigh: null,
  yearLow: null,
  yearHigh: null,
  marketCap: null,
  volume: null,
});

describe("grading an entry against what happened", () => {
  it("measures the move from the price it was written at", () => {
    // The one line that makes this a feedback loop rather than a notes app.
    const verdict = gradeEntry(entry({ priceAtWrite: 142.3 }), quote(189.44));
    expect(verdict.changePercent).toBeCloseTo(33.13, 2);
    expect(verdict.direction).toBe("up");
  });

  it("reports a thesis that went the other way", () => {
    const verdict = gradeEntry(entry({ priceAtWrite: 200 }), quote(150));
    expect(verdict.changePercent).toBeCloseTo(-25);
    expect(verdict.direction).toBe("down");
  });

  it("cannot score an entry written while prices were unavailable", () => {
    // No stamp was taken and none can be invented afterwards. The entry is
    // still worth reading.
    const verdict = gradeEntry(entry({ priceAtWrite: null }), quote(189.44));
    expect(verdict.changePercent).toBeNull();
    expect(verdict.direction).toBe("unknown");
  });

  it("cannot score an entry whose company has no price today", () => {
    const verdict = gradeEntry(entry(), undefined);
    expect(verdict.changePercent).toBeNull();
    expect(verdict.priceThen).toBe(142.3);
  });

  it("does not divide by a zero price", () => {
    expect(gradeEntry(entry({ priceAtWrite: 0 }), quote(50)).changePercent).toBeNull();
  });
});

describe("tags", () => {
  it("are counted most-used first", () => {
    const counts = tagCounts([
      entry({ tags: ["risk"] }),
      entry({ tags: ["risk", "thesis"] }),
      entry({ tags: ["thesis"] }),
      entry({ tags: ["catalyst"] }),
    ]);
    expect(counts.slice(0, 2).map((c) => c.count)).toEqual([2, 2]);
    expect(counts.at(-1)).toEqual({ tag: "catalyst", count: 1 });
  });

  it("narrow rather than widen when a second one is picked", () => {
    // Picking "risk" and "mistake" means the risks that turned out to be
    // mistakes -- otherwise a second selection would show more, not less.
    const entries = [
      entry({ id: "a", tags: ["risk"] }),
      entry({ id: "b", tags: ["risk", "mistake"] }),
      entry({ id: "c", tags: ["mistake"] }),
    ];
    expect(filterByTags(entries, ["risk", "mistake"]).map((e) => e.id)).toEqual(["b"]);
    expect(filterByTags(entries, ["risk"]).map((e) => e.id)).toEqual(["a", "b"]);
  });

  it("show everything when nothing is selected", () => {
    const entries = [entry({ tags: [] }), entry({ tags: ["risk"] })];
    expect(filterByTags(entries, [])).toHaveLength(2);
  });
});

describe("dates", () => {
  it("are written out in full so an entry can be placed", () => {
    expect(formatWritten("2025-03-04T00:00:00+00:00")).toMatch(/2025/);
  });

  it("survive a value that is not a date", () => {
    expect(formatWritten("nonsense")).toBe("nonsense");
  });

  it.each([
    [0, "today"],
    [1, "yesterday"],
    [12, "12 days ago"],
    [95, "3 months ago"],
    [800, "2.2 years ago"],
  ])("describes %s days ago as %s", (days, expected) => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    const written = new Date(now - days * 24 * 60 * 60 * 1000).toISOString();
    expect(describeElapsed(written, now)).toBe(expected);
  });
});
