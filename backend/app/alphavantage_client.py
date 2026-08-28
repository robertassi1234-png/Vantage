"""Alpha Vantage: fundamentals only, as a last resort.

Its free tier is 25 requests a day, which is far too little to serve the app
but perfectly good as the last name in a chain -- by the time it is reached,
everything else is spent and 25 is better than zero.

One request returns the whole company overview, so a ticker costs a single
call. Every number arrives as a string, including the literal "None", so all
of them go through one parser.
"""

import httpx

from app.config import settings

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageError(Exception):
    pass


def _number(value) -> float | None:
    """Everything arrives as a string, and "None" and "-" both mean missing."""
    if value in (None, "", "None", "-", "0.00"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_fundamentals(ticker: str) -> dict:
    if not settings.alpha_vantage_api_key:
        raise AlphaVantageError("ALPHA_VANTAGE_API_KEY is not set")

    ticker = ticker.strip().upper()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                BASE_URL,
                params={
                    "function": "OVERVIEW",
                    "symbol": ticker,
                    "apikey": settings.alpha_vantage_api_key,
                },
            )
    except httpx.HTTPError as e:
        raise AlphaVantageError(f"Couldn't reach Alpha Vantage: {e}") from e

    if response.status_code >= 400:
        raise AlphaVantageError(f"Alpha Vantage returned {response.status_code}")

    try:
        data = response.json()
    except ValueError as e:
        raise AlphaVantageError("Alpha Vantage returned a malformed response") from e

    if not isinstance(data, dict):
        raise AlphaVantageError("Alpha Vantage returned an unexpected response")

    # It answers 200 for everything, putting refusals in the body: "Note" for
    # a spent allowance, "Information" for a bad key. Both have to be read, or
    # a quota refusal looks like a company with no data.
    for key in ("Note", "Information", "Error Message"):
        if data.get(key):
            raise AlphaVantageError(str(data[key]))

    if not data.get("Symbol"):
        raise AlphaVantageError(f"No data found for ticker '{ticker}'")

    return {
        "ticker": ticker,
        "companyName": data.get("Name"),
        "sector": (data.get("Sector") or "").title() or None,
        "industry": (data.get("Industry") or "").title() or None,
        "price": None,
        "marketCap": _number(data.get("MarketCapitalization")),
        "beta": _number(data.get("Beta")),
        "peRatio": _number(data.get("PERatio")),
        "pegRatio": _number(data.get("PEGRatio")),
        "evToEbitda": _number(data.get("EVToEBITDA")),
        "priceToBook": _number(data.get("PriceToBookRatio")),
        "priceToSales": _number(data.get("PriceToSalesRatioTTM")),
        "debtToEquity": None,
        "currentRatio": None,
        "revenueGrowth": _number(data.get("QuarterlyRevenueGrowthYOY")),
        "epsGrowth": _number(data.get("QuarterlyEarningsGrowthYOY")),
        "netProfitMargin": _number(data.get("ProfitMargin")),
        "operatingMargin": _number(data.get("OperatingMarginTTM")),
        "returnOnEquity": _number(data.get("ReturnOnEquityTTM")),
        "dividendYield": _number(data.get("DividendYield")),
    }
