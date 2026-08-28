import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PortfolioSummary } from "./PortfolioSummary";
import { buildPortfolio } from "../positions";
import type { Lot, Quote } from "../types";

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

const quote = (symbol: string, price: number | null, change = 0): Quote => ({
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

describe("the portfolio strip", () => {
  it("stays hidden for someone using the app as a watchlist", () => {
    // A row of zeroes would imply they had missed a setup step.
    const { container } = render(<PortfolioSummary portfolio={buildPortfolio([], [quote("A", 10)])} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("leads with what the holdings are worth", () => {
    render(<PortfolioSummary portfolio={buildPortfolio([lot("A", 10, 100)], [quote("A", 150)])} />);
    expect(screen.getByText("$1,500.00")).toBeInTheDocument();
    expect(screen.getByText("1 position")).toBeInTheDocument();
  });

  it("shows the gain against cost, not against value", () => {
    render(<PortfolioSummary portfolio={buildPortfolio([lot("A", 10, 100)], [quote("A", 150)])} />);
    expect(screen.getByText("+$500.00")).toBeInTheDocument();
    expect(screen.getByText("+50.00%")).toBeInTheDocument();
  });

  it("marks a loss with an arrow as well as a colour", () => {
    // Red against green is the one distinction a colour-blind reader cannot
    // make, and this is the figure they most need.
    const { container } = render(
      <PortfolioSummary portfolio={buildPortfolio([lot("A", 10, 200)], [quote("A", 150)])} />,
    );
    expect(container.querySelector(".tone-down .portfolio-arrow")?.textContent).toBe("▼");
    expect(screen.getByText("−$500.00")).toBeInTheDocument();
  });

  it("hides realised profit until something has been sold", () => {
    render(<PortfolioSummary portfolio={buildPortfolio([lot("A", 10, 100)], [quote("A", 150)])} />);
    expect(screen.queryByText("Realised")).not.toBeInTheDocument();
  });

  it("shows realised profit once a lot has been sold", () => {
    const portfolio = buildPortfolio(
      [lot("A", 10, 100, "2025-01-01"), lot("A", -5, 200, "2025-02-01")],
      [quote("A", 150)],
    );
    render(<PortfolioSummary portfolio={portfolio} />);
    expect(screen.getByText("Realised")).toBeInTheDocument();
    expect(screen.getByText("+$500.00")).toBeInTheDocument();
  });

  it("says when a missing price makes the totals incomplete", () => {
    // Silently omitting an unpriced holding would understate the portfolio
    // and give no clue why.
    const portfolio = buildPortfolio([lot("A", 10, 100), lot("B", 1, 50)], [quote("A", 150)]);
    render(<PortfolioSummary portfolio={portfolio} />);
    expect(screen.getByText(/B has no price right now/)).toBeInTheDocument();
  });
});
