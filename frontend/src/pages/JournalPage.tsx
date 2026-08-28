import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { JournalComposer } from "../components/JournalComposer";
import { JournalEntryCard } from "../components/JournalEntryCard";
import { TickerSearch } from "../components/TickerSearch";
import { filterByTags, tagCounts } from "../journal";
import type { JournalEntry, Quote } from "../types";

/**
 * Everything you have written, newest first, each graded against what
 * happened since.
 *
 * The review nudge sits at the top rather than mixed into the list. An entry
 * is most useful exactly when it has stopped being read, and a journal that
 * only ever grows is a graveyard -- surfacing the old ones is what keeps it
 * honest.
 */
export function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [reviewDue, setReviewDue] = useState<string[]>([]);
  const [suggestedTags, setSuggestedTags] = useState<string[]>([]);
  const [reviewAfterDays, setReviewAfterDays] = useState(90);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [writingAbout, setWritingAbout] = useState<string | null>(null);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [onlyDue, setOnlyDue] = useState(false);

  const apply = useCallback(
    (body: { entries: JournalEntry[]; review_due: string[]; suggested_tags: string[]; review_after_days: number }) => {
      setEntries(body.entries);
      setReviewDue(body.review_due);
      setSuggestedTags(body.suggested_tags);
      setReviewAfterDays(body.review_after_days);
      return body.entries;
    },
    [],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const written = apply(await api.getJournal());

      // Quotes for whatever has been written about, so every entry can be
      // scored. Prices failing costs the scores, not the journal.
      const tickers = [...new Set(written.map((e) => e.ticker))];
      api.getQuotes(tickers).then(setQuotes).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    load();
  }, [load]);

  const quoteFor = useMemo(() => new Map(quotes.map((q) => [q.symbol, q])), [quotes]);
  const counts = useMemo(() => tagCounts(entries), [entries]);
  const dueSet = useMemo(() => new Set(reviewDue), [reviewDue]);
  const visible = useMemo(() => {
    const tagged = filterByTags(entries, selectedTags);
    return onlyDue ? tagged.filter((e) => dueSet.has(e.id)) : tagged;
  }, [entries, selectedTags, onlyDue, dueSet]);

  function toggleTag(tag: string) {
    setSelectedTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  }

  async function handleWrite(ticker: string, entry: { body: string; tags: string[]; priceAtWrite: number | null }) {
    apply(await api.addJournalEntry(ticker, entry));
    setWritingAbout(null);
  }

  async function handleDelete(id: string) {
    try {
      apply(await api.deleteJournalEntry(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleMarkReviewed(id: string) {
    try {
      apply(await api.markJournalReviewed(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const cardProps = (entry: JournalEntry) => ({
    entry,
    quote: quoteFor.get(entry.ticker),
    reviewDue: dueSet.has(entry.id),
    reviewAfterDays,
    onDelete: handleDelete,
    onMarkReviewed: handleMarkReviewed,
    onFollowUp: setWritingAbout,
  });

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Thesis journal</h2>
          <p className="page-subtitle">
            What you thought, when you thought it, and what the price has done since.
          </p>
        </div>
      </div>

      <TickerSearch onSelect={setWritingAbout} disabled={loading} />

      {writingAbout && (
        <div className="journal-writing">
          <h3 className="section-heading">
            Writing about {writingAbout}
            <span className="section-note">You’ll read this back in a year</span>
          </h3>
          <JournalComposer
            ticker={writingAbout}
            priceNow={quoteFor.get(writingAbout)?.price ?? null}
            suggestedTags={suggestedTags}
            autoFocus
            onSubmit={(entry) => handleWrite(writingAbout, entry)}
            onCancel={() => setWritingAbout(null)}
          />
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          <p>{error}</p>
        </div>
      )}

      {/* A prompt rather than a second copy of the entries. Rendering the due
          ones in their own section above meant every one of them appeared
          twice on the page, each with its own set of buttons. */}
      {reviewDue.length > 0 && (
        <p className="journal-nudge-banner">
          <span>
            {reviewDue.length} {reviewDue.length === 1 ? "entry has" : "entries have"} gone over{" "}
            {reviewAfterDays} days without a second look. That is usually when they are worth
            reading.
          </span>
          <button className="link-btn" onClick={() => setOnlyDue((v) => !v)}>
            {onlyDue ? "Show everything" : "Show me"}
          </button>
        </p>
      )}

      {counts.length > 0 && (
        <div className="journal-filter" role="group" aria-label="Filter by tag">
          {counts.map(({ tag, count }) => (
            <button
              key={tag}
              className={`tag-chip${selectedTags.includes(tag) ? " active" : ""}`}
              onClick={() => toggleTag(tag)}
              aria-pressed={selectedTags.includes(tag)}
            >
              {tag} <span className="tag-count">{count}</span>
            </button>
          ))}
          {selectedTags.length > 0 && (
            <button className="link-btn" onClick={() => setSelectedTags([])}>
              Clear
            </button>
          )}
        </div>
      )}

      <h3 className="section-heading">
        {onlyDue
          ? "Worth revisiting"
          : selectedTags.length > 0
            ? `Tagged ${selectedTags.join(" + ")}`
            : "Everything you’ve written"}
        <span className="section-note">
          {visible.length} {visible.length === 1 ? "entry" : "entries"}
        </span>
      </h3>

      {loading && entries.length === 0 ? (
        <div className="empty-state">
          <p>Loading your journal…</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="empty-state">
          <span className="empty-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
                 strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 4h11l5 5v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
              <path d="M14 4v6h6M8 14h7M8 17h5" />
            </svg>
          </span>
          <p className="empty-title">
            {entries.length === 0
              ? "Nothing written yet"
              : onlyDue
                ? "Nothing due for review"
                : "Nothing with those tags"}
          </p>
          <p>
            {entries.length === 0
              ? "Search a company above and write down why you're interested. The price is saved with it, so in a year you can see whether you were right."
              : "Clear the filter to see the rest."}
          </p>
        </div>
      ) : (
        <div className="journal-list">
          {visible.map((entry) => (
            <JournalEntryCard key={entry.id} {...cardProps(entry)} />
          ))}
        </div>
      )}
    </section>
  );
}
