from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.config import settings
from app.fmp_client import FMPError
from app.market_data import fetch_fundamentals, search_symbols
from app.models import FundamentalsRow, NoteRequest, TickerRequest
from app.space import current_owner

router = APIRouter(prefix="/api", tags=["stocks"])


@router.get("/search")
async def search(q: str) -> list[dict]:
    """Autocomplete for the add-ticker box: accepts a ticker or a company name."""
    try:
        return await search_symbols(q)
    except FMPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


def _valid_list(list_name: str) -> str:
    if list_name not in db.LIST_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown list '{list_name}'. Use one of: {', '.join(db.LIST_NAMES)}.",
        )
    return list_name


@router.get("/lists/{list_name}")
def get_list(list_name: str, owner: str = Depends(current_owner)) -> list[str]:
    return db.get_watchlist(owner, _valid_list(list_name))


@router.get("/lists/{list_name}/entries")
def get_list_entries(list_name: str, owner: str = Depends(current_owner)) -> list[dict]:
    """Tickers with the date each was added and any note on it."""
    return db.get_watchlist_entries(owner, _valid_list(list_name))


@router.post("/lists/{list_name}")
def add_to_list(
    list_name: str, req: TickerRequest, owner: str = Depends(current_owner)
) -> list[str]:
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty")
    db.add_to_watchlist(ticker, owner, _valid_list(list_name))
    return db.get_watchlist(owner, list_name)


@router.put("/lists/{list_name}/{ticker}/note")
def set_note(
    list_name: str, ticker: str, req: NoteRequest, owner: str = Depends(current_owner)
) -> list[dict]:
    db.set_watchlist_note(ticker.strip().upper(), req.note, owner, _valid_list(list_name))
    return db.get_watchlist_entries(owner, list_name)


@router.delete("/lists/{list_name}/{ticker}")
def remove_from_list(
    list_name: str, ticker: str, owner: str = Depends(current_owner)
) -> list[str]:
    db.remove_from_watchlist(ticker.strip().upper(), owner, _valid_list(list_name))
    return db.get_watchlist(owner, list_name)


def _is_stale(fetched_at: str) -> bool:
    fetched = datetime.fromisoformat(fetched_at)
    return datetime.now(timezone.utc) - fetched > timedelta(hours=settings.fundamentals_cache_hours)


@router.get("/fundamentals")
async def get_fundamentals(
    refresh: bool = False, owner: str = Depends(current_owner)
) -> list[FundamentalsRow]:
    # Fundamentals are the comparison table's data, so they follow that list.
    tickers = db.get_watchlist(owner, db.COMPARE_LIST)
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
