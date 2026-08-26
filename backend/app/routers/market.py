import asyncio

from fastapi import APIRouter, HTTPException

from app import db
from app.fmp_client import RANGE_DAYS, FMPError, fetch_history, fetch_quotes

router = APIRouter(prefix="/api/market", tags=["market"])

# FMP uses Yahoo-style carets for index symbols.
INDICES = [
    {"symbol": "^GSPC", "label": "S&P 500", "blurb": "500 large US companies"},
    {"symbol": "^IXIC", "label": "Nasdaq", "blurb": "Tech-heavy US index"},
    {"symbol": "^DJI", "label": "Dow Jones", "blurb": "30 large US companies"},
    {"symbol": "^RUT", "label": "Russell 2000", "blurb": "2,000 smaller US companies"},
]

# Quotes move constantly but the free tier is 250 calls/day, so serve a recent
# snapshot rather than refetching on every page load. Daily closes only change
# once a day, so history can be cached far longer.
QUOTE_TTL_SECONDS = 15 * 60
HISTORY_TTL_SECONDS = 12 * 60 * 60
SPARKLINE_POINTS = 30


@router.get("/indices")
async def get_indices(refresh: bool = False) -> list[dict]:
    """Quote plus a short sparkline series for each headline index."""
    cache_key = "indices"
    if not refresh:
        cached = db.get_market_cache(cache_key, QUOTE_TTL_SECONDS)
        if cached is not None:
            return cached

    symbols = [i["symbol"] for i in INDICES]

    def stale_or_fail(detail: str):
        """Old prices beat blank tiles; a blank cache is worth an honest error."""
        cached = db.get_market_cache(cache_key, max_age_seconds=7 * 24 * 3600)
        if cached is not None:
            return cached
        raise HTTPException(status_code=502, detail=detail)

    try:
        quotes = await fetch_quotes(symbols)
    except FMPError as e:
        return stale_or_fail(str(e))

    # fetch_quotes drops symbols it couldn't retrieve rather than raising, so an
    # outage that kills every symbol arrives here as an empty list. Caching that
    # would blank the dashboard for a full TTL and overwrite good prices.
    if not quotes:
        return stale_or_fail("Couldn't fetch index prices right now.")

    by_symbol = {q["symbol"]: q for q in quotes}
    sparklines = await asyncio.gather(*(_sparkline(i["symbol"]) for i in INDICES))

    results = []
    for index, sparkline in zip(INDICES, sparklines):
        quote = by_symbol.get(index["symbol"], {})
        results.append(
            {
                **index,
                "price": quote.get("price"),
                "change": quote.get("change"),
                "changePercent": quote.get("changePercent"),
                "sparkline": sparkline,
            }
        )

    db.set_market_cache(cache_key, results)
    return results


async def _sparkline(symbol: str) -> list[float]:
    """Recent closes for a stat-tile sparkline, cached separately from quotes."""
    key = f"spark:{symbol}"
    cached = db.get_market_cache(key, HISTORY_TTL_SECONDS)
    if cached is not None:
        return cached
    try:
        points = await fetch_history(symbol, "3M")
    except FMPError:
        return []
    closes = [p["close"] for p in points][-SPARKLINE_POINTS:]
    db.set_market_cache(key, closes)
    return closes


@router.get("/history/{symbol:path}")
async def get_history(symbol: str, range: str = "1Y") -> dict:
    """Daily closes for one symbol over a preset range."""
    range_key = range.upper()
    if range_key not in RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown range '{range}'. Choose one of: {', '.join(RANGE_DAYS)}.",
        )

    key = f"history:{symbol}:{range_key}"
    cached = db.get_market_cache(key, HISTORY_TTL_SECONDS)
    if cached is not None:
        return cached

    try:
        points = await fetch_history(symbol, range_key)
    except FMPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if not points:
        raise HTTPException(
            status_code=404, detail=f"No price history available for '{symbol}'."
        )

    payload = {"symbol": symbol.upper(), "range": range_key, "points": points}
    db.set_market_cache(key, payload)
    return payload


@router.get("/quotes")
async def get_quotes(symbols: str, refresh: bool = False) -> list[dict]:
    """Quotes for a comma-separated symbol list (the watchlist row data)."""
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not wanted:
        return []

    key = f"quotes:{','.join(sorted(wanted))}"
    if not refresh:
        cached = db.get_market_cache(key, QUOTE_TTL_SECONDS)
        if cached is not None:
            return cached

    try:
        quotes = await fetch_quotes(wanted)
    except FMPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    db.set_market_cache(key, quotes)
    return quotes
