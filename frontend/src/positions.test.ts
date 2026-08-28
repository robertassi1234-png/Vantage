import { describe, expect, it } from "vitest";
import { accumulate, buildPortfolio, describeSplit, groupLots } from "./positions";
import type { Lot, Quote } from "./types";

let counter = 0;
const lot = (ticker: string, shares: number, costPerShare: number, tradeDate = "2025-01-01"): Lot => ({
  id: `lot-${counter++}`,
  ticker,
  shares,
  costPerShare,
  tradeDate,
  note: null,
  created_at: tradeDate,
});

const quote = (symbol: string, price: number | null, change: number | null = 0): Quote => ({
  symbol,
  name: symbol,
  price,
  change,
  changePercent: null,
  dayLow: null,
  dayHigh: null,
  yearLow: null,
  yearHigh: null,
  marketCap: null,
  volume: null,
});

describe("average cost across lots", () => {
  it("is the weighted average, not the average of the prices", () => {
    // 10 at $100 and 30 at $200 averages $175, not $150. Getting this wrong
    // is the whole reason lots are stored individually.
    const { shares, costBasis } = accumulate([lot("A", 10, 100), lot("A", 30, 200)]);
    expect(shares).toBe(40);
    expect(costBasis / shares).toBe(175);
  });

  it("adds to a position rather than replacing it", () => {
    const { costBasis } = accumulate([lot("A", 10, 100), lot("A", 10, 300)]);
    expect(costBasis).toBe(4000);
  });

  it("leaves the remaining basis alone when part is sold", () => {
    // Bought 10 at $100, sold 5 at $150. The five still held cost $100 each,
    // not $50 -- selling the position's cheap half must not make the rest
    // look expensive, nor the reverse.
    const { shares, costBasis, realized } = accumulate([
      lot("A", 10, 100, "2025-01-01"),
      lot("A", -5, 150, "2025-06-01"),
    ]);
    expect(shares).toBe(5);
    expect(costBasis).toBe(500);
    expect(realized).toBe(250);
  });

  it("prices a sale against the basis as it stood that day", () => {
    // Buy 10 at $100, sell 10 at $150, then buy 10 at $500. The sale made
    // $500. Averaging over all three lots first would price the sale against
    // $300 and report a loss on a trade that made money.
    const { realized } = accumulate([
      lot("A", 10, 100, "2025-01-01"),
      lot("A", -10, 150, "2025-02-01"),
      lot("A", 10, 500, "2025-03-01"),
    ]);
    expect(realized).toBe(500);
  });

  it("reports a loss on a sale below cost", () => {
    const { realized } = accumulate([lot("A", 10, 100, "2025-01-01"), lot("A", -10, 60, "2025-02-01")]);
    expect(realized).toBe(-400);
  });

  it("leaves nothing behind when a position is sold out", () => {
    const { shares, costBasis } = accumulate([
      lot("A", 3, 33.33, "2025-01-01"),
      lot("A", -3, 40, "2025-02-01"),
    ]);
    expect(shares).toBe(0);
    // Floating point leaves a residue here; a basis of 4e-15 must not render
    // as a holding worth a fraction of a cent.
    expect(costBasis).toBe(0);
  });

  it("flags selling more than was ever bought instead of going short", () => {
    const { shares, oversold } = accumulate([lot("A", 5, 100, "2025-01-01"), lot("A", -8, 120, "2025-02-01")]);
    expect(oversold).toBe(true);
    expect(shares).toBe(0);
  });

  it("ignores a sale recorded before any purchase", () => {
    const { shares, realized, oversold } = accumulate([lot("A", -5, 100, "2025-01-01")]);
    expect(shares).toBe(0);
    expect(realized).toBe(0);
    expect(oversold).toBe(true);
  });
});

describe("grouping lots by ticker", () => {
  it("keeps each ticker's trades in the order they happened", () => {
    const grouped = groupLots([
      lot("A", 1, 10, "2025-06-01"),
      lot("B", 1, 10, "2025-01-01"),
      lot("A", 1, 10, "2025-01-01"),
    ]);
    expect(grouped.get("A")!.map((l) => l.tradeDate)).toEqual(["2025-01-01", "2025-06-01"]);
    expect([...grouped.keys()]).toEqual(["A", "B"]);
  });
});

