import type { FundamentalsRow } from "./types";

export type Band = "low" | "mid" | "high" | null;

export interface MetricDef {
  key: keyof FundamentalsRow;
  /** Conventional short label, e.g. "P/E". */
  label: string;
  /** Plain-English name for people who don't know the jargon. */
  plainLabel: string;
  /** One or two sentences explaining what it measures and why it matters. */
  explanation: string;
  group: GroupId;
  format: (v: unknown) => string;
  /** Where a value sits in a typical range. Purely descriptive. */
  band?: (v: number) => Band;
  /** Shown by default, or only when "all metrics" is on. */
  primary?: boolean;
}

export type GroupId = "identity" | "valuation" | "profitability" | "growth" | "health";

export const GROUPS: { id: GroupId; label: string; blurb: string }[] = [
  { id: "identity", label: "Company", blurb: "Who this is and what it's worth today." },
  {
    id: "valuation",
    label: "Valuation",
    blurb: "How expensive the stock is relative to what the business earns or owns.",
  },
  {
    id: "profitability",
    label: "Profitability",
    blurb: "How much of each sales dollar the company actually keeps.",
  },
  {
    id: "growth",
    label: "Growth",
    blurb: "How quickly sales and profits grew over the last reported year.",
  },
  {
    id: "health",
    label: "Financial Health",
    blurb: "How much debt it carries and whether it can cover near-term bills.",
  },
];

const dash = "—";

