import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ValuationTable } from "./ValuationTable";
import type { MetricStat, ValuationCompany, ValuationMetricDef } from "../types";

const METRICS: ValuationMetricDef[] = [
  { key: "peRatio", label: "P/E (trailing)", better: null, percent: false },
  { key: "grossMargin", label: "Gross margin", better: "high", percent: true },
  { key: "shareChange", label: "Share count change (YoY)", better: "low", percent: true },
];

const stat = (over: Partial<MetricStat> = {}): MetricStat => ({
  value: 30,
  median: 24,
  low: 18,
  high: 34,
  percentile: 0.9,
  samples: 20,
  ...over,
});

const company = (
  ticker: string,
  metrics: Record<string, MetricStat>,
  over: Partial<ValuationCompany> = {},
): ValuationCompany => ({
  ticker,
  companyName: `${ticker} Inc.`,
  sector: "Technology",
  price: 100,
  metrics,
  stale: false,
  error: null,
  ...over,
});

const show = (companies: ValuationCompany[], peerMedian: Record<string, number | null> = {}) =>
  render(<ValuationTable companies={companies} metrics={METRICS} peerMedian={peerMedian} />);

const row = (label: string) => screen.getByRole("row", { name: new RegExp(label) });

describe("the valuation table", () => {
  it("invites a company rather than showing an empty grid", () => {
    show([]);
    expect(screen.getByText("Nothing to value yet")).toBeInTheDocument();
  });

  it("puts companies across and metrics down", () => {
    show([company("AAPL", { peRatio: stat() }), company("MSFT", { peRatio: stat({ value: 40 }) })]);
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers[1]).toContain("AAPL");
    expect(headers[2]).toContain("MSFT");
    expect(screen.getByText("P/E (trailing)")).toBeInTheDocument();
  });

  it("shows today's figure and where it sits in the company's own range", () => {
    // The whole point: 30 means nothing until you know this company usually
    // trades at 24.
    const { container } = show([company("AAPL", { peRatio: stat({ value: 30, median: 24 }) })]);
    expect(screen.getByText("30.0")).toBeInTheDocument();
    expect(container.querySelector(".valuation-marker")).not.toBeNull();
    expect(screen.getByText(/Near its five-year high — typically 24.0/)).toBeInTheDocument();
  });

  it("draws no range for a company with only a quarter or two of history", () => {
    // A bar over two observations implies a five-year record that isn't
    // there.
    const { container } = show([company("AAPL", { peRatio: stat({ samples: 2 }) })]);
    expect(container.querySelector(".valuation-marker")).toBeNull();
    expect(screen.getByText("no five-year history")).toBeInTheDocument();
  });

  it("marks the best margin with a symbol as well as a tint", () => {
    show([
      company("AAPL", { grossMargin: stat({ value: 0.46 }) }),
      company("MSFT", { grossMargin: stat({ value: 0.69 }) }),
    ]);
    const cells = within(row("Gross margin")).getAllByRole("cell");
    expect(cells[1]).toHaveClass("leading");
    expect(within(cells[1]).getByLabelText("best of these")).toBeInTheDocument();
    expect(cells[0]).not.toHaveClass("leading");
  });

  it("marks no winner on a valuation multiple", () => {
    // The lowest P/E in a group is as often the most troubled company as the
    // best value.
    show([
      company("AAPL", { peRatio: stat({ value: 12 }) }),
      company("MSFT", { peRatio: stat({ value: 40 }) }),
    ]);
    expect(within(row("P/E")).queryByLabelText("best of these")).not.toBeInTheDocument();
  });

  it("says which way is better where there is a right answer", () => {
    show([company("AAPL", { grossMargin: stat({ value: 0.46 }) })]);
    expect(screen.getByText("higher is better")).toBeInTheDocument();
    expect(screen.getByText("lower is better")).toBeInTheDocument();
  });

  it("gives every number the middle of the group to sit against", () => {
    show(
      [company("AAPL", { peRatio: stat({ value: 30 }) }), company("MSFT", { peRatio: stat({ value: 40 }) })],
      { peRatio: 35 },
    );
    const cells = within(row("P/E")).getAllByRole("cell");
    expect(cells.at(-1)).toHaveTextContent("35.0");
    // Said explicitly, so it is not mistaken for an industry figure.
    expect(screen.getByText("of these 2")).toBeInTheDocument();
  });

  it("gives the provider's own reason, not a shrug", () => {
    // "Couldn't be valued right now" hid the one thing the reader can act on.
    // A spent allowance, a key never set, and an endpoint outside the plan
    // all read identically otherwise.
    show([
      company("AAPL", { peRatio: stat() }),
      company("MSFT", {}, { error: "FMP rate limit reached (free tier: 250 calls/day)" }),
    ]);
    const notice = screen.getByText(/250 calls\/day/);
    // Named, so a reader with several companies knows which one failed.
    expect(notice).toHaveTextContent("MSFT");
  });

  it("explains a day-old figure rather than presenting it as live", () => {
    show([company("AAPL", { peRatio: stat() }, { stale: true })]);
    expect(screen.getByText(/Showing yesterday’s figures for AAPL/)).toBeInTheDocument();
  });

  it("shows a dash where a company never reported a metric", () => {
    show([company("AAPL", { peRatio: stat() })]);
    const cells = within(row("Gross margin")).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("—");
  });
});
