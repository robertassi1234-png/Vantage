from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import alerts, auth, fed, market, notify, portability, stocks

app = FastAPI(title="Vantage", description="Personal stock research app")

# Sessions ride in a cookie, so the browser only sends them when the API says
# credentials are allowed -- and the spec forbids pairing that with a wildcard
# origin, hence the regex when someone has set CORS_ORIGINS=*.
_origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if _origins == ["*"] else _origins,
    allow_origin_regex=".*" if _origins == ["*"] else None,
    allow_credentials=True,
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
