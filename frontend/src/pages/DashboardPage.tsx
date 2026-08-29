import { useCallback, useEffect, useMemo, useState } from "react";
import { useCurrentAccount } from "../AccountContext";
import { ApiError, api } from "../api";
import { describeAge, readSnapshot, writeSnapshot } from "../snapshot";
import { MarketBoard } from "../components/MarketBoard";
import { MarketIndices } from "../components/MarketIndices";
import { PriceChart } from "../components/PriceChart";
import { TickerSearch } from "../components/TickerSearch";
import { WatchlistPanel } from "../components/WatchlistPanel";
import { PortfolioSummary } from "../components/PortfolioSummary";
import { ProviderStatus } from "../components/ProviderStatus";
import { buildPortfolio } from "../positions";
import { AlertsPanel } from "../components/AlertsPanel";
import { BackupPanel } from "../components/BackupPanel";
import {
  RANGES,
  type IndexQuote,
  type PriceAlert,
  type PricePoint,
  type Quote,
  type Lot,
  type MarketGroup,
  type RangeKey,
  type JournalEntry,
  type SplitAdjustment,
  type WatchlistEntry,
} from "../types";

export function DashboardPage() {
  const account = useCurrentAccount();
  // Keyed on who this is, so signing out never leaves the previous account's
  // watchlist on screen.
  const identity = account.signed_in ? (account.email ?? "account") : "anonymous";
  const cached = useMemo(() => readSnapshot(identity), [identity]);

  // The watchlist is the source of truth for what to render; quotes only
  // decorate it. Keeping them separate means a failed price lookup can no
  // longer make a populated list look empty.
  // Seeded from the last visit so the page has something to show while the
  // server wakes, rather than a blank half-minute.
  const [entries, setEntries] = useState<WatchlistEntry[]>(cached?.entries ?? []);
  const [quotes, setQuotes] = useState<Quote[]>(cached?.quotes ?? []);
  const [indices, setIndices] = useState<IndexQuote[]>(cached?.indices ?? []);
  const [board, setBoard] = useState<MarketGroup[]>(cached?.board ?? []);
  const [trends, setTrends] = useState<Record<string, number[]>>(cached?.trends ?? {});
  // Cleared the moment anything fresh lands, so the age note never outlives
  // the figures it describes.
  const [servedFrom, setServedFrom] = useState<number | null>(cached?.savedAt ?? null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);

  const [chartSymbol, setChartSymbol] = useState<string | null>(null);
  const [chartLabel, setChartLabel] = useState("");
  const [range, setRange] = useState<RangeKey>("1Y");
  const [points, setPoints] = useState<PricePoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<PriceAlert[]>(cached?.alerts ?? []);
  const [lots, setLots] = useState<Lot[]>(cached?.lots ?? []);
  const [splits, setSplits] = useState<SplitAdjustment[]>(cached?.splits ?? []);
  const [journal, setJournal] = useState<JournalEntry[]>(cached?.journal ?? []);
  const [journalTags, setJournalTags] = useState<string[]>([]);

  // Derived on every render rather than stored: a price refresh has to move
  // every figure at once, and a second copy of these numbers would be a
  // second thing to keep in step.
  const portfolio = useMemo(() => buildPortfolio(lots, quotes), [lots, quotes]);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      // Only the watchlist quotes depend on anything, so everything else is
      // started at once rather than after it. Waiting for the list first cost
      // a whole round trip on a page that already waits on a sleeping server.
      // Painted the moment it lands rather than at a later await, so a slow
      // market call cannot hold back the watchlist or vice versa.
      const marketPromise = Promise.allSettled([
        api.getIndices(refresh),
        api.getMarketBoard(refresh),
      ]).then((results) => {
        const [index, board] = results;
        if (index.status === "fulfilled") {
          setIndices(index.value);
          setServedFrom(null);
        }
        if (board.status === "fulfilled") setBoard(board.value);
        return results;
      });
      // Alerts are evaluated here because nothing runs while the app is
      // closed on free hosting. See NIGHT-LOG for what background delivery
      // would need.
      const alertPromise = api.checkAlerts().catch(() => null);
      // Cost basis does not depend on the watchlist, so it starts here rather
      // than waiting a round trip behind it. A failure leaves the rows as
      // pure watch items, which is what they were before.
      const positionsPromise = api
        .getPositions()
        .then((p) => {
          setLots(p.lots);
          setSplits(p.splits);
        })
        .catch(() => {});
      // Same reasoning: what you wrote about a company does not depend on the
      // list, and a failure leaves the row exactly as it was before.
      const journalPromise = api
        .getJournal()
        .then((j) => {
          setJournal(j.entries);
          setJournalTags(j.suggested_tags);
        })
        .catch(() => {});

      // Entries rather than bare tickers: the note lives alongside the symbol,
      // and one request beats two.
      const watchlist = await api.getListEntries("watch");
      setEntries(watchlist);

      const [quoteResult] = await Promise.allSettled([
        api.getQuotes(watchlist.map((e) => e.ticker), refresh),
      ]);
      if (quoteResult.status === "fulfilled") {
        setQuotes(quoteResult.value);
        setServedFrom(null);
      }

      const alertResult = await alertPromise;
      if (alertResult) setAlerts(alertResult.alerts);
      await Promise.all([positionsPromise, journalPromise]);

      // Row trend lines are decoration on top of a row that already works, so
      // they load last and a failure is simply no line.
      api
        .getTrends(watchlist.map((e) => e.ticker))
        .then(setTrends)
        .catch(() => {});

      const [indexResult] = await marketPromise;
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

  // Written after each successful load rather than on every render, so the
  // next visit opens on the last thing this browser actually saw.
  useEffect(() => {
    if (loading || entries.length === 0) return;
    writeSnapshot({ identity, entries, quotes, indices, board, alerts, trends, lots, splits, journal });
  }, [loading, identity, entries, quotes, indices, board, alerts, trends, lots, splits, journal]);

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

  // Each of these returns the whole set back, so the lots, the splits and
  // every figure derived from them stay in step without a second round trip.
  function applyPositions(next: { lots: Lot[]; splits: SplitAdjustment[] }) {
    setLots(next.lots);
    setSplits(next.splits);
  }

  const positionActions = {
    onAddLot: async (
      ticker: string,
      lot: { shares: number; costPerShare: number; tradeDate: string },
    ) => applyPositions(await api.addLot(ticker, lot)),
    onDeleteLot: async (id: string) => applyPositions(await api.deleteLot(id)),
    onApplySplit: async (ticker: string, ratio: number) =>
      applyPositions(await api.applySplit(ticker, ratio)),
    onUndoSplit: async (id: string) => applyPositions(await api.undoSplit(id)),
  };

  const journalSupport = {
    entries: journal,
    suggestedTags: journalTags,
    onWrite: async (
      ticker: string,
      entry: { body: string; tags: string[]; priceAtWrite: number | null },
    ) => {
      const result = await api.addJournalEntry(ticker, entry);
      setJournal(result.entries);
    },
  };

  // Cached prices, index tiles or the market strip all count: if any of them
  // rendered, the reader is looking at a usable page.
  const hasAnyData = quotes.length > 0 || indices.length > 0 || board.length > 0;

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

      {/* Figures from the last visit, shown while the server wakes. Marked
          with their age, because a stale price presented as live is worse
          than no price at all. */}
      {servedFrom !== null && (
        <p className="stale-banner">
          <span className="stale-dot" aria-hidden="true" />
          Showing what you saw {describeAge(servedFrom)} — refreshing now.
        </p>
      )}

      {/* Only when the page has nothing to show. Each panel already says its
          own piece -- the watchlist counts what it couldn't price, the market
          strip says prices are unavailable -- so a red banner on top of that
          makes a working page look broken. */}
      {error && !hasAnyData && (
        <div className={`alert ${waking ? "alert-info" : "alert-error"}`}>
          <p>{error}</p>
          {waking && (
            <button className="link-btn" onClick={() => load()}>
              Try again
            </button>
          )}
        </div>
      )}

      <PortfolioSummary portfolio={portfolio} />

      <h3 className="section-heading">
        Watchlist
        <span className="section-note">
          Click a row for its chart, ⌄ for what you paid, or ✎ to note why you’re watching
        </span>
      </h3>
      <WatchlistPanel
        entries={entries}
        quotes={quotes}
        trends={trends}
        portfolio={portfolio}
        splits={splits}
        positionActions={positionActions}
        journal={journalSupport}
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
        Under the surface
        <span className="section-note">
          How each part of the market is doing — click any for its chart
        </span>
      </h3>
      {/* Rendered whether or not the data arrived. Hiding the section on an
          empty response made a whole feature vanish during an outage, which
          reads as "it was never built" rather than "prices are down". */}
      <MarketBoard
        groups={board}
        loading={loading}
        onSelect={showChart}
        activeSymbol={chartSymbol}
      />

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
        Data sources
        <span className="section-note">Which providers are answering right now</span>
      </h3>
      <ProviderStatus />

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
