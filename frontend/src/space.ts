const STORAGE_KEY = "vantage.space";

/**
 * A per-browser id that keeps this browser's watchlist separate from anyone
 * else opening the same URL.
 *
 * Separation, not security: the id travels in a header and anyone holding it
 * can read that watchlist. It exists so two people don't edit one list, not to
 * keep secrets. Clearing site data starts a fresh, empty watchlist.
 */
function generateId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  // Older browsers: good enough for separating watchlists.
  return `s-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

let cached: string | null = null;

export function getSpaceId(): string {
  if (cached) return cached;

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      cached = stored;
      return stored;
    }
    const fresh = generateId();
    localStorage.setItem(STORAGE_KEY, fresh);
    cached = fresh;
    return fresh;
  } catch {
    // Private mode or blocked storage: stay usable for this page view rather
    // than failing, even though the watchlist won't survive a reload.
    cached ??= generateId();
    return cached;
  }
}

/** Replace this browser's workspace, e.g. to start over with an empty list. */
export function resetSpaceId(): string {
  cached = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing to clear */
  }
  return getSpaceId();
}
