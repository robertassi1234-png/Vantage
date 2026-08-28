import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JournalEntryCard } from "./JournalEntryCard";
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

const quote = (price: number | null): Quote => ({
  symbol: "AAPL",
  name: "Apple Inc.",
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

function show(over: Partial<React.ComponentProps<typeof JournalEntryCard>> = {}) {
  return render(
    <JournalEntryCard
      entry={entry()}
      quote={quote(189.44)}
      reviewDue={false}
      reviewAfterDays={90}
      onDelete={() => {}}
      onMarkReviewed={() => {}}
      {...over}
    />,
  );
}

describe("an entry, graded", () => {
  it("shows the price then, the price now, and the move between them", () => {
    // The line that makes this a feedback loop rather than a notes app.
    show();
    expect(screen.getByText(/Written at \$142\.30/)).toBeInTheDocument();
    expect(screen.getByText(/now \$189\.44/)).toBeInTheDocument();
    expect(screen.getByText(/\+33\.1%/)).toBeInTheDocument();
  });

  it("marks a thesis that went the other way with an arrow, not just red", () => {
    const { container } = show({ entry: entry({ priceAtWrite: 200 }), quote: quote(150) });
    expect(container.querySelector(".journal-verdict")).toHaveClass("tone-down");
    expect(screen.getByText(/▼/)).toBeInTheDocument();
    expect(screen.getByText(/−25\.0%/)).toBeInTheDocument();
  });

  it("says plainly when an entry has no price to score against", () => {
    // A bare dash would read as a rendering fault rather than a gap in the
    // record.
    show({ entry: entry({ priceAtWrite: null }) });
    expect(screen.getByText(/No price was recorded when this was written/)).toBeInTheDocument();
  });

  it("keeps the entry readable when today's price is missing", () => {
    show({ quote: undefined });
    expect(screen.getByText(/Written at \$142\.30/)).toBeInTheDocument();
    expect(screen.getByText(/price unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Services margin keeps expanding.")).toBeInTheDocument();
  });

  it("shows its tags", () => {
    show({ entry: entry({ tags: ["thesis", "catalyst"] }) });
    expect(screen.getByText("thesis")).toBeInTheDocument();
    expect(screen.getByText("catalyst")).toBeInTheDocument();
  });
});

describe("an entry due for review", () => {
  it("says why it is being surfaced", () => {
    show({ reviewDue: true });
    expect(screen.getByText(/Over 90 days old and never revisited/)).toBeInTheDocument();
  });

  it("offers a follow-up and a way to dismiss it", async () => {
    const onFollowUp = vi.fn();
    const onMarkReviewed = vi.fn();
    show({ reviewDue: true, onFollowUp, onMarkReviewed });

    await userEvent.click(screen.getByRole("button", { name: "Write a follow-up" }));
    expect(onFollowUp).toHaveBeenCalledWith("AAPL");

    await userEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
    expect(onMarkReviewed).toHaveBeenCalledWith("e1");
  });

  it("offers neither on an entry that is not due", () => {
    show({ reviewDue: false, onFollowUp: vi.fn() });
    expect(screen.queryByRole("button", { name: "Mark reviewed" })).not.toBeInTheDocument();
  });
});
