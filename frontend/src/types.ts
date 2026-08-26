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
}

export interface ImportResult {
  added: Record<string, number>;
  alerts_added: number;
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
