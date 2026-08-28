"""Cost basis for watchlist rows.

A watchlist answers "what is this worth"; a position answers "what is this
worth to me". The difference is a handful of lots -- what you paid and when --
and everything else follows from them arithmetically.

The arithmetic is deliberately not here. Market value, unrealised gain and
portfolio weight all depend on the current price, which the page already holds
and refreshes; computing them server-side would mean a second round trip to
learn what the browser could work out instantly. So this stores lots and
nothing more, and `frontend/src/positions.ts` derives the rest.
"""

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.models import LotRequest, SplitRequest
from app.space import current_owner

router = APIRouter(prefix="/api/positions", tags=["positions"])

# Above this a "split" is far more likely to be a typo than a real corporate
# action, and applying one rewrites every lot's basis destructively.
MAX_SPLIT_RATIO = 1000


@router.get("")
def get_positions(owner: str = Depends(current_owner)) -> dict:
    return {"lots": db.list_lots(owner), "splits": db.list_splits(owner)}


@router.post("/{ticker}/lots")
def add_lot(ticker: str, req: LotRequest, owner: str = Depends(current_owner)) -> dict:
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty.")
    if req.shares == 0:
        raise HTTPException(status_code=400, detail="Shares cannot be zero.")
    if req.costPerShare <= 0:
        # Zero is not a free share, it is an empty field. A gift or a grant
        # still has a cost basis, and treating a blank as zero would report a
        # gain of the entire position value.
        raise HTTPException(
            status_code=400,
            detail="Enter the price per share. For a grant or gift, use its value on the day you received it.",
        )
    if not req.tradeDate.strip():
        raise HTTPException(status_code=400, detail="Enter the date of the trade.")

    db.add_lot(owner, ticker, req.shares, req.costPerShare, req.tradeDate.strip(), req.note)
    return get_positions(owner)


@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: str, owner: str = Depends(current_owner)) -> dict:
    db.delete_lot(owner, lot_id)
    return get_positions(owner)


@router.post("/{ticker}/split")
def apply_split(ticker: str, req: SplitRequest, owner: str = Depends(current_owner)) -> dict:
    ticker = ticker.strip().upper()
    if req.ratio <= 0 or req.ratio > MAX_SPLIT_RATIO:
        raise HTTPException(
            status_code=400,
            detail=f"A split ratio must be between 0 and {MAX_SPLIT_RATIO}. "
            "A 4-for-1 split is 4; a reverse 1-for-10 is 0.1.",
        )
    if not db.list_lots(owner, ticker):
        raise HTTPException(
            status_code=400,
            detail=f"You have no lots recorded for {ticker}, so there is nothing to adjust.",
        )

    db.apply_split(owner, ticker, req.ratio)
    return get_positions(owner)


@router.delete("/splits/{split_id}")
def undo_split(split_id: str, owner: str = Depends(current_owner)) -> dict:
    if not db.undo_split(owner, split_id):
        raise HTTPException(status_code=404, detail="That split adjustment no longer exists.")
    return get_positions(owner)
