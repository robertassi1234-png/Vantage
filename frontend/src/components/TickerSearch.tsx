import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SymbolMatch } from "../types";

interface Props {
  onSelect: (symbol: string) => void | Promise<void>;
  disabled?: boolean;
}

/**
 * Add-ticker box that accepts a company name as readily as a ticker: typing
 * "apple" surfaces AAPL. Falls back to submitting the raw text so an exact
 * ticker still works if the lookup is unavailable.
 */
export function TickerSearch({ onSelect, disabled }: Props) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<SymbolMatch[]>([]);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const [searching, setSearching] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 1) {
      setMatches([]);
      setSearching(false);
      return;
    }

    setSearching(true);
    const seq = ++requestSeq.current;
    const timer = setTimeout(async () => {
      try {
        const results = await api.searchSymbols(trimmed);
        // Ignore responses that arrive out of order.
        if (seq !== requestSeq.current) return;
        setMatches(results);
        setHighlighted(0);
        setOpen(results.length > 0);
      } catch {
        if (seq !== requestSeq.current) return;
        setMatches([]);
        setOpen(false);
      } finally {
        if (seq === requestSeq.current) setSearching(false);
      }
    }, 220);

    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  async function choose(symbol: string) {
    setQuery("");
    setMatches([]);
    setOpen(false);
    await onSelect(symbol);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || matches.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => (i + 1) % matches.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => (i - 1 + matches.length) % matches.length);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    // Enter picks the highlighted suggestion, or falls back to the raw input.
    const chosen = open && matches[highlighted] ? matches[highlighted].symbol : trimmed.toUpperCase();
    await choose(chosen);
  }

  return (
    <div className="ticker-search" ref={containerRef}>
      <form className="add-ticker-form" onSubmit={handleSubmit}>
        <div className="search-field">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setOpen(matches.length > 0)}
            onKeyDown={handleKeyDown}
            placeholder="Search a company or ticker — e.g. Apple or AAPL"
            aria-label="Search for a company or ticker"
            autoComplete="off"
            disabled={disabled}
          />
          {searching && <span className="search-spinner" aria-hidden="true" />}

          {open && matches.length > 0 && (
            <ul className="search-results" role="listbox">
              {matches.map((match, i) => (
                <li key={match.symbol}>
                  <button
                    type="button"
                    className={`search-result${i === highlighted ? " highlighted" : ""}`}
                    onMouseEnter={() => setHighlighted(i)}
                    onClick={() => choose(match.symbol)}
                  >
                    <span className="result-symbol">{match.symbol}</span>
                    <span className="result-name">{match.name ?? "—"}</span>
                    {match.exchange && <span className="result-exchange">{match.exchange}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <button className="btn" type="submit" disabled={disabled || !query.trim()}>
          Add
        </button>
      </form>
    </div>
  );
}
