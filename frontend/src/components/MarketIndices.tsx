import { Sparkline } from "./Sparkline";
import type { IndexQuote } from "../types";

interface Props {
  indices: IndexQuote[];
  onSelect: (symbol: string, label: string) => void;
  activeSymbol?: string | null;
}

const fmtLevel = (v: number | null) =>
  typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—";

const fmtChange = (v: number | null) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}` : "—";

const fmtPercent = (v: number | null) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";

export function MarketIndices({ indices, onSelect, activeSymbol }: Props) {
  return (
    <div className="index-grid">
      {indices.map((index) => {
        const pct = index.changePercent;
        const direction = pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
        return (
          <button
            key={index.symbol}
            className={`index-tile tone-${direction}${
              activeSymbol === index.symbol ? " active" : ""
            }`}
            onClick={() => onSelect(index.symbol, index.label)}
            title={`Show the ${index.label} chart`}
          >
            <span className="index-label">{index.label}</span>
            <span className="index-blurb">{index.blurb}</span>
            <span className="index-value">{fmtLevel(index.price)}</span>
            <span className="index-delta">
              <span aria-hidden="true">{direction === "down" ? "▼" : direction === "up" ? "▲" : "■"}</span>{" "}
              {fmtChange(index.change)} ({fmtPercent(pct)})
            </span>
            <Sparkline values={index.sparkline} direction={direction} />
          </button>
        );
      })}
    </div>
  );
}
