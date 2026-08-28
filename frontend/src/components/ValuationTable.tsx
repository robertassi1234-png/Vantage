import {
  bestInRow,
  describePercentile,
  formatMetric,
  hasContext,
  markerPosition,
  medianPosition,
} from "../valuation";
import type { MetricStat, ValuationCompany, ValuationMetricDef } from "../types";

interface Props {
  companies: ValuationCompany[];
  metrics: ValuationMetricDef[];
  peerMedian: Record<string, number | null>;
  loading?: boolean;
}

/**
 * Valuation with the context that makes it mean anything.
 *
 * Companies across, metrics down. Every cell carries three things: what the
 * number is, where it sits in this company's own five years, and -- in the
 * last column -- what the rest of the comparison looks like. The middle one
 * is the point. "Is a P/E of 30 expensive" has no answer; "is 30 expensive
 * for this company, which has averaged 24" does.
 */
export function ValuationTable({ companies, metrics, peerMedian, loading }: Props) {
  if (companies.length === 0) {
    return (
      <div className="empty-state">
        <span className="empty-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"
               strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
          </svg>
        </span>
        <p className="empty-title">
          {loading ? "Loading valuations…" : "Nothing to value yet"}
        </p>
        <p>
          Add a company above and this fills in with how its multiples and margins compare to its
          own last five years.
        </p>
      </div>
    );
  }

  const failed = companies.filter((c) => c.error && Object.keys(c.metrics).length === 0);
  const stale = companies.filter((c) => c.stale);

  return (
    <>
      {failed.length > 0 && (
        <p className="notice-line">
          {failed.map((c) => c.ticker).join(", ")} couldn’t be valued right now.
        </p>
      )}
      {stale.length > 0 && (
        <p className="notice-line">
          Showing yesterday’s figures for {stale.map((c) => c.ticker).join(", ")} — fundamentals
          only change quarterly, so these are almost certainly still current.
        </p>
      )}

      <div className="valuation-scroll">
        <table className="valuation-table">
          <caption className="sr-only">
            Valuation metrics for each company, against its own five-year history
          </caption>
          <thead>
            <tr>
              <th scope="col" className="metric-col">
                Metric
              </th>
              {companies.map((company) => (
                <th key={company.ticker} scope="col">
                  <span className="valuation-ticker">{company.ticker}</span>
                  <span className="valuation-name">{company.companyName ?? ""}</span>
                </th>
              ))}
              <th scope="col" className="peer-col">
                <span className="valuation-ticker">Peer median</span>
                {/* Said explicitly: this is the middle of what is on screen,
                    not an industry figure. */}
                <span className="valuation-name">of these {companies.length}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((def) => {
              const leader = bestInRow(companies, def);
              return (
                <tr key={def.key}>
                  <th scope="row" className="metric-col">
                    {def.label}
                    {def.better && (
                      <span className="metric-direction">
                        {def.better === "high" ? "higher is better" : "lower is better"}
                      </span>
                    )}
                  </th>

                  {companies.map((company) => (
                    <ValuationCell
                      key={company.ticker}
                      stat={company.metrics[def.key]}
                      def={def}
                      leading={leader === company.ticker}
                    />
                  ))}

                  <td className="peer-col">
                    <span className="valuation-value">{formatMetric(peerMedian[def.key], def)}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ValuationCell({
  stat,
  def,
  leading,
}: {
  stat: MetricStat | undefined;
  def: ValuationMetricDef;
  leading: boolean;
}) {
  if (!stat) {
    return (
      <td>
        <span className="valuation-value">—</span>
      </td>
    );
  }

  const context = describePercentile(stat, def);

  return (
    <td className={leading ? "leading" : undefined}>
      <span className="valuation-value">
        {formatMetric(stat.value, def)}
        {/* Not colour alone: the leader is marked with a symbol too. */}
        {leading && (
          <span className="leader-mark" title="Best of these companies" aria-label="best of these">
            ★
          </span>
        )}
      </span>

      {hasContext(stat) ? (
        <RangeBar stat={stat} label={context} />
      ) : (
        <span className="valuation-nocontext">
          {stat.value == null ? "" : "no five-year history"}
        </span>
      )}
    </td>
  );
}

/**
 * Where today sits between this company's five-year low and high.
 *
 * A bar rather than a number because the question is positional. The tick is
 * the median; the dot is today. Drawn between the 5th and 95th percentiles,
 * so one distorted quarter cannot squash every real observation into a
 * corner -- which is why a genuine extreme pins to the end rather than
 * running off it.
 */
function RangeBar({ stat, label }: { stat: MetricStat; label: string | null }) {
  const marker = markerPosition(stat);
  const median = medianPosition(stat);
  if (marker == null) return <span className="valuation-nocontext" />;

  return (
    <span className="valuation-range" title={label ?? undefined}>
      <span className="valuation-track">
        {median != null && (
          <span className="valuation-median" style={{ left: `${median * 100}%` }} aria-hidden="true" />
        )}
        <span className="valuation-marker" style={{ left: `${marker * 100}%` }} aria-hidden="true" />
      </span>
      {label && <span className="sr-only">{label}</span>}
    </span>
  );
}
