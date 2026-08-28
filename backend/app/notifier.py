"""Turning a fired alert into an email.

Two things call this. A page load checks only the reader's own alerts, which
is instant but useless while nobody has the app open. A scheduled sweep checks
everyone's, which is what actually makes "email me when AAPL hits 320" true.
Both run the same code so a price can only ever fire once, whichever noticed
it first.

Only signed-in owners get email -- an anonymous browser has no address to send
to -- so their alerts still fire, they just surface in the UI instead.
"""

import asyncio
import logging

from app import alerts as alerts_module
from app import mailer
from app.engine import connect, q
from app.fmp_client import FMPError
from app.market_data import fetch_quotes

log = logging.getLogger(__name__)

USER_PREFIX = "user:"


def email_for_owner(owner_id: str) -> str | None:
    if not owner_id.startswith(USER_PREFIX):
        return None
    with connect() as conn:
        row = conn.execute(
            q("SELECT email FROM users WHERE id = :i"),
            {"i": owner_id[len(USER_PREFIX):]},
        ).mappings().first()
        return row["email"] if row else None


async def check_owner(owner_id: str, notify: bool = True) -> dict:
    """Evaluate one owner's pending alerts. Returns what fired and what was sent."""
    tickers = alerts_module.alert_tickers(owner_id)
    if not tickers:
        return {"fired": [], "checked": 0, "emailed": 0, "error": None}

    try:
        quotes = await fetch_quotes(tickers)
    except FMPError as e:
        return {"fired": [], "checked": 0, "emailed": 0, "error": str(e)}

    prices = {
        quote["symbol"]: quote["price"]
        for quote in quotes
        if isinstance(quote.get("price"), (int, float))
    }
    fired = alerts_module.evaluate(owner_id, prices)

    emailed = 0
    if notify and fired:
        emailed = await _send(owner_id, fired)

    return {"fired": fired, "checked": len(prices), "emailed": emailed, "error": None}


async def _send(owner_id: str, fired: list[dict]) -> int:
    address = email_for_owner(owner_id)
    if not address:
        return 0

    sent = 0
    for alert in fired:
        try:
            # Sending blocks on a network round trip. Off the event loop, so a
            # slow provider can't stall every other request on the server --
            # a sweep may send a great many of these in a row.
            delivered = await asyncio.to_thread(
                mailer.send_alert,
                address,
                alert["ticker"],
                alert["direction"],
                alert["threshold"],
                alert["triggered_price"],
            )
        except mailer.EmailError as e:
            # The alert has already fired in the database; a failed send must
            # not undo that or the next sweep would mail a stale crossing.
            log.warning("alert email to %s failed: %s", address, e)
            continue

        if delivered:
            alerts_module.mark_notified(alert["id"])
            sent += 1

    return sent


async def sweep() -> dict:
    """Check every owner with a pending alert. Driven by the scheduler."""
    owners = alerts_module.pending_owners()
    fired = 0
    emailed = 0
    errors: list[str] = []

    for owner_id in owners:
        result = await check_owner(owner_id)
        fired += len(result["fired"])
        emailed += result["emailed"]
        if result["error"]:
            errors.append(result["error"])

    return {
        "owners_checked": len(owners),
        "fired": fired,
        "emailed": emailed,
        # One provider outage shouldn't read as dozens of separate failures.
        "errors": sorted(set(errors)),
    }
