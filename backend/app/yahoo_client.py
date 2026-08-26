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

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"

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


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Current price and day change. One chart call per symbol, run concurrently."""
    if not symbols:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        payloads = await asyncio.gather(
            *(_get_json(client, CHART_URL.format(symbol=s), range="1d", interval="1d")
              for s in symbols),
            return_exceptions=True,
        )

    quotes = []
    for symbol, payload in zip(symbols, payloads):
        if isinstance(payload, Exception):
            continue
        try:
            quotes.append(_quote_from_chart(_chart_result(payload, symbol), symbol))
        except YahooError:
            continue
    return quotes


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
