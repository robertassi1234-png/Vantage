import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProviderStatus } from "./ProviderStatus";
import { api } from "../api";
import type { ProviderState } from "../types";

const provider = (over: Partial<ProviderState> = {}): ProviderState => ({
  name: "fmp",
  configured: true,
  available: true,
  cooldown_seconds: 0,
  reason: null,
  last_error: null,
  successes: 3,
  failures: 0,
  serves_fundamentals: true,
  ...over,
});

const stub = (providers: ProviderState[]) =>
  vi.spyOn(api, "getProviderStatus").mockResolvedValue({
    providers,
    order: providers.map((p) => p.name),
    fundamentals_order: ["fmp"],
    healthy: providers.filter((p) => p.configured && p.available).length,
  });

afterEach(() => vi.restoreAllMocks());

describe("why data is missing", () => {
  it("stays out of the way until asked", () => {
    const call = stub([provider()]);
    render(<ProviderStatus />);
    expect(screen.getByRole("button", { name: "Why is data missing?" })).toBeInTheDocument();
    expect(call).not.toHaveBeenCalled();
  });

  it("tells a missing key apart from a spent allowance", async () => {
    // The whole point. Both look like "no data" from the outside, and only
    // one of them is fixed by waiting.
    stub([
      provider({ name: "fmp", available: false, cooldown_seconds: 3600, reason: "rate limited" }),
      provider({ name: "finnhub", configured: false }),
      provider({ name: "stooq" }),
    ]);
    render(<ProviderStatus defaultOpen />);

    expect(await screen.findByText("no key set")).toBeInTheDocument();
    expect(screen.getByText("resting 1h")).toBeInTheDocument();
    expect(screen.getByText("answering")).toBeInTheDocument();
  });

  it("says a key is worth adding rather than just marking it absent", async () => {
    stub([provider({ name: "finnhub", configured: false })]);
    render(<ProviderStatus defaultOpen />);
    expect(await screen.findByText(/another allowance to fall back on/)).toBeInTheDocument();
  });

  it("names the way out when nothing is answering at all", async () => {
    stub([provider({ available: false, cooldown_seconds: 600 })]);
    render(<ProviderStatus defaultOpen />);
    expect(await screen.findByText(/Nothing is answering right now/)).toBeInTheDocument();
  });

  it("counts what is working when something is", async () => {
    stub([provider(), provider({ name: "finnhub", configured: false })]);
    render(<ProviderStatus defaultOpen />);
    expect(await screen.findByText(/1 of 2 answering/)).toBeInTheDocument();
  });

  it("survives the status call itself failing", async () => {
    vi.spyOn(api, "getProviderStatus").mockRejectedValue(new Error("server is waking up"));
    render(<ProviderStatus defaultOpen />);
    expect(await screen.findByText("server is waking up")).toBeInTheDocument();
  });

  it("can be closed again", async () => {
    stub([provider()]);
    render(<ProviderStatus defaultOpen />);
    await userEvent.click(await screen.findByRole("button", { name: "Hide" }));
    expect(screen.getByRole("button", { name: "Why is data missing?" })).toBeInTheDocument();
  });
});
