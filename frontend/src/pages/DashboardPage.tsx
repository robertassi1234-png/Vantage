import { useCallback, useEffect, useState } from "react";
import { useCurrentAccount } from "../AccountContext";
import { ApiError, api } from "../api";
import { MarketIndices } from "../components/MarketIndices";
import { PriceChart } from "../components/PriceChart";
import { TickerSearch } from "../components/TickerSearch";
import { WatchlistPanel } from "../components/WatchlistPanel";
import { AlertsPanel } from "../components/AlertsPanel";
import { BackupPanel } from "../components/BackupPanel";
import {
  RANGES,
  type IndexQuote,
  type PriceAlert,
  type PricePoint,
  type Quote,
  type RangeKey,
  type WatchlistEntry,
} from "../types";

export function DashboardPage() {
  const account = useCurrentAccount();

  // The watchlist is the source of truth for what to render; quotes only
  // decorate it. Keeping them separate means a failed price lookup can no
  // longer make a populated list look empty.
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
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
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      // Entries rather than bare tickers: the note lives alongside the symbol,
      // and one request beats two.
      const watchlist = await api.getListEntries("watch");
      setEntries(watchlist);
      const symbols = watchlist.map((e) => e.ticker);
      // Indices and quotes are independent; one failing shouldn't blank the other.
      const [indexResult, quoteResult] = await Promise.allSettled([
        api.getIndices(refresh),
        api.getQuotes(symbols, refresh),
      ]);

      if (indexResult.status === "fulfilled") setIndices(indexResult.value);
      if (quoteResult.status === "fulfilled") setQuotes(quoteResult.value);

      // Alerts are evaluated here because nothing runs while the app is
      // closed on free hosting. See NIGHT-LOG for what background delivery
      // would need.
      try {
        setAlerts((await api.checkAlerts()).alerts);
      } catch {
        // An alert check failing must not blank the dashboard.
      }

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
      setEntries((prev) => prev.filter((e) => e.ticker !== symbol));
      setQuotes((prev) => prev.filter((q) => q.symbol !== symbol));
      if (chartSymbol === symbol) setChartSymbol(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleSaveNote(symbol: string, note: string) {
    try {
      // The route returns the whole list back, so the note and everything
      // else stay in step without a second round trip.
      setEntries(await api.setNote("watch", symbol, note));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleCreateAlert(ticker: string, direction: string, threshold: number) {
    setAlerts(await api.createAlert(ticker, direction, threshold).then(() => api.getAlerts()));
  }

  async function handleDeleteAlert(id: string) {
    setAlerts(await api.deleteAlert(id));
  }

  async function handleAcknowledgeAlert(id: string) {
    setAlerts(await api.acknowledgeAlert(id));
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

      <h3 className="section-heading">
        Watchlist
        <span className="section-note">Click a row for its chart, or ✎ to note why you’re watching</span>
      </h3>
      <WatchlistPanel
        entries={entries}
        quotes={quotes}
        onSelect={showChart}
        onRemove={handleRemove}
        onSaveNote={handleSaveNote}
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

      <h3 className="section-heading">
        Price alerts
        <span className="section-note">
          {account.email_delivery && account.signed_in
            ? "Emailed to you when one triggers"
            : "Checked whenever you open Vantage"}
        </span>
      </h3>
      <AlertsPanel
        alerts={alerts}
        quotes={quotes}
        onCreate={handleCreateAlert}
        onDelete={handleDeleteAlert}
        onAcknowledge={handleAcknowledgeAlert}
      />

      <h3 className="section-heading">
        Backup
        <span className="section-note">Move your lists between devices</span>
      </h3>
      <BackupPanel />

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
