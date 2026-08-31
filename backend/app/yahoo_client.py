"""Yahoo Finance client for quotes, price history and symbol search.

Talks to Yahoo's public JSON endpoints directly rather than going through the
`yfinance` package. yfinance would work, but it pulls in pandas, numpy and
curl_cffi -- about 250MB -- which on a small instance means slower builds and
another second or two of cold start. The two endpoints used here return plain
JSON, so httpx (already a dependency) is enough.

The trade-off is that Yahoo's response shapes are undocumented and can change.
Every failure raises YahooError so callers can fall back to FMP; nothing here
is allowed to take an endpoint down.
"""

import asyncio
from datetime import datetime, timezone

import httpx

from app import provider_health

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Many symbols in one request. The chart endpoint carries more per symbol --
# the 52-week range and the company name -- but costs a request each, and on
# shared hosting seventeen requests in a burst is what gets an address rate
# limited in the first place. So the batch goes first and the chart fills in
# only what it has to.
SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
# "People also watch" -- Yahoo's own similar-company list, keyed on a symbol.
PEERS_URL = "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{symbol}"

# Yahoo rejects requests without a browser-ish User-Agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Yahoo takes a range plus a candle interval rather than explicit dates.
RANGE_PARAMS = {
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
}


class YahooError(Exception):
    pass


async def _get_json(client: httpx.AsyncClient, url: str, **params) -> dict:
    try:
        resp = await client.get(url, params=params, headers=HEADERS)
    except httpx.HTTPError as e:
        raise YahooError(f"Couldn't reach Yahoo Finance: {e}") from e

    if resp.status_code == 429:
        raise YahooError("Yahoo Finance is rate limiting this address")
    if resp.status_code >= 400:
        raise YahooError(f"Yahoo Finance returned {resp.status_code}")

    try:
        return resp.json()
    except ValueError as e:
        raise YahooError("Yahoo Finance returned a malformed response") from e


def _chart_result(payload: dict, symbol: str) -> dict:
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise YahooError(f"Yahoo Finance has no data for '{symbol}'")
    results = chart.get("result") or []
    if not results:
        raise YahooError(f"Yahoo Finance has no data for '{symbol}'")
    return results[0]


def _quote_from_chart(result: dict, symbol: str) -> dict:
    """Yahoo's chart meta carries the live quote, so one call covers both."""
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")

    change = None
    change_percent = None
    if isinstance(price, (int, float)) and isinstance(previous, (int, float)) and previous:
        change = price - previous
        change_percent = (change / previous) * 100

    return {
        "symbol": meta.get("symbol") or symbol,
        "name": meta.get("longName") or meta.get("shortName"),
        "price": price,
        "change": change,
        "changePercent": change_percent,
        "dayLow": meta.get("regularMarketDayLow"),
        "dayHigh": meta.get("regularMarketDayHigh"),
        "yearLow": meta.get("fiftyTwoWeekLow"),
        "yearHigh": meta.get("fiftyTwoWeekHigh"),
        "marketCap": None,  # not present on the chart endpoint
        "volume": meta.get("regularMarketVolume"),
    }


def _points_from_chart(result: dict) -> list[dict]:
    timestamps = result.get("timestamp") or []
    quote_blocks = ((result.get("indicators") or {}).get("quote")) or [{}]
    closes = (quote_blocks[0] or {}).get("close") or []

    points = []
    for ts, close in zip(timestamps, closes):
        # Yahoo pads holidays and halted sessions with nulls.
        if close is None or not isinstance(close, (int, float)):
            continue
        date = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        points.append({"date": date, "close": float(close)})

    points.sort(key=lambda p: p["date"])
    return points


# Long enough to cover a dashboard in one request, short enough that the URL
# stays within what the endpoint accepts.
SPARK_BATCH = 25


def _quote_from_spark(row: dict, symbol: str) -> dict | None:
    """A quote from the batch endpoint, which carries less than the chart.

    No company name and no 52-week range: those come from the chart endpoint
    or from whatever the caller already knows. A row without a usable price is
    returned as None so the caller can fall back for that symbol rather than
    rendering a tile with a blank in it.
    """
    closes = [c for c in (row.get("close") or []) if isinstance(c, (int, float))]
    price = closes[-1] if closes else None
    previous = row.get("chartPreviousClose") or row.get("previousClose")

    if not isinstance(price, (int, float)):
        return None

    change = None
    change_percent = None
    if isinstance(previous, (int, float)) and previous:
        change = price - previous
        change_percent = (change / previous) * 100

    return {
        "symbol": str(row.get("symbol") or symbol).upper(),
        "name": None,
        "price": price,
        "change": change,
        "changePercent": change_percent,
        "dayLow": None,
        "dayHigh": None,
        "yearLow": None,
        "yearHigh": None,
        "marketCap": None,
        "volume": None,
    }


