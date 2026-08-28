import { useEffect, useRef, useState } from "react";
import { Sparkline } from "./Sparkline";
import type { Quote, WatchlistEntry } from "../types";

interface Props {
  /** The watchlist itself. Rows come from here, never from the quotes. */
  entries: WatchlistEntry[];
  quotes: Quote[];
  /** Recent closes per symbol, for the row trend line. Optional and best-effort. */
  trends?: Record<string, number[]>;
  onSelect: (symbol: string, label: string) => void;
  onRemove: (symbol: string) => void;
  onSaveNote: (symbol: string, note: string) => void | Promise<void>;
  activeSymbol?: string | null;
}

/** A row with no quote yet: the ticker is known, the pricing is not. */
const placeholderQuote = (symbol: string): Quote => ({
  symbol,
  name: null,
  price: null,
  change: null,
  changePercent: null,
  dayLow: null,
  dayHigh: null,
  yearLow: null,
  yearHigh: null,
  marketCap: null,
  volume: null,
});

const fmtPrice = (v: number | null) => (typeof v === "number" ? `$${v.toFixed(2)}` : "—");

const fmtChange = (v: number | null) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}` : "—";

const fmtPercent = (v: number | null) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";

/** Where today's price sits inside the 52-week range, as a 0-1 fraction. */
function yearPosition(q: Quote): number | null {
  if (q.price == null || q.yearLow == null || q.yearHigh == null) return null;
  const span = q.yearHigh - q.yearLow;
  if (span <= 0) return null;
  return Math.min(Math.max((q.price - q.yearLow) / span, 0), 1);
}

export function WatchlistPanel({
  entries,
  quotes,
  trends = {},
  onSelect,
  onRemove,
  onSaveNote,
  activeSymbol,
}: Props) {
  const [editing, setEditing] = useState<string | null>(null);

  // Empty means the list is empty -- not that pricing failed. Deriving rows
  // from the quotes made a working watchlist look unsaved whenever the market
  // data provider was throttling.
  if (entries.length === 0) {
    return (
      <div className="empty-state">
        <p className="empty-title">Your watchlist is empty</p>
        <p>Search for a company above to add it. You'll see its price, today's move, and where it sits in its 52-week range.</p>
      </div>
    );
  }

  const quoteFor = new Map(quotes.map((q) => [q.symbol, q]));
  const unpriced = entries.filter((e) => quoteFor.get(e.ticker)?.price == null).length;

  return (
    <>
      {unpriced > 0 && (
        <p className="notice-line">
          {unpriced === entries.length
            ? "Prices are unavailable right now — your list is safe, try Refresh in a moment."
            : `${unpriced} of these couldn't be priced right now.`}
        </p>
      )}
      <ul className="watchlist">
      {entries.map((entry) => {
        const q = quoteFor.get(entry.ticker) ?? placeholderQuote(entry.ticker);
        const pct = q.changePercent;
        const direction = pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
        const pos = yearPosition(q);
        const isEditing = editing === q.symbol;

        return (
          <li key={q.symbol} className={`watch-row tone-${direction}${activeSymbol === q.symbol ? " active" : ""}`}>
            <div className="watch-line">
              <button className="watch-main" onClick={() => onSelect(q.symbol, q.name ?? q.symbol)}>
                <span className="watch-symbol">{q.symbol}</span>
                <span className="watch-name">{q.name ?? "Price unavailable"}</span>

                {/* The row had a wide empty gap between the name and the
                    price. A trend line is the most useful thing that can go
                    there: it answers "and what has it been doing?" without a
                    click. */}
                <span className="watch-spark">
                  {trends[q.symbol]?.length ? (
                    <Sparkline
                      values={trends[q.symbol]}
                      direction={direction}
                      width={96}
                      height={26}
                    />
                  ) : null}
                </span>

                <span className="watch-price">{fmtPrice(q.price)}</span>
                <span className="watch-delta">
                  <span aria-hidden="true">
                    {direction === "down" ? "▼" : direction === "up" ? "▲" : "■"}
                  </span>{" "}
                  {fmtChange(q.change)} ({fmtPercent(pct)})
                </span>

                <span className="watch-range" title="Where today's price sits between the 52-week low and high">
                  {pos == null ? (
                    <span className="watch-range-na">—</span>
                  ) : (
                    <>
                      <span className="range-low">{q.yearLow?.toFixed(0)}</span>
                      <span className="range-track">
                        <span className="range-marker" style={{ left: `${pos * 100}%` }} />
                      </span>
                      <span className="range-high">{q.yearHigh?.toFixed(0)}</span>
                    </>
                  )}
                </span>
              </button>

              <button
                className={`note-btn${entry.note ? " has-note" : ""}`}
                onClick={() => setEditing(isEditing ? null : q.symbol)}
                aria-expanded={isEditing}
                title={entry.note ? `Edit your note on ${q.symbol}` : `Add a note on ${q.symbol}`}
                aria-label={entry.note ? `Edit your note on ${q.symbol}` : `Add a note on ${q.symbol}`}
              >
                <span aria-hidden="true">✎</span>
              </button>

              <button
                className="remove-btn"
                onClick={() => onRemove(q.symbol)}
                title={`Remove ${q.symbol}`}
                aria-label={`Remove ${q.symbol}`}
              >
                ✕
              </button>
            </div>

            {isEditing ? (
              <NoteEditor
                symbol={q.symbol}
                note={entry.note ?? ""}
                onSave={async (text) => {
                  await onSaveNote(q.symbol, text);
                  setEditing(null);
                }}
                onCancel={() => setEditing(null)}
              />
            ) : (
              entry.note && <p className="watch-note">{entry.note}</p>
            )}
          </li>
        );
      })}
      </ul>
    </>
  );
}

interface NoteEditorProps {
  symbol: string;
  note: string;
  onSave: (note: string) => void | Promise<void>;
  onCancel: () => void;
}

/**
 * Why you added a stock, in your own words.
 *
 * The numbers say what a company is doing; they never say what you were
 * thinking when you started watching it. Six months later that is the part
 * worth having.
 */
function NoteEditor({ symbol, note, onSave, onCancel }: NoteEditorProps) {
  const [text, setText] = useState(note);
  const [saving, setSaving] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    field.current?.focus();
    // Put the caret after existing text rather than selecting it, so typing
    // adds to a note instead of replacing it.
    field.current?.setSelectionRange(note.length, note.length);
  }, [note]);

  async function save() {
    setSaving(true);
    try {
      await onSave(text.trim());
    } finally {
      setSaving(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") onCancel();
    // Enter saves; Shift+Enter is a newline, as in every chat box.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void save();
    }
  }

  return (
    <div className="note-editor">
      <label className="sr-only" htmlFor={`note-${symbol}`}>
        Your note on {symbol}
      </label>
      <textarea
        id={`note-${symbol}`}
        ref={field}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        maxLength={500}
        placeholder={`Why are you watching ${symbol}?`}
      />
      <div className="note-actions">
        <button className="btn btn-small" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="ghost-btn" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <span className="note-hint">Enter to save · Esc to cancel</span>
      </div>
    </div>
  );
}
