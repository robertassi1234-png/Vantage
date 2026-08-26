import type { FedRefreshResult, FedStatement, FundamentalsRow, SymbolMatch } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Free Render instances sleep when idle and take ~50s to wake up. */
const COLD_START_RETRIES = 2;
const COLD_START_DELAY_MS = 4000;

export class ApiError extends Error {
  isColdStart: boolean;

  constructor(message: string, isColdStart = false) {
    super(message);
    this.name = "ApiError";
    this.isColdStart = isColdStart;
  }
}

function friendlyServerError(status: number, body: string): string {
  const detail = (() => {
    try {
      const parsed = JSON.parse(body);
      return typeof parsed?.detail === "string" ? parsed.detail : null;
    } catch {
      return null;
    }
  })();

  if (detail) return detail;
  if (status === 502 || status === 503 || status === 504) {
    return "The data service is temporarily unavailable. Try again in a moment.";
  }
  return `Something went wrong (error ${status}).`;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  for (let attempt = 0; attempt <= COLD_START_RETRIES; attempt++) {
    try {
      const res = await fetch(`${BASE_URL}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });

      if (!res.ok) {
        throw new ApiError(friendlyServerError(res.status, await res.text()));
      }
      return (await res.json()) as T;
    } catch (e) {
      // A failed fetch (as opposed to an error response) means we never reached
      // the server -- usually a sleeping free-tier instance waking up.
      if (e instanceof ApiError) throw e;
      if (attempt < COLD_START_RETRIES) await sleep(COLD_START_DELAY_MS);
    }
  }

  throw new ApiError(
    "Couldn't reach the server. It may be waking up from sleep — wait about a " +
      "minute and try again.",
    true,
  );
}

export const api = {
  searchSymbols: (query: string) =>
    request<SymbolMatch[]>(`/api/search?q=${encodeURIComponent(query)}`),

  getWatchlist: () => request<string[]>("/api/watchlist"),

  addTicker: (ticker: string) =>
    request<string[]>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    }),

  removeTicker: (ticker: string) =>
    request<string[]>(`/api/watchlist/${encodeURIComponent(ticker)}`, {
      method: "DELETE",
    }),

  getFundamentals: (refresh = false) =>
    request<FundamentalsRow[]>(`/api/fundamentals?refresh=${refresh}`),

  getFedTimeline: () => request<FedStatement[]>("/api/fed/timeline"),

  refreshFedTimeline: () =>
    request<FedRefreshResult>("/api/fed/refresh", { method: "POST" }),
};
