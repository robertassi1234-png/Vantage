"""Price alerts.

An alert is a standing question -- "tell me when AAPL goes above 320" --
evaluated against the quotes the app already fetches. It fires once: the first
crossing stamps `triggered_at`, and the alert stays triggered until the reader
acknowledges or deletes it, rather than re-firing on every page load while the
price sits past the threshold.

Delivery is the hard part, not the logic. Checking a price while nobody has the
app open needs a process that is always running and storage that survives a
restart, neither of which a sleeping free-tier instance provides. So evaluation
is driven by whatever fetches quotes -- a page load today, a scheduler later --
and the same code serves both.
"""

import uuid
from datetime import datetime, timezone

from app import db
from app.engine import connect, q

ABOVE = "above"
BELOW = "below"
DIRECTIONS = (ABOVE, BELOW)


class AlertError(Exception):
    pass


def create_alert(
    owner_id: str, ticker: str, direction: str, threshold: float, note: str | None = None
) -> dict:
    direction = direction.strip().lower()
    if direction not in DIRECTIONS:
        raise AlertError(f"Direction must be one of: {', '.join(DIRECTIONS)}.")
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        raise AlertError("The alert price must be a positive number.")

    ticker = ticker.strip().upper()
    if not ticker:
        raise AlertError("Ticker cannot be empty.")

    alert_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            q(
                "INSERT INTO alerts "
                "(id, owner_id, ticker, direction, threshold, note, created_at) "
                "VALUES (:i, :o, :t, :d, :th, :n, :c)"
            ),
            {
                "i": alert_id,
                "o": owner_id,
                "t": ticker,
                "d": direction,
                "th": float(threshold),
                "n": note or None,
                "c": db.now_iso(),
            },
        )
    return get_alert(owner_id, alert_id)


def get_alert(owner_id: str, alert_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            q("SELECT * FROM alerts WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": alert_id},
        ).mappings().first()
        return _row_to_alert(row) if row else None


def list_alerts(owner_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            q("SELECT * FROM alerts WHERE owner_id = :o ORDER BY created_at DESC"),
            {"o": owner_id},
        ).mappings()
        return [_row_to_alert(r) for r in rows]


def delete_alert(owner_id: str, alert_id: str) -> None:
    with connect() as conn:
        conn.execute(
            q("DELETE FROM alerts WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": alert_id},
        )


def acknowledge_alert(owner_id: str, alert_id: str) -> dict | None:
    """Mark a fired alert as seen so it stops being surfaced."""
    with connect() as conn:
        conn.execute(
            q("UPDATE alerts SET acknowledged = 1 WHERE owner_id = :o AND id = :i"),
            {"o": owner_id, "i": alert_id},
        )
    return get_alert(owner_id, alert_id)


def alert_tickers(owner_id: str) -> list[str]:
    """Distinct tickers with an untriggered alert, so quotes can be fetched."""
    with connect() as conn:
        rows = conn.execute(
            q(
                "SELECT DISTINCT ticker FROM alerts "
                "WHERE owner_id = :o AND triggered_at IS NULL"
            ),
            {"o": owner_id},
        ).mappings()
        return [r["ticker"] for r in rows]


def evaluate(owner_id: str, prices: dict[str, float]) -> list[dict]:
    """Fire any alert whose condition the supplied prices now satisfy.

    `prices` maps ticker to last price. Returns the alerts that fired on this
    pass -- not everything already triggered -- so a caller can notify once.
    """
    fired: list[dict] = []
    now = db.now_iso()

    with connect() as conn:
        pending = conn.execute(
            q("SELECT * FROM alerts WHERE owner_id = :o AND triggered_at IS NULL"),
            {"o": owner_id},
        ).mappings().all()

        for row in pending:
            price = prices.get(row["ticker"])
            if not isinstance(price, (int, float)):
                continue

            crossed = (
                price >= row["threshold"]
                if row["direction"] == ABOVE
                else price <= row["threshold"]
            )
            if not crossed:
                continue

            conn.execute(
                q(
                    "UPDATE alerts SET triggered_at = :t, triggered_price = :p WHERE id = :i"
                ),
                {"t": now, "p": float(price), "i": row["id"]},
            )
            alert = _row_to_alert(row)
            alert.update(triggered_at=now, triggered_price=float(price))
            fired.append(alert)

    return fired


def mark_notified(alert_id: str) -> None:
    """Stamp an alert as emailed, so a retry of the sweep can't mail it twice."""
    with connect() as conn:
        conn.execute(
            q("UPDATE alerts SET notified_at = :t WHERE id = :i"),
            {"t": db.now_iso(), "i": alert_id},
        )


def pending_owners() -> list[str]:
    """Every owner with an untriggered alert, for the scheduled sweep."""
    with connect() as conn:
        rows = conn.execute(
            q("SELECT DISTINCT owner_id FROM alerts WHERE triggered_at IS NULL")
        ).mappings()
        return [r["owner_id"] for r in rows]


def _row_to_alert(row) -> dict:
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "direction": row["direction"],
        "threshold": row["threshold"],
        "note": row["note"],
        "created_at": row["created_at"],
        "triggered_at": row["triggered_at"],
        "triggered_price": row["triggered_price"],
        "acknowledged": bool(row["acknowledged"]),
        "notified_at": row["notified_at"] if "notified_at" in row.keys() else None,
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
