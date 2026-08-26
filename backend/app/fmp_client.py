"""Thin client for the Financial Modeling Prep API.

Uses the "stable" API (the legacy /api/v3/ endpoints were retired by FMP
in August 2025). Docs: https://site.financialmodelingprep.com/developer/docs/stable
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

BASE_URL = "https://financialmodelingprep.com/stable"


class FMPError(Exception):
    pass


def _first(items: list | dict | None) -> dict:
    if isinstance(items, list):
        return items[0] if items else {}
    if isinstance(items, dict):
        return items
    return {}


def _pick(source: dict, *names: str):
    """Return the first present, non-null field.

    FMP has renamed fields across API generations (mktCap -> marketCap,
    changesPercentage -> changePercentage), so accept the known spellings
    rather than pinning to one and breaking on the next rename.
    """
    for name in names:
        value = source.get(name)
        if value is not None:
            return value
    return None


async def _get(client: httpx.AsyncClient, path: str, **params: str) -> list | dict:
    """Single choke point for FMP calls.

    Every failure leaves here as an FMPError, including transport-level ones.
    Callers catch FMPError to degrade gracefully; letting a raw httpx timeout
    or connection error escape turns one flaky request into a 500 for the
    whole endpoint.
    """
    try:
        resp = await client.get(
            f"{BASE_URL}/{path}",
            params={"apikey": settings.fmp_api_key, **params},
        )
    except httpx.HTTPError as e:
        raise FMPError(f"Couldn't reach the market data service: {e}") from e

    if resp.status_code == 401 or resp.status_code == 403:
        raise FMPError("FMP API key is missing or invalid")
    if resp.status_code == 429:
        raise FMPError("FMP API rate limit reached (free tier: 250 calls/day)")

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise FMPError(f"Market data service returned {resp.status_code}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise FMPError("Market data service returned a malformed response") from e

    if isinstance(data, dict) and data.get("Error Message"):
        raise FMPError(data["Error Message"])
    return data


async def search_symbols(query: str, limit: int = 8) -> list[dict]:
    """Look up tickers by symbol *or* company name.

    Queries both FMP search endpoints and merges the results so that typing
    either "AAPL" or "apple" finds Apple. Exact symbol matches rank first.
    """
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")

    query = query.strip()
    if not query:
        return []

    async with httpx.AsyncClient(timeout=10) as client:
        by_symbol, by_name = await asyncio.gather(
            _get(client, "search-symbol", query=query, limit=str(limit)),
            _get(client, "search-name", query=query, limit=str(limit)),
            return_exceptions=True,
        )

    results: dict[str, dict] = {}
    for batch in (by_symbol, by_name):
        if isinstance(batch, Exception) or not isinstance(batch, list):
            continue
        for item in batch:
            symbol = (item or {}).get("symbol")
            if not symbol or symbol in results:
                continue
            results[symbol] = {
                "symbol": symbol,
                "name": item.get("name"),
                "exchange": item.get("exchange") or item.get("exchangeFullName"),
                "currency": item.get("currency"),
            }

    if not results:
        return []

    upper = query.upper()

    def rank(entry: dict) -> tuple:
        symbol = entry["symbol"].upper()
        name = (entry.get("name") or "").upper()
        return (
            symbol != upper,               # exact ticker match first
            not symbol.startswith(upper),  # then ticker prefix
            not name.startswith(upper),    # then company-name prefix
            len(symbol),                   # prefer plain tickers over suffixed listings
            symbol,
        )

    return sorted(results.values(), key=rank)[:limit]


async def fetch_fundamentals(ticker: str) -> dict:
    """Fetch and combine the fundamentals we care about for one ticker."""
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")

    async with httpx.AsyncClient(timeout=15) as client:
        profile, ratios, key_metrics, growth = await _gather(client, ticker)

    if not profile:
        raise FMPError(f"No data found for ticker '{ticker}'")

    return {
        "ticker": ticker.upper(),
        "companyName": profile.get("companyName"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "price": profile.get("price"),
        "marketCap": profile.get("marketCap"),
        "beta": profile.get("beta"),
        "peRatio": ratios.get("priceToEarningsRatioTTM"),
        "pegRatio": ratios.get("priceToEarningsGrowthRatioTTM"),
        "evToEbitda": key_metrics.get("evToEBITDATTM"),
        "priceToBook": ratios.get("priceToBookRatioTTM"),
        "priceToSales": ratios.get("priceToSalesRatioTTM"),
        "debtToEquity": ratios.get("debtToEquityRatioTTM"),
        "currentRatio": ratios.get("currentRatioTTM"),
        "revenueGrowth": growth.get("growthRevenue"),
        "epsGrowth": growth.get("growthEPS"),
        "netProfitMargin": ratios.get("netProfitMarginTTM"),
        "operatingMargin": ratios.get("operatingProfitMarginTTM"),
        "returnOnEquity": key_metrics.get("returnOnEquityTTM"),
        "dividendYield": ratios.get("dividendYieldTTM"),
    }


RANGE_DAYS = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366, "5Y": 1827}


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Current price and day change for one or more symbols.

    Requests run concurrently; a symbol that fails is omitted rather than
    failing the whole batch, so one bad index symbol can't blank the row.
    """
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")
    if not symbols:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        responses = await asyncio.gather(
            *(_get(client, "quote", symbol=s) for s in symbols),
            return_exceptions=True,
        )

    quotes = []
    for symbol, response in zip(symbols, responses):
        if isinstance(response, Exception):
            continue
        data = _first(response)
        if not data:
            continue
        quotes.append(
            {
                "symbol": data.get("symbol") or symbol,
                "name": _pick(data, "name", "companyName"),
                "price": _pick(data, "price", "previousClose"),
                "change": _pick(data, "change", "changes"),
                "changePercent": _pick(data, "changePercentage", "changesPercentage"),
                "dayLow": _pick(data, "dayLow"),
                "dayHigh": _pick(data, "dayHigh"),
                "yearLow": _pick(data, "yearLow"),
                "yearHigh": _pick(data, "yearHigh"),
                "marketCap": _pick(data, "marketCap", "mktCap"),
                "volume": _pick(data, "volume"),
            }
        )
    return quotes


