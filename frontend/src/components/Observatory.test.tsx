import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Observatory } from "./Observatory";

describe("Observatory", () => {
  it("lets the reader pause and resume decorative motion", () => {
    render(<Observatory />);
    fireEvent.click(screen.getByRole("button", { name: "Pause decorative animation" }));
    expect(screen.getByRole("button", { name: "Resume decorative animation" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Resume decorative animation" }));
    expect(screen.getByRole("button", { name: "Pause decorative animation" }).getAttribute("aria-pressed")).toBe("false");
  });
  it("links directly to the research dashboard", () => {
    render(<Observatory />);
    expect(screen.getByRole("link", { name: /Explore your dashboard/ }).getAttribute("href")).toBe("#research-dashboard");
  });
});
