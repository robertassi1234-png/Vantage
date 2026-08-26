import "@testing-library/jest-dom/vitest";

// jsdom has no layout engine, so ResizeObserver (used by PriceChart to size
// itself) has to be stubbed for component tests to mount.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
