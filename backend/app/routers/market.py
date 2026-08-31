import asyncio

from fastapi import APIRouter, HTTPException

from app import db, market_data, provider_health
from app.fmp_client import RANGE_DAYS, FMPError
from app.market_data import fetch_history, fetch_quotes

router = APIRouter(prefix="/api/market", tags=["market"])

# FMP uses Yahoo-style carets for index symbols.
INDICES = [
    {"symbol": "^GSPC", "label": "S&P 500", "blurb": "500 large US companies"},
    {"symbol": "^IXIC", "label": "Nasdaq", "blurb": "Tech-heavy US index"},
    {"symbol": "^DJI", "label": "Dow Jones", "blurb": "30 large US companies"},
    {"symbol": "^RUT", "label": "Russell 2000", "blurb": "2,000 smaller US companies"},
]

# What the parts of the market are doing, which the four headline indices
# cannot show: an index says the market rose, this says energy fell while
# technology carried it.
#
# Deliberately additive -- no overlap with the indices row above, because the
# same thing priced two ways (an index level and its ETF) reads as a
# contradiction to anyone new. Grouped by how these sectors actually behave,
# so the rotation teaches something rather than just scrolling: growth leads
# in a rally, defensives hold up in a fall, cyclicals track the economy.
MARKET_BOARD = [
    {
        "group": "Growth",
        "entries": [
            {"symbol": "XLK", "label": "Technology", "blurb": "Software, chips and hardware"},
            {"symbol": "XLY", "label": "Consumer discretionary", "blurb": "What people buy when times are good"},
            {"symbol": "XLC", "label": "Communications", "blurb": "Media, telecom and social"},
        ],
    },
    {
        "group": "Defensive",
        "entries": [
            {"symbol": "XLV", "label": "Healthcare", "blurb": "Pharma, insurers and devices"},
            {"symbol": "XLP", "label": "Consumer staples", "blurb": "Food and household basics"},
            {"symbol": "XLU", "label": "Utilities", "blurb": "Power and water — steady demand"},
        ],
    },
    {
        "group": "Cyclical",
        "entries": [
            {"symbol": "XLF", "label": "Financials", "blurb": "Banks, brokers and insurers"},
            {"symbol": "XLI", "label": "Industrials", "blurb": "Machinery, transport and defence"},
            {"symbol": "XLE", "label": "Energy", "blurb": "Oil, gas and drilling"},
        ],
    },
    {
        "group": "Global & other",
        "entries": [
            {"symbol": "VEA", "label": "Developed markets", "blurb": "Europe, Japan and Australia"},
            {"symbol": "VWO", "label": "Emerging markets", "blurb": "China, India, Brazil and more"},
            {"symbol": "AGG", "label": "US bonds", "blurb": "Investment-grade debt"},
            {"symbol": "GLD", "label": "Gold", "blurb": "Tracks the gold price"},
        ],
    },
]

# Quotes move constantly but the free tier is 250 calls/day, so serve a recent
# snapshot rather than refetching on every page load. Daily closes only change
# once a day, so history can be cached far longer.
QUOTE_TTL_SECONDS = 15 * 60
# The sector board is context, not a ticker tape: which parts of the market
# are leading does not change meaningfully inside an hour, and refreshing it
# four times as often costs four times the allowance for no reader benefit.
BOARD_TTL_SECONDS = 60 * 60
# How old a price may be and still be worth carrying past a symbol the
# providers have stopped answering for. Bounded, because at some point
# yesterday's number presented as today's is worse than an honest blank.
CARRY_FORWARD_SECONDS = 24 * 60 * 60
HISTORY_TTL_SECONDS = 12 * 60 * 60
SPARKLINE_POINTS = 30


@router.get("/providers")
def provider_status() -> dict:
    """Which data providers are answering, and which are out of quota.

    Exists so "why is the table empty?" has an answer that doesn't involve
    reading server logs. Reports whether each provider is configured, since a
    missing key and a spent allowance look identical from the outside.
    """
    statuses = provider_health.snapshot(list(market_data.PROVIDERS))
    for status in statuses:
        status["configured"] = market_data.is_configured(status["name"])
        status["serves_fundamentals"] = (
            status["name"] in market_data.FUNDAMENTALS_PROVIDERS
        )

    usable = [s for s in statuses if s["configured"] and s["available"]]
    return {
        "providers": statuses,
        "order": market_data._order(),
        "fundamentals_order": market_data._fundamentals_order(),
        "healthy": len(usable),
    }


