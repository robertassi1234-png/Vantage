import type { Quote } from "../types";

interface Props {
  quotes: Quote[];
  onSelect: (symbol: string, label: string) => void;
  onRemove: (symbol: string) => void;
  activeSymbol?: string | null;
}

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

export function WatchlistPanel({ quotes, onSelect, onRemove, activeSymbol }: Props) {
  if (quotes.length === 0) {
    return (
      <div className="empty-state">
        <p className="empty-title">Your watchlist is empty</p>
        <p>Search for a company above to add it. You'll see its price, today's move, and where it sits in its 52-week range.</p>
      </div>
    );
  }

  return (
    <ul className="watchlist">
      {quotes.map((q) => {
        const pct = q.changePercent;
        const direction = pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
        const pos = yearPosition(q);

        return (
          <li key={q.symbol} className={`watch-row tone-${direction}${activeSymbol === q.symbol ? " active" : ""}`}>
            <button className="watch-main" onClick={() => onSelect(q.symbol, q.name ?? q.symbol)}>
              <span className="watch-symbol">{q.symbol}</span>
              <span className="watch-name">{q.name ?? "—"}</span>

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
  );
}
