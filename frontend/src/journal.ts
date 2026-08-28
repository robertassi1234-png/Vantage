import type { JournalEntry, Quote } from "./types";

/**
 * Grading what you wrote against what happened.
 *
 * The entry stores one number -- the price on the day it was written -- and
 * everything here compares that to a live quote. That single comparison is
 * what separates a journal from a notes app: it turns "I thought this was
 * cheap" into "I thought this was cheap at $142.30, and it is $189.44 now".
 */

export interface EntryVerdict {
  priceThen: number | null;
  priceNow: number | null;
  /** Return since the entry was written, as a percentage. */
  changePercent: number | null;
  direction: "up" | "down" | "flat" | "unknown";
}

export function gradeEntry(entry: JournalEntry, quote: Quote | undefined): EntryVerdict {
  const priceThen = entry.priceAtWrite;
  const priceNow = quote?.price ?? null;

  if (priceThen == null || priceNow == null || priceThen <= 0) {
    // An entry written while every provider was throttled has no stamp, and
    // no amount of arithmetic can invent one afterwards. It is still worth
    // reading; it just cannot be scored.
    return { priceThen, priceNow, changePercent: null, direction: "unknown" };
  }

  const changePercent = ((priceNow - priceThen) / priceThen) * 100;
  return {
    priceThen,
    priceNow,
    changePercent,
    direction: changePercent > 0 ? "up" : changePercent < 0 ? "down" : "flat",
  };
}

/** Every tag in use, most-used first, for the filter row. */
export function tagCounts(entries: JournalEntry[]): { tag: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const entry of entries) {
    for (const tag of entry.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

/** Entries carrying every selected tag. No selection means everything. */
export function filterByTags(entries: JournalEntry[], selected: string[]): JournalEntry[] {
  if (selected.length === 0) return entries;
  // Every tag rather than any: narrowing is the point of picking a second one.
  return entries.filter((entry) => selected.every((tag) => entry.tags.includes(tag)));
}

/** "4 March 2025" -- long enough to place, short enough to scan. */
export function formatWritten(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}

/** How long ago, in the units a reader thinks in. */
export function describeElapsed(iso: string, now = Date.now()): string {
  const written = new Date(iso).getTime();
  if (Number.isNaN(written)) return "";

  const days = Math.floor((now - written) / (24 * 60 * 60 * 1000));
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;

  const months = Math.round(days / 30);
  if (months < 18) return `${months} month${months === 1 ? "" : "s"} ago`;

  const years = (days / 365).toFixed(1).replace(/\.0$/, "");
  return `${years} years ago`;
}
