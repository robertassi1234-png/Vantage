import type { PeerSuggestion } from "../types";

interface Props {
  suggestions: PeerSuggestion[];
  loading: boolean;
  error: string | null;
  onAdd: (symbol: string) => void | Promise<void>;
  adding?: string | null;
}

const fmtPrice = (v: number | null | undefined) =>
  typeof v === "number" ? `$${v.toFixed(2)}` : null;

const fmtPercent = (v: number | null | undefined) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : null;

/** "because it's a peer of AAPL and MSFT" -- said the way a person would. */
function because(from: string[]): string {
  if (from.length === 1) return `Peer of ${from[0]}`;
  if (from.length === 2) return `Peer of ${from[0]} and ${from[1]}`;
  return `Peer of ${from.slice(0, -1).join(", ")} and ${from[from.length - 1]}`;
}

/**
 * Companies worth adding to the comparison.
 *
 * A multiple only means something next to competitors, and finding those by
 * hand needs the industry knowledge someone new to a name doesn't have yet.
 * Each row says why it is being suggested, so the list is a starting point
 * rather than an oracle.
 */
export function PeerSuggestions({ suggestions, loading, error, onAdd, adding }: Props) {
  if (loading && suggestions.length === 0) {
    return <p className="notice-line">Looking for similar companies…</p>;
  }

  if (error) return <p className="notice-line">{error}</p>;
  if (suggestions.length === 0) return null;

  return (
    <ul className="peer-list">
      {suggestions.map((peer) => {
        const price = fmtPrice(peer.price);
        const pct = fmtPercent(peer.changePercent);
        const direction =
          peer.changePercent == null ? "flat" : peer.changePercent >= 0 ? "up" : "down";

        return (
          <li key={peer.symbol} className="peer-card">
            <div className="peer-head">
              <span className="peer-symbol">{peer.symbol}</span>
              {price && <span className="peer-price">{price}</span>}
            </div>
            {peer.name && <p className="peer-name">{peer.name}</p>}
            <p className="peer-why">
              {because(peer.because_of)}
              {pct && <span className={`peer-move tone-${direction}`}> · {pct}</span>}
            </p>
            <button
              className="btn btn-small"
              onClick={() => onAdd(peer.symbol)}
              disabled={adding === peer.symbol}
            >
              {adding === peer.symbol ? "Adding…" : "Compare"}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
