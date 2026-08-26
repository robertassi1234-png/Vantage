import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PriceChart, axisTicks, niceStep } from "./PriceChart";
import type { PricePoint } from "../types";

const points = (closes: number[]): PricePoint[] =>
  closes.map((close, i) => ({
    date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10),
    close,
  }));

describe("niceStep", () => {
  it("snaps to 1 / 2 / 5 × a power of ten", () => {
    expect(niceStep(1)).toBe(1);
    expect(niceStep(1.4)).toBe(2);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(7)).toBe(10);
    expect(niceStep(23)).toBe(50);
  });

  it("works below one", () => {
    expect(niceStep(0.11)).toBe(0.2);
    expect(niceStep(0.03)).toBe(0.05);
  });

  it("always returns a positive step", () => {
    for (const raw of [0.001, 0.7, 12, 900, 45_000]) {
      expect(niceStep(raw)).toBeGreaterThan(0);
    }
  });
});

describe("axisTicks", () => {
  it("produces round, ascending values covering the range", () => {
    const ticks = axisTicks(252, 312);
    expect(ticks.length).toBeGreaterThan(1);
    expect([...ticks].sort((a, b) => a - b)).toEqual(ticks);
    expect(ticks[0]).toBeGreaterThanOrEqual(252);
    expect(ticks[ticks.length - 1]).toBeLessThanOrEqual(312);
  });

  it("collapses to a single tick when the series is flat", () => {
    expect(axisTicks(100, 100)).toEqual([100]);
  });

  it("does not hang or explode on a non-finite range", () => {
    expect(axisTicks(Number.NaN, 10)).toEqual([Number.NaN]);
    expect(axisTicks(0, Number.POSITIVE_INFINITY)).toEqual([0]);
  });

  it("avoids floating-point dust in the labels", () => {
    for (const tick of axisTicks(0.1, 0.9)) {
      expect(String(tick)).not.toMatch(/\d{10,}/);
    }
  });

  it("handles a tiny range without producing thousands of ticks", () => {
    expect(axisTicks(100, 100.0001).length).toBeLessThan(10);
  });
});

describe("PriceChart", () => {
  it("shows a message instead of an empty frame when there is no data", () => {
    const { container, getByText } = render(<PriceChart points={[]} label="AAPL" />);
    expect(container.querySelector("svg.price-chart")).toBeNull();
    expect(getByText(/Not enough price history/)).toBeInTheDocument();
  });

  it("treats a single point as insufficient", () => {
    const { getByText } = render(<PriceChart points={points([10])} label="AAPL" />);
    expect(getByText(/Not enough price history/)).toBeInTheDocument();
  });

  it("draws a path with no NaN coordinates", () => {
    const { container } = render(<PriceChart points={points([10, 20, 15, 30])} label="AAPL" />);
    const d = container.querySelector(".chart-line")!.getAttribute("d")!;
    expect(d).not.toMatch(/NaN/);
  });

  it("survives a completely flat series", () => {
    const { container } = render(<PriceChart points={points([5, 5, 5, 5])} label="FLAT" />);
    const d = container.querySelector(".chart-line")!.getAttribute("d")!;
    expect(d).not.toMatch(/NaN|Infinity/);
  });

  it("marks a falling series with the down tone", () => {
    const { container } = render(<PriceChart points={points([30, 20, 10])} label="DOWN" />);
    expect(container.querySelector("svg.price-chart")).toHaveClass("tone-down");
  });

  it("marks a rising series with the up tone", () => {
    const { container } = render(<PriceChart points={points([10, 20, 30])} label="UP" />);
    expect(container.querySelector("svg.price-chart")).toHaveClass("tone-up");
  });

  it("labels the chart for screen readers", () => {
    const { container } = render(<PriceChart points={points([10, 20])} label="Apple Inc." />);
    expect(container.querySelector("svg.price-chart")!.getAttribute("aria-label")).toMatch(
      /Apple Inc\./,
    );
  });

  it("never renders two x-axis labels at the same position", () => {
    const { container } = render(<PriceChart points={points(Array(180).fill(0).map((_, i) => i))} label="X" />);
    const xs = [...container.querySelectorAll(".chart-x-label")].map((el) =>
      Number(el.getAttribute("x")),
    );
    expect(new Set(xs).size).toBe(xs.length);
  });

  it("keeps x-axis labels inside the drawing area", () => {
    const { container } = render(<PriceChart points={points(Array(120).fill(0).map((_, i) => i))} label="X" />);
    const svgWidth = Number(container.querySelector("svg.price-chart")!.getAttribute("width"));
    for (const el of container.querySelectorAll(".chart-x-label")) {
      const x = Number(el.getAttribute("x"));
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(svgWidth);
    }
  });
});
