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
