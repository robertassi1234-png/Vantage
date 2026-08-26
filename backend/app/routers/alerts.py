from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import alerts as alerts_module
from app.fmp_client import FMPError
from app.market_data import fetch_quotes
from app.space import current_space

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
    error: str | None = None


@router.get("")
def list_alerts(space: str = Depends(current_space)) -> list[dict]:
    return alerts_module.list_alerts(space)


@router.post("")
def create_alert(req: AlertRequest, space: str = Depends(current_space)) -> dict:
    try:
        return alerts_module.create_alert(
            space, req.ticker, req.direction, req.threshold, req.note
        )
    except alerts_module.AlertError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{alert_id}")
def delete_alert(alert_id: str, space: str = Depends(current_space)) -> list[dict]:
    alerts_module.delete_alert(space, alert_id)
    return alerts_module.list_alerts(space)


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: str, space: str = Depends(current_space)) -> list[dict]:
    if alerts_module.acknowledge_alert(space, alert_id) is None:
        raise HTTPException(status_code=404, detail="No such alert.")
    return alerts_module.list_alerts(space)


@router.post("/check")
async def check_alerts(space: str = Depends(current_space)) -> CheckResult:
    """Fetch prices for tickers with pending alerts and fire any that crossed.

    Called by the app on load. On hosting that stays awake this same function
    is what a scheduler would call -- the evaluation logic doesn't care who
    triggers it.
    """
    tickers = alerts_module.alert_tickers(space)
    if not tickers:
        return CheckResult(fired=[], alerts=alerts_module.list_alerts(space), checked=0)

    try:
        quotes = await fetch_quotes(tickers)
    except FMPError as e:
        # A price lookup failing shouldn't hide the alerts the user already has.
        return CheckResult(
            fired=[],
            alerts=alerts_module.list_alerts(space),
            checked=0,
            error=str(e),
        )

    prices = {
        q["symbol"]: q["price"]
        for q in quotes
        if isinstance(q.get("price"), (int, float))
    }
    fired = alerts_module.evaluate(space, prices)

    return CheckResult(
        fired=fired, alerts=alerts_module.list_alerts(space), checked=len(prices)
    )
