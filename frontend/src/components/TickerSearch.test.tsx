import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TickerSearch } from "./TickerSearch";
import { api } from "../api";
import type { SymbolMatch } from "../types";

// Real timers throughout: the debounce is only 220ms, and driving userEvent
// from a fake clock deadlocks on its internal awaits.
const DEBOUNCE_MS = 220;

const MATCHES: SymbolMatch[] = [
  { symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", currency: "USD" },
  { symbol: "APLE", name: "Apple Hospitality REIT", exchange: "NYSE", currency: "USD" },
];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Wait `ms` inside act(), so the state updates the debounce timer triggers are
 * flushed by React rather than landing outside a render pass and warning.
 */
const settle = (ms: number) => act(() => sleep(ms));

function mockSearch(impl: (q: string) => Promise<SymbolMatch[]>) {
  return vi.spyOn(api, "searchSymbols").mockImplementation(impl);
}

const box = () => screen.getByLabelText("Search for a company or ticker") as HTMLInputElement;
const suggestions = () => screen.findByText("Apple Inc.");

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TickerSearch", () => {
  it("suggests a ticker when a company name is typed", async () => {
    mockSearch(async () => MATCHES);
    render(<TickerSearch onSelect={vi.fn()} />);

    await userEvent.type(box(), "apple");

    expect(await suggestions()).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("debounces so a burst of keystrokes makes one request", async () => {
    const spy = mockSearch(async () => MATCHES);
    render(<TickerSearch onSelect={vi.fn()} />);

    await userEvent.type(box(), "apple");
    await suggestions();

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("apple");
  });

  it("ignores a slow response that lands after a newer one", async () => {
    // Without the stale-response guard a slow "app" request resolving after
    // "apple" would overwrite the newer, correct suggestions.
    mockSearch(async (q: string) => {
      if (q !== "apple") {
        // Plain sleep: this is latency inside the mocked request, not a
        // test-level wait, so it must not be wrapped in act().
        await sleep(DEBOUNCE_MS * 3);
        return [{ symbol: "STALE", name: "Stale Result", exchange: "X", currency: "USD" }];
      }
      return MATCHES;
    });

    render(<TickerSearch onSelect={vi.fn()} />);

    await userEvent.type(box(), "app");
    await settle(DEBOUNCE_MS + 40); // let the slow request start
    await userEvent.type(box(), "le");

    expect(await suggestions()).toBeInTheDocument();

    await settle(DEBOUNCE_MS * 4); // outlive the slow response
    expect(screen.queryByText("Stale Result")).toBeNull();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });

  it("submits the highlighted suggestion on Enter", async () => {
    mockSearch(async () => MATCHES);
    const onSelect = vi.fn();
    render(<TickerSearch onSelect={onSelect} />);

    await userEvent.type(box(), "apple");
    await suggestions();
    await userEvent.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith("AAPL");
  });

  it("moves the highlight with the arrow keys", async () => {
    mockSearch(async () => MATCHES);
    const onSelect = vi.fn();
    render(<TickerSearch onSelect={onSelect} />);

    await userEvent.type(box(), "apple");
    await suggestions();
    await userEvent.keyboard("{ArrowDown}{Enter}");

    expect(onSelect).toHaveBeenCalledWith("APLE");
  });

  it("wraps the highlight around the ends of the list", async () => {
    mockSearch(async () => MATCHES);
    const onSelect = vi.fn();
    render(<TickerSearch onSelect={onSelect} />);

    await userEvent.type(box(), "apple");
    await suggestions();
    // Up from the first entry lands on the last.
    await userEvent.keyboard("{ArrowUp}{Enter}");

    expect(onSelect).toHaveBeenCalledWith("APLE");
  });

  it("closes the list on Escape", async () => {
    mockSearch(async () => MATCHES);
    render(<TickerSearch onSelect={vi.fn()} />);

    await userEvent.type(box(), "apple");
    await suggestions();
    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByText("Apple Inc.")).toBeNull());
  });

  it("falls back to the raw input when the lookup fails", async () => {
    // An exact ticker must still be addable when search is unavailable.
    mockSearch(async () => {
      throw new Error("search down");
    });
    const onSelect = vi.fn();
    render(<TickerSearch onSelect={onSelect} />);

    await userEvent.type(box(), "tsla");
    await settle(DEBOUNCE_MS + 60);
    await userEvent.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith("TSLA");
  });

  it("uppercases a raw ticker before submitting", async () => {
    mockSearch(async () => []);
    const onSelect = vi.fn();
    render(<TickerSearch onSelect={onSelect} />);

    await userEvent.type(box(), "msft");
    await settle(DEBOUNCE_MS + 60);
    await userEvent.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith("MSFT");
  });

  it("does not submit a whitespace-only query", async () => {
    mockSearch(async () => []);
    const onSelect = vi.fn();
    render(<TickerSearch onSelect={onSelect} />);

    await userEvent.type(box(), "   ");
    await settle(DEBOUNCE_MS + 60);
    await userEvent.keyboard("{Enter}");

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("makes no request for a blank query", async () => {
    const spy = mockSearch(async () => []);
    render(<TickerSearch onSelect={vi.fn()} />);

    await userEvent.type(box(), "  ");
    await settle(DEBOUNCE_MS + 60);

    expect(spy).not.toHaveBeenCalled();
  });

  it("clears the input after a selection", async () => {
    mockSearch(async () => MATCHES);
    render(<TickerSearch onSelect={vi.fn()} />);

    await userEvent.type(box(), "apple");
    await userEvent.click(await suggestions());

    await waitFor(() => expect(box().value).toBe(""));
  });

  it("disables the input while the parent is busy", () => {
    mockSearch(async () => MATCHES);
    render(<TickerSearch onSelect={vi.fn()} disabled />);
    expect(box()).toBeDisabled();
  });
});
