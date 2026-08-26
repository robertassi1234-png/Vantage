import { useState } from "react";
import type { PriceAlert, Quote } from "../types";

interface Props {
  alerts: PriceAlert[];
  quotes: Quote[];
  onCreate: (ticker: string, direction: string, threshold: number) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onAcknowledge: (id: string) => Promise<void>;
}

const money = (v: number | null) => (typeof v === "number" ? `$${v.toFixed(2)}` : "—");

export function AlertsPanel({ alerts, quotes, onCreate, onDelete, onAcknowledge }: Props) {
  const [ticker, setTicker] = useState("");
  const [direction, setDirection] = useState("above");
  const [threshold, setThreshold] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const priceOf = (symbol: string) =>
    quotes.find((q) => q.symbol === symbol)?.price ?? null;

  const triggered = alerts.filter((a) => a.triggered_at && !a.acknowledged);
  const pending = alerts.filter((a) => !a.triggered_at);
  const done = alerts.filter((a) => a.triggered_at && a.acknowledged);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = Number(threshold);
    if (!ticker.trim()) return setError("Choose a company first.");
    if (!Number.isFinite(value) || value <= 0) return setError("Enter a price above zero.");

    setBusy(true);
    setError(null);
    try {
      await onCreate(ticker.trim().toUpperCase(), direction, value);
      setThreshold("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="alerts-panel">
      {triggered.length > 0 && (
        <div className="alert alert-fired" role="status">
          <p className="fired-title">
            {triggered.length === 1 ? "An alert fired" : `${triggered.length} alerts fired`}
          </p>
          <ul className="fired-list">
            {triggered.map((a) => (
              <li key={a.id}>
                <strong>{a.ticker}</strong> went {a.direction} {money(a.threshold)} — hit{" "}
                {money(a.triggered_price)}
                <button className="link-btn" onClick={() => onAcknowledge(a.id)}>
                  Dismiss
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="alert-form" onSubmit={submit}>
        <select
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          aria-label="Company to watch"
        >
          <option value="">Choose a company…</option>
          {quotes.map((q) => (
            <option key={q.symbol} value={q.symbol}>
              {q.symbol} — {q.name ?? q.symbol}
            </option>
          ))}
        </select>

        <select
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          aria-label="Alert direction"
        >
          <option value="above">rises above</option>
          <option value="below">falls below</option>
        </select>

        <input
          type="number"
          step="0.01"
          min="0"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          placeholder={ticker ? String(priceOf(ticker) ?? "Price") : "Price"}
          aria-label="Alert price"
        />

        <button className="btn" type="submit" disabled={busy}>
          Add alert
        </button>
      </form>

      {error && <p className="error-line">{error}</p>}

      {alerts.length === 0 ? (
        <p className="empty-state">
          No alerts yet. Pick a company from your watchlist and a price, and Vantage will
          tell you when it gets there.
        </p>
      ) : (
        <ul className="alert-list">
          {[...pending, ...done].map((a) => {
            const current = priceOf(a.ticker);
            const distance =
              typeof current === "number"
                ? ((a.threshold - current) / current) * 100
                : null;

            return (
              <li key={a.id} className={`alert-row${a.triggered_at ? " is-triggered" : ""}`}>
                <span className="alert-ticker">{a.ticker}</span>
                <span className="alert-rule">
                  {a.direction === "above" ? "rises above" : "falls below"}{" "}
                  <strong>{money(a.threshold)}</strong>
                </span>
                <span className="alert-status">
                  {a.triggered_at ? (
                    <>fired at {money(a.triggered_price)}</>
                  ) : distance === null ? (
                    "waiting"
                  ) : (
                    <>
                      now {money(current)} · {Math.abs(distance).toFixed(1)}% away
                    </>
                  )}
                </span>
                <button
                  className="remove-btn"
                  onClick={() => onDelete(a.id)}
                  aria-label={`Delete alert for ${a.ticker}`}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