async def fetch_history(symbol: str, range_key: str = "1Y") -> list[dict]:
    """Daily closing prices for a symbol over the requested range."""
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")

    days = RANGE_DAYS.get(range_key.upper(), 366)
    start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    end = datetime.now(timezone.utc).date().isoformat()

    async with httpx.AsyncClient(timeout=20) as client:
        data = await _get(
            client, "historical-price-eod/light", symbol=symbol, **{"from": start, "to": end}
        )

    # The light endpoint returns a bare list; some variants nest it under
    # "historical" alongside the symbol.
    rows = data if isinstance(data, list) else data.get("historical", [])

    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        close = _pick(row, "close", "price", "adjClose")
        if date and isinstance(close, (int, float)):
            points.append({"date": str(date)[:10], "close": float(close)})

    # FMP returns newest-first; charts read left-to-right oldest-first.
    points.sort(key=lambda p: p["date"])
    return points


async def _gather(client: httpx.AsyncClient, ticker: str):
    profile_task = _get(client, "profile", symbol=ticker)
    ratios_task = _get(client, "ratios-ttm", symbol=ticker)
    key_metrics_task = _get(client, "key-metrics-ttm", symbol=ticker)
    growth_task = _get(client, "income-statement-growth", symbol=ticker, limit="1")

    profile, ratios, key_metrics, growth = await asyncio.gather(
        profile_task, ratios_task, key_metrics_task, growth_task
    )
    return _first(profile), _first(ratios), _first(key_metrics), _first(growth)
