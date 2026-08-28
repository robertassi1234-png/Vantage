import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StockTable } from "./StockTable";
import { METRICS, PRIMARY_METRICS } from "../metrics";
import type { FundamentalsRow } from "../types";

const row = (over: Partial<FundamentalsRow> = {}): FundamentalsRow => ({
  ticker: "AAPL",
  companyName: "Apple Inc.",
  sector: "Technology",
  industry: "Consumer Electronics",
  price: 309.9,
  marketCap: 4_551_611_624_400,
  beta: 1.086,
  peRatio: 35.4,
  pegRatio: 1.08,
  evToEbitda: 27.3,
  priceToBook: 42.3,
  priceToSales: 9.75,
  debtToEquity: 0.78,
  currentRatio: 1.0,
  revenueGrowth: 0.064,
  epsGrowth: 0.226,
  netProfitMargin: 0.276,
  operatingMargin: 0.332,
  returnOnEquity: 1.371,
  dividendYield: 0.0034,
  stale: false,
  fetchedAt: "2026-08-26T03:00:00Z",
  error: null,
  ...over,
});

/** Ticker cells, in rendered order. */
function tickerOrder(): string[] {
  const body = document.querySelector("tbody")!;
  return [...body.querySelectorAll("tr")].map(
    (tr) => tr.querySelector(".ticker-cell")!.textContent!,
  );
}

const clickHeader = (label: string) =>
  userEvent.click(screen.getByRole("columnheader", { name: new RegExp(label) }));

afterEach(() => vi.restoreAllMocks());

