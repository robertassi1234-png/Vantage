import type {
  FedRefreshResult,
  FedStatement,
  FundamentalsRow,
  JournalEntry,
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
  PeerSuggestions,
  MarketGroup,
  PositionsResponse,
  JournalResponse,
  ValuationResponse,
  ProviderStatus,
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

  // FastAPI answers an unknown path with a bare "Not Found", which as a
  // message tells the reader nothing. It means the server is running an
  // older build than the page is -- the site and the API deploy separately,
  // so one can be minutes ahead of the other.
  if (status === 404 && (!detail || detail === "Not Found")) {
    return (
      "This part of the app isn't on the server yet — it's probably still " +
      "deploying. Wait a minute and reload."
    );
  }

  if (detail) return detail;
  if (status === 502 || status === 503 || status === 504) {
    return "The data service is temporarily unavailable. Try again in a moment.";
  }
  return `Something went wrong (error ${status}).`;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Whether to send the session cookie.
 *
 * "include" is what accounts need. But a browser refuses outright to send a
 * credentialed request to an API that answers with a wildcard origin, and it
 * refuses the whole request, not just the cookie -- so a server configured
 * that way would fail every call rather than just failing to sign anyone in.
 * Dropping to "omit" there gives back the signed-out app, which is exactly
 * what a wildcard server can offer.
 */
let credentials: RequestCredentials = "include";

/** True once a credentialed request was refused and we fell back. */
export function isAnonymousOnly(): boolean {
  return credentials === "omit";
}

let probe: Promise<boolean> | null = null;

/** Reset between tests; the mode is otherwise sticky for the page's life. */
export function resetCredentialsMode(): void {
  credentials = "include";
  probe = null;
}

const reachable = async (mode: RequestCredentials) => {
  try {
    return (await fetch(`${BASE_URL}/api/health`, { credentials: mode })).ok;
  } catch {
    return false;
  }
};

/**
 * Is the server up, and refusing us specifically because of the cookie?
 *
 * A CORS refusal, a sleeping instance and a flaky connection are all the same
 * "Failed to fetch" to JavaScript, so the same health check is run both ways
 * and the answers compared. Only "fails with the cookie, succeeds without it"
 * means the cookie is the problem.
 *
 * Testing just the cookie-less call would be wrong: a single dropped request
 * against a perfectly healthy server would look identical, and we would stop
 * sending the session cookie for the rest of the visit -- quietly signing out
 * someone who was signed in.
 */
function serverRefusesCredentials(): Promise<boolean> {
  // The page loads several requests at once, and they fail together. Sharing
  // one probe keeps that from becoming a burst of identical health checks.
  probe ??= (async () => {
    try {
      const [withCookie, withoutCookie] = await Promise.all([
        reachable("include"),
        reachable("omit"),
      ]);
      return !withCookie && withoutCookie;
    } finally {
      // Cleared so a later failure -- a genuinely sleeping server, say -- is
      // diagnosed afresh rather than reusing this answer.
      setTimeout(() => {
        probe = null;
      }, 0);
    }
  })();
  return probe;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  for (let attempt = 0; attempt <= COLD_START_RETRIES; attempt++) {
    try {
      const res = await fetch(`${BASE_URL}${path}`, {
        ...options,
        credentials,
        headers: {
          "Content-Type": "application/json",
          // Scopes the watchlist to this browser so two people opening the
          // same URL don't share one list. This is what carries identity
          // once the cookie has been ruled out.
          "X-Vantage-Space": getSpaceId(),
          ...options?.headers,
        },
      });

      if (!res.ok) {
        throw new ApiError(friendlyServerError(res.status, await res.text()));
      }
      return (await res.json()) as T;
    } catch (e) {
      // A failed fetch (as opposed to an error response) means the response
      // never arrived -- a sleeping instance, or a cookie the browser
      // refused to send.
      if (e instanceof ApiError) throw e;

      // Only on the first failure: on a sleeping server every attempt would
      // otherwise carry a probe, doubling the requests in the common case.
      if (attempt === 0 && credentials === "include") {
        if (await serverRefusesCredentials()) {
          credentials = "omit";
          continue; // Retry immediately: the server is awake, not asleep.
        }
      }

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

  getPeers: () => request<PeerSuggestions>("/api/peers"),

  getPositions: () => request<PositionsResponse>("/api/positions"),

  addLot: (ticker: string, lot: { shares: number; costPerShare: number; tradeDate: string; note?: string | null }) =>
    request<PositionsResponse>(`/api/positions/${encodeURIComponent(ticker)}/lots`, {
      method: "POST",
      body: JSON.stringify({ note: null, ...lot }),
    }),

  deleteLot: (id: string) =>
    request<PositionsResponse>(`/api/positions/lots/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  applySplit: (ticker: string, ratio: number) =>
    request<PositionsResponse>(`/api/positions/${encodeURIComponent(ticker)}/split`, {
      method: "POST",
      body: JSON.stringify({ ratio }),
    }),

  undoSplit: (id: string) =>
    request<PositionsResponse>(`/api/positions/splits/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  getJournal: (ticker?: string) =>
    request<JournalResponse>(
      ticker ? `/api/journal?ticker=${encodeURIComponent(ticker)}` : "/api/journal",
    ),

  addJournalEntry: (
    ticker: string,
    entry: { body: string; tags: string[]; priceAtWrite: number | null },
  ) =>
    request<JournalResponse & { entry: JournalEntry }>(
      `/api/journal/${encodeURIComponent(ticker)}`,
      { method: "POST", body: JSON.stringify(entry) },
    ),

  deleteJournalEntry: (id: string) =>
    request<JournalResponse>(`/api/journal/${encodeURIComponent(id)}`, { method: "DELETE" }),

  markJournalReviewed: (id: string) =>
    request<JournalResponse>(`/api/journal/${encodeURIComponent(id)}/reviewed`, {
      method: "POST",
    }),

  getProviderStatus: () => request<ProviderStatus>("/api/market/providers"),

  getValuation: (refresh = false) =>
    request<ValuationResponse>(`/api/valuation?refresh=${refresh}`),

  getFundamentals: (refresh = false) =>
    request<FundamentalsRow[]>(`/api/fundamentals?refresh=${refresh}`),

  getTrends: (symbols: string[]) =>
    symbols.length === 0
      ? Promise.resolve({} as Record<string, number[]>)
      : request<Record<string, number[]>>(
          `/api/market/trends?symbols=${encodeURIComponent(symbols.join(","))}`,
        ),

  getMarketBoard: (refresh = false) =>
    request<MarketGroup[]>(`/api/market/board?refresh=${refresh}`),

  getIndices: (refresh = false) =>
    request<IndexQuote[]>(`/api/market/indices?refresh=${refresh}`),

  getQuotes: (symbols: string[], refresh = false) =>
    symbols.length === 0
      ? Promise.resolve([] as Quote[])
      : request<Quote[]>(
          `/api/market/quotes?symbols=${encodeURIComponent(symbols.join(","))}&refresh=${refresh}`,
        ),

  getHistory: async (symbol: string, range: RangeKey) => {
    const history = await request<PriceHistory>(
      `/api/market/history/${encodeURIComponent(symbol)}?range=${range}`,
    );
    // A response missing its points used to reach the chart as undefined and
    // take the whole page down with it. An empty chart is the honest result.
    return { ...history, points: history?.points ?? [] };
  },

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
