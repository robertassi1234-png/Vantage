import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import alerts, auth, fed, market, notify, portability, stocks

log = logging.getLogger(__name__)

app = FastAPI(title="Vantage", description="Personal stock research app")

# Sessions ride in a cookie, and a cookie is only sent cross-origin when the
# API allows credentials. Allowing them alongside a wildcard origin would let
# any website read a signed-in reader's watchlist, so the wildcard keeps the
# anonymous app working from anywhere and sign-in waits for a named origin.
_credentialed = settings.allows_credentialed_cors
if not _credentialed:
    log.warning(
        "CORS_ORIGINS is '*', so signing in from another origin is disabled. "
        "Set it to your site's address to enable accounts."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=_credentialed,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(market.router)
app.include_router(alerts.router)
app.include_router(notify.router)
app.include_router(portability.router)
app.include_router(fed.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
