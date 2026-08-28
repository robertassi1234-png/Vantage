import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JournalComposer } from "./JournalComposer";

const TAGS = ["thesis", "risk", "catalyst", "mistake"];
const noop = async () => {};

describe("writing an entry", () => {
  it("stamps it with the price on screen, not one fetched later", async () => {
    // What gets recorded is the number the reader was looking at when they
    // formed the view.
    const onSubmit = vi.fn(noop);
    render(<JournalComposer ticker="AAPL" priceNow={142.3} suggestedTags={TAGS} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("What you think about AAPL"), "Margins keep expanding.");
    await userEvent.click(screen.getByRole("button", { name: "Save entry" }));

    expect(onSubmit).toHaveBeenCalledWith({
      body: "Margins keep expanding.",
      tags: [],
      priceAtWrite: 142.3,
    });
  });

  it("says which price it is about to save against", async () => {
    render(<JournalComposer ticker="AAPL" priceNow={142.3} suggestedTags={TAGS} onSubmit={noop} />);
    expect(screen.getByText(/Saved against AAPL at \$142\.30/)).toBeInTheDocument();
  });

  it("says so when there is no price to stamp", async () => {
    // Better than saving one silently unscored and leaving the reader to
    // discover it a year later.
    render(<JournalComposer ticker="AAPL" priceNow={null} suggestedTags={TAGS} onSubmit={noop} />);
    expect(screen.getByText(/No price for AAPL right now/)).toBeInTheDocument();
  });

  it("saves without a price rather than losing the thought", async () => {
    const onSubmit = vi.fn(noop);
    render(<JournalComposer ticker="AAPL" priceNow={null} suggestedTags={TAGS} onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("What you think about AAPL"), "Worth a look.");
    await userEvent.click(screen.getByRole("button", { name: "Save entry" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ priceAtWrite: null }));
  });

  it("attaches the tags that were picked", async () => {
    const onSubmit = vi.fn(noop);
    render(<JournalComposer ticker="AAPL" priceNow={142.3} suggestedTags={TAGS} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "risk" }));
    await userEvent.click(screen.getByRole("button", { name: "catalyst" }));
    await userEvent.type(screen.getByLabelText("What you think about AAPL"), "Supply is tight.");
    await userEvent.click(screen.getByRole("button", { name: "Save entry" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ tags: ["risk", "catalyst"] }));
  });

  it("lets a tag be unpicked", async () => {
    const onSubmit = vi.fn(noop);
    render(<JournalComposer ticker="AAPL" priceNow={142.3} suggestedTags={TAGS} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "risk" }));
    await userEvent.click(screen.getByRole("button", { name: "risk" }));
    await userEvent.type(screen.getByLabelText("What you think about AAPL"), "Fine.");
    await userEvent.click(screen.getByRole("button", { name: "Save entry" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ tags: [] }));
  });

  it("refuses an empty entry", async () => {
    const onSubmit = vi.fn(noop);
    render(<JournalComposer ticker="AAPL" priceNow={142.3} suggestedTags={TAGS} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: "Save entry" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Write something first.")).toBeInTheDocument();
  });
});
