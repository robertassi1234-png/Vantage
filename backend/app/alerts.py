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

ABOVE = "above"
BELOW = "below"
DIRECTIONS = (ABOVE, BELOW)


class AlertError(Exception):
    pass


def create_alert(
    space_id: str, ticker: str, direction: str, threshold: float, note: str | None = None
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
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO alerts (id, space_id, ticker, direction, threshold, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (alert_id, space_id, ticker, direction, float(threshold), note or None, db.now_iso()),
        )
    return get_alert(space_id, alert_id)


def get_alert(space_id: str, alert_id: str) -> dict | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM alerts WHERE space_id = ? AND id = ?", (space_id, alert_id)
        ).fetchone()
        return _row_to_alert(row) if row else None


def list_alerts(space_id: str) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE space_id = ? ORDER BY created_at DESC", (space_id,)
        ).fetchall()
        return [_row_to_alert(r) for r in rows]


def delete_alert(space_id: str, alert_id: str) -> None:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM alerts WHERE space_id = ? AND id = ?", (space_id, alert_id))


def acknowledge_alert(space_id: str, alert_id: str) -> dict | None:
    """Mark a fired alert as seen so it stops being surfaced."""
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE alerts SET acknowledged = 1 WHERE space_id = ? AND id = ?",
            (space_id, alert_id),
        )
    return get_alert(space_id, alert_id)


def alert_tickers(space_id: str) -> list[str]:
    """Distinct tickers with an untriggered alert, so quotes can be fetched."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM alerts WHERE space_id = ? AND triggered_at IS NULL",
            (space_id,),
        ).fetchall()
        return [r["ticker"] for r in rows]


def evaluate(space_id: str, prices: dict[str, float]) -> list[dict]:
    """Fire any alert whose condition the supplied prices now satisfy.

    `prices` maps ticker to last price. Returns the alerts that fired on this
    pass -- not everything already triggered -- so a caller can notify once.
    """
    fired: list[dict] = []
    now = db.now_iso()

    with db.get_conn() as conn:
        pending = conn.execute(
            "SELECT * FROM alerts WHERE space_id = ? AND triggered_at IS NULL", (space_id,)
        ).fetchall()

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
                "UPDATE alerts SET triggered_at = ?, triggered_price = ? WHERE id = ?",
                (now, float(price), row["id"]),
            )
            alert = _row_to_alert(row)
            alert.update(triggered_at=now, triggered_price=float(price))
            fired.append(alert)

    return fired


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
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
