from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app import db
from app.config import settings
from app.fmp_client import FMPError, fetch_fundamentals
from app.models import FundamentalsRow, TickerRequest

router = APIRouter(prefix="/api", tags=["stocks"])


@router.get("/watchlist")
def list_watchlist() -> list[str]:
    return db.get_watchlist()


@router.post("/watchlist")
def add_ticker(req: TickerRequest) -> list[str]:
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty")
    db.add_to_watchlist(ticker)
    return db.get_watchlist()


@router.delete("/watchlist/{ticker}")
def remove_ticker(ticker: str) -> list[str]:
    db.remove_from_watchlist(ticker.strip().upper())
    return db.get_watchlist()


def _is_stale(fetched_at: str) -> bool:
    fetched = datetime.fromisoformat(fetched_at)
    return datetime.now(timezone.utc) - fetched > timedelta(hours=settings.fundamentals_cache_hours)


@router.get("/fundamentals")
async def get_fundamentals(refresh: bool = False) -> list[FundamentalsRow]:
    tickers = db.get_watchlist()
    results: list[FundamentalsRow] = []

    for ticker in tickers:
        cached = db.get_cached_fundamentals(ticker)
        needs_fetch = refresh or cached is None or _is_stale(cached["fetched_at"])

        if needs_fetch:
            try:
                data = await fetch_fundamentals(ticker)
                db.set_cached_fundamentals(ticker, data)
                results.append(FundamentalsRow(**data, stale=False))
                continue
            except FMPError as e:
                if cached:
                    results.append(
                        FundamentalsRow(**cached["data"], stale=True, fetchedAt=cached["fetched_at"], error=str(e))
                    )
                else:
                    results.append(FundamentalsRow(ticker=ticker, error=str(e)))
                continue

        results.append(FundamentalsRow(**cached["data"], stale=False, fetchedAt=cached["fetched_at"]))

    return results
