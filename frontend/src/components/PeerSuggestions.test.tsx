import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PeerSuggestions } from "./PeerSuggestions";
import type { PeerSuggestion } from "../types";

const peer = (over: Partial<PeerSuggestion> = {}): PeerSuggestion => ({
  symbol: "MSFT",
  count: 1,
  because_of: ["AAPL"],
  name: "Microsoft Corporation",
  price: 410.25,
  changePercent: 1.2,
  ...over,
});

const renderPanel = (props: Partial<React.ComponentProps<typeof PeerSuggestions>> = {}) =>
  render(
    <PeerSuggestions
      suggestions={[peer()]}
      loading={false}
      error={null}
      onAdd={vi.fn()}
      {...props}
    />,
  );

describe("PeerSuggestions", () => {
  it("shows the ticker, name and price", () => {
    renderPanel();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("Microsoft Corporation")).toBeInTheDocument();
    expect(screen.getByText("$410.25")).toBeInTheDocument();
  });

  it("says why each company is being suggested", () => {
    // Without a reason the list is an oracle; with one it's a starting point.
    renderPanel();
    expect(screen.getByText(/peer of AAPL/i)).toBeInTheDocument();
  });

  it("reads naturally when two holdings share a peer", () => {
    renderPanel({ suggestions: [peer({ because_of: ["AAPL", "MSFT"], symbol: "GOOG" })] });
    expect(screen.getByText(/peer of AAPL and MSFT/i)).toBeInTheDocument();
  });

  it("uses a comma list for three or more", () => {
    renderPanel({
      suggestions: [peer({ because_of: ["AAPL", "MSFT", "NVDA"], symbol: "GOOG" })],
    });
    expect(screen.getByText(/peer of AAPL, MSFT and NVDA/i)).toBeInTheDocument();
  });

  it("adds the company when Compare is clicked", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    renderPanel({ onAdd });

    await user.click(screen.getByRole("button", { name: /compare/i }));
    expect(onAdd).toHaveBeenCalledWith("MSFT");
  });

  it("disables the button for the row being added", () => {
    renderPanel({ adding: "MSFT" });
    expect(screen.getByRole("button", { name: /adding/i })).toBeDisabled();
  });

  it("renders nothing at all when there is nothing to suggest", () => {
    const { container } = renderPanel({ suggestions: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it("says it is looking while the first load runs", () => {
    renderPanel({ suggestions: [], loading: true });
    expect(screen.getByText(/looking for similar companies/i)).toBeInTheDocument();
  });

  it("keeps showing what it has while refreshing", () => {
    // Blanking the list on every reload would make it flicker on each add.
    renderPanel({ loading: true });
    expect(screen.getByText("MSFT")).toBeInTheDocument();
  });

  it("reports an outage instead of pretending there are no peers", () => {
    renderPanel({ suggestions: [], error: "Couldn't look up peers right now." });
    expect(screen.getByText(/couldn't look up peers/i)).toBeInTheDocument();
  });

  it("survives a suggestion with no name or price", () => {
    // The quote lookup is allowed to fail; the ticker is still the suggestion.
    renderPanel({ suggestions: [peer({ name: null, price: null, changePercent: null })] });
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compare/i })).toBeInTheDocument();
  });

  it("signs the day move", () => {
    renderPanel({ suggestions: [peer({ changePercent: -2.4 })] });
    expect(screen.getByText(/-2\.40%/)).toBeInTheDocument();
  });
});
