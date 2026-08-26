import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { StockTable } from "../components/StockTable";
import { TickerSearch } from "../components/TickerSearch";
import type { FundamentalsRow } from "../types";

export function ComparisonPage() {
  const [rows, setRows] = useState<FundamentalsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [waking, setWaking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadFundamentals(refresh = false) {
    setLoading(true);
    setError(null);
    try {
      setRows(await api.getFundamentals(refresh));
      setWaking(false);
    } catch (e) {
      if (e instanceof ApiError && e.isColdStart) setWaking(true);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadFundamentals();
  }, []);

  async function handleAdd(symbol: string) {
    setError(null);
    try {
      await api.addTicker(symbol);
      await loadFundamentals();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRemove(ticker: string) {
    try {
      await api.removeTicker(ticker);
      setRows((prev) => prev.filter((r) => r.ticker !== ticker));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Stock Comparison</h2>
          <p className="page-subtitle">
            Search a company by name or ticker, then compare the fundamentals side by side.
          </p>
        </div>
        <button className="btn" onClick={() => loadFundamentals(true)} disabled={loading}>
          {loading && <span className="spinner" />}
          {loading ? "Loading…" : "Refresh data"}
        </button>
      </div>

      <TickerSearch onSelect={handleAdd} disabled={loading} />

      {error && (
        <div className={`alert ${waking ? "alert-info" : "alert-error"}`}>
          <p>{error}</p>
          {waking && (
            <button className="link-btn" onClick={() => loadFundamentals()}>
              Try again
            </button>
          )}
        </div>
      )}

      {loading && rows.length === 0 ? (
        <div className="empty-state">
          <p>Loading your watchlist…</p>
        </div>
      ) : (
        <StockTable rows={rows} onRemove={handleRemove} />
      )}
    </section>
  );
}
