import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketBoard } from "./MarketBoard";
import type { MarketGroup, MarketTile } from "../types";

const tile = (over: Partial<MarketTile> = {}): MarketTile => ({
  symbol: "XLK",
  label: "Technology",
  blurb: "Software, chips and hardware",
  price: 288.4,
  change: 5.4,
  changePercent: 1.92,
  sparkline: [100, 101, 103, 102, 105],
  ...over,
});

const groups: MarketGroup[] = [
  { group: "Growth", entries: [tile()] },
  {
    group: "Defensive",
    entries: [tile({ symbol: "XLV", label: "Healthcare", changePercent: -0.4 })],
  },
  { group: "Cyclical", entries: [tile({ symbol: "XLF", label: "Financials" })] },
];

function setup(props: Partial<React.ComponentProps<typeof MarketBoard>> = {}) {
  return render(
    <MarketBoard groups={groups} onSelect={vi.fn()} {...props} />,
  );
}

describe("MarketBoard", () => {
  it("shows the first group's tiles", () => {
    setup();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("$288.40")).toBeInTheDocument();
  });

  it("signs the move", () => {
    setup();
    expect(screen.getByText(/\+1\.92%/)).toBeInTheDocument();
  });

  it("carries direction as an arrow, not colour alone", () => {
    // Colour is not available to every reader, so it can never be the only
    // thing saying which way a number went.
    const { container } = setup();
    expect(container.querySelector(".tone-up")).not.toBeNull();
    expect(screen.getByText("▲")).toBeInTheDocument();
  });

  it("switches group when a tab is clicked", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("tab", { name: "Defensive" }));
    expect(screen.getByText("Healthcare")).toBeInTheDocument();
    expect(screen.queryByText("Technology")).not.toBeInTheDocument();
  });

  it("opens the chart for a tile", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    setup({ onSelect });

    await user.click(screen.getByRole("button", { name: /Technology.*Show its chart/i }));
    expect(onSelect).toHaveBeenCalledWith("XLK", "Technology");
  });

  it("survives a tile with no price", () => {
    // A provider that dropped one symbol must not blank the strip.
    const { container } = setup({
      groups: [{ group: "Growth", entries: [tile({ price: null, changePercent: null })] }],
    });

    // Both the value and the move read as a dash, and the tile still opens.
    expect(container.querySelector(".tile-value")).toHaveTextContent("—");
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Show its chart/i })).toBeInTheDocument();
  });

  it("keeps its place on the page when there is nothing to show", () => {
    // Hiding the section on an empty response made a whole feature vanish
    // during an outage, which reads as never having been built.
    const { container } = setup({ groups: [] });

    expect(container.querySelectorAll(".board-skeleton")).toHaveLength(4);
    expect(screen.getByText(/unavailable right now/i)).toBeInTheDocument();
  });

  it("says it is loading rather than that data is missing", () => {
    setup({ groups: [], loading: true });
    expect(screen.getByText(/loading how each part/i)).toBeInTheDocument();
  });

  it("hides the tabs when there is only one group", () => {
    setup({ groups: [groups[0]] });
    expect(screen.queryByRole("tab", { name: "Defensive" })).not.toBeInTheDocument();
  });
});

describe("rotation", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("advances on its own", async () => {
    setup();
    expect(screen.getByText("Technology")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(7000);
    });
    expect(screen.getByText("Healthcare")).toBeInTheDocument();
  });

  it("wraps back to the first group", async () => {
    setup();
    await act(async () => {
      vi.advanceTimersByTime(7000 * 3);
    });
    expect(screen.getByText("Technology")).toBeInTheDocument();
  });

  it("stops while the pointer is over it", async () => {
    // Motion that carries on while you are reading a tile is a nuisance.
    const { container } = setup();
    await act(async () => {
      (container.querySelector(".market-board") as HTMLElement).dispatchEvent(
        new MouseEvent("mouseover", { bubbles: true }),
      );
    });

    await act(async () => {
      vi.advanceTimersByTime(7000 * 2);
    });
    expect(screen.getByText("Technology")).toBeInTheDocument();
  });

  it("does not rotate for a reader who asked for reduced motion", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    setup();
    await act(async () => {
      vi.advanceTimersByTime(7000 * 2);
    });

    expect(screen.getByText("Technology")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("can always be driven by hand", async () => {
    // Rotation you cannot override is worse than none.
    setup();
    const dots = screen.getAllByRole("button", { name: /^Show / });
    expect(dots).toHaveLength(3);
  });
});

describe("a tile with no price", () => {
  const group = (price: number | null, sparkline: number[] = []) => [
    {
      group: "Growth",
      entries: [
        { symbol: "XLK", label: "Technology", blurb: "Software", price, change: null, changePercent: null, sparkline },
      ],
    },
  ];

  it("shimmers while the page is still loading", () => {
    // Dashes and a flat line read as a rendering fault. A tile that is
    // waiting should look like it is waiting.
    const { container } = render(
      <MarketBoard groups={group(null)} loading onSelect={() => {}} />,
    );
    expect(container.querySelectorAll(".board-tile .shimmer").length).toBeGreaterThan(0);
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("says so quietly once loading has finished", () => {
    render(<MarketBoard groups={group(null)} loading={false} onSelect={() => {}} />);
    expect(screen.getByText("No price yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Technology, no price yet/ })).toBeInTheDocument();
  });

  it("draws no sparkline for a series with nothing in it", () => {
    const { container } = render(
      <MarketBoard groups={group(null)} loading={false} onSelect={() => {}} />,
    );
    expect(container.querySelector(".tile-spark svg")).toBeNull();
    expect(container.querySelector(".tile-spark-empty")).not.toBeNull();
  });

  it("still marks the label as the thing to read", () => {
    const { container } = render(
      <MarketBoard groups={group(null)} loading={false} onSelect={() => {}} />,
    );
    expect(container.querySelector(".board-tile.unpriced")).not.toBeNull();
    expect(screen.getByText("Technology")).toBeInTheDocument();
  });

  it("renders normally the moment a price arrives", () => {
    render(
      <MarketBoard groups={group(312.9, [1, 2, 3])} loading={false} onSelect={() => {}} />,
    );
    expect(screen.getByText("$312.90")).toBeInTheDocument();
    expect(screen.queryByText("No price yet")).not.toBeInTheDocument();
  });
});
