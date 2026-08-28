"""The thesis journal.

A note in a watchlist row says why you are watching something. A journal entry
says what you thought on a particular day, at a particular price -- and that
second part is the whole feature. An opinion recorded next to the price it was
formed at can be graded later; the same opinion without it is just a note.

So `priceAtWrite` is stamped once, here, and never recomputed. Everything the
reader sees afterwards -- the return since writing, whether the thesis worked
-- is derived from that stamp against a live quote. Recalculating the stamp
would quietly erase the record it exists to keep.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.market_data import fetch_quotes
from app.models import JournalRequest
from app.space import current_owner

router = APIRouter(prefix="/api/journal", tags=["journal"])

# Long enough that a thesis has had a chance to play out, short enough to still
# remember writing it. A quarter is also how often the companies themselves
# report, so there is usually something new to judge it against.
REVIEW_AFTER_DAYS = 90

MAX_BODY = 4000
MAX_TAGS = 6
MAX_TAG_LENGTH = 24

#: Offered as one-click chips. Not a closed set -- a journal nobody can
#: annotate in their own words stops being used -- but these four are what
#: makes filtering worth doing later.
SUGGESTED_TAGS = ("thesis", "risk", "catalyst", "mistake")


@router.get("")
def list_entries(ticker: str | None = None, owner: str = Depends(current_owner)) -> dict:
    entries = db.list_journal(owner, ticker.strip().upper() if ticker else None)
    return {
        "entries": entries,
        "review_due": [e["id"] for e in entries if is_review_due(e)],
        "suggested_tags": list(SUGGESTED_TAGS),
        "review_after_days": REVIEW_AFTER_DAYS,
    }


@router.post("/{ticker}")
async def add_entry(
    ticker: str, req: JournalRequest, owner: str = Depends(current_owner)
) -> dict:
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty.")

    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Write something first.")
    if len(body) > MAX_BODY:
        raise HTTPException(
            status_code=400, detail=f"Keep an entry under {MAX_BODY} characters."
        )

    price = req.priceAtWrite
    if price is None:
        # The page usually has the price already, and that is the honest
        # snapshot -- it is the number the reader was looking at when they
        # formed the view. Fetching is the fallback for writing somewhere the
        # price is not on screen.
        price = await _current_price(ticker)

    entry = db.add_journal_entry(owner, ticker, body, price, _clean_tags(req.tags))
    return {"entry": entry, **list_entries(owner=owner)}


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, owner: str = Depends(current_owner)) -> dict:
    db.delete_journal_entry(owner, entry_id)
    return list_entries(owner=owner)


@router.post("/{entry_id}/reviewed")
def mark_reviewed(entry_id: str, owner: str = Depends(current_owner)) -> dict:
    if not db.mark_journal_reviewed(owner, entry_id):
        raise HTTPException(status_code=404, detail="That entry no longer exists.")
    return list_entries(owner=owner)


def is_review_due(entry: dict) -> bool:
    """Whether an entry is old enough to be worth revisiting, and never was.

    This is what stops the journal becoming a graveyard: entries are written
    with conviction and then never read again, which is precisely when they
    are most useful.
    """
    if entry.get("reviewedAt"):
        return False
    try:
        written = datetime.fromisoformat(entry["dateWritten"])
    except (TypeError, ValueError):
        return False
    if written.tzinfo is None:
        written = written.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - written > timedelta(days=REVIEW_AFTER_DAYS)


def _clean_tags(tags: list[str] | None) -> list[str]:
    """Lower-cased, de-duplicated, and capped.

    Case-folded because "Risk" and "risk" filtering as two different things
    would make the filter useless within a week.
    """
    cleaned: list[str] = []
    for tag in tags or []:
        tag = tag.strip().lower()[:MAX_TAG_LENGTH]
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:MAX_TAGS]


async def _current_price(ticker: str) -> float | None:
    """Best-effort price stamp. An entry without one is still worth keeping."""
    try:
        quotes = await fetch_quotes([ticker])
    except Exception:
        return None
    for quote in quotes:
        if quote.get("symbol") == ticker and isinstance(quote.get("price"), (int, float)):
            return float(quote["price"])
    return None
