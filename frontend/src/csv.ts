import { METRICS } from "./metrics";
import type { FundamentalsRow } from "./types";

/**
 * Escape one CSV field.
 *
 * A leading =, +, - or @ is prefixed with a quote: spreadsheets treat those as
 * formulas, so a value like "-8.4%" can be executed rather than displayed.
 */
function escapeField(value: unknown): string {
  const text = value == null ? "" : String(value);
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** Comparison table as CSV, using raw numbers so the values stay computable. */
export function rowsToCsv(rows: FundamentalsRow[]): string {
  const header = ["Ticker", ...METRICS.map((m) => m.label)];
  const lines = [header.map(escapeField).join(",")];

  for (const row of rows) {
    const cells = [row.ticker, ...METRICS.map((m) => row[m.key])];
    lines.push(cells.map(escapeField).join(","));
  }

  return lines.join("\n");
}

export function downloadCsv(rows: FundamentalsRow[], filename = "vantage-comparison.csv"): void {
  const blob = new Blob([rowsToCsv(rows)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
