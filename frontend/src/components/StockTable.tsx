import { useMemo, useState } from "react";
import { GROUPS, METRICS, PRIMARY_METRICS, type MetricDef } from "../metrics";
import type { FundamentalsRow } from "../types";

interface Props {
  rows: FundamentalsRow[];
  onRemove: (ticker: string) => void;
}

export function StockTable({ rows, onRemove }: Props) {
  const [sortKey, setSortKey] = useState<keyof FundamentalsRow>("ticker");
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const [showAll, setShowAll] = useState(false);

  const columns = showAll ? METRICS : PRIMARY_METRICS;

  const visibleGroups = useMemo(
    () =>
      GROUPS.map((group) => ({
        ...group,
        span: columns.filter((c) => c.group === group.id).length,
      })).filter((g) => g.span > 0),
    [columns],
  );

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir;
      return String(av).localeCompare(String(bv)) * sortDir;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  function toggleSort(key: keyof FundamentalsRow) {
    if (key === sortKey) {
      setSortDir((d) => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      setSortDir(1);
    }
  }

  if (rows.length === 0) {
    return (
      <div className="empty-state">
        <p className="empty-title">No companies yet</p>
        <p>
          Search for a company above — by name or ticker — to see its fundamentals here.
          Add two or more to compare them side by side.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="table-toolbar">
        <button className="link-btn" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show key metrics only" : `Show all ${METRICS.length} metrics`}
        </button>
        <span className="toolbar-hint">
          Click a heading to sort · hover one for what it means · scroll sideways for more
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr className="group-row">
              <th className="sticky-col" />
              {visibleGroups.map((group) => (
                <th key={group.id} colSpan={group.span} className={`group-head group-${group.id}`}>
                  {group.label}
                </th>
              ))}
              <th />
            </tr>
            <tr>
              <th className="sticky-col" onClick={() => toggleSort("ticker")}>
                Ticker{sortKey === "ticker" ? (sortDir === 1 ? " ▲" : " ▼") : ""}
              </th>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={col.group === "identity" && col.key === "companyName" ? "" : "numeric"}
                  onClick={() => toggleSort(col.key)}
                  title={`${col.plainLabel} — ${col.explanation}`}
                >
                  <span className="th-label">{col.label}</span>
                  {sortKey === col.key ? (sortDir === 1 ? " ▲" : " ▼") : ""}
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.ticker} className={row.error ? "row-error" : row.stale ? "row-stale" : ""}>
                <td className="sticky-col ticker-cell">{row.ticker}</td>
                {columns.map((col) => (
                  <MetricCell key={col.key} col={col} row={row} />
                ))}
                <td>
                  <button
                    className="remove-btn"
                    onClick={() => onRemove(row.ticker)}
                    title={`Remove ${row.ticker}`}
                    aria-label={`Remove ${row.ticker}`}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TableNotes rows={rows} />

      <Legend />
    </>
  );
}

/** Whether a row actually carries figures, or is only a ticker and a reason. */
const hasFigures = (row: FundamentalsRow) =>
  row.companyName != null || row.peRatio != null || row.marketCap != null;

/**
 * One line per distinct problem, rather than one per row.
 *
 * When a provider is rate limited every row reports the same sentence, and
 * six identical red lines under a table full of numbers reads as total
 * failure — when the figures are there and merely a few hours old. Grouping
 * by message collapses that to one line without hiding anything: a genuinely
 * different problem, like a rejected key, still gets said in its own words.
 */
function TableNotes({ rows }: { rows: FundamentalsRow[] }) {
  const failed = rows.filter((r) => r.error);
  if (failed.length === 0) return null;

  const byMessage = new Map<string, FundamentalsRow[]>();
  for (const row of failed) {
    const message = row.error as string;
    byMessage.set(message, [...(byMessage.get(message) ?? []), row]);
  }

  return (
    <div className="table-notes">
      {[...byMessage].map(([message, affected]) => {
        // Rows that kept their cached figures are showing real numbers, just
        // not fresh ones. That is a milder thing than a row with nothing.
        const salvaged = affected.every(hasFigures);
        return (
          <p key={message} className={salvaged ? "note-stale" : "note-error"}>
            <strong>{affected.map((r) => r.ticker).join(", ")}</strong> — {message}
            {salvaged && " Saved figures are shown above."}
          </p>
        );
      })}
    </div>
  );
}

function MetricCell({ col, row }: { col: MetricDef; row: FundamentalsRow }) {
  const raw = row[col.key];
  const isNameCell = col.key === "companyName" || col.key === "sector";
  const band =
    col.band && typeof raw === "number" && Number.isFinite(raw) ? col.band(raw) : null;

  return (
    <td className={`${isNameCell ? "" : "numeric"}${band ? ` band-${band}` : ""}`}>
      {col.format(raw)}
    </td>
  );
}

function Legend() {
  const [open, setOpen] = useState(false);

  return (
    <div className="legend">
      <button className="link-btn" onClick={() => setOpen((o) => !o)}>
        {open ? "Hide" : "What do these numbers mean?"}
      </button>

      {open && (
        <div className="legend-body">
          <p className="legend-note">
            Shading marks values that sit unusually{" "}
            <span className="band-chip band-low">below</span> or{" "}
            <span className="band-chip band-high">above</span> a broad market norm;{" "}
            <span className="band-chip band-mid">typical</span> values are left plain. It
            flags what's worth a second look — it is <strong>not</strong> a buy or sell
            signal, and high is not the same as good. A high P/E is normal for a
            fast-growing company and a low one can be a warning sign. These norms are
            rough, market-wide rules of thumb, so compare companies within the same sector.
          </p>

          {GROUPS.map((group) => {
            const items = METRICS.filter((m) => m.group === group.id && m.band);
            if (items.length === 0) return null;
            return (
              <div key={group.id} className="legend-group">
                <h4>{group.label}</h4>
                <p className="legend-blurb">{group.blurb}</p>
                <dl>
                  {items.map((m) => (
                    <div key={m.key} className="legend-item">
                      <dt>
                        {m.label} <span className="legend-plain">{m.plainLabel}</span>
                      </dt>
                      <dd>{m.explanation}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
