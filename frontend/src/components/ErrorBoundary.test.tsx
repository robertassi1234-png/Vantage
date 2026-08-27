import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): React.ReactElement {
  throw new Error("points is not defined");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs the caught error itself; keep the test output readable.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => vi.restoreAllMocks());

  it("renders its children when nothing is wrong", () => {
    render(
      <ErrorBoundary>
        <p>the dashboard</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("the dashboard")).toBeInTheDocument();
  });

  it("shows a message instead of a blank page when a render throws", () => {
    // The failure this exists for: one bad value used to unmount the whole
    // app, leaving the reader with nothing on screen at all.
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong on this page/i)).toBeInTheDocument();
  });

  it("reassures that nothing was lost", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/nothing has been lost/i)).toBeInTheDocument();
  });

  it("offers a way out", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("button", { name: /reload the page/i })).toBeInTheDocument();
  });

  it("keeps the underlying error available rather than hiding it", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("points is not defined")).toBeInTheDocument();
  });

  it("still logs the crash so it can be diagnosed afterwards", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining("Vantage crashed"),
      expect.anything(),
      expect.anything(),
    );
  });
});
