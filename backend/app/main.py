import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import (
    alerts,
    auth,
    fed,
    journal,
    market,
    notify,
    portability,
    positions,
    stocks,
    valuation,
)

log = logging.getLogger(__name__)

app = FastAPI(title="Vantage", description="Personal stock research app")

# Sessions ride in a cookie, and a browser only sends one cross-origin when
# the API allows credentials. Allowing that alongside a wildcard origin would
# let any website read a signed-in reader's watchlist, and browsers refuse the
# combination outright -- a wildcard plus a credentialed request is blocked,
# which takes down every call, not just sign-in. So the wildcard is treated as
# "no accounts here", and the client falls back to sending no cookie.
_credentialed = settings.allows_credentialed_cors
if not _credentialed:
    log.warning(
        "CORS_ORIGINS is '*'. The app will work signed out, but accounts are "
        "off: browsers refuse to send a session cookie to a wildcard origin. "
        "Set CORS_ORIGINS to your site's address (e.g. "
        "https://your-site.onrender.com) to enable sign-in."
    )
else:
    log.info("CORS: accepting credentialed requests from %s", settings.cors_summary)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=_credentialed,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(market.router)
app.include_router(alerts.router)
app.include_router(positions.router)
app.include_router(journal.router)
app.include_router(valuation.router)
app.include_router(notify.router)
app.include_router(portability.router)
app.include_router(fed.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
