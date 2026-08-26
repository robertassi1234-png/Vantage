import { describe, expect, it } from "vitest";
import { rowsToCsv } from "./csv";
import type { FundamentalsRow } from "./types";

const row = (over: Partial<FundamentalsRow> = {}): FundamentalsRow =>
  ({
    ticker: "AAPL",
    companyName: "Apple Inc.",
    peRatio: 35.4,
    epsGrowth: -0.084,
    stale: false,
    error: null,
    ...over,
  }) as FundamentalsRow;

describe("rowsToCsv", () => {
  it("puts the ticker first in the header", () => {
    expect(rowsToCsv([]).split("\n")[0].startsWith("Ticker,")).toBe(true);
  });

  it("emits one line per row plus the header", () => {
    const csv = rowsToCsv([row({ ticker: "AAPL" }), row({ ticker: "MSFT" })]);
    expect(csv.split("\n")).toHaveLength(3);
  });

  it("writes raw numbers so the values stay computable in a spreadsheet", () => {
    // 35.4, not "35.4x" or a pre-formatted percentage.
    expect(rowsToCsv([row({ peRatio: 35.4 })])).toContain("35.4");
  });

  it("leaves missing values as empty fields rather than the display dash", () => {
    const line = rowsToCsv([row({ peRatio: null })]).split("\n")[1];
    expect(line).not.toContain("—");
    expect(line).toContain(",,");
  });

  it("quotes a company name containing a comma", () => {
    const csv = rowsToCsv([row({ companyName: "Alphabet, Inc." })]);
    expect(csv).toContain('"Alphabet, Inc."');
  });

  it("escapes embedded quotes by doubling them", () => {
    const csv = rowsToCsv([row({ companyName: 'The "Big" Co' })]);
    expect(csv).toContain('"The ""Big"" Co"');
  });

  it("neutralises fields a spreadsheet would run as a formula", () => {
    // Excel and Sheets execute a cell starting with = + - or @. A negative
    // growth figure is the everyday case, and =cmd|... is the malicious one.
    const csv = rowsToCsv([row({ companyName: "=1+1" })]);
    expect(csv).toContain("'=1+1");
    expect(csv).not.toMatch(/,=1\+1/);
  });

  it("does not treat a plain negative number as a formula risk in isolation", () => {
    // It is still prefixed for safety, but must remain readable.
    const csv = rowsToCsv([row({ companyName: "-Acme" })]);
    expect(csv).toContain("'-Acme");
  });
});
