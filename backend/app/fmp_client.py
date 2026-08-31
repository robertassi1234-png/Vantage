"""Thin client for the Financial Modeling Prep API.

Uses the "stable" API (the legacy /api/v3/ endpoints were retired by FMP
in August 2025). Docs: https://site.financialmodelingprep.com/developer/docs/stable
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app import provider_health
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


# A comma-separated symbol list in one request, rather than one request per
# symbol. This is the difference between a dashboard costing seventeen calls
# and costing one: the free allowance is 250 a day, so per-symbol fetching
# spent the whole day's budget in about seven page loads.
#
# Kept modest so a long watchlist splits into a few requests rather than one
# URL the service refuses for its length.
QUOTE_BATCH = 20


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Current price and day change for one or more symbols.

    Asks for the whole batch at once and only falls back to per-symbol
    requests for what the batch did not return. If the batch form is not
    supported the fallback covers everything, so the behaviour is the same as
    before at the cost of one extra call -- but where it is supported the
    saving is most of the daily allowance.
    """
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")
    if not symbols:
        return []

    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    if not wanted:
        return []

    async with httpx.AsyncClient(timeout=20) as client:
        rows = await _batched_quotes(client, wanted)

        missing = [s for s in wanted if s not in rows]
        if missing:
            responses = await asyncio.gather(
                *(_get(client, "quote", symbol=s) for s in missing),
                return_exceptions=True,
            )
            for symbol, response in zip(missing, responses):
                if isinstance(response, Exception):
                    continue
                data = _first(response)
                if data:
                    rows[symbol] = data

    quotes = []
    for symbol in wanted:
        data = rows.get(symbol)
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


async def _batched_quotes(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, dict]:
    """Quotes keyed by symbol, asked for in as few requests as possible.

    A batch that fails is not an error: it means this deployment's plan or API
    generation does not take a symbol list, and the caller falls back to one
    request per symbol. Silence here is the whole point -- a provider change
    should cost quota, not the page.
    """
    rows: dict[str, dict] = {}
    for start in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[start : start + QUOTE_BATCH]
        try:
            payload = await _get(client, "quote", symbol=",".join(chunk))
        except Exception as e:
            # Broad on purpose: this is an optimisation with a fallback behind
            # it, and the per-symbol path is what the code did before batching
            # existed. Letting anything escape here would turn a saving into a
            # page-wide failure.
            #
            # A spent allowance is the exception. Falling back would spend
            # another call per symbol on a service that has already said no,
            # so it is raised and the chain moves to the next provider.
            if provider_health.looks_rate_limited(str(e)):
                raise
            continue

        for item in payload if isinstance(payload, list) else [payload]:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if symbol in {s.upper() for s in chunk}:
                rows[symbol] = item
    return rows


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


async def fetch_peers(ticker: str, limit: int = 6) -> list[str]:
    """FMP's peer list for a ticker.

    The response shape has changed across FMP versions -- a flat list of
    companies in `stable`, a single row carrying `peersList` in the older
    ones -- so both are read rather than assuming whichever is live today.
    """
    if not settings.fmp_api_key:
        raise FMPError("FMP_API_KEY is not set")

    ticker = ticker.strip().upper()
    if not ticker:
        return []

    async with httpx.AsyncClient(timeout=10) as client:
        data = await _get(client, "stock-peers", symbol=ticker)

    peers: list[str] = []
    for row in data if isinstance(data, list) else [data]:
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("peersList"), list):
            peers.extend(str(p) for p in row["peersList"] if p)
        elif row.get("symbol"):
            peers.append(str(row["symbol"]))

    seen: list[str] = []
    for peer in peers:
        peer = peer.strip().upper()
        if peer and peer != ticker and peer not in seen:
            seen.append(peer)
    return seen[:limit]
