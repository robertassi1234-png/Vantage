"""Stooq: quotes and daily history as CSV, with no API key at all.

Worth having precisely because it needs no signup and publishes no quota. When
Yahoo throttles an address and FMP's daily allowance is spent, this still
answers, which is the difference between a working watchlist and an empty one.

What it does not do is fundamentals, search, or intraday. It is a floor, not a
replacement: last close, previous close, and a daily series. Placing it last in
the chain means its coarser data is only ever used when the alternative is
nothing.

CSV rather than JSON, so every field is parsed defensively -- Stooq writes
"N/D" for values it does not have, and a bad row must not take a whole batch
down with it.
"""

import csv
import io
from datetime import datetime, timezone

import httpx

QUOTE_URL = "https://stooq.com/q/l/"
HISTORY_URL = "https://stooq.com/q/d/l/"

# Stooq namespaces its symbols by market; US listings carry a .us suffix.
US_SUFFIX = ".us"

# Stooq indexes carry a ^ prefix like Yahoo's, but under different names.
INDEX_SYMBOLS = {
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "^DJI": "^dji",
    "^RUT": "^rut",
}

RANGE_INTERVAL = {"1M": "d", "3M": "d", "6M": "d", "1Y": "d", "5Y": "w"}


class StooqError(Exception):
    pass


def to_stooq_symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if symbol.upper() in INDEX_SYMBOLS:
        return INDEX_SYMBOLS[symbol.upper()]
    if symbol.startswith("^"):
        # An index we have no mapping for; Stooq would not know it either.
        raise StooqError(f"Stooq has no symbol for '{symbol}'")
    return f"{symbol.lower()}{US_SUFFIX}"


def from_stooq_symbol(stooq_symbol: str) -> str:
    lowered = stooq_symbol.lower()
    for original, mapped in INDEX_SYMBOLS.items():
        if mapped == lowered:
            return original
    if lowered.endswith(US_SUFFIX):
        return lowered[: -len(US_SUFFIX)].upper()
    return stooq_symbol.upper()


async def _get_csv(url: str, **params) -> str:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise StooqError(f"Couldn't reach Stooq: {e}") from e

    if response.status_code == 429:
        raise StooqError("Stooq is rate limiting this address")
    if response.status_code >= 400:
        raise StooqError(f"Stooq returned {response.status_code}")

    text = response.text.strip()
    if not text or text.lower().startswith("exceeded"):
        # Stooq answers an over-limit request with a plain-text notice rather
        # than a status code, so the body has to be read to notice.
        raise StooqError("Stooq daily request limit exceeded")
    return text


def _number(value: str) -> float | None:
    """Stooq writes N/D for anything it does not have."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Last price and the move since the previous close, one row per symbol."""
    if not symbols:
        return []

    wanted = {}
    for symbol in symbols:
        try:
            wanted[to_stooq_symbol(symbol)] = symbol.upper()
        except StooqError:
            continue
    if not wanted:
        return []

    # s=a,b,c fetches a whole batch in one request, which is the difference
    # between one call per page load and one per ticker.
    text = await _get_csv(
        QUOTE_URL, s=",".join(wanted), f="sd2t2ohlcv", h="", e="csv"
    )

    quotes = []
    for row in csv.DictReader(io.StringIO(text)):
        stooq_symbol = (row.get("Symbol") or "").lower()
        price = _number(row.get("Close"))
        if not stooq_symbol or price is None:
            continue

        open_price = _number(row.get("Open"))
        # Stooq's snapshot has no previous close, so the day's open is the
        # closest honest reference for a change figure.
        change = price - open_price if open_price is not None else None

        quotes.append(
            {
                "symbol": wanted.get(stooq_symbol, from_stooq_symbol(stooq_symbol)),
                "name": None,
                "price": price,
                "change": change,
                "changePercent": (
                    (change / open_price * 100) if change is not None and open_price else None
                ),
                "dayLow": _number(row.get("Low")),
                "dayHigh": _number(row.get("High")),
                "yearLow": None,
                "yearHigh": None,
                "marketCap": None,
                "volume": _number(row.get("Volume")),
            }
        )
    return quotes


async def fetch_history(symbol: str, range_key: str = "1Y") -> list[dict]:
    """Daily or weekly closes, oldest first."""
    stooq_symbol = to_stooq_symbol(symbol)
    text = await _get_csv(
        HISTORY_URL, s=stooq_symbol, i=RANGE_INTERVAL.get(range_key, "d")
    )

    points = []
    for row in csv.DictReader(io.StringIO(text)):
        close = _number(row.get("Close"))
        date = row.get("Date")
        if close is None or not date:
            continue
        points.append({"date": date, "close": close})

    if not points:
        raise StooqError(f"Stooq has no history for '{symbol}'")

    # Stooq returns everything it has; the caller asked for a window.
    return points[-_points_for(range_key):]


def _points_for(range_key: str) -> int:
    # Trading days, roughly: about 21 a month, and weekly candles past a year.
    return {"1M": 22, "3M": 65, "6M": 130, "1Y": 260, "5Y": 260}.get(range_key, 260)


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
