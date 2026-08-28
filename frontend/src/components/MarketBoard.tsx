import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkline } from "./Sparkline";
import type { MarketGroup } from "../types";

interface Props {
  groups: MarketGroup[];
  onSelect: (symbol: string, label: string) => void;
  activeSymbol?: string | null;
}

const ROTATE_MS = 7000;

const fmtPrice = (v: number | null) =>
  typeof v === "number" ? `$${v.toFixed(2)}` : "—";

const fmtPercent = (v: number | null) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";

const toneOf = (v: number | null) =>
  v == null ? "flat" : v > 0 ? "up" : v < 0 ? "down" : "flat";

/** Respect a reader who has asked the OS to stop things moving. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    setReduced(query.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  return reduced;
}

/**
 * A wider read on the market than the four headline indices.
 *
 * Rotates through themed groups -- the US market, then sectors, then global
 * and other -- because each answers a different question, and four tiles at a
 * time stays readable where twelve at once is wallpaper. Rotation stops on
 * hover, on focus, and for anyone who has asked their system to reduce
 * motion, and the dots below are always there to drive it by hand: motion
 * that cannot be stopped is a nuisance rather than a feature.
 */
export function MarketBoard({ groups, onSelect, activeSymbol }: Props) {
  const [page, setPage] = useState(0);
  const [paused, setPaused] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  const timer = useRef<number | undefined>(undefined);

  const advance = useCallback(() => {
    setPage((current) => (current + 1) % Math.max(groups.length, 1));
  }, [groups.length]);

  useEffect(() => {
    if (paused || reducedMotion || groups.length < 2) return;
    timer.current = window.setInterval(advance, ROTATE_MS);
    return () => window.clearInterval(timer.current);
  }, [advance, paused, reducedMotion, groups.length]);

  if (groups.length === 0) return null;

  const current = groups[Math.min(page, groups.length - 1)];

  return (
    <div
      className="market-board"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
    >
      <div className="board-head">
        <div className="board-tabs" role="tablist" aria-label="Market groups">
          {groups.map((group, index) => (
            <button
              key={group.group}
              role="tab"
              aria-selected={index === page}
              className={`board-tab${index === page ? " active" : ""}`}
              onClick={() => setPage(index)}
            >
              {group.group}
            </button>
          ))}
        </div>
        {!reducedMotion && groups.length > 1 && (
          <span className="board-hint" aria-hidden="true">
            {paused ? "paused" : "rotating"}
          </span>
        )}
      </div>

      <ul className="board-grid" key={current.group}>
        {current.entries.map((entry) => {
          const tone = toneOf(entry.changePercent);
          const isActive = activeSymbol === entry.symbol;

          return (
            <li key={entry.symbol}>
              <button
                className={`board-tile tone-${tone}${isActive ? " active" : ""}`}
                onClick={() => onSelect(entry.symbol, entry.label)}
                aria-label={`${entry.label}, ${fmtPrice(entry.price)}, ${fmtPercent(
                  entry.changePercent,
                )}. Show its chart.`}
              >
                <span className="tile-top">
                  <span className="tile-label">{entry.label}</span>
                  <span className="tile-symbol">{entry.symbol}</span>
                </span>

                <span className="tile-value">{fmtPrice(entry.price)}</span>

                <span className="tile-delta">
                  {/* An arrow as well as the colour: direction must not be
                      carried by hue alone. */}
                  <span aria-hidden="true">
                    {tone === "up" ? "▲" : tone === "down" ? "▼" : "■"}
                  </span>{" "}
                  {fmtPercent(entry.changePercent)}
                </span>

                <span className="tile-spark">
                  <Sparkline values={entry.sparkline} direction={tone} width={132} height={34} />
                </span>

                <span className="tile-blurb">{entry.blurb}</span>
              </button>
            </li>
          );
        })}
      </ul>

      {groups.length > 1 && (
        <div className="board-dots">
          {groups.map((group, index) => (
            <button
              key={group.group}
              className={`board-dot${index === page ? " active" : ""}`}
              onClick={() => setPage(index)}
              aria-label={`Show ${group.group}`}
              aria-current={index === page}
            />
          ))}
        </div>
      )}
    </div>
  );
}
