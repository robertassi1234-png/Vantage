from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.config import settings
from app.fmp_client import FMPError, fetch_fundamentals, search_symbols
from app.models import FundamentalsRow, NoteRequest, TickerRequest
from app.space import current_space

router = APIRouter(prefix="/api", tags=["stocks"])


@router.get("/search")
async def search(q: str) -> list[dict]:
    """Autocomplete for the add-ticker box: accepts a ticker or a company name."""
    try:
        return await search_symbols(q)
    except FMPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/watchlist")
def list_watchlist(space: str = Depends(current_space)) -> list[str]:
    return db.get_watchlist(space)


@router.get("/watchlist/entries")
def list_watchlist_entries(space: str = Depends(current_space)) -> list[dict]:
    """Watchlist with the date each ticker was added and any note on it."""
    return db.get_watchlist_entries(space)


@router.post("/watchlist")
def add_ticker(req: TickerRequest, space: str = Depends(current_space)) -> list[str]:
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty")
    db.add_to_watchlist(ticker, space)
    return db.get_watchlist(space)


@router.put("/watchlist/{ticker}/note")
def set_note(
    ticker: str, req: NoteRequest, space: str = Depends(current_space)
) -> list[dict]:
    db.set_watchlist_note(ticker.strip().upper(), req.note, space)
    return db.get_watchlist_entries(space)


@router.delete("/watchlist/{ticker}")
def remove_ticker(ticker: str, space: str = Depends(current_space)) -> list[str]:
    db.remove_from_watchlist(ticker.strip().upper(), space)
    return db.get_watchlist(space)


def _is_stale(fetched_at: str) -> bool:
    fetched = datetime.fromisoformat(fetched_at)
    return datetime.now(timezone.utc) - fetched > timedelta(hours=settings.fundamentals_cache_hours)


@router.get("/fundamentals")
async def get_fundamentals(
    refresh: bool = False, space: str = Depends(current_space)
) -> list[FundamentalsRow]:
    tickers = db.get_watchlist(space)
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