describe("StockTable", () => {
  it("invites the user to add a company when empty", () => {
    render(<StockTable rows={[]} onRemove={vi.fn()} />);
    expect(screen.getByText(/No companies yet/i)).toBeInTheDocument();
  });

  /**
   * Headers in the metric row only. The table has two header rows — a group
   * row (Valuation, Profitability, …) above the per-metric row — so counting
   * every `columnheader` on the page double-counts.
   */
  const metricHeaderCount = () =>
    document.querySelectorAll("thead tr:last-child th").length;

  it("shows only the primary metrics by default", () => {
    render(<StockTable rows={[row()]} onRemove={vi.fn()} />);
    // +1 for the ticker column, +1 for the remove-button column.
    expect(metricHeaderCount()).toBe(PRIMARY_METRICS.length + 2);
  });

  it("reveals the full metric set on request", async () => {
    render(<StockTable rows={[row()]} onRemove={vi.fn()} />);
    await userEvent.click(screen.getByText(/Show all \d+ metrics/));
    expect(metricHeaderCount()).toBe(METRICS.length + 2);
  });

  it("groups the metric columns under section headings", () => {
    render(<StockTable rows={[row()]} onRemove={vi.fn()} />);
    const groupRow = document.querySelector("thead tr.group-row")!;
    const labels = [...groupRow.querySelectorAll("th")]
      .map((th) => th.textContent?.trim())
      .filter(Boolean);
    expect(labels).toContain("Valuation");
    expect(labels).toContain("Profitability");
  });

  describe("sorting", () => {
    const rows = [
      row({ ticker: "MSFT", peRatio: 32.1 }),
      row({ ticker: "AAPL", peRatio: 35.4 }),
      row({ ticker: "F", peRatio: 11.2 }),
    ];

    it("sorts by ticker ascending by default", () => {
      render(<StockTable rows={rows} onRemove={vi.fn()} />);
      expect(tickerOrder()).toEqual(["AAPL", "F", "MSFT"]);
    });

    it("sorts numerically, not lexically, on a numeric column", async () => {
      render(<StockTable rows={rows} onRemove={vi.fn()} />);
      await clickHeader("P/E");
      // Lexical order would put 11.2 after 32.1 as strings.
      expect(tickerOrder()).toEqual(["F", "MSFT", "AAPL"]);
    });

    it("reverses direction when the same header is clicked twice", async () => {
      render(<StockTable rows={rows} onRemove={vi.fn()} />);
      await clickHeader("P/E");
      await clickHeader("P/E");
      expect(tickerOrder()).toEqual(["AAPL", "MSFT", "F"]);
    });

    it("starts a newly chosen column ascending", async () => {
      render(<StockTable rows={rows} onRemove={vi.fn()} />);
      await clickHeader("P/E");
      await clickHeader("P/E"); // now descending
      await clickHeader("Market Cap"); // switching column resets direction
      const marketCaps = rows.map((r) => r.marketCap!);
      expect(marketCaps.every((v) => v === marketCaps[0])).toBe(true);
    });

    it("keeps missing values last in both directions", async () => {
      const withGaps = [
        row({ ticker: "AAA", peRatio: 20 }),
        row({ ticker: "BBB", peRatio: null }),
        row({ ticker: "CCC", peRatio: 10 }),
      ];
      render(<StockTable rows={withGaps} onRemove={vi.fn()} />);

      await clickHeader("P/E");
      expect(tickerOrder()).toEqual(["CCC", "AAA", "BBB"]);

      // A blank is not "smaller than everything"; it stays out of the ranking.
      await clickHeader("P/E");
      expect(tickerOrder()).toEqual(["AAA", "CCC", "BBB"]);
    });

    it("does not mutate the rows prop while sorting", async () => {
      const original = [row({ ticker: "MSFT" }), row({ ticker: "AAPL" })];
      const snapshot = original.map((r) => r.ticker);
      render(<StockTable rows={original} onRemove={vi.fn()} />);
      await clickHeader("P/E");
      expect(original.map((r) => r.ticker)).toEqual(snapshot);
    });
  });

  describe("row state", () => {
    it("dims a stale row", () => {
      render(<StockTable rows={[row({ stale: true })]} onRemove={vi.fn()} />);
      expect(document.querySelector("tbody tr")).toHaveClass("row-stale");
    });

    it("surfaces a per-row error message", () => {
      render(
        <StockTable rows={[row({ error: "FMP API key is missing or invalid" })]} onRemove={vi.fn()} />,
      );
      expect(screen.getByText(/FMP API key is missing or invalid/)).toBeInTheDocument();
    });

    it("collapses one shared problem into a single line", () => {
      // A rate limit makes every row report the same sentence. Six identical
      // red lines under a table full of numbers reads as total failure.
      const limited = "Market data is rate limited across every provider right now.";
      render(
        <StockTable
          rows={[
            row({ ticker: "AAPL", error: limited }),
            row({ ticker: "MSFT", error: limited }),
            row({ ticker: "AMZN", error: limited }),
          ]}
          onRemove={vi.fn()}
        />,
      );

      expect(screen.getAllByText(new RegExp(limited.slice(0, 30)))).toHaveLength(1);
      expect(screen.getByText("AAPL, MSFT, AMZN")).toBeInTheDocument();
    });

    it("keeps a different problem in its own words", () => {
      // Collapsing must not hide an actionable failure behind a general one.
      render(
        <StockTable
          rows={[
            row({ ticker: "AAPL", error: "Market data is rate limited right now." }),
            row({ ticker: "CRWV", error: "No data found for ticker 'CRWV'." }),
          ]}
          onRemove={vi.fn()}
        />,
      );

      expect(screen.getByText(/rate limited/)).toBeInTheDocument();
      expect(screen.getByText(/No data found/)).toBeInTheDocument();
    });

    it("says saved figures are shown when the numbers survived", () => {
      const { container } = render(
        <StockTable rows={[row({ error: "Rate limited." })]} onRemove={vi.fn()} />,
      );

      expect(container.querySelector(".note-stale")).not.toBeNull();
      expect(screen.getByText(/Saved figures are shown above/)).toBeInTheDocument();
    });

    it("marks a row with nothing at all as an error, not stale data", () => {
      const { container } = render(
        <StockTable
          rows={[{ ticker: "CRWV", error: "No data found." } as never]}
          onRemove={vi.fn()}
        />,
      );

      expect(container.querySelector(".note-error")).not.toBeNull();
    });

    it("renders missing metrics as a dash, never NaN", () => {
      render(
        <StockTable
          rows={[row({ peRatio: null, marketCap: null, revenueGrowth: null })]}
          onRemove={vi.fn()}
        />,
      );
      const body = within(document.querySelector("tbody")!);
      expect(body.queryByText(/NaN/)).toBeNull();
      expect(body.getAllByText("—").length).toBeGreaterThan(0);
    });
  });

  it("removes the row the button belongs to", async () => {
    const onRemove = vi.fn();
    render(<StockTable rows={[row({ ticker: "AAPL" })]} onRemove={onRemove} />);
    await userEvent.click(screen.getByLabelText("Remove AAPL"));
    expect(onRemove).toHaveBeenCalledWith("AAPL");
  });

  describe("glossary", () => {
    it("stays collapsed until asked for", () => {
      render(<StockTable rows={[row()]} onRemove={vi.fn()} />);
      expect(screen.queryByText(/not a buy or sell signal/i)).toBeNull();
    });

    it("explains that shading is not advice", async () => {
      render(<StockTable rows={[row()]} onRemove={vi.fn()} />);
      await userEvent.click(screen.getByText(/What do these numbers mean\?/));
      expect(screen.getByText(/buy or sell signal/i)).toBeInTheDocument();
    });
  });
});
