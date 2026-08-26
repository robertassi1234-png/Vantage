import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { MarketIndices } from "../components/MarketIndices";
import { PriceChart } from "../components/PriceChart";
import { TickerSearch } from "../components/TickerSearch";
import { WatchlistPanel } from "../components/WatchlistPanel";
import { RANGES, type IndexQuote, type PricePoint, type Quote, type RangeKey } from "../types";

export function DashboardPage() {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [indices, setIndices] = useState<IndexQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);

  const [chartSymbol, setChartSymbol] = useState<string | null>(null);
  const [chartLabel, setChartLabel] = useState("");
  const [range, setRange] = useState<RangeKey>("1Y");
  const [points, setPoints] = useState<PricePoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const watchlist = await api.getList("watch");
      // Indices and quotes are independent; one failing shouldn't blank the other.
      const [indexResult, quoteResult] = await Promise.allSettled([
        api.getIndices(refresh),
        api.getQuotes(watchlist, refresh),
      ]);

      if (indexResult.status === "fulfilled") setIndices(indexResult.value);
      if (quoteResult.status === "fulfilled") setQuotes(quoteResult.value);

      const failure = [indexResult, quoteResult].find((r) => r.status === "rejected");
      if (failure && failure.status === "rejected") {
        const reason = failure.reason;
        if (reason instanceof ApiError && reason.isColdStart) setWaking(true);
        setError(reason instanceof Error ? reason.message : String(reason));
      } else {
        setWaking(false);
      }
    } catch (e) {
      if (e instanceof ApiError && e.isColdStart) setWaking(true);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Fetch history whenever the selected symbol or range changes.
  useEffect(() => {
    if (!chartSymbol) return;
    let cancelled = false;

    (async () => {
      setChartLoading(true);
      setChartError(null);
      try {
        const history = await api.getHistory(chartSymbol, range);
        if (!cancelled) setPoints(history.points);
      } catch (e) {
        if (!cancelled) {
          setPoints([]);
          setChartError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setChartLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chartSymbol, range]);

  function showChart(symbol: string, label: string) {
    setChartSymbol(symbol);
    setChartLabel(label);
  }

  async function handleAdd(symbol: string) {
    setError(null);
    try {
      await api.addToList("watch", symbol);
      await load();
      showChart(symbol, symbol);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRemove(symbol: string) {
    try {
      await api.removeFromList("watch", symbol);
      setQuotes((prev) => prev.filter((q) => q.symbol !== symbol));
      if (chartSymbol === symbol) setChartSymbol(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Dashboard</h2>
          <p className="page-subtitle">
            Your watchlist, the major US indices, and price charts for anything you follow.
          </p>
        </div>
        <button className="btn" onClick={() => load(true)} disabled={loading}>
          {loading && <span className="spinner" />}
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      <TickerSearch onSelect={handleAdd} disabled={loading} />

      {error && (
        <div className={`alert ${waking ? "alert-info" : "alert-error"}`}>
          <p>{error}</p>
          {waking && (
            <button className="link-btn" onClick={() => load()}>
              Try again
            </button>
          )}
        </div>
      )}

      <h3 className="section-heading">Watchlist</h3>
      <WatchlistPanel
        quotes={quotes}
        onSelect={showChart}
        onRemove={handleRemove}
        activeSymbol={chartSymbol}
      />

      <h3 className="section-heading">
        Market indices
        <span className="section-note">The broad US market, for context</span>
      </h3>
      {indices.length > 0 ? (
        <MarketIndices indices={indices} onSelect={showChart} activeSymbol={chartSymbol} />
      ) : (
        <div className="empty-state">
          <p>Index data unavailable right now.</p>
        </div>
      )}

      {chartSymbol && (
        <>
          <h3 className="section-heading">
            {chartLabel}
            <span className="section-note">{chartSymbol}</span>
          </h3>

          <div className="chart-card">
            <div className="range-row" role="group" aria-label="Chart time range">
              {RANGES.map((r) => (
                <button
                  key={r}
                  className={`range-btn${range === r ? " active" : ""}`}
                  onClick={() => setRange(r)}
                >
                  {r}
                </button>
              ))}
            </div>

            {chartError ? (
              <div className="chart-empty">{chartError}</div>
            ) : (
              <div className={chartLoading ? "chart-loading" : undefined}>
                <PriceChart points={points} label={chartLabel} />
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
