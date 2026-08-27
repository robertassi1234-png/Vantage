import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, isAnonymousOnly, resetCredentialsMode } from "./api";

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
    resetCredentialsMode();
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
    // Health checks are counted separately: a failure also triggers one
    // diagnostic probe, which is not a retry of the request itself.
    let listCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith("/api/health")) throw new TypeError("Failed to fetch");
      listCalls += 1;
      if (listCalls === 1) throw new TypeError("Failed to fetch");
      return jsonResponse(["AAPL"]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.getList("watch"))).resolves.toEqual(["AAPL"]);
    expect(listCalls).toBe(2);
  });

  it("gives up after the retry budget and flags a cold start", async () => {
    let listCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (!String(url).endsWith("/api/health")) listCalls += 1;
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetchMock);

    const error = await runWithTimers(() => api.getList("watch")).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.isColdStart).toBe(true);
    expect(error.message).toMatch(/waking up/);
    // Initial attempt plus two retries.
    expect(listCalls).toBe(3);
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

/**
 * The regression these exist for: every request began sending
 * `credentials: "include"` for the session cookie, and a browser refuses such
 * a request outright when the API answers with a wildcard origin. It refuses
 * the whole request, not just the cookie, so a server left on CORS_ORIGINS=*
 * failed every single call and the app looked completely offline.
 */
describe("credentialed requests being refused", () => {
  const corsBlocked = () => Promise.reject(new TypeError("Failed to fetch"));

  beforeEach(() => {
    vi.useFakeTimers();
    resetCredentialsMode();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    resetCredentialsMode();
  });

  it("sends the session cookie by default", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(["AAPL"]));
    vi.stubGlobal("fetch", fetchMock);

    await runWithTimers(() => api.getList("watch"));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
  });

  it("retries without the cookie when a live server refuses it", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.credentials === "include") return corsBlocked();
      if (url.endsWith("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse(["AAPL"]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.getList("watch"))).resolves.toEqual(["AAPL"]);
    expect(isAnonymousOnly()).toBe(true);
  });

  it("stays without the cookie for later requests", async () => {
    // Re-testing on every call would double the request count for the
    // whole session.
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.credentials === "include") return corsBlocked();
      if (url.endsWith("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await runWithTimers(() => api.getList("watch"));
    fetchMock.mockClear();
    await runWithTimers(() => api.getList("compare"));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "omit" });
  });

  it("does not fall back when the server is genuinely unreachable", async () => {
    // A sleeping instance must still read as a cold start, not as a CORS
    // problem -- otherwise the app silently drops the cookie for no reason.
    vi.stubGlobal("fetch", vi.fn(corsBlocked));

    await expect(runWithTimers(() => api.getList("watch"))).rejects.toThrow(/waking up/i);
    expect(isAnonymousOnly()).toBe(false);
  });

  it("does not fall back on an error response", async () => {
    // A 500 reached the server, so the cookie was accepted.
    vi.stubGlobal("fetch", vi.fn(async () => errorResponse(500, "boom")));

    await expect(runWithTimers(() => api.getList("watch"))).rejects.toBeInstanceOf(ApiError);
    expect(isAnonymousOnly()).toBe(false);
  });

  it("probes once for a burst of simultaneous failures", async () => {
    // The dashboard fires several requests at mount; they fail together.
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.credentials === "include") return corsBlocked();
      if (url.endsWith("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await runWithTimers(() =>
      Promise.all([api.getList("watch"), api.getList("compare"), api.getAlerts()]),
    );

    // One diagnosis, not one per request -- though it asks both ways.
    const probes = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/health"));
    expect(probes).toHaveLength(2);
  });

  it("keeps the browser-space header, which is what identifies you without a cookie", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.credentials === "include") return corsBlocked();
      if (url.endsWith("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await runWithTimers(() => api.getList("watch"));
    const last = fetchMock.mock.calls[fetchMock.mock.calls.length - 1][1] as RequestInit;
    expect((last.headers as Record<string, string>)["X-Vantage-Space"]).toBeTruthy();
  });

  it("still writes, not just reads, after falling back", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.credentials === "include") return corsBlocked();
      if (url.endsWith("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse(["AAPL"]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.addToList("watch", "AAPL"))).resolves.toEqual(["AAPL"]);
  });
});

describe("telling a cookie problem apart from a flaky one", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetCredentialsMode();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    resetCredentialsMode();
  });

  it("keeps sending the cookie when one request just fell over", async () => {
    // The bug this guards: probing only without the cookie makes a single
    // dropped request against a healthy server look exactly like a CORS
    // refusal, which would quietly sign out someone who was signed in.
    let listCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith("/api/health")) return jsonResponse({ status: "ok" });
      listCalls += 1;
      if (listCalls === 1) throw new TypeError("Failed to fetch");
      return jsonResponse(["AAPL"]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.getList("watch"))).resolves.toEqual(["AAPL"]);
    expect(isAnonymousOnly()).toBe(false);
  });

  it("falls back only when the cookie is what the server rejects", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.credentials === "include") throw new TypeError("Failed to fetch");
      if (String(url).endsWith("/api/health")) return jsonResponse({ status: "ok" });
      return jsonResponse(["AAPL"]);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(runWithTimers(() => api.getList("watch"))).resolves.toEqual(["AAPL"]);
    expect(isAnonymousOnly()).toBe(true);
  });

  it("does not fall back when the whole server is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));

    await expect(runWithTimers(() => api.getList("watch"))).rejects.toThrow(/waking up/i);
    expect(isAnonymousOnly()).toBe(false);
  });
});

describe("a server running an older build than the page", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetCredentialsMode();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    resetCredentialsMode();
  });

  it("explains a bare 404 instead of relaying \"Not Found\"", async () => {
    // The site and the API deploy separately, so the page can call a route
    // the running server does not have yet. "Not Found" tells nobody that.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => errorResponse(404, JSON.stringify({ detail: "Not Found" }))),
    );

    await expect(runWithTimers(() => api.requestSignInLink("a@b.com"))).rejects.toThrow(
      /still deploying/i,
    );
  });

  it("keeps a 404 that actually says something useful", async () => {
    // An unknown list name is a real 404 with a real explanation.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        errorResponse(404, JSON.stringify({ detail: "Unknown list 'portfolio'." })),
      ),
    );

    await expect(runWithTimers(() => api.getList("watch" as never))).rejects.toThrow(
      /Unknown list 'portfolio'/,
    );
  });
});
