import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearSnapshot, describeAge, readSnapshot, writeSnapshot } from "./snapshot";
import type { Snapshot } from "./snapshot";

const base: Omit<Snapshot, "savedAt"> = {
  identity: "alice@example.com",
  entries: [{ ticker: "AAPL", added_at: "2026-01-01T00:00:00Z", note: null }],
  quotes: [],
  indices: [],
  board: [],
  alerts: [],
  trends: {},
  lots: [],
  splits: [],
  journal: [],
};

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

describe("the last dashboard this browser saw", () => {
  it("comes back for the same person", () => {
    writeSnapshot(base);
    expect(readSnapshot("alice@example.com")?.entries).toHaveLength(1);
  });

  it("is never shown to a different account", () => {
    // Signing out must not leave the previous account's watchlist on screen.
    writeSnapshot(base);
    expect(readSnapshot("bob@example.com")).toBeNull();
  });

  it("is never shown to a signed-out reader", () => {
    writeSnapshot(base);
    expect(readSnapshot("anonymous")).toBeNull();
  });

  it("is dropped once it is too old to be worth showing", () => {
    vi.useFakeTimers();
    writeSnapshot(base);

    vi.advanceTimersByTime(25 * 60 * 60 * 1000);
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("is still served a few hours later", () => {
    vi.useFakeTimers();
    writeSnapshot(base);

    vi.advanceTimersByTime(6 * 60 * 60 * 1000);
    expect(readSnapshot("alice@example.com")).not.toBeNull();
  });

  it("records when it was taken, so its age can be stated", () => {
    writeSnapshot(base);
    const snapshot = readSnapshot("alice@example.com");
    expect(snapshot?.savedAt).toBeTypeOf("number");
  });

  it("survives nothing being stored", () => {
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("survives a corrupt entry rather than breaking the page", () => {
    localStorage.setItem("vantage.snapshot.v1", "{not json");
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("survives a stored value of the wrong shape", () => {
    localStorage.setItem(
      "vantage.snapshot.v1",
      JSON.stringify({ identity: "alice@example.com", savedAt: Date.now() }),
    );
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("survives storage being unavailable", () => {
    // Private browsing throws on access rather than returning null.
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });

    expect(() => writeSnapshot(base)).not.toThrow();
    spy.mockRestore();
  });

  it("can be cleared", () => {
    writeSnapshot(base);
    clearSnapshot();
    expect(readSnapshot("alice@example.com")).toBeNull();
  });
});

describe("saying how old the figures are", () => {
  const now = Date.parse("2026-08-27T12:00:00Z");

  it.each([
    [30 * 1000, "moments ago"],
    [3 * 60 * 1000, "3 minutes ago"],
    [60 * 60 * 1000, "1 hour ago"],
    [5 * 60 * 60 * 1000, "5 hours ago"],
    [30 * 60 * 60 * 1000, "yesterday"],
  ])("reads naturally at %i ms", (age, expected) => {
    expect(describeAge(now - age, now)).toBe(expected);
  });

  it("says minute, not minutes, for one", () => {
    expect(describeAge(now - 60 * 1000, now)).toBe("1 minute ago");
  });
});

describe("a snapshot written by a different build", () => {
  // Storage outlives a deploy. The day a field is renamed, the next visit
  // reads back yesterday's shape and hands it to a component that maps over
  // it -- and since the reload reads the same storage, a crash there would
  // repeat forever. Each of these is a shape that used to render and no
  // longer does.
  const store = (snapshot: unknown) =>
    localStorage.setItem("vantage.snapshot.v1", JSON.stringify({ ...(snapshot as object), savedAt: Date.now() }));

  it("is refused when the board groups are shaped the old way", () => {
    store({ ...base, board: [{ label: "Growth", tiles: [] }] });
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("is refused when a list arrived as something other than a list", () => {
    store({ ...base, quotes: { AAPL: 1 } });
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("is refused when trends are not arrays of numbers", () => {
    store({ ...base, trends: { AAPL: "1,2,3" } });
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("is refused when an entry has no ticker to render", () => {
    store({ ...base, entries: [{ added_at: "2026-01-01T00:00:00Z" }] });
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("is refused when savedAt is missing, so its age cannot be judged", () => {
    localStorage.setItem("vantage.snapshot.v1", JSON.stringify(base));
    expect(readSnapshot("alice@example.com")).toBeNull();
  });

  it("is thrown away rather than re-read on every visit", () => {
    store({ ...base, board: [{ label: "Growth", tiles: [] }] });
    readSnapshot("alice@example.com");
    expect(localStorage.getItem("vantage.snapshot.v1")).toBeNull();
  });

  it("keeps a snapshot that merely belongs to someone else", () => {
    // Wrong reader is not wrong shape: they may sign back in.
    writeSnapshot(base);
    readSnapshot("bob@example.com");
    expect(localStorage.getItem("vantage.snapshot.v1")).not.toBeNull();
  });

  it("still accepts a board that is shaped the current way", () => {
    store({ ...base, board: [{ group: "Growth", entries: [] }] });
    expect(readSnapshot("alice@example.com")).not.toBeNull();
  });
});

describe("cached lots", () => {
  const store = (snapshot: unknown) =>
    localStorage.setItem("vantage.snapshot.v1", JSON.stringify({ ...(snapshot as object), savedAt: Date.now() }));

  it("come back so the portfolio strip paints during a cold start", () => {
    writeSnapshot({
      ...base,
      lots: [
        {
          id: "l1",
          ticker: "AAPL",
          shares: 10,
          costPerShare: 142.3,
          tradeDate: "2025-03-04",
          note: null,
          created_at: "2025-03-04",
        },
      ],
    });
    expect(readSnapshot("alice@example.com")?.lots).toHaveLength(1);
  });

  it("are refused when a share count is not a number", () => {
    // These drive money figures. A share count read back as a string would
    // render a portfolio worth NaN rather than simply failing to render.
    store({ ...base, lots: [{ id: "l1", ticker: "AAPL", shares: "10", costPerShare: 142.3 }] });
    expect(readSnapshot("alice@example.com")).toBeNull();
  });
});
