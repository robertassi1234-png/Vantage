import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("draws a path through every point", () => {
    const { container } = render(<Sparkline values={[1, 2, 3, 4]} direction="up" />);
    const path = container.querySelector("path");
    expect(path).not.toBeNull();
    // One move plus three lines.
    expect(path!.getAttribute("d")).toMatch(/^M.* L.* L.* L/);
  });

  it("renders a placeholder rather than crashing on too few points", () => {
    const { container } = render(<Sparkline values={[]} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector(".sparkline-empty")).not.toBeNull();
  });

  it("carries the direction in its class so CSS can colour it", () => {
    const { container } = render(<Sparkline values={[3, 2, 1]} direction="down" />);
    expect(container.querySelector("svg")).toHaveClass("sparkline-down");
  });

  it("keeps every point inside the viewport", () => {
    const width = 120;
    const height = 32;
    const { container } = render(
      <Sparkline values={[10, 500, 3, 88]} direction="up" width={width} height={height} />,
    );

    const coords = container
      .querySelector("path")!
      .getAttribute("d")!
      .match(/-?\d+\.?\d*/g)!
      .map(Number);

    for (let i = 0; i < coords.length; i += 2) {
      expect(coords[i]).toBeGreaterThanOrEqual(0);
      expect(coords[i]).toBeLessThanOrEqual(width);
      expect(coords[i + 1]).toBeGreaterThanOrEqual(0);
      expect(coords[i + 1]).toBeLessThanOrEqual(height);
    }
  });

  it("survives a flat series without dividing by zero", () => {
    const { container } = render(<Sparkline values={[5, 5, 5]} direction="flat" />);
    expect(container.querySelector("path")!.getAttribute("d")).not.toMatch(/NaN/);
  });
});
