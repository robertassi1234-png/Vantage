import type {
  IndexQuote,
  JournalEntry,
  Lot,
  MarketGroup,
  PriceAlert,
  Quote,
  SplitAdjustment,
  WatchlistEntry,
} from "./types";

/**
 * The last dashboard this browser saw, kept so the next visit paints instantly.
 *
 * The server sleeps after fifteen idle minutes and takes the better part of a
 * minute to wake, during which the app has nothing to show. Almost all of
 * that wait is spent looking at a page the reader has seen before: the same
 * watchlist, the same tickers, prices a few hours old. Painting that
 * immediately and refreshing underneath turns a blank half-minute into a
 * page that is simply a little behind.
 *
 * Held per identity, because the watchlist belongs to whoever is signed in
 * and signing out must not leave the previous account's list on screen.
 * Prices are marked with their age wherever they are shown, since a stale
 * number presented as live is worse than no number.
 */

const KEY = "vantage.snapshot.v1";
// Beyond this the figures are too old to be worth showing even briefly.
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

export interface Snapshot {
  identity: string;
  savedAt: number;
  entries: WatchlistEntry[];
  quotes: Quote[];
  indices: IndexQuote[];
  board: MarketGroup[];
  alerts: PriceAlert[];
  trends: Record<string, number[]>;
  lots: Lot[];
  splits: SplitAdjustment[];
  journal: JournalEntry[];
}

/**
 * Whether a stored value still matches what the components expect.
 *
 * This is the part that has to be paranoid. A snapshot written by an older
 * build sits in storage indefinitely, so the day a field is renamed the next
 * visit hands stale-shaped data straight into a render -- and because storage
 * survives the reload, a white screen from that would repeat forever rather
 * than clear itself. Anything that does not look right is discarded whole:
 * the cost is one slow load, against a page that never comes back.
 */
function looksUsable(snapshot: Snapshot): boolean {
  const arrays = [
    snapshot.entries,
    snapshot.quotes,
    snapshot.indices,
    snapshot.alerts,
    snapshot.lots,
    snapshot.splits,
    snapshot.journal,
  ];
  if (!arrays.every(Array.isArray)) return false;
  // A snapshot with no watchlist saves nothing worth showing.
  if (snapshot.entries.length === 0) return false;
  if (!snapshot.entries.every((e) => e && typeof e.ticker === "string")) return false;

  if (!Array.isArray(snapshot.board)) return false;
  // The board renders as groups of tiles, and maps over both levels.
  const groupsAreShaped = snapshot.board.every(
    (g) => g && typeof g.group === "string" && Array.isArray(g.entries),
  );
  if (!groupsAreShaped) return false;

  // Lots drive money figures, so a malformed one is worse than none: a share
  // count read as undefined would render a portfolio worth NaN.
  const lotsAreShaped = snapshot.lots.every(
    (l) => l && typeof l.shares === "number" && typeof l.costPerShare === "number",
  );
  if (!lotsAreShaped) return false;

  if (!snapshot.trends || typeof snapshot.trends !== "object") return false;
  return Object.values(snapshot.trends).every(Array.isArray);
}

export function readSnapshot(identity: string): Snapshot | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;

    const snapshot = JSON.parse(raw) as Snapshot;
    if (snapshot.identity !== identity) return null;
    if (!(typeof snapshot.savedAt === "number")) return null;
    if (Date.now() - snapshot.savedAt > MAX_AGE_MS) return null;
    if (!looksUsable(snapshot)) {
      // Written by a build that shaped things differently. It will never
      // become readable, so drop it rather than re-checking it every visit.
      clearSnapshot();
      return null;
    }

    return snapshot;
  } catch {
    // Corrupt, or storage blocked. Neither is worth failing a page load over.
    return null;
  }
}

export function writeSnapshot(snapshot: Omit<Snapshot, "savedAt">): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...snapshot, savedAt: Date.now() }));
  } catch {
    // Private mode, or the quota is full. The app works without it.
  }
}

export function clearSnapshot(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}

/** "3 minutes ago", for saying plainly how old the figures on screen are. */
export function describeAge(savedAt: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - savedAt) / 1000));
  if (seconds < 60) return "moments ago";

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return "yesterday";
}
