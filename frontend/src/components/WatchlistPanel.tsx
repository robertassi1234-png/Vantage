import type { Quote } from "../types";

interface Props {
  /** The watchlist itself. Rows come from here, never from the quotes. */
  tickers: string[];
  quotes: Quote[];
  onSelect: (symbol: string, label: string) => void;
  onRemove: (symbol: string) => void;
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

export function WatchlistPanel({ tickers, quotes, onSelect, onRemove, activeSymbol }: Props) {
  // Empty means the list is empty -- not that pricing failed. Deriving rows
  // from the quotes made a working watchlist look unsaved whenever the market
  // data provider was throttling.
  if (tickers.length === 0) {
    return (
      <div className="empty-state">
        <p className="empty-title">Your watchlist is empty</p>
        <p>Search for a company above to add it. You'll see its price, today's move, and where it sits in its 52-week range.</p>
      </div>
    );
  }

  const quoteFor = new Map(quotes.map((q) => [q.symbol, q]));
  const rows = tickers.map((t) => quoteFor.get(t) ?? placeholderQuote(t));
  const unpriced = rows.filter((r) => r.price == null).length;

  return (
    <>
      {unpriced > 0 && (
        <p className="notice-line">
          {unpriced === rows.length
            ? "Prices are unavailable right now — your list is safe, try Refresh in a moment."
            : `${unpriced} of these couldn't be priced right now.`}
        </p>
      )}
      <ul className="watchlist">
      {rows.map((q) => {
        const pct = q.changePercent;
        const direction = pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
        const pos = yearPosition(q);

        return (
          <li key={q.symbol} className={`watch-row tone-${direction}${activeSymbol === q.symbol ? " active" : ""}`}>
            <button className="watch-main" onClick={() => onSelect(q.symbol, q.name ?? q.symbol)}>
              <span className="watch-symbol">{q.symbol}</span>
              <span className="watch-name">{q.name ?? "Price unavailable"}</span>

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
              className="remove-btn"
              onClick={() => onRemove(q.symbol)}
              title={`Remove ${q.symbol}`}
              aria-label={`Remove ${q.symbol}`}
            >
              ✕
            </button>
          </li>
        );
      })}
      </ul>
    </>
  );
}