def _has_prices(payload) -> bool:
    """Whether a cached payload is worth anything to a reader.

    A payload of tiles that are all blank is not a cheaper version of the
    board, it is the absence of one. Treating it as a cache hit meant serving
    dashes for a full TTL without asking any provider, and writing it meant
    those dashes outlived the outage that produced them. Neither is a cache;
    both are a way to stay broken.
    """
    return isinstance(payload, list) and any(
        isinstance(tile, dict) and tile.get("price") is not None for tile in payload
    )


async def _priced_tiles(
    cache_key: str, entries: list[dict], refresh: bool, ttl: int = QUOTE_TTL_SECONDS
) -> list[dict]:
    """Quote plus a short sparkline for each entry, cached as one payload."""
    if not refresh:
        cached = db.get_market_cache(cache_key, ttl)
        if _has_prices(cached):
            return cached

    def stale_or_fail(detail: str):
        """Old prices beat blank tiles; a blank cache is worth an honest error."""
        cached = db.get_market_cache(cache_key, max_age_seconds=7 * 24 * 3600)
        if _has_prices(cached):
            return cached
        raise HTTPException(status_code=502, detail=detail)

    try:
        quotes = await fetch_quotes([e["symbol"] for e in entries])
    except FMPError as e:
        return stale_or_fail(str(e))

    # fetch_quotes drops symbols it couldn't retrieve rather than raising, so an
    # outage that kills every symbol arrives here as an empty list. Caching that
    # would blank the dashboard for a full TTL and overwrite good prices.
    if not quotes:
        return stale_or_fail("Couldn't fetch market prices right now.")

    # The same hazard one step down. A partial outage -- one symbol answered of
    # thirteen -- is not an empty list, so it used to be written straight over
    # the cache and blank twelve tiles that had prices a moment earlier. Worse,
    # it then served those blanks for the whole TTL, so a provider recovering
    # changed nothing visible. Last known price wins over a dash.
    previous = {
        tile["symbol"]: tile
        for tile in (db.get_market_cache(cache_key, CARRY_FORWARD_SECONDS) or [])
        if isinstance(tile, dict) and tile.get("symbol")
    }

    by_symbol = {q["symbol"]: q for q in quotes}
    sparklines = await asyncio.gather(*(_sparkline(e["symbol"]) for e in entries))

    results = []
    for entry, sparkline in zip(entries, sparklines):
        quote = by_symbol.get(entry["symbol"], {})
        carried = previous.get(entry["symbol"], {})
        # All three move together: a fresh price with yesterday's change would
        # be a figure that never existed.
        source = quote if quote.get("price") is not None else carried
        results.append(
            {
                **entry,
                "price": source.get("price"),
                "change": source.get("change"),
                "changePercent": source.get("changePercent"),
                # A sparkline is cached for half a day of its own, so an empty
                # one here is the same outage; keep the drawn line rather than
                # flattening the tile as well.
                "sparkline": sparkline or carried.get("sparkline") or [],
            }
        )

    if not _has_prices(results):
        # Nothing came back priced, and nothing was carried. Writing that
        # would put the outage in the cache and serve it back for the next
        # fifteen minutes, so the recovery nobody can see starts here. Reach
        # further back for real prices instead, and leave the cache alone so
        # the next load asks again.
        older = db.get_market_cache(cache_key, max_age_seconds=7 * 24 * 3600)
        return older if _has_prices(older) else results

    db.set_market_cache(cache_key, results)
    return results


@router.get("/indices")
async def get_indices(refresh: bool = False) -> list[dict]:
    """Quote plus a short sparkline series for each headline index."""
    return await _priced_tiles("indices", INDICES, refresh)


@router.get("/trends")
async def get_trends(symbols: str, refresh: bool = False) -> dict[str, list[float]]:
    """Short close series per symbol, for the watchlist row trend lines.

    Reads the same cache the sparklines already fill, so a watchlist whose
    charts have been looked at costs nothing extra. Best-effort throughout: a
    row simply has no line rather than the request failing.
    """
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()][:25]
    if not wanted:
        return {}

    series = await asyncio.gather(*(_sparkline(symbol) for symbol in wanted))
    return {symbol: points for symbol, points in zip(wanted, series) if points}


@router.get("/board")
async def get_board(refresh: bool = False) -> list[dict]:
    """The wider market, grouped into themes the strip rotates through."""
    entries = [e for group in MARKET_BOARD for e in group["entries"]]
    tiles = await _priced_tiles("board", entries, refresh, ttl=BOARD_TTL_SECONDS)
    by_symbol = {t["symbol"]: t for t in tiles}

    return [
        {
            "group": group["group"],
            "entries": [
                by_symbol[e["symbol"]] for e in group["entries"] if e["symbol"] in by_symbol
            ],
        }
        for group in MARKET_BOARD
    ]


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
