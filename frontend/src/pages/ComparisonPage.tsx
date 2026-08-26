import { useEffect, useState } from "react";
import { api } from "../api";
import { StockTable } from "../components/StockTable";
import type { FundamentalsRow } from "../types";

export function ComparisonPage() {
  const [rows, setRows] = useState<FundamentalsRow[]>([]);
  const [tickerInput, setTickerInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadFundamentals(refresh = false) {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getFundamentals(refresh);
      setRows(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadFundamentals();
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const ticker = tickerInput.trim();
    if (!ticker) return;
    setTickerInput("");
    setError(null);
    try {
      await api.addTicker(ticker);
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
          <p className="page-subtitle">Fundamentals for everything on your watchlist, side by side.</p>
        </div>
        <button className="btn" onClick={() => loadFundamentals(true)} disabled={loading}>
          {loading && <span className="spinner" />}
          {loading ? "Refreshing…" : "Refresh data"}
        </button>
      </div>

      <form className="add-ticker-form" onSubmit={handleAdd}>
        <input
          value={tickerInput}
          onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
          placeholder="Add ticker (e.g. AAPL)"
          maxLength={10}
        />
        <button className="btn" type="submit">
          Add
        </button>
      </form>

      {error && <p className="error-line">{error}</p>}

      <StockTable rows={rows} onRemove={handleRemove} />
    </section>
  );
}
