import type { Lot, Quote, SplitAdjustment } from "./types";

/**
 * What a watchlist is worth to the person holding it.
 *
 * Everything here is derived from two things the app already has: the lots
 * the reader entered, and the quotes the dashboard refreshes anyway. Nothing
 * is stored, so a price update moves every figure at once and there is no
 * second copy of the arithmetic to drift out of step.
 *
 * Cost basis uses the average-cost method, walked in trade order. Trade order
 * is the part that matters: a sale has to be priced against the basis as it
 * stood on the day, not against the average of everything including the
 * shares bought afterwards.
 */

/** Share counts arrive as floats; a residue of 1e-15 is zero, not a holding. */
const DUST = 1e-9;

export interface Position {
  ticker: string;
  /** Net shares held after every buy and sale. */
  shares: number;
  /** Weighted average of what the held shares cost. Null once nothing is held. */
  averageCost: number | null;
  costBasis: number;
  marketValue: number | null;
  unrealized: number | null;
  unrealizedPercent: number | null;
  /** Today's move in money: shares held times the day's change per share. */
  dayChange: number | null;
  /** Profit already taken, from lots sold. */
  realized: number;
  /** Share of the portfolio's market value, 0-1. Null until prices arrive. */
  weight: number | null;
  /** Held nothing, but has history: sold out rather than never owned. */
  closed: boolean;
  /** More shares sold than were ever bought -- the entry is incomplete. */
  oversold: boolean;
  lots: Lot[];
}

export interface Portfolio {
  positions: Position[];
  byTicker: Map<string, Position>;
  totalValue: number;
  totalCost: number;
  dayChange: number;
  dayChangePercent: number | null;
  unrealized: number;
  unrealizedPercent: number | null;
  realized: number;
  /** Whether anything is actually held. The summary strip hides without this. */
  hasPositions: boolean;
  /** Positions whose price is missing, so the totals are incomplete. */
  unpriced: string[];
}

/** Lots grouped by ticker, each in the order the trades happened. */
export function groupLots(lots: Lot[]): Map<string, Lot[]> {
  const grouped = new Map<string, Lot[]>();
  for (const lot of lots) {
    const existing = grouped.get(lot.ticker);
    if (existing) existing.push(lot);
    else grouped.set(lot.ticker, [lot]);
  }
  for (const group of grouped.values()) {
    // The server orders these, but a lot added optimistically in the browser
    // arrives last regardless of its date, and average cost is order-sensitive.
    group.sort((a, b) => a.tradeDate.localeCompare(b.tradeDate));
  }
  return grouped;
}

interface Basis {
  shares: number;
  costBasis: number;
  realized: number;
  oversold: boolean;
}

/**
 * Walk one ticker's lots to a share count, a cost basis, and realised profit.
 *
 * A sale takes its share of the basis away at the average cost of the moment,
 * and books the difference as realised. That is what keeps a partial sale from
 * flattering the remaining position: selling the cheap half of a holding must
 * not leave the rest looking like it was bought at the expensive price.
 */
export function accumulate(lots: Lot[]): Basis {
  let shares = 0;
  let costBasis = 0;
  let realized = 0;
  let oversold = false;

  for (const lot of lots) {
    if (lot.shares > 0) {
      shares += lot.shares;
      costBasis += lot.shares * lot.costPerShare;
      continue;
    }

    const wanted = -lot.shares;
    if (wanted > shares + DUST) oversold = true;

    // Clamped rather than allowed to go negative: a share count below zero
    // would be read as a short position, which this does not model, and the
    // likelier explanation is a purchase the reader has not entered yet.
    const sold = Math.min(wanted, shares);
    if (sold <= 0) continue;

    const average = costBasis / shares;
    realized += sold * (lot.costPerShare - average);
    costBasis -= sold * average;
    shares -= sold;
  }

  if (Math.abs(shares) < DUST) {
    shares = 0;
    costBasis = 0;
  }
  return { shares, costBasis, realized, oversold };
}

/**
 * Build every position, then the totals across them.
 *
 * Weights need the portfolio total, and the total needs each position, so
 * this is one pass to value them and a second to weight them.
 */
export function buildPortfolio(lots: Lot[], quotes: Quote[]): Portfolio {
  const priceFor = new Map(quotes.map((q) => [q.symbol, q]));
  const grouped = groupLots(lots);

  const positions: Position[] = [];
  for (const [ticker, group] of grouped) {
    const { shares, costBasis, realized, oversold } = accumulate(group);
    const quote = priceFor.get(ticker);
    const price = quote?.price ?? null;

    const marketValue = price == null ? null : shares * price;
    const unrealized = marketValue == null ? null : marketValue - costBasis;

    positions.push({
      ticker,
      shares,
      averageCost: shares > 0 ? costBasis / shares : null,
      costBasis,
      marketValue,
      unrealized,
      // Against cost, not against value: a 20% gain means twenty cents on
      // each dollar put in.
      unrealizedPercent:
        unrealized == null || costBasis <= 0 ? null : (unrealized / costBasis) * 100,
      dayChange: quote?.change == null ? null : shares * quote.change,
      realized,
      weight: null,
      closed: shares === 0 && group.length > 0,
      oversold,
      lots: group,
    });
  }

  positions.sort((a, b) => (b.marketValue ?? 0) - (a.marketValue ?? 0));

  const held = positions.filter((p) => p.shares > 0);
  const totalValue = sum(held.map((p) => p.marketValue ?? 0));
  const totalCost = sum(held.map((p) => p.costBasis));
  const dayChange = sum(held.map((p) => p.dayChange ?? 0));
  const unrealized = totalValue === 0 ? 0 : totalValue - totalCost;

  for (const position of positions) {
    position.weight =
      totalValue > 0 && position.marketValue != null && position.shares > 0
        ? position.marketValue / totalValue
        : null;
  }

  // Yesterday's close is the denominator for a day move, not today's -- a
  // portfolio that rose to 110 rose by 10% from 100, not by 9.1% of itself.
  const opening = totalValue - dayChange;

  return {
    positions,
    byTicker: new Map(positions.map((p) => [p.ticker, p])),
    totalValue,
    totalCost,
    dayChange,
    dayChangePercent: opening > 0 ? (dayChange / opening) * 100 : null,
    unrealized,
    unrealizedPercent: totalCost > 0 ? (unrealized / totalCost) * 100 : null,
    realized: sum(positions.map((p) => p.realized)),
    hasPositions: held.length > 0,
    unpriced: held.filter((p) => p.marketValue == null).map((p) => p.ticker),
  };
}

/** Splits already applied to a ticker's lots, newest first. */
export function splitsFor(splits: SplitAdjustment[], ticker: string): SplitAdjustment[] {
  return splits.filter((s) => s.ticker === ticker);
}

/** "4-for-1", the way a split is actually spoken about. */
export function describeSplit(ratio: number): string {
  if (ratio >= 1) return `${trim(ratio)}-for-1`;
  return `1-for-${trim(1 / ratio)}`;
}

const trim = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, ""));

const sum = (values: number[]) => values.reduce((total, v) => total + v, 0);
