import type { Portfolio } from "../positions";

/**
 * What the whole thing is worth, above the list it is derived from.
 *
 * Four figures, because those are the four questions in order: what is it
 * worth, what did it do today, what has it made since I bought, and what have
 * I actually banked. Realised profit only appears once something has been
 * sold -- until then it is a zero that invites the wrong reading.
 *
 * The strip renders only when a position exists. Someone using the app purely
 * as a watchlist should never see a row of zeroes implying they are missing
 * something.
 */
export function PortfolioSummary({ portfolio }: { portfolio: Portfolio }) {
  if (!portfolio.hasPositions) return null;

  const { totalValue, dayChange, dayChangePercent, unrealized, unrealizedPercent } = portfolio;

  return (
    <section className="portfolio-strip" aria-label="Your portfolio">
      <Figure label="Portfolio value" value={money(totalValue)} sub={count(portfolio)} />
      <Figure
        label="Today"
        value={signedMoney(dayChange)}
        sub={dayChangePercent == null ? undefined : signedPercent(dayChangePercent)}
        tone={toneOf(dayChange)}
      />
      <Figure
        label="Unrealised"
        value={signedMoney(unrealized)}
        sub={unrealizedPercent == null ? undefined : signedPercent(unrealizedPercent)}
        tone={toneOf(unrealized)}
      />
      {portfolio.realized !== 0 && (
        <Figure
          label="Realised"
          value={signedMoney(portfolio.realized)}
          sub="from sales"
          tone={toneOf(portfolio.realized)}
        />
      )}

      {portfolio.unpriced.length > 0 && (
        <p className="portfolio-caveat">
          {portfolio.unpriced.join(", ")} {portfolio.unpriced.length === 1 ? "has" : "have"} no
          price right now, so these totals are incomplete.
        </p>
      )}
    </section>
  );
}

interface FigureProps {
  label: string;
  value: string;
  sub?: string;
  tone?: "up" | "down" | "flat";
}

function Figure({ label, value, sub, tone }: FigureProps) {
  return (
    <div className={`portfolio-figure${tone ? ` tone-${tone}` : ""}`}>
      <span className="portfolio-label">{label}</span>
      <span className="portfolio-value">
        {/* The arrow carries the direction for anyone who cannot separate the
            red from the green. */}
        {tone && tone !== "flat" && (
          <span className="portfolio-arrow" aria-hidden="true">{tone === "up" ? "▲" : "▼"}</span>
        )}
        {value}
      </span>
      {sub && <span className="portfolio-sub">{sub}</span>}
    </div>
  );
}

const count = (p: Portfolio) => {
  const held = p.positions.filter((x) => x.shares > 0).length;
  return `${held} ${held === 1 ? "position" : "positions"}`;
};

const toneOf = (v: number): "up" | "down" | "flat" => (v > 0 ? "up" : v < 0 ? "down" : "flat");

export const money = (v: number) =>
  v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export const signedMoney = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${money(Math.abs(v))}`;

export const signedPercent = (v: number) =>
  `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`;
