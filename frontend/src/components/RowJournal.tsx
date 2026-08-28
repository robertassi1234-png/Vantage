import { useState } from "react";
import { JournalComposer } from "./JournalComposer";
import { describeElapsed, gradeEntry } from "../journal";
import type { JournalEntry, Quote } from "../types";

interface Props {
  ticker: string;
  quote: Quote | undefined;
  entries: JournalEntry[];
  suggestedTags: string[];
  onWrite: (
    ticker: string,
    entry: { body: string; tags: string[]; priceAtWrite: number | null },
  ) => Promise<void>;
}

/**
 * Writing a thesis from the row it is about.
 *
 * The second entry point, and the one that matters: the moment worth writing
 * something down is while looking at the price, not later on a separate page.
 * Only the most recent entry is shown here -- the rest are a tab away, and a
 * watchlist row is not where a year of thinking should be read.
 */
export function RowJournal({ ticker, quote, entries, suggestedTags, onWrite }: Props) {
  const [writing, setWriting] = useState(false);
  const latest = entries[0];

  return (
    <div className="row-journal">
      <div className="row-journal-head">
        <h4>Thesis</h4>
        {!writing && (
          <button className="link-btn" onClick={() => setWriting(true)}>
            {latest ? "Add an entry" : `Why ${ticker}?`}
          </button>
        )}
      </div>

      {latest && !writing && <LatestEntry entry={latest} quote={quote} count={entries.length} />}

      {!latest && !writing && (
        <p className="row-journal-empty">
          Nothing written yet. The price is saved with whatever you write, so in a year you can
          see whether you were right.
        </p>
      )}

      {writing && (
        <JournalComposer
          ticker={ticker}
          priceNow={quote?.price ?? null}
          suggestedTags={suggestedTags}
          autoFocus
          onSubmit={async (entry) => {
            await onWrite(ticker, entry);
            setWriting(false);
          }}
          onCancel={() => setWriting(false)}
        />
      )}
    </div>
  );
}

function LatestEntry({ entry, quote, count }: { entry: JournalEntry; quote: Quote | undefined; count: number }) {
  const verdict = gradeEntry(entry, quote);

  return (
    <div className="row-journal-latest">
      <p className={`journal-verdict tone-${verdict.direction === "unknown" ? "flat" : verdict.direction}`}>
        <span className="journal-elapsed">Written {describeElapsed(entry.dateWritten)}</span>
        {verdict.changePercent != null && (
          <>
            <span className="journal-sep" aria-hidden="true"> · </span>
            <span>at ${verdict.priceThen!.toFixed(2)}</span>
            <span className="journal-sep" aria-hidden="true"> · </span>
            <strong className="journal-return">
              <span aria-hidden="true">{verdict.direction === "up" ? "▲" : verdict.direction === "down" ? "▼" : "■"}</span>{" "}
              {`${verdict.changePercent > 0 ? "+" : verdict.changePercent < 0 ? "−" : ""}${Math.abs(verdict.changePercent).toFixed(1)}%`}
            </strong>
          </>
        )}
      </p>
      <p className="journal-body">{entry.body}</p>
      {count > 1 && (
        <p className="row-journal-more">
          {count - 1} earlier {count === 2 ? "entry" : "entries"} in the Journal tab.
        </p>
      )}
    </div>
  );
}
