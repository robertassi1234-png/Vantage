from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import alerts as alerts_module
from app import notifier
from app.space import current_owner

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertRequest(BaseModel):
    ticker: str
    direction: str
    threshold: float
    note: str | None = None


class CheckResult(BaseModel):
    fired: list[dict]
    alerts: list[dict]
    checked: int
    emailed: int = 0
    error: str | None = None


@router.get("")
def list_alerts(owner: str = Depends(current_owner)) -> list[dict]:
    return alerts_module.list_alerts(owner)


@router.post("")
def create_alert(req: AlertRequest, owner: str = Depends(current_owner)) -> dict:
    try:
        return alerts_module.create_alert(
            owner, req.ticker, req.direction, req.threshold, req.note
        )
    except alerts_module.AlertError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{alert_id}")
def delete_alert(alert_id: str, owner: str = Depends(current_owner)) -> list[dict]:
    alerts_module.delete_alert(owner, alert_id)
    return alerts_module.list_alerts(owner)


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: str, owner: str = Depends(current_owner)) -> list[dict]:
    if alerts_module.acknowledge_alert(owner, alert_id) is None:
        raise HTTPException(status_code=404, detail="No such alert.")
    return alerts_module.list_alerts(owner)


@router.post("/check")
async def check_alerts(owner: str = Depends(current_owner)) -> CheckResult:
    """Fetch prices for tickers with pending alerts and fire any that crossed.

    Called by the app on load, so an alert lands the moment you open the page
    even if the scheduled sweep hasn't run. Signed-in readers also get the
    email from here; the sweep is what covers the hours nobody is looking.
    """
    result = await notifier.check_owner(owner)
    return CheckResult(
        fired=result["fired"],
        # A failed price lookup shouldn't hide the alerts already set.
        alerts=alerts_module.list_alerts(owner),
        checked=result["checked"],
        emailed=result["emailed"],
        error=result["error"],
    )
