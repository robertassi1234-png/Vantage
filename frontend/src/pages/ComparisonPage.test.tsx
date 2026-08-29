import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ComparisonPage } from "./ComparisonPage";
import { api } from "../api";
import type { FundamentalsRow } from "../types";

const row = (ticker: string): FundamentalsRow => ({
  ticker,
  companyName: `${ticker} Inc.`,
  sector: "Technology",
  industry: "Software",
  price: 100,
  marketCap: 1e12,
  beta: 1,
  peRatio: 30,
  pegRatio: 2,
  evToEbitda: 20,
  priceToBook: 10,
  priceToSales: 8,
  debtToEquity: 1,
  currentRatio: 1,
  revenueGrowth: 0.1,
  epsGrowth: 0.1,
  netProfitMargin: 0.25,
  operatingMargin: 0.3,
  returnOnEquity: 1.2,
  dividendYield: 0.005,
  stale: false,
  fetchedAt: null,
  error: null,
});

function stub(over: Record<string, unknown> = {}) {
  vi.spyOn(api, "getFundamentals").mockResolvedValue([row("AAPL")]);
  vi.spyOn(api, "getHistory").mockResolvedValue({ symbol: "AAPL", range: "1Y", points: [] });
  vi.spyOn(api, "getPeers").mockResolvedValue({ suggestions: [], based_on: [], error: null });
  vi.spyOn(api, "getValuation").mockResolvedValue({ companies: [], metrics: [], peerMedian: {} });
  vi.spyOn(api, "searchSymbols").mockResolvedValue([]);
  vi.spyOn(api, "getProviderStatus").mockResolvedValue({
    providers: [],
    order: [],
    fundamentals_order: [],
    healthy: 0,
  });
  for (const [key, value] of Object.entries(over)) {
    vi.spyOn(api, key as keyof typeof api).mockImplementation(value as never);
  }
}

afterEach(() => vi.restoreAllMocks());

describe("the comparison page", () => {
  it("keeps the fundamentals when peer suggestions come back malformed", async () => {
    // A response missing its suggestions list reached `peers.length` as
    // undefined and took the whole page down -- losing the table over a
    // sidebar of nice-to-haves.
    stub({ getPeers: async () => ({}) });
    render(<ComparisonPage />);
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
  });

  it("keeps the fundamentals when the valuation table cannot load", async () => {
    stub({
      getValuation: async () => {
        throw new Error("rate limited");
      },
    });
    render(<ComparisonPage />);
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("rate limited")).toBeInTheDocument();
  });

  it("shows the valuation section once there is something to value", async () => {
    stub();
    render(<ComparisonPage />);
    expect(await screen.findByText("Valuation in context")).toBeInTheDocument();
  });
});
