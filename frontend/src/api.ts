import type {
  FedRefreshResult,
  FedStatement,
  FundamentalsRow,
  IndexQuote,
  PriceHistory,
  Quote,
  RangeKey,
  SymbolMatch,
  ListName,
  WatchlistEntry,
  PriceAlert,
  AlertCheckResult,
  WorkspaceExport,
  ImportResult,
  Account,
  SignInLinkResult,
  SignInResult,
} from "./types";
import { getSpaceId } from "./space";

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
        ...options,
        // The session lives in an httpOnly cookie, which the browser only
        // attaches cross-origin when the request asks for credentials.
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          // Scopes the watchlist to this browser so two people opening the
          // same URL don't share one list.
          "X-Vantage-Space": getSpaceId(),
          ...options?.headers,
        },
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

  getList: (list: ListName) => request<string[]>(`/api/lists/${list}`),

  getListEntries: (list: ListName) =>
    request<WatchlistEntry[]>(`/api/lists/${list}/entries`),

  addToList: (list: ListName, ticker: string) =>
    request<string[]>(`/api/lists/${list}`, {
      method: "POST",
      body: JSON.stringify({ ticker }),
    }),

  removeFromList: (list: ListName, ticker: string) =>
    request<string[]>(`/api/lists/${list}/${encodeURIComponent(ticker)}`, {
      method: "DELETE",
    }),

  setNote: (list: ListName, ticker: string, note: string) =>
    request<WatchlistEntry[]>(`/api/lists/${list}/${encodeURIComponent(ticker)}/note`, {
      method: "PUT",
      body: JSON.stringify({ note }),
    }),

  getFundamentals: (refresh = false) =>
    request<FundamentalsRow[]>(`/api/fundamentals?refresh=${refresh}`),

  getIndices: (refresh = false) =>
    request<IndexQuote[]>(`/api/market/indices?refresh=${refresh}`),

  getQuotes: (symbols: string[], refresh = false) =>
    symbols.length === 0
      ? Promise.resolve([] as Quote[])
      : request<Quote[]>(
          `/api/market/quotes?symbols=${encodeURIComponent(symbols.join(","))}&refresh=${refresh}`,
        ),

  getHistory: (symbol: string, range: RangeKey) =>
    request<PriceHistory>(
      `/api/market/history/${encodeURIComponent(symbol)}?range=${range}`,
    ),

  getAccount: () => request<Account>("/api/auth/me"),

  requestSignInLink: (email: string) =>
    request<SignInLinkResult>("/api/auth/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  verifySignIn: (token: string, claimSpace = true) =>
    request<SignInResult>("/api/auth/verify", {
      method: "POST",
      body: JSON.stringify({ token, claim_space: claimSpace }),
    }),

  signOut: () => request<{ signed_in: boolean }>("/api/auth/signout", { method: "POST" }),

  getAlerts: () => request<PriceAlert[]>("/api/alerts"),

  createAlert: (ticker: string, direction: string, threshold: number, note?: string) =>
    request<PriceAlert>("/api/alerts", {
      method: "POST",
      body: JSON.stringify({ ticker, direction, threshold, note: note ?? null }),
    }),

  deleteAlert: (id: string) =>
    request<PriceAlert[]>(`/api/alerts/${encodeURIComponent(id)}`, { method: "DELETE" }),

  acknowledgeAlert: (id: string) =>
    request<PriceAlert[]>(`/api/alerts/${encodeURIComponent(id)}/acknowledge`, {
      method: "POST",
    }),

  checkAlerts: () => request<AlertCheckResult>("/api/alerts/check", { method: "POST" }),

  exportWorkspace: () => request<WorkspaceExport>("/api/export"),

  importWorkspace: (payload: WorkspaceExport, replace = false) =>
    request<ImportResult>(`/api/import?replace=${replace}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getFedTimeline: () => request<FedStatement[]>("/api/fed/timeline"),

  refreshFedTimeline: () =>
    request<FedRefreshResult>("/api/fed/refresh", { method: "POST" }),
};
