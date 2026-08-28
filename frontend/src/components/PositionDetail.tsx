import { useState } from "react";
import type { Position } from "../positions";
import { describeSplit } from "../positions";
import { money, signedMoney, signedPercent } from "./PortfolioSummary";
import type { SplitAdjustment } from "../types";

interface Props {
  ticker: string;
  position: Position | undefined;
  splits: SplitAdjustment[];
  /** Rendered under the trades, so one expander covers holding and thinking. */
  journal?: React.ReactNode;
  onAddLot: (lot: { shares: number; costPerShare: number; tradeDate: string }) => Promise<void>;
  onDeleteLot: (id: string) => Promise<void>;
  onApplySplit: (ratio: number) => Promise<void>;
  onUndoSplit: (id: string) => Promise<void>;
}

/**
 * The trades behind a row, and the form for adding another.
 *
 * Kept behind an expander because most of the time the question is "what is
 * it doing", not "what did I pay". The lots are the source of every derived
 * figure above, so they are shown as entered -- one line per trade, deletable
 * -- rather than summarised into a number that cannot be checked or corrected.
 */
export function PositionDetail({
  ticker,
  position,
  splits,
  journal,
  onAddLot,
  onDeleteLot,
  onApplySplit,
  onUndoSplit,
}: Props) {
  const lots = position?.lots ?? [];

  return (
    <div className="position-detail">
      {position && position.shares > 0 && (
        <dl className="position-stats">
          <Stat label="Shares" value={shares(position.shares)} />
          <Stat label="Average cost" value={position.averageCost == null ? "—" : money(position.averageCost)} />
          <Stat label="Cost basis" value={money(position.costBasis)} />
          <Stat
            label="Market value"
            value={position.marketValue == null ? "—" : money(position.marketValue)}
          />
          <Stat
            label="Unrealised"
            value={position.unrealized == null ? "—" : signedMoney(position.unrealized)}
            sub={position.unrealizedPercent == null ? undefined : signedPercent(position.unrealizedPercent)}
            tone={position.unrealized == null ? undefined : tone(position.unrealized)}
          />
          <Stat
            label="Portfolio weight"
            value={position.weight == null ? "—" : `${(position.weight * 100).toFixed(1)}%`}
          />
        </dl>
      )}

      {position && position.realized !== 0 && (
        <p className="position-realised">
          Realised from sales:{" "}
          <strong className={`tone-${tone(position.realized)}`}>
            {signedMoney(position.realized)}
          </strong>
        </p>
      )}

      {position?.oversold && (
        <p className="position-warning" role="status">
          You have recorded more shares sold than bought for {ticker}. A purchase is probably
          missing — until it is added, the cost basis here understates what you paid.
        </p>
      )}

      {lots.length > 0 && (
        <table className="lot-table">
          <caption className="sr-only">Trades recorded for {ticker}</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Type</th>
              <th scope="col" className="num">Shares</th>
              <th scope="col" className="num">Price</th>
              <th scope="col" className="num">Total</th>
              <th scope="col"><span className="sr-only">Remove</span></th>
            </tr>
          </thead>
          <tbody>
            {lots.map((lot) => (
              <tr key={lot.id}>
                <td>{lot.tradeDate}</td>
                <td>
                  <span className={`lot-kind lot-${lot.shares > 0 ? "buy" : "sell"}`}>
                    {lot.shares > 0 ? "Bought" : "Sold"}
                  </span>
                </td>
                <td className="num">{shares(Math.abs(lot.shares))}</td>
                <td className="num">{money(lot.costPerShare)}</td>
                <td className="num">{money(Math.abs(lot.shares) * lot.costPerShare)}</td>
                <td>
                  <button
                    className="remove-btn"
                    onClick={() => void onDeleteLot(lot.id)}
                    aria-label={`Remove the ${lot.tradeDate} trade of ${ticker}`}
                    title="Remove this trade"
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <AddLotForm ticker={ticker} onAdd={onAddLot} />

      <SplitControl
        ticker={ticker}
        splits={splits}
        hasLots={lots.length > 0}
        onApply={onApplySplit}
        onUndo={onUndoSplit}
      />

      {journal}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className={`position-stat${tone ? ` tone-${tone}` : ""}`}>
      <dt>{label}</dt>
      <dd>
        {value}
        {sub && <span className="position-stat-sub">{sub}</span>}
      </dd>
    </div>
  );
}

const tone = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

/** Whole shares stay whole; fractional ones keep enough digits to be exact. */
const shares = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, ""));

const today = () => new Date().toISOString().slice(0, 10);

function AddLotForm({
  ticker,
  onAdd,
}: {
  ticker: string;
  onAdd: (lot: { shares: number; costPerShare: number; tradeDate: string }) => Promise<void>;
}) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [date, setDate] = useState(today());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const parsedQty = Number(qty);
    const parsedPrice = Number(price);

    if (!Number.isFinite(parsedQty) || parsedQty <= 0) {
      setError("Enter how many shares.");
      return;
    }
    if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) {
      setError("Enter the price per share.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      // A sale is the same shape with the sign flipped, so one form covers
      // both and the lot list stays a single ordered history.
      await onAdd({
        shares: side === "buy" ? parsedQty : -parsedQty,
        costPerShare: parsedPrice,
        tradeDate: date,
      });
      setQty("");
      setPrice("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="lot-form" onSubmit={submit}>
      <div className="lot-side" role="group" aria-label="Trade type">
        {(["buy", "sell"] as const).map((option) => (
          <button
            key={option}
            type="button"
            className={`side-btn${side === option ? " active" : ""}`}
            onClick={() => setSide(option)}
            aria-pressed={side === option}
          >
            {option === "buy" ? "Bought" : "Sold"}
          </button>
        ))}
      </div>

      <label className="lot-field">
        <span>Shares</span>
        <input
          type="number"
          step="any"
          min="0"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="10"
          aria-label={`Shares of ${ticker}`}
        />
      </label>

      <label className="lot-field">
        <span>{side === "buy" ? "Price paid" : "Price sold at"}</span>
        <input
          type="number"
          step="any"
          min="0"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="142.30"
          aria-label={`Price per share of ${ticker}`}
        />
      </label>

      <label className="lot-field">
        <span>Date</span>
        <input
          type="date"
          value={date}
          max={today()}
          onChange={(e) => setDate(e.target.value)}
          aria-label={`Date of the ${ticker} trade`}
        />
      </label>

      <button className="btn btn-small" type="submit" disabled={saving}>
        {saving ? "Saving…" : "Add trade"}
      </button>

      {error && <p className="lot-error">{error}</p>}
    </form>
  );
}

/**
 * Restating a position for a share split.
 *
 * A split multiplies the share count and divides the price, so a position left
 * unadjusted reports a loss of three quarters of its value after a 4-for-1 and
 * looks like a catastrophe rather than an accounting artefact. There is no
 * automatic feed of corporate actions here, so it is entered by hand -- and
 * because entering it wrongly is destructive, every adjustment stays listed
 * with a way back.
 */
function SplitControl({
  ticker,
  splits,
  hasLots,
  onApply,
  onUndo,
}: {
  ticker: string;
  splits: SplitAdjustment[];
  hasLots: boolean;
  onApply: (ratio: number) => Promise<void>;
  onUndo: (id: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [ratio, setRatio] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!hasLots && splits.length === 0) return null;

  async function apply(e: React.FormEvent) {
    e.preventDefault();
    const parsed = Number(ratio);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError("Enter the split ratio: 4 for a 4-for-1, or 0.1 for a reverse 1-for-10.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onApply(parsed);
      setRatio("");
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="split-control">
      {splits.length > 0 && (
        <ul className="split-list">
          {splits.map((split) => (
            <li key={split.id}>
              <span>
                Adjusted for a {describeSplit(split.ratio)} split on{" "}
                {split.applied_at.slice(0, 10)}
              </span>
              <button className="link-btn" onClick={() => void onUndo(split.id)}>
                Undo
              </button>
            </li>
          ))}
        </ul>
      )}

      {open ? (
        <form className="split-form" onSubmit={apply}>
          <label className="lot-field">
            <span>Split ratio</span>
            <input
              type="number"
              step="any"
              min="0"
              value={ratio}
              onChange={(e) => setRatio(e.target.value)}
              placeholder="4"
              aria-label={`Split ratio for ${ticker}`}
              autoFocus
            />
          </label>
          <button className="btn btn-small" type="submit" disabled={busy}>
            {busy ? "Adjusting…" : "Adjust"}
          </button>
          <button className="ghost-btn" type="button" onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </button>
          <p className="lot-hint">
            4 for a 4-for-1 split; 0.1 for a reverse 1-for-10. Your shares multiply and your cost
            per share divides, so what you paid in total does not move. This can be undone.
          </p>
          {error && <p className="lot-error">{error}</p>}
        </form>
      ) : (
        hasLots && (
          <button className="link-btn" onClick={() => setOpen(true)}>
            Adjust for a share split
          </button>
        )
      )}
    </div>
  );
}
