import { describeElapsed, formatWritten, gradeEntry } from "../journal";
import type { JournalEntry, Quote } from "../types";

interface Props {
  entry: JournalEntry;
  quote: Quote | undefined;
  reviewDue: boolean;
  reviewAfterDays: number;
  onDelete: (id: string) => void;
  onMarkReviewed: (id: string) => void;
  onFollowUp?: (ticker: string) => void;
  /** Hidden on a per-company view, where every entry names the same one. */
  showTicker?: boolean;
}

/**
 * One entry, with the line that makes the whole thing worth keeping.
 *
 * "Written at $142.30 · now $189.44 · +33.1%" is the feature. It sits above
 * the text rather than below it, because the score is what makes you read the
 * reasoning again -- and reading the reasoning again is the entire point.
 */
export function JournalEntryCard({
  entry,
  quote,
  reviewDue,
  reviewAfterDays,
  onDelete,
  onMarkReviewed,
  onFollowUp,
  showTicker = true,
}: Props) {
  const verdict = gradeEntry(entry, quote);

  return (
    <article className={`journal-entry${reviewDue ? " review-due" : ""}`}>
      <header className="journal-head">
        {showTicker && <span className="journal-ticker">{entry.ticker}</span>}
        <span className="journal-date" title={formatWritten(entry.dateWritten)}>
          {formatWritten(entry.dateWritten)}
          <span className="journal-elapsed"> · {describeElapsed(entry.dateWritten)}</span>
        </span>

        <div className="journal-actions">
          {reviewDue && onFollowUp && (
            <button className="link-btn" onClick={() => onFollowUp(entry.ticker)}>
              Write a follow-up
            </button>
          )}
          {reviewDue && (
            <button className="link-btn" onClick={() => onMarkReviewed(entry.id)}>
              Mark reviewed
            </button>
          )}
          <button
            className="remove-btn"
            onClick={() => onDelete(entry.id)}
            title="Delete this entry"
            aria-label={`Delete the ${formatWritten(entry.dateWritten)} entry on ${entry.ticker}`}
          >
            ✕
          </button>
        </div>
      </header>

      <p className={`journal-verdict tone-${verdict.direction === "unknown" ? "flat" : verdict.direction}`}>
        {verdict.priceThen == null ? (
          // Honest about the gap rather than showing a dash that reads as a
          // rendering fault.
          <span className="journal-unscored">
            No price was recorded when this was written, so it can’t be scored.
          </span>
        ) : (
          <>
            <span className="journal-then">Written at {price(verdict.priceThen)}</span>
            <span className="journal-sep" aria-hidden="true"> · </span>
            <span className="journal-now">
              {verdict.priceNow == null ? "price unavailable" : `now ${price(verdict.priceNow)}`}
            </span>
            {verdict.changePercent != null && (
              <>
                <span className="journal-sep" aria-hidden="true"> · </span>
                <strong className="journal-return">
                  <span aria-hidden="true">
                    {verdict.direction === "up" ? "▲" : verdict.direction === "down" ? "▼" : "■"}
                  </span>{" "}
                  {signed(verdict.changePercent)}
                </strong>
              </>
            )}
          </>
        )}
      </p>

      <p className="journal-body">{entry.body}</p>

      {(entry.tags.length > 0 || reviewDue) && (
        <footer className="journal-foot">
          {entry.tags.map((tag) => (
            <span key={tag} className="journal-tag">
              {tag}
            </span>
          ))}
          {reviewDue && (
            <span className="journal-nudge">
              Over {reviewAfterDays} days old and never revisited
            </span>
          )}
        </footer>
      )}
    </article>
  );
}

const price = (v: number) => `$${v.toFixed(2)}`;
const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
