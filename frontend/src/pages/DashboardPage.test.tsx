import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { ApiError, api } from "../api";
import type { Quote } from "../types";

const quote = (symbol: string, price = 300): Quote => ({
  symbol,
  name: `${symbol} Inc.`,
  price,
  change: 1,
  changePercent: 0.3,
  dayLow: null,
  dayHigh: null,
  yearLow: 200,
  yearHigh: 400,
  marketCap: null,
  volume: null,
});

/** Wire up the whole api surface so only the behaviour under test varies. */
function stubApi(over: Partial<typeof api> = {}) {
  vi.spyOn(api, "getList").mockResolvedValue([]);
  vi.spyOn(api, "getIndices").mockResolvedValue([]);
  vi.spyOn(api, "getQuotes").mockResolvedValue([]);
  vi.spyOn(api, "checkAlerts").mockResolvedValue({
    fired: [],
    alerts: [],
    checked: 0,
    error: null,
  });
  vi.spyOn(api, "getHistory").mockResolvedValue({ symbol: "X", range: "1Y", points: [] });
  vi.spyOn(api, "addToList").mockResolvedValue([]);
  vi.spyOn(api, "removeFromList").mockResolvedValue([]);
  vi.spyOn(api, "searchSymbols").mockResolvedValue([
    { symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", currency: "USD" },
  ]);
  for (const [key, value] of Object.entries(over)) {
    vi.spyOn(api, key as keyof typeof api).mockImplementation(value as never);
  }
}

/** Scoped to the watchlist: a ticker also appears in the chart heading. */
const watchlistRow = (symbol: string) =>
  within(document.querySelector(".watchlist") as HTMLElement).getByText(symbol);

afterEach(() => vi.restoreAllMocks());

describe("DashboardPage watchlist", () => {
  it("shows a ticker that has no quote yet", async () => {
    // The bug this guards: the panel rendered from the quote list, so a
    // failed or empty price lookup made a populated watchlist look empty --
    // indistinguishable from having added nothing at all.
    stubApi();
    vi.spyOn(api, "getList").mockResolvedValue(["AAPL"]);
    vi.spyOn(api, "getQuotes").mockResolvedValue([]);

    render(<DashboardPage />);

    await waitFor(() => expect(document.querySelector(".watchlist")).not.toBeNull());
    expect(watchlistRow("AAPL")).toBeInTheDocument();
    expect(screen.queryByText(/watchlist is empty/i)).toBeNull();
  });

  it("still lists tickers when the quote request fails outright", async () => {
    stubApi();
    vi.spyOn(api, "getList").mockResolvedValue(["AAPL", "MSFT"]);
    vi.spyOn(api, "getQuotes").mockRejectedValue(new ApiError("rate limited"));

    render(<DashboardPage />);

    await waitFor(() => expect(document.querySelector(".watchlist")).not.toBeNull());
    expect(watchlistRow("AAPL")).toBeInTheDocument();
    expect(watchlistRow("MSFT")).toBeInTheDocument();
  });

  it("shows prices once they arrive", async () => {
    stubApi();
    vi.spyOn(api, "getList").mockResolvedValue(["AAPL"]);
    vi.spyOn(api, "getQuotes").mockResolvedValue([quote("AAPL", 309.9)]);

    render(<DashboardPage />);
    expect(await screen.findByText("$309.90")).toBeInTheDocument();
  });

  it("only claims the watchlist is empty when it really is", async () => {
    stubApi();
    render(<DashboardPage />);
    expect(await screen.findByText(/watchlist is empty/i)).toBeInTheDocument();
  });

  it("adds a ticker picked from the search suggestions", async () => {
    stubApi();
    const added: string[] = [];
    vi.spyOn(api, "addToList").mockImplementation(async (_list, ticker) => {
      added.push(ticker);
      return added;
    });
    vi.spyOn(api, "getList").mockImplementation(async () => added);

    render(<DashboardPage />);
    await screen.findByText(/watchlist is empty/i);

    await userEvent.type(screen.getByLabelText("Search for a company or ticker"), "apple");
    await userEvent.click(await screen.findByText("Apple Inc."));

    await waitFor(() => expect(added).toEqual(["AAPL"]));
    await waitFor(() => expect(watchlistRow("AAPL")).toBeInTheDocument());
  });

  it("keeps the ticker visible even if pricing it fails after adding", async () => {
    stubApi();
    const added: string[] = [];
    vi.spyOn(api, "addToList").mockImplementation(async (_list, ticker) => {
      added.push(ticker);
      return added;
    });
    vi.spyOn(api, "getList").mockImplementation(async () => added);
    vi.spyOn(api, "getQuotes").mockRejectedValue(new ApiError("upstream down"));

    render(<DashboardPage />);
    await screen.findByText(/watchlist is empty/i);

    await userEvent.type(screen.getByLabelText("Search for a company or ticker"), "apple");
    await userEvent.click(await screen.findByText("Apple Inc."));

    // Adding worked; only the price lookup failed. The row must still appear,
    // or the click looks like it did nothing.
    await waitFor(() => expect(watchlistRow("AAPL")).toBeInTheDocument());
  });
});