describe("a portfolio built from lots and live prices", () => {
  it("values a position at the current price, not what was paid", () => {
    const p = buildPortfolio([lot("A", 10, 100)], [quote("A", 150)]);
    const position = p.byTicker.get("A")!;
    expect(position.marketValue).toBe(1500);
    expect(position.costBasis).toBe(1000);
    expect(position.unrealized).toBe(500);
    expect(position.unrealizedPercent).toBe(50);
  });

  it("measures the gain against what was put in", () => {
    // 20% means twenty cents on each dollar invested. Dividing by market
    // value instead would report 16.7% for the same trade.
    const p = buildPortfolio([lot("A", 10, 100)], [quote("A", 120)]);
    expect(p.byTicker.get("A")!.unrealizedPercent).toBeCloseTo(20);
  });

  it("turns the day's move per share into money", () => {
    const p = buildPortfolio([lot("A", 40, 100)], [quote("A", 150, 2.5)]);
    expect(p.byTicker.get("A")!.dayChange).toBe(100);
  });

  it("weights each position by its share of the total", () => {
    const p = buildPortfolio([lot("A", 10, 10), lot("B", 10, 10)], [quote("A", 75), quote("B", 25)]);
    expect(p.byTicker.get("A")!.weight).toBeCloseTo(0.75);
    expect(p.byTicker.get("B")!.weight).toBeCloseTo(0.25);
  });

  it("measures the day's move against yesterday, not today", () => {
    // Worth 110 today having risen 10: that is 10% up from 100, not 9.1% of
    // where it ended.
    const p = buildPortfolio([lot("A", 1, 50)], [quote("A", 110, 10)]);
    expect(p.dayChangePercent).toBeCloseTo(10);
  });

  it("totals value, cost and gain across positions", () => {
    const p = buildPortfolio(
      [lot("A", 10, 100), lot("B", 5, 200)],
      [quote("A", 150), quote("B", 300)],
    );
    expect(p.totalValue).toBe(3000);
    expect(p.totalCost).toBe(2000);
    expect(p.unrealized).toBe(1000);
    expect(p.unrealizedPercent).toBeCloseTo(50);
    expect(p.hasPositions).toBe(true);
  });

  it("says so when a held position has no price", () => {
    // The totals are then incomplete, and presenting them as a full portfolio
    // value would understate it silently.
    const p = buildPortfolio([lot("A", 10, 100), lot("B", 1, 50)], [quote("A", 150)]);
    expect(p.unpriced).toEqual(["B"]);
    expect(p.byTicker.get("B")!.marketValue).toBeNull();
  });

  it("has no positions when only watch-only tickers exist", () => {
    const p = buildPortfolio([], [quote("A", 150)]);
    expect(p.hasPositions).toBe(false);
    expect(p.totalValue).toBe(0);
    expect(p.dayChangePercent).toBeNull();
  });

  it("keeps a sold-out position's realised profit but not its weight", () => {
    const p = buildPortfolio(
      [lot("A", 10, 100, "2025-01-01"), lot("A", -10, 150, "2025-02-01"), lot("B", 1, 10)],
      [quote("A", 200), quote("B", 10)],
    );
    const closed = p.byTicker.get("A")!;
    expect(closed.closed).toBe(true);
    expect(closed.realized).toBe(500);
    expect(closed.weight).toBeNull();
    // A position no longer held is not part of what the portfolio is worth,
    // however well it did.
    expect(p.totalValue).toBe(10);
    expect(p.realized).toBe(500);
  });

  it("puts the largest holding first", () => {
    const p = buildPortfolio([lot("A", 1, 1), lot("B", 100, 1)], [quote("A", 5), quote("B", 5)]);
    expect(p.positions.map((x) => x.ticker)).toEqual(["B", "A"]);
  });

  it("has no average cost for a position that is fully sold", () => {
    const p = buildPortfolio(
      [lot("A", 10, 100, "2025-01-01"), lot("A", -10, 150, "2025-02-01")],
      [quote("A", 200)],
    );
    expect(p.byTicker.get("A")!.averageCost).toBeNull();
  });

  it("does not divide by a zero cost basis", () => {
    const p = buildPortfolio([lot("A", 10, 100, "2025-01-01"), lot("A", -10, 150, "2025-02-01")], []);
    expect(p.byTicker.get("A")!.unrealizedPercent).toBeNull();
    expect(p.unrealizedPercent).toBeNull();
  });
});

describe("describing a split the way people say it", () => {
  it.each([
    [4, "4-for-1"],
    [2, "2-for-1"],
    [0.1, "1-for-10"],
    [0.05, "1-for-20"],
  ])("calls ratio %s a %s split", (ratio, expected) => {
    expect(describeSplit(ratio)).toBe(expected);
  });
});
