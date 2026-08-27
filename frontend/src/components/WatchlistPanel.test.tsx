import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WatchlistPanel } from "./WatchlistPanel";
import type { Quote, WatchlistEntry } from "../types";

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

/** Watchlist entries from a list of tickers, for the cases notes don't matter to. */
const entries = (...tickers: string[]): WatchlistEntry[] =>
  tickers.map((ticker) => ({ ticker, added_at: "2026-01-01T00:00:00+00:00", note: null }));

const markerLeft = (container: HTMLElement) =>
  (container.querySelector(".range-marker") as HTMLElement | null)?.style.left;

describe("WatchlistPanel", () => {
  it("prompts to add something when empty", () => {
    render(<WatchlistPanel entries={[]} quotes={[]} onSelect={vi.fn()} onRemove={vi.fn()} onSaveNote={vi.fn()} />);
    expect(screen.getByText(/watchlist is empty/i)).toBeInTheDocument();
  });

  it("shows price and percent change", () => {
    render(<WatchlistPanel entries={entries("AAPL")} quotes={[quote()]} onSelect={vi.fn()} onRemove={vi.fn()} onSaveNote={vi.fn()} />);
    expect(screen.getByText("$300.00")).toBeInTheDocument();
    expect(screen.getByText(/\+0\.67%/)).toBeInTheDocument();
  });

  it("signs a negative move and tones the row down", () => {
    const { container } = render(
      <WatchlistPanel
        entries={entries("AAPL")} quotes={[quote({ change: -3.18, changePercent: -0.62 })]}
        onSelect={vi.fn()}
        onRemove={vi.fn()} onSaveNote={vi.fn()}
      />,
    );
    expect(screen.getByText(/-3\.18/)).toBeInTheDocument();
    expect(container.querySelector(".watch-row")).toHaveClass("tone-down");
  });

  describe("52-week range marker", () => {
    it("sits halfway when the price is midway", () => {
      const { container } = render(
        <WatchlistPanel
          entries={entries("AAPL")} quotes={[quote({ price: 300, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()} onSaveNote={vi.fn()}
        />,
      );
      expect(markerLeft(container)).toBe("50%");
    });

    it("pins to each end at the low and the high", () => {
      const low = render(
        <WatchlistPanel
          entries={entries("AAPL")} quotes={[quote({ price: 200, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()} onSaveNote={vi.fn()}
        />,
      );
      expect(markerLeft(low.container)).toBe("0%");

      const high = render(
        <WatchlistPanel
          entries={entries("AAPL")} quotes={[quote({ price: 400, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()} onSaveNote={vi.fn()}
        />,
      );
      expect(markerLeft(high.container)).toBe("100%");
    });

    it("clamps a price that has broken out of its 52-week range", () => {
      // Intraday highs can exceed a stale yearHigh; the marker must not escape.
      const { container } = render(
        <WatchlistPanel
          entries={entries("AAPL")} quotes={[quote({ price: 500, yearLow: 200, yearHigh: 400 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()} onSaveNote={vi.fn()}
        />,
      );
      expect(markerLeft(container)).toBe("100%");
    });

    it("is omitted when the range data is missing", () => {
      const { container } = render(
        <WatchlistPanel
          entries={entries("AAPL")} quotes={[quote({ yearLow: null, yearHigh: null })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()} onSaveNote={vi.fn()}
        />,
      );
      expect(container.querySelector(".range-marker")).toBeNull();
    });

    it("is omitted rather than dividing by zero on a zero-width range", () => {
      const { container } = render(
        <WatchlistPanel
          entries={entries("AAPL")} quotes={[quote({ price: 200, yearLow: 200, yearHigh: 200 })]}
          onSelect={vi.fn()}
          onRemove={vi.fn()} onSaveNote={vi.fn()}
        />,
      );
      expect(container.querySelector(".range-marker")).toBeNull();
    });
  });

  describe("interaction", () => {
    it("selects the symbol when the row is clicked", async () => {
      const onSelect = vi.fn();
      render(<WatchlistPanel entries={entries("AAPL")} quotes={[quote()]} onSelect={onSelect} onRemove={vi.fn()} onSaveNote={vi.fn()} />);

      await userEvent.click(screen.getByText("Apple Inc."));
      expect(onSelect).toHaveBeenCalledWith("AAPL", "Apple Inc.");
    });

    it("removes without also triggering selection", async () => {
      const onSelect = vi.fn();
      const onRemove = vi.fn();
      render(<WatchlistPanel entries={entries("AAPL")} quotes={[quote()]} onSelect={onSelect} onRemove={onRemove} onSaveNote={vi.fn()} />);

      await userEvent.click(screen.getByLabelText("Remove AAPL"));
      expect(onRemove).toHaveBeenCalledWith("AAPL");
      expect(onSelect).not.toHaveBeenCalled();
    });

    it("falls back to the symbol when the company name is missing", async () => {
      const onSelect = vi.fn();
      render(
        <WatchlistPanel entries={entries("AAPL")} quotes={[quote({ name: null })]} onSelect={onSelect} onRemove={vi.fn()} onSaveNote={vi.fn()} />,
      );

      await userEvent.click(screen.getByText("AAPL"));
      expect(onSelect).toHaveBeenCalledWith("AAPL", "AAPL");
    });
  });

  it("renders missing prices as a dash rather than NaN", () => {
    render(
      <WatchlistPanel
        entries={entries("AAPL")} quotes={[quote({ price: null, change: null, changePercent: null })]}
        onSelect={vi.fn()}
        onRemove={vi.fn()} onSaveNote={vi.fn()}
      />,
    );
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});

describe("notes", () => {
  const withNote = (note: string | null): WatchlistEntry[] => [
    { ticker: "AAPL", added_at: "2026-01-01T00:00:00+00:00", note },
  ];

  const renderPanel = (entryList: WatchlistEntry[], onSaveNote = vi.fn()) =>
    render(
      <WatchlistPanel
        entries={entryList}
        quotes={[quote()]}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
        onSaveNote={onSaveNote}
      />,
    );

  it("shows an existing note under the row", () => {
    renderPanel(withNote("Waiting for a dip below 250"));
    expect(screen.getByText("Waiting for a dip below 250")).toBeInTheDocument();
  });

  it("shows nothing extra when there is no note", () => {
    const { container } = renderPanel(withNote(null));
    expect(container.querySelector(".watch-note")).toBeNull();
  });

  it("opens an editor prefilled with the current note", async () => {
    const user = userEvent.setup();
    renderPanel(withNote("existing thoughts"));

    await user.click(screen.getByRole("button", { name: /edit your note on AAPL/i }));
    expect(screen.getByRole("textbox")).toHaveValue("existing thoughts");
  });

  it("saves what was typed", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote(null), onSaveNote);

    await user.click(screen.getByRole("button", { name: /add a note on AAPL/i }));
    await user.type(screen.getByRole("textbox"), "cheap on earnings");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSaveNote).toHaveBeenCalledWith("AAPL", "cheap on earnings");
  });

  it("trims whitespace rather than saving a blank-looking note", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote(null), onSaveNote);

    await user.click(screen.getByRole("button", { name: /add a note on AAPL/i }));
    await user.type(screen.getByRole("textbox"), "   spaced   ");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSaveNote).toHaveBeenCalledWith("AAPL", "spaced");
  });

  it("clearing the box and saving removes the note", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote("no longer true"), onSaveNote);

    await user.click(screen.getByRole("button", { name: /edit your note on AAPL/i }));
    await user.clear(screen.getByRole("textbox"));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSaveNote).toHaveBeenCalledWith("AAPL", "");
  });

  it("cancel discards the edit", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote("keep me"), onSaveNote);

    await user.click(screen.getByRole("button", { name: /edit your note on AAPL/i }));
    await user.type(screen.getByRole("textbox"), " and more");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onSaveNote).not.toHaveBeenCalled();
    expect(screen.getByText("keep me")).toBeInTheDocument();
  });

  it("Escape cancels too", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote("keep me"), onSaveNote);

    await user.click(screen.getByRole("button", { name: /edit your note on AAPL/i }));
    await user.keyboard("{Escape}");

    expect(onSaveNote).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("Enter saves without reaching for the mouse", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote(null), onSaveNote);

    await user.click(screen.getByRole("button", { name: /add a note on AAPL/i }));
    await user.type(screen.getByRole("textbox"), "quick thought{Enter}");

    expect(onSaveNote).toHaveBeenCalledWith("AAPL", "quick thought");
  });

  it("Shift+Enter writes a second line instead of saving", async () => {
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote(null), onSaveNote);

    await user.click(screen.getByRole("button", { name: /add a note on AAPL/i }));
    await user.type(screen.getByRole("textbox"), "line one{Shift>}{Enter}{/Shift}line two");

    expect(onSaveNote).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toHaveValue("line one\nline two");
  });

  it("typing appends rather than replacing an existing note", async () => {
    // Selecting the text on focus would make one keystroke destroy the note.
    const user = userEvent.setup();
    const onSaveNote = vi.fn();
    renderPanel(withNote("first"), onSaveNote);

    await user.click(screen.getByRole("button", { name: /edit your note on AAPL/i }));
    await user.keyboard(" second");

    expect(screen.getByRole("textbox")).toHaveValue("first second");
  });

  it("closes the editor once the save resolves", async () => {
    const user = userEvent.setup();
    renderPanel(withNote(null), vi.fn().mockResolvedValue(undefined));

    await user.click(screen.getByRole("button", { name: /add a note on AAPL/i }));
    await user.type(screen.getByRole("textbox"), "done{Enter}");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("marks rows that already carry a note", () => {
    // The pencil is otherwise invisible until hover, which would hide notes.
    const { container } = renderPanel(withNote("something"));
    expect(container.querySelector(".note-btn.has-note")).not.toBeNull();
  });

  it("keeps notes on the right row when several are open-able", async () => {
    const user = userEvent.setup();
    render(
      <WatchlistPanel
        entries={[
          { ticker: "AAPL", added_at: "2026-01-01T00:00:00+00:00", note: "apple note" },
          { ticker: "MSFT", added_at: "2026-01-02T00:00:00+00:00", note: "msft note" },
        ]}
        quotes={[quote(), quote({ symbol: "MSFT", name: "Microsoft" })]}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
        onSaveNote={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /edit your note on MSFT/i }));

    expect(screen.getByRole("textbox")).toHaveValue("msft note");
    expect(screen.getByText("apple note")).toBeInTheDocument();
  });
});
