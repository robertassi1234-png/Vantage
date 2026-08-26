import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

function errorResponse(status: number, body: string) {
  return {
    ok: false,
    status,
    statusText: "Error",
    json: async () => JSON.parse(body),
    text: async () => body,
  } as Response;
}

/** Drive the retry backoff without actually waiting for it. */
async function runWithTimers<T>(work: () => Promise<T>): Promise<T> {
  // Capture the outcome before flushing timers: the promise can reject while
  // the timers run, which Node reports as an unhandled rejection if the
  // caller's assertion hasn't attached its handler yet.
  const settled = work().then(
    (value) => ({ ok: true as const, value }),
    (error) => ({ ok: false as const, error }),
  );
  await vi.runAllTimersAsync();

  const result = await settled;
  if (!result.ok) throw result.error;
  return result.value;
}

describe("api request handling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(["AAPL"])));
    await expect(runWithTimers(() => api.getList("watch"))).resolves.toEqual(["AAPL"]);
  });

  it("surfaces the server's detail message verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => errorResponse(400, JSON.stringify({ detail: "Ticker cannot be empty" }))),
    );

    await expect(runWithTimers(() => api.addToList("compare", ""))).rejects.toThrow("Ticker cannot be empty");
  });

  it("does not retry a real error response", async () => {
    const fetchMock = vi.fn(async () => errorResponse(404, JSON.stringify({ detail: "nope" })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.getList("watch"))).rejects.toThrow("nope");
    // A 404 is an answer, not a cold start -- retrying it just wastes time.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("translates a bare gateway error into plain language", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => errorResponse(502, "upstream boom")));
    await expect(runWithTimers(() => api.getList("watch"))).rejects.toThrow(
      /temporarily unavailable/,
    );
  });

  it("translates an unlabelled status into a readable message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => errorResponse(418, "not json at all")));
    await expect(runWithTimers(() => api.getList("watch"))).rejects.toThrow(
      /Something went wrong \(error 418\)/,
    );
  });

  it("retries a network failure and succeeds on a later attempt", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(["AAPL"]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.getList("watch"))).resolves.toEqual(["AAPL"]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("gives up after the retry budget and flags a cold start", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const error = await runWithTimers(() => api.getList("watch")).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.isColdStart).toBe(true);
    expect(error.message).toMatch(/waking up/);
    // Initial attempt plus two retries.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe("api url construction", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function captureUrl() {
    // Typed with the url parameter so `mock.calls[0][0]` is reachable.
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("encodes caret index symbols so the path survives", async () => {
    const fetchMock = captureUrl();
    await runWithTimers(() => api.getHistory("^GSPC", "1Y"));
    expect(fetchMock.mock.calls[0][0]).toContain("%5EGSPC");
  });

  it("encodes search queries", async () => {
    const fetchMock = captureUrl();
    await runWithTimers(() => api.searchSymbols("johnson & johnson"));
    expect(fetchMock.mock.calls[0][0]).toContain("johnson%20%26%20johnson");
  });

  it("skips the request entirely for an empty quote list", async () => {
    const fetchMock = captureUrl();
    await runWithTimers(() => api.getQuotes([]));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("joins quote symbols into one batched request", async () => {
    const fetchMock = captureUrl();
    await runWithTimers(() => api.getQuotes(["AAPL", "MSFT"]));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("AAPL%2CMSFT");
  });
});
