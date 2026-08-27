"""Suggesting companies to compare against.

Comparing a stock to nothing tells you very little -- a 28x earnings multiple
is only high or low next to the companies it competes with. Finding those
peers by hand means already knowing the industry, which is exactly what
someone new to a name does not.

So the suggestions come from what is already in the comparison list: peers of
each member, ranked by how many members suggested them. A name that shows up
as a peer of three of your holdings is a more useful addition than one that
came from a single row.
"""

import asyncio
import logging

from app import db
from app.fmp_client import FMPError
from app.market_data import fetch_peers, fetch_quotes

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 6
# Enough to rank well without spending a call per row on a long list.
MAX_SEEDS = 8


async def suggest(owner_id: str, limit: int = MAX_SUGGESTIONS) -> dict:
    """Peer suggestions for an owner's comparison list."""
    current = db.get_watchlist(owner_id, db.COMPARE_LIST)
    if not current:
        return {"suggestions": [], "based_on": [], "error": None}

    seeds = current[:MAX_SEEDS]
    results = await asyncio.gather(
        *(fetch_peers(seed) for seed in seeds), return_exceptions=True
    )

    held = {t.upper() for t in current}
    # Also exclude the watchlist: suggesting something already being followed
    # is noise, even though the two lists are separate.
    held |= {t.upper() for t in db.get_watchlist(owner_id, db.WATCH_LIST)}

    ranked: dict[str, dict] = {}
    failures = 0

    for seed, result in zip(seeds, results):
        if isinstance(result, BaseException):
            log.warning("peers for %s failed: %s", seed, result)
            failures += 1
            continue

        for peer in result:
            if peer in held:
                continue
            entry = ranked.setdefault(peer, {"symbol": peer, "count": 0, "because_of": []})
            entry["count"] += 1
            entry["because_of"].append(seed)

    if not ranked:
        error = None
        if failures == len(seeds):
            error = "Couldn't look up peers right now."
        return {"suggestions": [], "based_on": seeds, "error": error}

    # Most-shared first; ties broken by the order the list is already in, so
    # the ranking is stable rather than shuffling between page loads.
    order = {t: i for i, t in enumerate(seeds)}
    top = sorted(
        ranked.values(),
        key=lambda e: (-e["count"], order.get(e["because_of"][0], 99), e["symbol"]),
    )[:limit]

    await _attach_names(top)
    return {"suggestions": top, "based_on": seeds, "error": None}


async def _attach_names(suggestions: list[dict]) -> None:
    """Add a company name and price, so a row means something before it's added."""
    if not suggestions:
        return

    try:
        quotes = await fetch_quotes([s["symbol"] for s in suggestions])
    except FMPError as e:
        # A bare ticker is still worth suggesting; names are decoration.
        log.warning("peer quote lookup failed: %s", e)
        return

    by_symbol = {q["symbol"]: q for q in quotes}
    for suggestion in suggestions:
        quote = by_symbol.get(suggestion["symbol"]) or {}
        suggestion["name"] = quote.get("name")
        suggestion["price"] = quote.get("price")
        suggestion["changePercent"] = quote.get("changePercent")
