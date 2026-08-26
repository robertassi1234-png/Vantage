import type { FedRefreshResult, FedStatement, FundamentalsRow } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
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
