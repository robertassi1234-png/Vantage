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
