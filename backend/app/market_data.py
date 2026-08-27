"""Routes each market-data request through providers in order.

Yahoo has no published quota, FMP's free tier allows 250 calls a day, so Yahoo
goes first and FMP is the safety net. If Yahoo changes a response shape or
throttles this address, the request quietly falls through and the app keeps
working.

Fundamentals are FMP-only: Yahoo's fundamentals endpoint needs an
authenticated crumb, and those numbers are cached for 24 hours anyway, so they
were never what burned the quota. The call-heavy paths -- quotes, history and
search -- are the ones Yahoo now absorbs.
"""

import logging

from app import fmp_client, yahoo_client
from app.config import settings
from app.fmp_client import FMPError
from app.yahoo_client import YahooError

log = logging.getLogger(__name__)

# Raised by whichever provider failed; the chain treats them alike.
PROVIDER_ERRORS = (FMPError, YahooError)

PROVIDERS = {
    "yahoo": yahoo_client,
    "fmp": fmp_client,
}


def _order() -> list[str]:
    """Provider preference, from the PROVIDER_ORDER environment variable."""
    names = [n.strip().lower() for n in settings.provider_order.split(",") if n.strip()]
    valid = [n for n in names if n in PROVIDERS]
    return valid or ["fmp"]


async def _first_success(operation: str, call, *args, **kwargs):
    """Try each provider in turn; raise the last error if all fail."""
    last_error: Exception | None = None

    for name in _order():
        provider = PROVIDERS[name]
        func = getattr(provider, call, None)
        if func is None:
            continue
        try:
            result = await func(*args, **kwargs)
        except PROVIDER_ERRORS as e:
            # A provider being down is expected; note it and move on.
            log.warning("%s: provider %s failed: %s", operation, name, e)
            last_error = e
            continue

        # An empty result is a miss, not a failure -- but if a later provider
        # can do better, prefer that over returning nothing.
        if result:
            return result
        last_error = last_error or None

    if last_error is not None:
        raise FMPError(str(last_error))
    return []


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    return await _first_success("quotes", "fetch_quotes", symbols)


async def fetch_history(symbol: str, range_key: str = "1Y") -> list[dict]:
    return await _first_success("history", "fetch_history", symbol, range_key)


async def search_symbols(query: str, limit: int = 8) -> list[dict]:
    if not query.strip():
        return []
    return await _first_success("search", "search_symbols", query, limit)


async def fetch_peers(symbol: str, limit: int = 6) -> list[str]:
    return await _first_success("peers", "fetch_peers", symbol, limit)


async def fetch_fundamentals(ticker: str) -> dict:
    """FMP only -- see the module docstring."""
    return await fmp_client.fetch_fundamentals(ticker)
