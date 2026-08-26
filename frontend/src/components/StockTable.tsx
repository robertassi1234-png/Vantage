import { useMemo, useState } from "react";
import type { FundamentalsRow } from "../types";

interface Column {
  key: keyof FundamentalsRow;
  label: string;
  format?: (v: FundamentalsRow[keyof FundamentalsRow]) => string;
}

const fmtNum = (digits = 2) => (v: unknown) =>
  typeof v === "number" ? v.toFixed(digits) : "—";

const fmtPercent = (v: unknown) =>
  typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—";

const fmtBillions = (v: unknown) =>
  typeof v === "number" ? `$${(v / 1e9).toFixed(1)}B` : "—";

const COLUMNS: Column[] = [
  { key: "ticker", label: "Ticker" },
  { key: "companyName", label: "Company" },
  { key: "price", label: "Price", format: fmtNum(2) },
  { key: "marketCap", label: "Market Cap", format: fmtBillions },
  { key: "peRatio", label: "P/E", format: fmtNum(1) },
  { key: "pegRatio", label: "PEG", format: fmtNum(2) },
  { key: "evToEbitda", label: "EV/EBITDA", format: fmtNum(1) },
  { key: "priceToBook", label: "P/B", format: fmtNum(2) },
  { key: "priceToSales", label: "P/S", format: fmtNum(2) },
  { key: "debtToEquity", label: "Debt/Equity", format: fmtNum(2) },
  { key: "currentRatio", label: "Current Ratio", format: fmtNum(2) },
  { key: "revenueGrowth", label: "Revenue Growth", format: fmtPercent },
  { key: "epsGrowth", label: "EPS Growth", format: fmtPercent },
  { key: "netProfitMargin", label: "Net Margin", format: fmtPercent },
  { key: "operatingMargin", label: "Operating Margin", format: fmtPercent },
  { key: "returnOnEquity", label: "ROE", format: fmtPercent },
  { key: "dividendYield", label: "Dividend Yield", format: fmtPercent },
];

interface Props {
  rows: FundamentalsRow[];
  onRemove: (ticker: string) => void;
}

export function StockTable({ rows, onRemove }: Props) {
  const [sortKey, setSortKey] = useState<keyof FundamentalsRow>("ticker");
  const [sortDir, setSortDir] = useState<1 | -1>(1);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return (av - bv) * sortDir;
      }
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
    return <p className="empty-state">Add a ticker above to start comparing stocks.</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {COLUMNS.map((col) => (
              <th key={col.key} onClick={() => toggleSort(col.key)}>
                {col.label}
                {sortKey === col.key ? (sortDir === 1 ? " ▲" : " ▼") : ""}
              </th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.ticker} className={row.error ? "row-error" : row.stale ? "row-stale" : ""}>
              {COLUMNS.map((col) => (
                <td key={col.key}>
                  {col.format ? col.format(row[col.key]) : (row[col.key] as string) ?? "—"}
                </td>
              ))}
              <td>
                <button className="remove-btn" onClick={() => onRemove(row.ticker)} title="Remove">
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.some((r) => r.error) && (
        <div className="errors">
          {rows
            .filter((r) => r.error)
            .map((r) => (
              <p key={r.ticker} className="error-line">
                {r.ticker}: {r.error}
              </p>
            ))}
        </div>
      )}
    </div>
  );
}