def _spark_rows(payload) -> list[dict]:
    """The rows out of whichever shape this endpoint is returning today.

    It has shipped as a bare mapping of symbol to row and as a result list
    under a "spark" key. Both are read rather than pinning to one and going
    blank the day it changes.
    """
    if isinstance(payload, dict):
        nested = (payload.get("spark") or {}).get("result")
        if isinstance(nested, list):
            rows = []
            for entry in nested:
                blocks = (entry or {}).get("response") or []
                for block in blocks:
                    if isinstance(block, dict):
                        merged = dict(block.get("meta") or {})
                        merged.setdefault("symbol", entry.get("symbol"))
                        merged["close"] = (
                            (block.get("indicators") or {}).get("quote") or [{}]
                        )[0].get("close") or []
                        rows.append(merged)
            return rows
        return [row for row in payload.values() if isinstance(row, dict)]
    return []


async def _batched_quotes(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, dict]:
    """As many symbols per request as the endpoint will take.

    A failure here is not an error: the caller falls back to one chart request
    per symbol, which is what it always did.
    """
    found: dict[str, dict] = {}
    for start in range(0, len(symbols), SPARK_BATCH):
        chunk = symbols[start : start + SPARK_BATCH]
        try:
            payload = await _get_json(
                client, SPARK_URL, symbols=",".join(chunk), range="5d", interval="1d"
            )
        except Exception as e:
            # Broad on purpose: the per-symbol chart path behind this is what
            # the code did before batching, so nothing here should be able to
            # fail the call. A throttled address is the exception -- falling
            # back would make a request per symbol to an address already being
            # told to stop, which is how the throttle got there.
            if provider_health.looks_rate_limited(str(e)):
                raise
            continue

        upper = {s.upper() for s in chunk}
        for row in _spark_rows(payload):
            symbol = str(row.get("symbol") or "").upper()
            if symbol not in upper:
                continue
            quote = _quote_from_spark(row, symbol)
            if quote:
                found[symbol] = quote
    return found


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Current price and day change, in as few requests as possible."""
    if not symbols:
        return []

    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    if not wanted:
        return []

    async with httpx.AsyncClient(timeout=20) as client:
        found = await _batched_quotes(client, wanted)

        missing = [s for s in wanted if s not in found]
        if missing:
            payloads = await asyncio.gather(
                *(_get_json(client, CHART_URL.format(symbol=s), range="1d", interval="1d")
                  for s in missing),
                return_exceptions=True,
            )
            for symbol, payload in zip(missing, payloads):
                if isinstance(payload, Exception):
                    continue
                try:
                    found[symbol] = _quote_from_chart(_chart_result(payload, symbol), symbol)
                except YahooError:
                    continue

    return [found[s] for s in wanted if s in found]


async def fetch_history(symbol: str, range_key: str = "1Y") -> list[dict]:
    """Closing prices over a preset range."""
    period, interval = RANGE_PARAMS.get(range_key.upper(), RANGE_PARAMS["1Y"])

    async with httpx.AsyncClient(timeout=20) as client:
        payload = await _get_json(
            client, CHART_URL.format(symbol=symbol), range=period, interval=interval
        )

    return _points_from_chart(_chart_result(payload, symbol))


async def search_symbols(query: str, limit: int = 8) -> list[dict]:
    """Ticker or company-name lookup. One call, where FMP needs two."""
    query = query.strip()
    if not query:
        return []

    async with httpx.AsyncClient(timeout=10) as client:
        payload = await _get_json(client, SEARCH_URL, q=query, quotesCount=limit, newsCount=0)

    results = []
    for item in (payload or {}).get("quotes") or []:
        symbol = item.get("symbol")
        # Skip futures, options and currencies -- this app is about companies.
        if not symbol or item.get("quoteType") not in (None, "EQUITY", "ETF", "INDEX"):
            continue
        results.append(
            {
                "symbol": symbol,
                "name": item.get("longname") or item.get("shortname"),
                "exchange": item.get("exchDisp") or item.get("exchange"),
                "currency": None,
            }
        )
    return results[:limit]


async def fetch_peers(symbol: str, limit: int = 6) -> list[str]:
    """Companies Yahoo considers similar to `symbol`.

    Yahoo derives these from what people actually look at together, which
    tends to match how an investor thinks about competitors better than a
    sector code does -- it puts NVDA next to AMD rather than next to every
    semiconductor on the exchange.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return []

    async with httpx.AsyncClient(timeout=10) as client:
        payload = await _get_json(client, PEERS_URL.format(symbol=symbol))

    results = ((payload or {}).get("finance") or {}).get("result") or []
    if not results:
        return []

    peers = []
    for item in results[0].get("recommendedSymbols") or []:
        peer = (item or {}).get("symbol")
        if peer and peer.upper() != symbol:
            peers.append(peer.upper())
    return peers[:limit]
