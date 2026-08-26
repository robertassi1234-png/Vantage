import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WatchlistPanel } from "./WatchlistPanel";
import type { Quote } from "../types";

const quote = (over: Partial<Quote> = {}): Quote => ({
  symbol: "AAPL",
  name: "Apple Inc.",
  price: 300,
  change: 2,
  changePercent: 0.67,
  dayLow: null,
  dayHigh: null,
  yearLow: 200,
  yearHigh: 400,
  marketCap: null,
  volume: null,
  ...over,
});

const markerLeft = (container: HTMLElement) =>
  (container.querySelector(".range-marker") as HTMLElement | null)?.style.left;

describe("WatchlistPanel", () => {
  it("prompts to add something when empty", () => {
    render(<WatchlistPanel quotes={[]} onSelect={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText(/watchlist is empty/i)).toBeInTheDocument();
  });

  it("shows price and percent change", () => {
    render(<WatchlistPanel quotes={[quote()]} onSelect={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText("$300.00")).toBeInTheDocument();
    expect(screen.getByText(/\+0\.67%/)).toBeInTheDocument();
  });

  it("signs a negative move and tones the row down", () => {
    const { container } = render(
      <WatchlistPanel
        quotes={[quote({ change: -3.18, changePercent: -0.62 })]}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.getByText(/-3\.18/)).toBeInTheDocument();
    expect(container.querySelector(".watch-row")).toHaveClass("tone-down");
  });

  describe("52-week range marker", () => {
    it("sits halfway when the price is midway", () => {
      const { container } = render(
        <WatchlistPanel
          quotes={[quote({ price: 300, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />,
      );
      expect(markerLeft(container)).toBe("50%");
    });

    it("pins to each end at the low and the high", () => {
      const low = render(
        <WatchlistPanel
          quotes={[quote({ price: 200, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />,
      );
      expect(markerLeft(low.container)).toBe("0%");

      const high = render(
        <WatchlistPanel
          quotes={[quote({ price: 400, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />,
      );
      expect(markerLeft(high.container)).toBe("100%");
    });

    it("clamps a price that has broken out of its 52-week range", () => {
      // Intraday highs can exceed a stale yearHigh; the marker must not escape.
      const { container } = render(
        <WatchlistPanel
          quotes={[quote({ price: 500, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />,
      );
      expect(markerLeft(container)).toBe("100%");
    });

    it("is omitted when the range data is missing", () => {
      const { container } = render(
        <WatchlistPanel
          quotes={[quote({ yearLow: null, yearHigh: null })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />,
      );
      expect(container.querySelector(".range-marker")).toBeNull();
    });

    it("is omitted rather than dividing by zero on a zero-width range", () => {
      const { container } = render(
        <WatchlistPanel
          quotes={[quote({ price: 200, yearLow: 200, yearHigh: 200 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()}
        />,
      );
      expect(container.querySelector(".range-marker")).toBeNull();
    });
  });

  describe("interaction", () => {
    it("selects the symbol when the row is clicked", async () => {
      const onSelect = vi.fn();
      render(<WatchlistPanel quotes={[quote()]} onSelect={onSelect} onRemove={vi.fn()} />);

      await userEvent.click(screen.getByText("Apple Inc."));
      expect(onSelect).toHaveBeenCalledWith("AAPL", "Apple Inc.");
    });

    it("removes without also triggering selection", async () => {
      const onSelect = vi.fn();
      const onRemove = vi.fn();
      render(<WatchlistPanel quotes={[quote()]} onSelect={onSelect} onRemove={onRemove} />);

      await userEvent.click(screen.getByLabelText("Remove AAPL"));
      expect(onRemove).toHaveBeenCalledWith("AAPL");
      expect(onSelect).not.toHaveBeenCalled();
    });

    it("falls back to the symbol when the company name is missing", async () => {
      const onSelect = vi.fn();
      render(
        <WatchlistPanel quotes={[quote({ name: null })]} onSelect={onSelect} onRemove={vi.fn()} />,
      );

      await userEvent.click(screen.getByText("AAPL"));
      expect(onSelect).toHaveBeenCalledWith("AAPL", "AAPL");
    });
  });

  it("renders missing prices as a dash rather than NaN", () => {
    render(
      <WatchlistPanel
        quotes={[quote({ price: null, change: null, changePercent: null })]}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});
