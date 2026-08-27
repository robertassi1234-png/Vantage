"""The scheduled alert sweep.

An HTTP endpoint rather than a background thread because the free hosting tier
sleeps: a timer inside a sleeping process never fires, but an inbound request
wakes it. A shared secret guards it, since anything that sends email from a
public URL will eventually be found.
"""

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException

from app import auth, notifier
from app.config import settings

router = APIRouter(prefix="/api/notify", tags=["notify"])
log = logging.getLogger(__name__)


@router.post("/sweep")
async def sweep(x_cron_secret: str | None = Header(default=None)) -> dict:
    if not settings.cron_secret:
        raise HTTPException(
            status_code=503,
            detail="Scheduled alerts are off: set CRON_SECRET on the server to enable them.",
        )
    # compare_digest so a wrong guess can't be narrowed down by timing.
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(status_code=401, detail="Bad or missing cron secret.")

    result = await notifier.sweep()
    auth.purge_expired()
    log.info("alert sweep: %s", result)
    return result
