import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { ComparisonChart, SERIES_COLORS, type ChartSeries } from "../components/ComparisonChart";
import { PeerSuggestions } from "../components/PeerSuggestions";
import { downloadCsv } from "../csv";
import { StockTable } from "../components/StockTable";
import { ValuationTable } from "../components/ValuationTable";
import { ProviderStatus } from "../components/ProviderStatus";
import { TickerSearch } from "../components/TickerSearch";
import {
  RANGES,
  type FundamentalsRow,
  type PeerSuggestion,
  type RangeKey,
  type ValuationResponse,
} from "../types";

export function ComparisonPage() {
  const [rows, setRows] = useState<FundamentalsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [waking, setWaking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [range, setRange] = useState<RangeKey>("1Y");
  const [series, setSeries] = useState<ChartSeries[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  const [valuation, setValuation] = useState<ValuationResponse | null>(null);
  const [valuationLoading, setValuationLoading] = useState(false);
  const [valuationError, setValuationError] = useState<string | null>(null);

  const [peers, setPeers] = useState<PeerSuggestion[]>([]);
  const [peersLoading, setPeersLoading] = useState(false);
  const [peersError, setPeersError] = useState<string | null>(null);
  const [addingPeer, setAddingPeer] = useState<string | null>(null);

  const tickers = rows.map((r) => r.ticker).join(",");

  // Price history for the overlay chart, refetched when the list or range
  // changes. Capped at five series: past that the lines stop being tellable
  // apart, and the palette only guarantees separation for five.
  useEffect(() => {
    const symbols = tickers ? tickers.split(",").slice(0, SERIES_COLORS) : [];
    if (symbols.length === 0) {
      setSeries([]);
      return;
    }

    let cancelled = false;
    (async () => {
      setSeriesLoading(true);
      setSeriesError(null);
      try {
        const loaded = await Promise.all(
          symbols.map(async (symbol) => ({
            symbol,
            points: (await api.getHistory(symbol, range)).points,
          })),
        );
        if (!cancelled) setSeries(loaded);
      } catch (e) {
        if (!cancelled) {
          setSeries([]);
          setSeriesError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setSeriesLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tickers, range]);

  // Five years of quarterly fundamentals is six provider calls per company,
  // so this follows the list rather than the refresh button: it reloads when
  // the companies change and otherwise leaves the day-old cache alone.
  useEffect(() => {
    if (!tickers) {
      setValuation(null);
      return;
    }

    let cancelled = false;
    (async () => {
      setValuationLoading(true);
      setValuationError(null);
      try {
        const loaded = await api.getValuation();
        if (!cancelled) setValuation(loaded);
      } catch (e) {
        if (!cancelled) setValuationError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setValuationLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tickers]);

  // Suggestions follow the list: adding a company changes what else is worth
  // looking at. Kept apart from the table load so a peer outage can't stop
  // the fundamentals rendering.
  useEffect(() => {
    if (!tickers) {
      setPeers([]);
      setPeersError(null);
      return;
    }

    let cancelled = false;
    (async () => {
      setPeersLoading(true);
      setPeersError(null);
      try {
        const result = await api.getPeers();
        if (cancelled) return;
        // Defended rather than trusted: a response without its suggestions
        // list -- an older server, a proxy rewriting the body -- reached
        // `peers.length` as undefined and took the whole page down, losing
        // the fundamentals table over a sidebar of nice-to-haves.
        setPeers(Array.isArray(result?.suggestions) ? result.suggestions : []);
        setPeersError(result?.error ?? null);
      } catch (e) {
        if (!cancelled) {
          setPeers([]);
          setPeersError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setPeersLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tickers]);

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
      await api.addToList("compare", symbol);
      await loadFundamentals();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleAddPeer(symbol: string) {
    setAddingPeer(symbol);
    try {
      await handleAdd(symbol);
    } finally {
      setAddingPeer(null);
    }
  }

  async function handleRemove(ticker: string) {
    try {
      await api.removeFromList("compare", ticker);
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
        <div className="header-buttons">
          {rows.length > 0 && (
            <button
              className="btn btn-secondary"
              onClick={() => downloadCsv(rows)}
              title="Download the table as a spreadsheet"
            >
              Export CSV
            </button>
          )}
          <button className="btn" onClick={() => loadFundamentals(true)} disabled={loading}>
            {loading && <span className="spinner" />}
            {loading ? "Loading…" : "Refresh data"}
          </button>
        </div>
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
          <p>Loading your comparison list…</p>
        </div>
      ) : (
        <StockTable rows={rows} onRemove={handleRemove} />
      )}

      {rows.length > 0 && (
        <>
          <h3 className="section-heading">
            Valuation in context
            <span className="section-note">
              Each figure against the same company’s own last five years
            </span>
          </h3>

          {valuationError ? (
            <p className="notice-line">{valuationError}</p>
          ) : (
            <ValuationTable
              companies={valuation?.companies ?? []}
              metrics={valuation?.metrics ?? []}
              peerMedian={valuation?.peerMedian ?? {}}
              loading={valuationLoading}
            />
          )}

          {/* Offered where the failure is, since that is where the question
              gets asked. */}
          {(valuationError || valuation?.companies.some((c) => c.error)) && (
            <ProviderStatus />
          )}
        </>
      )}

      {rows.length > 0 && (peersLoading || peers.length > 0 || peersError) && (
        <>
          <h3 className="section-heading">
            Similar companies
            <span className="section-note">
              A multiple only means something next to competitors
            </span>
          </h3>
          <PeerSuggestions
            suggestions={peers}
            loading={peersLoading}
            error={peersError}
            onAdd={handleAddPeer}
            adding={addingPeer}
          />
        </>
      )}

      {rows.length > 0 && (
        <>
          <h3 className="section-heading">
            Relative performance
            <span className="section-note">
              Each line starts at 0%, so different share prices stay comparable
            </span>
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

            {seriesError ? (
              <div className="chart-empty">{seriesError}</div>
            ) : (
              <div className={seriesLoading ? "chart-loading" : undefined}>
                <ComparisonChart series={series} />
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
