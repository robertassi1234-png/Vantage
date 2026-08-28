import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PositionDetail } from "./PositionDetail";
import { buildPortfolio } from "../positions";
import type { Lot, Quote, SplitAdjustment } from "../types";

let counter = 0;
const lot = (shares: number, costPerShare: number, tradeDate = "2025-01-01"): Lot => ({
  id: `lot-${counter++}`,
  ticker: "AAPL",
  shares,
  costPerShare,
  tradeDate,
  note: null,
  created_at: tradeDate,
});

const quote = (price: number | null): Quote => ({
  symbol: "AAPL",
  name: "Apple Inc.",
  price,
  change: 0,
  changePercent: null,
  dayLow: null,
  dayHigh: null,
  yearLow: null,
  yearHigh: null,
  marketCap: null,
  volume: null,
});

const noop = async () => {};

function show(lots: Lot[], price: number | null = 200, splits: SplitAdjustment[] = [], overrides = {}) {
  const portfolio = buildPortfolio(lots, price == null ? [] : [quote(price)]);
  return render(
    <PositionDetail
      ticker="AAPL"
      position={portfolio.byTicker.get("AAPL")}
      splits={splits}
      onAddLot={noop}
      onDeleteLot={noop}
      onApplySplit={noop}
      onUndoSplit={noop}
      {...overrides}
    />,
  );
}

describe("the trades behind a row", () => {
  it("lists each trade as entered rather than one summary number", () => {
    // The lots are the source of every figure above them, so they have to be
    // checkable and correctable one by one.
    show([lot(10, 100, "2025-01-01"), lot(5, 200, "2025-06-01")]);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Bought")).toBeInTheDocument();
    expect(within(rows[0]).getByText("$100.00")).toBeInTheDocument();
  });

  it("labels a negative lot as a sale", () => {
    show([lot(10, 100, "2025-01-01"), lot(-4, 180, "2025-06-01")]);
    // Scoped to the table: the form's own "Sold" toggle carries the same word.
    expect(within(screen.getByRole("table")).getByText("Sold")).toBeInTheDocument();
  });

  it("shows the weighted average cost, not the last price paid", () => {
    show([lot(10, 100, "2025-01-01"), lot(30, 200, "2025-06-01")]);
    expect(screen.getByText("Average cost").closest(".position-stat")).toHaveTextContent("$175.00");
  });

  it("warns when more shares are sold than were bought", () => {
    show([lot(5, 100, "2025-01-01"), lot(-8, 120, "2025-02-01")]);
    expect(screen.getByRole("status")).toHaveTextContent(/more shares sold than bought/);
  });

  it("offers only the form when nothing has been entered yet", () => {
    show([]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add trade" })).toBeInTheDocument();
  });

  it("sends a purchase with positive shares", async () => {
    const onAddLot = vi.fn(noop);
    show([], 200, [], { onAddLot });

    await userEvent.type(screen.getByLabelText("Shares of AAPL"), "10");
    await userEvent.type(screen.getByLabelText("Price per share of AAPL"), "142.3");
    await userEvent.click(screen.getByRole("button", { name: "Add trade" }));

    expect(onAddLot).toHaveBeenCalledWith(
      expect.objectContaining({ shares: 10, costPerShare: 142.3 }),
    );
  });

  it("sends a sale as the same shape with the sign flipped", async () => {
    const onAddLot = vi.fn(noop);
    show([lot(10, 100)], 200, [], { onAddLot });

    await userEvent.click(screen.getByRole("button", { name: "Sold" }));
    await userEvent.type(screen.getByLabelText("Shares of AAPL"), "4");
    await userEvent.type(screen.getByLabelText("Price per share of AAPL"), "180");
    await userEvent.click(screen.getByRole("button", { name: "Add trade" }));

    expect(onAddLot).toHaveBeenCalledWith(expect.objectContaining({ shares: -4, costPerShare: 180 }));
  });

  it("refuses a trade with no price rather than recording it as free", async () => {
    const onAddLot = vi.fn(noop);
    show([], 200, [], { onAddLot });

    await userEvent.type(screen.getByLabelText("Shares of AAPL"), "10");
    await userEvent.click(screen.getByRole("button", { name: "Add trade" }));

    expect(onAddLot).not.toHaveBeenCalled();
    expect(screen.getByText("Enter the price per share.")).toBeInTheDocument();
  });
});

describe("adjusting for a split", () => {
  it("is offered once there is something to adjust", async () => {
    show([lot(10, 400)]);
    expect(screen.getByRole("button", { name: /Adjust for a share split/ })).toBeInTheDocument();
  });

  it("is not offered on a row with no trades", () => {
    show([]);
    expect(screen.queryByRole("button", { name: /Adjust for a share split/ })).not.toBeInTheDocument();
  });

  it("explains the ratio in the terms a split is announced in", async () => {
    show([lot(10, 400)]);
    await userEvent.click(screen.getByRole("button", { name: /Adjust for a share split/ }));
    expect(screen.getByText(/4 for a 4-for-1 split; 0.1 for a reverse 1-for-10/)).toBeInTheDocument();
    // Said plainly, because the action rewrites every cost basis for the row.
    expect(screen.getByText(/This can be undone/)).toBeInTheDocument();
  });

  it("passes the ratio through as entered", async () => {
    const onApplySplit = vi.fn(noop);
    show([lot(10, 400)], 200, [], { onApplySplit });

    await userEvent.click(screen.getByRole("button", { name: /Adjust for a share split/ }));
    await userEvent.type(screen.getByLabelText("Split ratio for AAPL"), "4");
    await userEvent.click(screen.getByRole("button", { name: "Adjust" }));

    expect(onApplySplit).toHaveBeenCalledWith(4);
  });

  it("lists an applied split in spoken terms with a way back", async () => {
    const onUndoSplit = vi.fn(noop);
    const splits: SplitAdjustment[] = [
      { id: "s1", ticker: "AAPL", ratio: 0.1, applied_at: "2026-08-01T00:00:00Z" },
    ];
    show([lot(1, 4000)], 200, splits, { onUndoSplit });

    expect(screen.getByText(/1-for-10 split on 2026-08-01/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndoSplit).toHaveBeenCalledWith("s1");
  });
});
