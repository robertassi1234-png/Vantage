"""Finnhub: quotes and fundamentals on a free key.

Here mainly for fundamentals. Those were FMP-only, which made a 250-call daily
allowance the ceiling on the whole comparison table -- four calls per ticker
meant a few dozen refreshes and the feature simply stopped. Finnhub's free
tier is 60 calls a minute with no daily cap, so it absorbs that comfortably.

Its metric names differ from FMP's and it does not publish everything FMP
does. Missing fields come back as None rather than being guessed at, and the
table already renders a dash for those: a partial row beats no row.
"""

import httpx

from app.config import settings

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubError(Exception):
    pass


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict:
    if not settings.finnhub_api_key:
        raise FinnhubError("FINNHUB_API_KEY is not set")

    try:
        response = await client.get(
            f"{BASE_URL}/{path}", params={**params, "token": settings.finnhub_api_key}
        )
    except httpx.HTTPError as e:
        raise FinnhubError(f"Couldn't reach Finnhub: {e}") from e

    if response.status_code == 429:
        raise FinnhubError("Finnhub rate limit reached (free tier: 60 calls/minute)")
    if response.status_code in (401, 403):
        raise FinnhubError("Finnhub API key is missing or invalid")
    if response.status_code >= 400:
        raise FinnhubError(f"Finnhub returned {response.status_code}")

    try:
        data = response.json()
    except ValueError as e:
        raise FinnhubError("Finnhub returned a malformed response") from e

    if not isinstance(data, dict):
        raise FinnhubError("Finnhub returned an unexpected response")
    return data


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _percent(value) -> float | None:
    """Finnhub reports margins and growth as percentages; the app uses fractions."""
    number = _number(value)
    return number / 100 if number is not None else None


async def fetch_quotes(symbols: list[str]) -> list[dict]:
    """One request per symbol -- Finnhub has no batch quote endpoint."""
    if not symbols:
        return []

    quotes = []
    async with httpx.AsyncClient(timeout=10) as client:
        for symbol in symbols:
            try:
                data = await _get(client, "quote", symbol=symbol.upper())
            except FinnhubError:
                # One bad symbol must not lose the rest of the batch.
                continue

            price = _number(data.get("c"))
            if not price:
                continue
            previous = _number(data.get("pc"))
            quotes.append(
                {
                    "symbol": symbol.upper(),
                    "name": None,
                    "price": price,
                    "change": _number(data.get("d")),
                    "changePercent": _number(data.get("dp")),
                    "dayLow": _number(data.get("l")),
                    "dayHigh": _number(data.get("h")),
                    "yearLow": None,
                    "yearHigh": None,
                    "marketCap": None,
                    "volume": None,
                    "previousClose": previous,
                }
            )
    return quotes


async def fetch_fundamentals(ticker: str) -> dict:
    """Ratios and margins, in the shape the comparison table expects."""
    ticker = ticker.strip().upper()
    async with httpx.AsyncClient(timeout=15) as client:
        profile = await _get(client, "stock/profile2", symbol=ticker)
        metrics = await _get(client, "stock/metric", symbol=ticker, metric="all")

    metric = metrics.get("metric") or {}
    if not profile and not metric:
        raise FinnhubError(f"No data found for ticker '{ticker}'")

    return {
        "ticker": ticker,
        "companyName": profile.get("name"),
        "sector": profile.get("finnhubIndustry"),
        "industry": profile.get("finnhubIndustry"),
        "price": None,
        # Finnhub reports market capitalisation in millions.
        "marketCap": (
            _number(profile.get("marketCapitalization")) * 1_000_000
            if _number(profile.get("marketCapitalization")) is not None
            else None
        ),
        "beta": _number(metric.get("beta")),
        "peRatio": _number(metric.get("peTTM")),
        "pegRatio": _number(metric.get("pegTTM")),
        "evToEbitda": _number(metric.get("currentEv/freeCashFlowTTM")),
        "priceToBook": _number(metric.get("pbQuarterly")) or _number(metric.get("pbAnnual")),
        "priceToSales": _number(metric.get("psTTM")),
        "debtToEquity": (
            _number(metric.get("totalDebt/totalEquityQuarterly"))
            or _number(metric.get("totalDebt/totalEquityAnnual"))
        ),
        "currentRatio": (
            _number(metric.get("currentRatioQuarterly"))
            or _number(metric.get("currentRatioAnnual"))
        ),
        "revenueGrowth": _percent(metric.get("revenueGrowthTTMYoy")),
        "epsGrowth": _percent(metric.get("epsGrowthTTMYoy")),
        "netProfitMargin": _percent(metric.get("netProfitMarginTTM")),
        "operatingMargin": _percent(metric.get("operatingMarginTTM")),
        "returnOnEquity": _percent(metric.get("roeTTM")),
        "dividendYield": _percent(metric.get("dividendYieldIndicatedAnnual")),
    }
