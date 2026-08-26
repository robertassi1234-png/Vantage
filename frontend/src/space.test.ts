import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function freshModule() {
  vi.resetModules();
  return import("./space");
}

describe("space id", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("generates an id on first use and persists it", async () => {
    const { getSpaceId } = await freshModule();
    const id = getSpaceId();

    expect(id).toBeTruthy();
    expect(localStorage.getItem("vantage.space")).toBe(id);
  });

  it("returns the same id across calls", async () => {
    const { getSpaceId } = await freshModule();
    expect(getSpaceId()).toBe(getSpaceId());
  });

  it("reuses an id already in storage", async () => {
    localStorage.setItem("vantage.space", "existing-id");
    const { getSpaceId } = await freshModule();
    expect(getSpaceId()).toBe("existing-id");
  });

  it("produces an id the backend will accept", async () => {
    const { getSpaceId } = await freshModule();
    // The server falls back to the shared default for anything outside
    // [A-Za-z0-9_-]{1,64}, which would silently merge watchlists.
    expect(getSpaceId()).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it("stays usable when storage throws", async () => {
    // Private browsing and blocked-cookie settings both throw here.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const { getSpaceId } = await freshModule();
    const id = getSpaceId();
    expect(id).toBeTruthy();
    expect(getSpaceId()).toBe(id);
  });

  it("falls back to a valid id when randomUUID is unavailable", async () => {
    vi.stubGlobal("crypto", {});
    const { getSpaceId } = await freshModule();
    expect(getSpaceId()).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it("issues a different id after a reset", async () => {
    const { getSpaceId, resetSpaceId } = await freshModule();
    const first = getSpaceId();
    const second = resetSpaceId();

    expect(second).not.toBe(first);
    expect(getSpaceId()).toBe(second);
  });
});
