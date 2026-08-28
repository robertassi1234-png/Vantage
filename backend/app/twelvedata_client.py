"""Twelve Data: quotes, history and fundamentals on a free key.

Worth adding because its free allowance is 800 calls a day -- several times
FMP's -- and, unlike the keyless providers, it does not care what address the
request comes from. Yahoo throttles by IP and shared hosting shares that
reputation with every other tenant; Stooq refuses the datacentre outright. A
key sidesteps both.

Its quirk is that a refusal arrives as HTTP 200 with the failure in the body,
so the status code alone never tells you whether a call worked, and an
exhausted allowance would otherwise be read as "this company has no data".
"""

import httpx

from app.config import settings

BASE_URL = "https://api.twelvedata.com"

# Its history endpoint takes a bar count rather than a date range.
RANGE_BARS = {"1M": 22, "3M": 65, "6M": 130, "1Y": 260, "5Y": 260}
RANGE_INTERVAL = {"1M": "1day", "3M": "1day", "6M": "1day", "1Y": "1day", "5Y": "1week"}

# It uses plain index symbols where Yahoo uses a caret.
INDEX_SYMBOLS = {"^GSPC": "SPX", "^IXIC": "IXIC", "^DJI": "DJI", "^RUT": "RUT"}


class TwelveDataError(Exception):
    pass


def _number(value) -> float | None:
    """Everything arrives as a string, and missing values as "" or None."""
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_symbol(symbol: str) -> str:
    return INDEX_SYMBOLS.get(symbol.upper(), symbol.upper())


def _from_symbol(symbol: str) -> str:
    for original, mapped in INDEX_SYMBOLS.items():
        if mapped == symbol.upper():
            return original
    return symbol.upper()


def _check(payload: dict) -> dict:
    """Raise if the body carries a refusal, whatever the status code said."""
    if not isinstance(payload, dict):
        raise TwelveDataError("Twelve Data returned an unexpected response")

    if payload.get("status") == "error" or payload.get("code") in (400, 401, 403, 429):
        message = str(payload.get("message") or "Twelve Data refused the request")
        if payload.get("code") == 429 or "credits" in message.lower():
            # Worded so the health tracker recognises it and benches the
            # provider rather than asking again on the next lookup.
            raise TwelveDataError(f"Twelve Data rate limit reached: {message}")
        raise TwelveDataError(message)
    return payload


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict:
    if not settings.twelve_data_api_key:
        raise TwelveDataError("TWELVE_DATA_API_KEY is not set")

    try:
        response = await client.get(
            f"{BASE_URL}/{path}", params={**params, "apikey": settings.twelve_data_api_key}
        )
    except httpx.HTTPError as e:
        raise TwelveDataError(f"Couldn't reach Twelve Data: {e}") from e

    if response.status_code >= 400:
        raise TwelveDataError(f"Twelve Data returned {response.status_code}")

    try:
        return _check(response.json())
    except ValueError as e:
        raise TwelveDataError("Twelve Data returned a malformed response") from e


def _quote_row(symbol: str, data: dict) -> dict | None:
    price = _number(data.get("close"))
    if price is None:
        return None

    year = data.get("fifty_two_week") or {}
    return {
        "symbol": _from_symbol(symbol),
        "name": data.get("name"),
        "price": price,
        "change": _number(data.get("change")),
        "changePercent": _number(data.get("percent_change")),
        "dayLow": _number(data.get("low")),
        "dayHigh": _number(data.get("high")),
        "yearLow": _number(year.get("low")),
        "yearHigh": _number(year.get("high")),
        "marketCap": None,
        "volume": _number(data.get("volume")),
    }


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """A whole batch in one call, which is what keeps the allowance intact."""
    if not symbols:
        return []

    mapped = [_to_symbol(s) for s in symbols]
    async with httpx.AsyncClient(timeout=12) as client:
        payload = await _get(client, "quote", symbol=",".join(mapped))

    # One symbol comes back as a bare quote object, several come back keyed by
    # symbol. Decided by looking at the payload rather than by counting what
    # was asked for, so a single-symbol batch that arrives keyed anyway -- or
    # a shape that changes between versions -- still reads correctly.
    rows = {mapped[0]: payload} if "close" in payload else payload

    quotes = []
    for symbol, data in rows.items():
        if not isinstance(data, dict):
            continue
        # A batch reports per-symbol failures inline; skip those, keep the rest.
        if data.get("status") == "error":
            continue
        row = _quote_row(symbol, data)
        if row:
            quotes.append(row)
    return quotes


async def fetch_history(symbol: str, range_key: str = "1Y") -> list[dict]:
    async with httpx.AsyncClient(timeout=12) as client:
        payload = await _get(
            client,
            "time_series",
            symbol=_to_symbol(symbol),
            interval=RANGE_INTERVAL.get(range_key, "1day"),
            outputsize=str(RANGE_BARS.get(range_key, 260)),
        )

    values = payload.get("values") or []
    points = []
    for row in values:
        close = _number((row or {}).get("close"))
        date = (row or {}).get("datetime")
        if close is not None and date:
            points.append({"date": date, "close": close})

    if not points:
        raise TwelveDataError(f"Twelve Data has no history for '{symbol}'")

    # It returns newest first; every chart in the app reads oldest first.
    points.reverse()
    return points
