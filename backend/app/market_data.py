"""Routes each market-data request through providers in order.

Yahoo has no published quota, FMP's free tier allows 250 calls a day, and
Stooq needs no key at all. So Yahoo goes first, FMP is the safety net, and
Stooq is the floor beneath both -- coarser data, but it answers when the
others have stopped. A provider that reports being out of quota is set aside
for a while rather than retried on every lookup; see `provider_health`.

Fundamentals follow their own chain. They were FMP-only, which made a 250-call
daily allowance the ceiling on the whole comparison table: four calls per
ticker, so a few dozen refreshes and the feature stopped. Yahoo cannot serve
them without an authenticated crumb, so the fallbacks are keyed providers --
each skipped automatically when its key is unset.
"""

import logging

from app import (
    alphavantage_client,
    finnhub_client,
    fmp_client,
    provider_health,
    stooq_client,
    twelvedata_client,
    yahoo_client,
)
from app.config import settings
from app.fmp_client import FMPError
from app.alphavantage_client import AlphaVantageError
from app.finnhub_client import FinnhubError
from app.stooq_client import StooqError
from app.twelvedata_client import TwelveDataError
from app.yahoo_client import YahooError

log = logging.getLogger(__name__)

# Raised by whichever provider failed; the chain treats them alike.
PROVIDER_ERRORS = (
    FMPError,
    YahooError,
    StooqError,
    FinnhubError,
    AlphaVantageError,
    TwelveDataError,
)

PROVIDERS = {
    "yahoo": yahoo_client,
    "fmp": fmp_client,
    # No key and no signup, so it is always available as a floor. Last,
    # because it carries no company names or 52-week range.
    "stooq": stooq_client,
    # Optional, keyed. Skipped when no key is set, so the app runs on none,
    # one or all of them. A key also sidesteps the address-reputation problem
    # the keyless providers have on shared hosting.
    "twelvedata": twelvedata_client,
    "finnhub": finnhub_client,
    "alphavantage": alphavantage_client,
}


# A keyed provider with no key is not a fallback, it is a wasted round trip.
# Named here so the status endpoint can tell "not set up" from "out of quota".
REQUIRED_KEYS = {
    "fmp": "fmp_api_key",
    "finnhub": "finnhub_api_key",
    "twelvedata": "twelve_data_api_key",
    "alphavantage": "alpha_vantage_api_key",
}


def is_configured(name: str) -> bool:
    """Whether a provider can be called at all."""
    key = REQUIRED_KEYS.get(name)
    return bool(getattr(settings, key, "")) if key else True


def _order() -> list[str]:
    """Provider preference, from the PROVIDER_ORDER environment variable."""
    names = [n.strip().lower() for n in settings.provider_order.split(",") if n.strip()]
    valid = [n for n in names if n in PROVIDERS]
    # Keyed providers not named in the order still serve as a backstop, so
    # adding a key is enough to get a fallback without also editing the order.
    return (valid or ["fmp"]) + [
        n for n in PROVIDERS if n not in valid and n in REQUIRED_KEYS
    ]


def _summarise(failures: list[tuple[str, str]], benched: list[str]) -> str:
    """One sentence for the reader when every provider has failed.

    The last provider to fail is the least informative one -- it is the
    fallback of a fallback, reached only because everything better was already
    gone. Reporting it produced "Stooq returned 404" for what was really an
    exhausted primary. So the first real failure leads, since that is the
    provider that was supposed to serve the request.
    """
    if failures and all(provider_health.looks_rate_limited(m) for _, m in failures):
        return (
            "Market data is rate limited across every provider right now. "
            "They recover on their own -- try again in a few minutes."
        )

    if benched and not failures:
        return (
            "Market data is rate limited across every provider right now. "
            "They recover on their own -- try again in a few minutes."
        )

    if failures:
        return failures[0][1]
    return "Market data is unavailable right now."


async def _first_success(operation: str, call, *args, **kwargs):
    """Try each provider in turn; summarise if all of them fail."""
    failures: list[tuple[str, str]] = []
    benched: list[str] = []
    attempted = 0

    for name in _order():
        provider = PROVIDERS[name]
        func = getattr(provider, call, None)
        if func is None:
            continue

        # A provider with no key is not a fallback, it is a wasted round trip
        # -- and its "key is not set" complaint would otherwise surface to the
        # reader as the reason their data is missing.
        if not is_configured(name):
            continue

        # A provider that has just said it is out of quota will say so again.
        # Skipping it saves a round trip per lookup rather than per session.
        if not provider_health.is_available(name):
            benched.append(name)
            continue

        attempted += 1
        try:
            result = await func(*args, **kwargs)
        except PROVIDER_ERRORS as e:
            # A provider being down is expected; note it and move on.
            log.warning("%s: provider %s failed: %s", operation, name, e)
            provider_health.record_failure(name, str(e))
            failures.append((name, str(e)))
            continue

        # An empty result is a miss, not a failure -- but if a later provider
        # can do better, prefer that over returning nothing.
        if result:
            provider_health.record_success(name)
            return result

    if failures:
        raise FMPError(_summarise(failures, benched))

    # Nothing ran at all, so there is no error to report and no data either.
    # Say which, rather than returning an empty result that reads as "no such
    # ticker". Only when every provider was benched: if one actually ran and
    # simply had nothing, that is a genuine empty result.
    if benched and attempted == 0:
        raise FMPError(_summarise(failures, benched))
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


# Yahoo and Stooq have no fundamentals endpoint, so this is its own order.
FUNDAMENTALS_PROVIDERS = ("fmp", "finnhub", "alphavantage")


def _fundamentals_order() -> list[str]:
    """Configured order, narrowed to providers that actually serve these."""
    configured = [n for n in _order() if n in FUNDAMENTALS_PROVIDERS]
    # Anything configured comes first, then the rest as a backstop, so adding
    # a key is enough to get a fallback without also editing PROVIDER_ORDER.
    return configured + [n for n in FUNDAMENTALS_PROVIDERS if n not in configured]


async def fetch_fundamentals(ticker: str) -> dict:
    """Fundamentals for one ticker, from whichever provider still answers."""
    failures: list[tuple[str, str]] = []
    benched: list[str] = []
    attempted = 0

    for name in _fundamentals_order():
        # An unkeyed provider cannot serve anything, and saying so in the
        # table -- "ALPHA_VANTAGE_API_KEY is not set" against a ticker -- tells
        # the reader nothing about their stock.
        if not is_configured(name):
            continue

        if not provider_health.is_available(name):
            benched.append(name)
            continue

        attempted += 1
        try:
            result = await PROVIDERS[name].fetch_fundamentals(ticker)
        except PROVIDER_ERRORS as e:
            log.warning("fundamentals: provider %s failed: %s", name, e)
            provider_health.record_failure(name, str(e))
            failures.append((name, str(e)))
            continue

        if result:
            provider_health.record_success(name)
            return result

    if failures or benched:
        raise FMPError(_summarise(failures, benched))
    raise FMPError(f"No data found for ticker '{ticker}'")
