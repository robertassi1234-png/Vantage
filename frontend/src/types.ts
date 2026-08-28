export interface FundamentalsRow {
  ticker: string;
  companyName: string | null;
  sector: string | null;
  industry: string | null;
  price: number | null;
  marketCap: number | null;
  beta: number | null;
  peRatio: number | null;
  pegRatio: number | null;
  evToEbitda: number | null;
  priceToBook: number | null;
  priceToSales: number | null;
  debtToEquity: number | null;
  currentRatio: number | null;
  revenueGrowth: number | null;
  epsGrowth: number | null;
  netProfitMargin: number | null;
  operatingMargin: number | null;
  returnOnEquity: number | null;
  dividendYield: number | null;
  stale: boolean;
  fetchedAt: string | null;
  error: string | null;
}

export interface SymbolMatch {
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string | null;
}

/** "watch" follows prices; "compare" is the fundamentals table. Independent. */
export type ListName = "watch" | "compare";

export interface WatchlistEntry {
  ticker: string;
  added_at: string;
  note: string | null;
}

/**
 * One purchase or sale. Negative shares are a sale, with costPerShare
 * carrying the price sold at, so a position's history stays a single ordered
 * list rather than two that have to be interleaved to compute anything.
 */
export interface Lot {
  id: string;
  ticker: string;
  shares: number;
  costPerShare: number;
  tradeDate: string;
  note: string | null;
  created_at: string;
}

/** A share split already applied to a ticker's lots. Kept so it can be undone. */
export interface SplitAdjustment {
  id: string;
  ticker: string;
  /** New shares per old one: 4-for-1 is 4, a reverse 1-for-10 is 0.1. */
  ratio: number;
  applied_at: string;
}

export interface PositionsResponse {
  lots: Lot[];
  splits: SplitAdjustment[];
}

/**
 * A dated opinion about a company, stamped with the price it was written at.
 *
 * `priceAtWrite` is captured once and never recomputed: it is the record the
 * entry exists for, and recalculating it against a live price would erase it.
 */
export interface JournalEntry {
  id: string;
  ticker: string;
  body: string;
  priceAtWrite: number | null;
  dateWritten: string;
  tags: string[];
  reviewedAt: string | null;
}

export interface JournalResponse {
  entries: JournalEntry[];
  /** Ids old enough to be worth revisiting and never revisited. */
  review_due: string[];
  suggested_tags: string[];
  review_after_days: number;
}

export type AlertDirection = "above" | "below";

export interface PriceAlert {
  id: string;
  ticker: string;
  direction: AlertDirection;
  threshold: number;
  note: string | null;
  created_at: string;
  triggered_at: string | null;
  triggered_price: number | null;
  acknowledged: boolean;
}

export interface AlertCheckResult {
  fired: PriceAlert[];
  alerts: PriceAlert[];
  checked: number;
  error: string | null;
}

export interface WorkspaceExport {
  version: number;
  exported_at: string;
  lists: Record<string, { ticker: string; added_at?: string | null; note?: string | null }[]>;
  alerts: { ticker: string; direction: string; threshold: number; note?: string | null }[];
  /** Added in v2. Absent in a file written before positions existed. */
  lots?: {
    ticker: string;
    shares: number;
    costPerShare: number;
    tradeDate: string;
    note?: string | null;
  }[];
}

export interface ImportResult {
  added: Record<string, number>;
  alerts_added: number;
  lots_added?: number;
  skipped: string[];
}

export interface PricePoint {
  date: string;
  close: number;
}

export interface PriceHistory {
  symbol: string;
  range: string;
  points: PricePoint[];
}

export interface Quote {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  changePercent: number | null;
  dayLow: number | null;
  dayHigh: number | null;
  yearLow: number | null;
  yearHigh: number | null;
  marketCap: number | null;
  volume: number | null;
}

export interface IndexQuote {
  symbol: string;
  label: string;
  blurb: string;
  price: number | null;
  change: number | null;
  changePercent: number | null;
  sparkline: number[];
}

export const RANGES = ["1M", "3M", "6M", "1Y", "5Y"] as const;
export type RangeKey = (typeof RANGES)[number];

export type Sentiment = "hawkish" | "dovish" | "neutral";

export interface FedStatement {
  id: string;
  date: string;
  title: string;
  url: string;
  summary: string | null;
  sentiment: Sentiment | null;
  key_takeaways: string[];
  fetched_at: string;
}

export interface FedRefreshResult {
  added: string[];
  errors: string[];
  timeline: FedStatement[];
}


export interface Account {
  signed_in: boolean;
  email: string | null;
  /** Whether this server is actually set up to keep accounts. */
  accounts_available: boolean;
  durable_storage: boolean;
  email_delivery: boolean;
  /** Plain-language explanation when accounts are unavailable. */
  reason: string | null;
}

export interface SignInLinkResult {
  sent: boolean;
  message: string;
  /** Only present when no mail provider is configured, i.e. local development. */
  dev_link?: string;
}

export interface SignInResult {
  signed_in: boolean;
  email: string | null;
  claimed: { watchlist: number; alerts: number };
}


export interface PeerSuggestion {
  symbol: string;
  /** How many of the compared companies list this one as a peer. */
  count: number;
  because_of: string[];
  name?: string | null;
  price?: number | null;
  changePercent?: number | null;
}

export interface PeerSuggestions {
  suggestions: PeerSuggestion[];
  /** The compared tickers the suggestions were derived from. */
  based_on: string[];
  error: string | null;
}


export interface MarketTile {
  symbol: string;
  label: string;
  blurb: string;
  price: number | null;
  change: number | null;
  changePercent: number | null;
  sparkline: number[];
}

export interface MarketGroup {
  group: string;
  entries: MarketTile[];
}