const num = (digits = 2) => (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : dash;

const percent = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : dash;

const money = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? `$${v.toFixed(2)}` : dash;

const bigMoney = (v: unknown) => {
  if (typeof v !== "number" || !Number.isFinite(v)) return dash;
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toFixed(0)}`;
};

const text = (v: unknown) => (typeof v === "string" && v ? v : dash);

/**
 * Bands mark where a value sits versus a broad market norm — purely positional,
 * never a judgement. A high P/E is normal for a fast-growing company and a low
 * one can signal trouble, so "high" must not be read as "good".
 */
const bandBy =
  (lowBelow: number, highAbove: number) =>
  (v: number): Band => {
    if (!Number.isFinite(v)) return null;
    if (v < lowBelow) return "low";
    if (v > highAbove) return "high";
    return "mid";
  };

export const METRICS: MetricDef[] = [
  {
    key: "companyName",
    label: "Company",
    plainLabel: "Company",
    explanation: "The company's registered name.",
    group: "identity",
    format: text,
    primary: true,
  },
  {
    key: "sector",
    label: "Sector",
    plainLabel: "Sector",
    explanation:
      "The broad industry it operates in. Metrics are most meaningful when compared within the same sector.",
    group: "identity",
    format: text,
  },
  {
    key: "price",
    label: "Price",
    plainLabel: "Share price",
    explanation: "What one share costs right now.",
    group: "identity",
    format: money,
    primary: true,
  },
  {
    key: "marketCap",
    label: "Market Cap",
    plainLabel: "Company size",
    explanation:
      "The total value of all shares combined — share price times number of shares. This is what the market thinks the whole company is worth.",
    group: "identity",
    format: bigMoney,
    primary: true,
  },

  {
    key: "peRatio",
    label: "P/E",
    plainLabel: "Price vs. earnings",
    explanation:
      "How many dollars you pay for each $1 of annual profit. A high number means investors expect strong growth ahead — or that the stock is expensive.",
    group: "valuation",
    format: num(1),
    band: bandBy(12, 35),
    primary: true,
  },
  {
    key: "pegRatio",
    label: "PEG",
    plainLabel: "Price vs. earnings, growth-adjusted",
    explanation:
      "The P/E ratio divided by the growth rate. It asks whether a high P/E is justified by how fast profits are growing. Around 1 is often treated as fairly priced.",
    group: "valuation",
    format: num(2),
    band: bandBy(0.8, 2.5),
    primary: true,
  },
  {
    key: "evToEbitda",
    label: "EV/EBITDA",
    plainLabel: "Whole-business value vs. operating profit",
    explanation:
      "Like P/E, but it counts debt too and looks at profit before interest and taxes. Useful for comparing companies that carry very different amounts of debt.",
    group: "valuation",
    format: num(1),
    band: bandBy(8, 25),
    primary: true,
  },
  {
    key: "priceToBook",
    label: "P/B",
    plainLabel: "Price vs. book value",
    explanation:
      "Share price versus the accounting value of the company's net assets. Most meaningful for banks and asset-heavy businesses.",
    group: "valuation",
    format: num(2),
    band: bandBy(1, 6),
  },
  {
    key: "priceToSales",
    label: "P/S",
    plainLabel: "Price vs. sales",
    explanation:
      "Share price versus revenue per share. Handy for companies that aren't profitable yet, since P/E doesn't work without earnings.",
    group: "valuation",
    format: num(2),
    band: bandBy(1, 10),
  },
  {
    key: "dividendYield",
    label: "Dividend Yield",
    plainLabel: "Annual dividend payout",
    explanation:
      "The cash dividend paid over a year as a percentage of the share price. Zero means the company reinvests its profits instead of paying them out.",
    group: "valuation",
    format: percent,
  },

  {
    key: "netProfitMargin",
    label: "Net Margin",
    plainLabel: "Profit kept per sales dollar",
    explanation:
      "Of every $1 of sales, how much is left as profit after all costs, interest and taxes. Higher generally means a more efficient or better-protected business.",
    group: "profitability",
    format: percent,
    band: bandBy(0.03, 0.25),
    primary: true,
  },
  {
    key: "operatingMargin",
    label: "Operating Margin",
    plainLabel: "Profit from core operations",
    explanation:
      "Profit from the main business, before interest and taxes. It isolates how well the actual operation runs.",
    group: "profitability",
    format: percent,
    band: bandBy(0.05, 0.3),
  },
  {
    key: "returnOnEquity",
    label: "ROE",
    plainLabel: "Return on shareholder money",
    explanation:
      "Profit generated per $1 of shareholder equity. High figures can reflect a strong business — or heavy borrowing, so read it alongside Debt/Equity.",
    group: "profitability",
    format: percent,
    band: bandBy(0.08, 0.3),
    primary: true,
  },

  {
    key: "revenueGrowth",
    label: "Revenue Growth",
    plainLabel: "Sales growth (last year)",
    explanation:
      "How much total sales grew versus the prior year. Negative means sales shrank.",
    group: "growth",
    format: percent,
    band: bandBy(0, 0.2),
    primary: true,
  },
  {
    key: "epsGrowth",
    label: "EPS Growth",
    plainLabel: "Profit-per-share growth",
    explanation:
      "How much profit per share grew versus the prior year. This can outpace sales growth if the company cut costs or bought back shares.",
    group: "growth",
    format: percent,
    band: bandBy(0, 0.2),
    primary: true,
  },

  {
    key: "debtToEquity",
    label: "Debt/Equity",
    plainLabel: "Borrowed vs. owners' money",
    explanation:
      "How much debt the company carries for each $1 of shareholder equity. Higher means more leverage, which amplifies both gains and risk.",
    group: "health",
    format: num(2),
    band: bandBy(0.3, 2),
    primary: true,
  },
  {
    key: "currentRatio",
    label: "Current Ratio",
    plainLabel: "Can it cover near-term bills?",
    explanation:
      "Short-term assets divided by short-term obligations. Above 1 means it can cover the next year's bills from assets already on hand.",
    group: "health",
    format: num(2),
    band: bandBy(0.8, 2.5),
    primary: true,
  },
  {
    key: "beta",
    label: "Beta",
    plainLabel: "Volatility vs. the market",
    explanation:
      "How much the share price swings relative to the overall market. 1 moves with the market; above 1 swings harder in both directions.",
    group: "health",
    format: num(2),
    band: bandBy(0.7, 1.4),
  },
];

export const PRIMARY_METRICS = METRICS.filter((m) => m.primary);
