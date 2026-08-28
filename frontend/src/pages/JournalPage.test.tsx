import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JournalPage } from "./JournalPage";
import { api } from "../api";
import type { JournalEntry, Quote } from "../types";

const entry = (over: Partial<JournalEntry> = {}): JournalEntry => ({
  id: "e1",
  ticker: "AAPL",
  body: "Services margin keeps expanding.",
  priceAtWrite: 142.3,
  dateWritten: "2025-03-04T00:00:00+00:00",
  tags: [],
  reviewedAt: null,
  ...over,
});

const quote = (symbol: string, price: number): Quote => ({
  symbol,
  name: `${symbol} Inc.`,
  price,
  change: null,
  changePercent: null,
  dayLow: null,
  dayHigh: null,
  yearLow: null,
  yearHigh: null,
  marketCap: null,
  volume: null,
});

function stub(entries: JournalEntry[], reviewDue: string[] = [], quotes: Quote[] = []) {
  vi.spyOn(api, "getJournal").mockResolvedValue({
    entries,
    review_due: reviewDue,
    suggested_tags: ["thesis", "risk", "catalyst", "mistake"],
    review_after_days: 90,
  });
  vi.spyOn(api, "getQuotes").mockResolvedValue(quotes);
  vi.spyOn(api, "searchSymbols").mockResolvedValue([]);
}

afterEach(() => vi.restoreAllMocks());

describe("the journal", () => {
  it("grades each entry against the price today", async () => {
    stub([entry()], [], [quote("AAPL", 189.44)]);
    render(<JournalPage />);
    expect(await screen.findByText(/\+33\.1%/)).toBeInTheDocument();
  });

  it("invites a first entry rather than showing an empty list", async () => {
    stub([]);
    render(<JournalPage />);
    expect(await screen.findByText("Nothing written yet")).toBeInTheDocument();
  });

  it("nudges about old entries without listing them all over again", async () => {
    // An entry is most useful exactly when it has stopped being read -- but
    // a separate section for the due ones put each of them on the page twice,
    // each with its own set of buttons.
    stub([entry({ id: "old" }), entry({ id: "new", ticker: "MSFT" })], ["old"]);
    render(<JournalPage />);

    expect(await screen.findByText(/1 entry has gone over 90 days/)).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("narrows to just the old ones on request", async () => {
    stub([entry({ id: "old" }), entry({ id: "new", ticker: "MSFT" })], ["old"]);
    render(<JournalPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Show me" }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.queryByText("MSFT")).not.toBeInTheDocument();
  });

  it("says nothing about review when nothing is due", async () => {
    stub([entry()]);
    render(<JournalPage />);
    await screen.findByText(/Everything you/);
    expect(screen.queryByText(/gone over 90 days/)).not.toBeInTheDocument();
  });

  it("narrows to a tag when one is picked", async () => {
    stub([
      entry({ id: "a", tags: ["risk"] }),
      entry({ id: "b", ticker: "MSFT", tags: ["thesis"] }),
    ]);
    render(<JournalPage />);

    await screen.findByRole("button", { name: /^risk/ });
    await userEvent.click(screen.getByRole("button", { name: /^risk/ }));

    expect(screen.getByText("Tagged risk")).toBeInTheDocument();
    expect(screen.queryByText("MSFT")).not.toBeInTheDocument();
  });

  it("says the filter is what is hiding things, not an empty journal", async () => {
    stub([entry({ id: "a", tags: ["risk"] }), entry({ id: "b", tags: ["catalyst"] })]);
    render(<JournalPage />);

    await screen.findByRole("button", { name: /^risk/ });
    await userEvent.click(screen.getByRole("button", { name: /^risk/ }));
    await userEvent.click(screen.getByRole("button", { name: /^catalyst/ }));

    expect(screen.getByText("Nothing with those tags")).toBeInTheDocument();
  });

  it("marking an entry reviewed clears the nudge", async () => {
    stub([entry({ id: "old" })], ["old"]);
    const marked = vi.spyOn(api, "markJournalReviewed").mockResolvedValue({
      entries: [entry({ id: "old", reviewedAt: "2026-08-28T00:00:00Z" })],
      review_due: [],
      suggested_tags: [],
      review_after_days: 90,
    });

    render(<JournalPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Mark reviewed" }));

    expect(marked).toHaveBeenCalledWith("old");
    expect(screen.queryByText("Worth revisiting")).not.toBeInTheDocument();
  });

  it("keeps the journal readable when prices cannot be fetched", async () => {
    // Losing the scores is survivable; losing the writing is not.
    stub([entry()]);
    vi.spyOn(api, "getQuotes").mockRejectedValue(new Error("rate limited"));

    render(<JournalPage />);
    expect(await screen.findByText("Services margin keeps expanding.")).toBeInTheDocument();
  });
});
