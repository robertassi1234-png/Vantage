"""Export and import a workspace.

A space id lives in one browser's localStorage, so clearing site data or
switching device loses the watchlist. Export writes everything that space owns
to a JSON file; import restores it anywhere. That makes the browser-scoped
storage recoverable without requiring accounts.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import alerts as alerts_module
from app import db
from app.space import current_owner

router = APIRouter(prefix="/api", tags=["portability"])

EXPORT_VERSION = 1


class ExportedAlert(BaseModel):
    ticker: str
    direction: str
    threshold: float
    note: str | None = None


class ExportedEntry(BaseModel):
    ticker: str
    added_at: str | None = None
    note: str | None = None


class WorkspaceExport(BaseModel):
    version: int = EXPORT_VERSION
    exported_at: str
    lists: dict[str, list[ExportedEntry]] = Field(default_factory=dict)
    alerts: list[ExportedAlert] = Field(default_factory=list)


class ImportResult(BaseModel):
    added: dict[str, int]
    alerts_added: int
    skipped: list[str]


@router.get("/export")
def export_workspace(owner: str = Depends(current_owner)) -> WorkspaceExport:
    return WorkspaceExport(
        exported_at=db.now_iso(),
        lists={
            name: [ExportedEntry(**entry) for entry in db.get_watchlist_entries(owner, name)]
            for name in db.LIST_NAMES
        },
        alerts=[
            ExportedAlert(
                ticker=a["ticker"],
                direction=a["direction"],
                threshold=a["threshold"],
                note=a["note"],
            )
            for a in alerts_module.list_alerts(owner)
        ],
    )


@router.post("/import")
def import_workspace(
    payload: WorkspaceExport, replace: bool = False, owner: str = Depends(current_owner)
) -> ImportResult:
    """Merge an exported workspace into this space.

    Merging is the default: importing on a device that already has tickers
    should not silently discard them. `replace=true` is the explicit opt-in for
    "make this device match the file".
    """
    if payload.version > EXPORT_VERSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This file was made by a newer version of Vantage "
                f"(v{payload.version}); this one understands up to v{EXPORT_VERSION}."
            ),
        )

    skipped: list[str] = []
    added = {name: 0 for name in db.LIST_NAMES}

    if replace:
        for name in db.LIST_NAMES:
            for ticker in db.get_watchlist(owner, name):
                db.remove_from_watchlist(ticker, owner, name)

    for list_name, entries in payload.lists.items():
        if list_name not in db.LIST_NAMES:
            skipped.append(f"unknown list '{list_name}'")
            continue

        existing = set(db.get_watchlist(owner, list_name))
        for entry in entries:
            ticker = entry.ticker.strip().upper()
            if not ticker or ticker in existing:
                continue
            db.add_to_watchlist(ticker, owner, list_name)
            if entry.note:
                db.set_watchlist_note(ticker, entry.note, owner, list_name)
            added[list_name] += 1
            existing.add(ticker)

    alerts_added = 0
    for alert in payload.alerts:
        try:
            alerts_module.create_alert(
                owner, alert.ticker, alert.direction, alert.threshold, alert.note
            )
            alerts_added += 1
        except alerts_module.AlertError as e:
            skipped.append(f"alert for {alert.ticker}: {e}")

    return ImportResult(added=added, alerts_added=alerts_added, skipped=skipped)
