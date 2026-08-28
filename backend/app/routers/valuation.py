"""The valuation snapshot for the comparison list.

One endpoint rather than one per company, because the peer median is a
property of the set: it only exists once every company in the comparison has
been priced. Computing it here also keeps the browser from having to know
which metrics are medians of what.

Caching matters more here than anywhere else in the app. Five years of
quarterly fundamentals is six calls per company, against a free plan that
allows 250 a day -- so a full table of five companies is a tenth of the daily
budget. Cached for a day, that is one refresh; uncached it would be gone by
lunchtime.
"""

import asyncio
import statistics

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.config import settings
from app.fmp_client import FMPError
from app.space import current_owner
from app.valuation import METRICS, fetch_valuation

router = APIRouter(prefix="/api/valuation", tags=["valuation"])

# Fundamentals change four times a year. Anything shorter spends quota to
# re-fetch numbers that cannot have moved.
CACHE_SECONDS = 24 * 60 * 60

# Past this the table stops being readable and the quota stops being
# affordable in the same breath.
MAX_COMPANIES = 8


@router.get("")
async def get_valuation(refresh: bool = False, owner: str = Depends(current_owner)) -> dict:
    tickers = db.get_watchlist(owner, db.COMPARE_LIST)[:MAX_COMPANIES]
    if not tickers:
        return {"companies": [], "metrics": _metric_defs(), "peerMedian": {}}

    companies = await asyncio.gather(*(_one(t, refresh) for t in tickers))
    return {
        "companies": companies,
        "metrics": _metric_defs(),
        "peerMedian": _peer_medians(companies),
    }


async def _one(ticker: str, refresh: bool) -> dict:
    key = f"valuation:{ticker}"
    if not refresh:
        cached = db.get_market_cache(key, CACHE_SECONDS)
        if cached:
            return {**cached, "stale": False}

    try:
        data = await fetch_valuation(ticker)
    except FMPError as e:
        # A day-old table is worth far more than an error message, so an
        # expired entry is served rather than discarded when the refresh
        # fails. This is the common case on a free plan.
        stale = db.get_market_cache(key, max_age_seconds=10**9)
        if stale:
            return {**stale, "stale": True, "error": str(e)}
        return {
            "ticker": ticker,
            "companyName": None,
            "sector": None,
            "price": None,
            "metrics": {},
            "stale": False,
            "error": str(e),
        }

    db.set_market_cache(key, data)
    return {**data, "stale": False}


def _peer_medians(companies: list[dict]) -> dict[str, float | None]:
    """The middle of whatever is currently being compared.

    Cheap to compute and it gives every number a reference point: a 34x
    multiple reads differently when the others are at 12 than when they are
    at 40. It is the median of the companies on screen, nothing more -- not
    an industry figure -- which is why the column says so.
    """
    medians: dict[str, float | None] = {}
    for metric in METRICS:
        values = [
            company["metrics"][metric.key]["value"]
            for company in companies
            if isinstance(company.get("metrics", {}).get(metric.key, {}).get("value"), (int, float))
        ]
        medians[metric.key] = statistics.median(values) if values else None
    return medians


def _metric_defs() -> list[dict]:
    return [
        {
            "key": m.key,
            "label": m.label,
            "better": m.better,
            "percent": m.percent,
        }
        for m in METRICS
    ]
