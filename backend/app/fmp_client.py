"""Thin client for the Financial Modeling Prep API (free tier).

Docs: https://site.financialmodelingprep.com/developer/docs
"""

import httpx

from app.config import settings

BASE_URL = "https://financialmodelingprep.com/api/v3"


class FMPError(Exception):
    pass


def _first(items: list | dict | None) -> dict:
    if isinstance(items, list):
        return items[0] if items else {}
    if isinstance(items, dict):
        return items
    return {}


async def _get(client: httpx.AsyncClient, path: str) -> list | dict:
    resp = await client.get(
        f"{BASE_URL}/{path}",
        params={"apikey": settings.fmp_api_key},
    )
    if resp.status_code == 401 or resp.status_code == 403:
        raise FMPError("FMP API key is missing or invalid")
    if resp.status_code == 429:
        raise FMPError("FMP API rate limit reached (free tier: 250 calls/day)")
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise FMPError(data["Error Message"])
    return data


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
        "marketCap": profile.get("mktCap"),
        "beta": profile.get("beta"),
        "peRatio": ratios.get("peRatioTTM") or profile.get("pe"),
        "pegRatio": ratios.get("pegRatioTTM"),
        "evToEbitda": key_metrics.get("enterpriseValueOverEBITDATTM"),
        "priceToBook": ratios.get("priceToBookRatioTTM"),
        "priceToSales": ratios.get("priceToSalesRatioTTM"),
        "debtToEquity": ratios.get("debtEquityRatioTTM"),
        "currentRatio": ratios.get("currentRatioTTM"),
        "revenueGrowth": growth.get("growthRevenue"),
        "epsGrowth": growth.get("growthEPS"),
        "netProfitMargin": ratios.get("netProfitMarginTTM"),
        "operatingMargin": ratios.get("operatingProfitMarginTTM"),
        "returnOnEquity": ratios.get("returnOnEquityTTM"),
        "dividendYield": ratios.get("dividendYielTTM") or ratios.get("dividendYieldTTM"),
    }


async def _gather(client: httpx.AsyncClient, ticker: str):
    import asyncio

    profile_task = _get(client, f"profile/{ticker}")
    ratios_task = _get(client, f"ratios-ttm/{ticker}")
    key_metrics_task = _get(client, f"key-metrics-ttm/{ticker}")
    growth_task = _get(client, f"income-statement-growth/{ticker}?limit=1")

    profile, ratios, key_metrics, growth = await asyncio.gather(
        profile_task, ratios_task, key_metrics_task, growth_task
    )
    return _first(profile), _first(ratios), _first(key_metrics), _first(growth)
