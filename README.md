# Vantage

A personal stock research app: compare stock fundamentals side-by-side and track
Fed policy sentiment over time. Single-user, local-only MVP.

- **Backend:** Python (FastAPI) + SQLite (used purely as a local cache/store)
- **Frontend:** React + TypeScript (Vite)

## Features

1. **Stock comparison** — add tickers to a watchlist, see PE ratio, EV/EBITDA,
   market cap, revenue/EPS growth, margins, debt/equity, ROE, dividend yield,
   and more in a sortable table. Data from [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs).
   Fundamentals are cached for 24h (configurable) so you don't burn API calls
   on every page load.
2. **Fed policy tracker** — pulls recent FOMC statements from federalreserve.gov
   (public RSS feed, no API key needed), summarizes tone (hawkish/dovish/neutral)
   and key takeaways using Claude Haiku, and shows a timeline. Refresh is
   **on-demand** (a button) rather than a background daily job — simpler to
   build and run for a single user; each statement is only summarized once and
   then cached permanently (statements don't change after the fact).

## Prerequisites

- Python 3.11+
- Node.js 18+
- A free [Financial Modeling Prep API key](https://site.financialmodelingprep.com/developer/docs)
  (free tier: 250 calls/day)
- An [Anthropic API key](https://console.anthropic.com/) for Claude Haiku

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and fill in FMP_API_KEY and ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. A SQLite file (`vantage.db` by
default, see `VANTAGE_DB_PATH` in `.env`) is created automatically and holds
your watchlist, cached fundamentals, and Fed statement history.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # defaults to http://localhost:8000, only needed if you change the backend port
npm run dev
```

Open `http://localhost:5173`.

## Usage

- **Stock Comparison tab:** type a ticker and hit Add. Fundamentals are
  fetched once and cached for 24 hours; use "Refresh data" to force a refetch
  of everything on your watchlist (be mindful of the free-tier 250 calls/day
  limit — each ticker refresh costs a handful of calls).
- **Fed Tracker tab:** click "Check for new statements" to pull the latest
  releases from federalreserve.gov and summarize any that aren't already
  cached. Already-summarized statements are skipped, so repeated clicks don't
  re-spend Claude API calls.

## Project layout

```
backend/
  app/
    main.py           FastAPI app, CORS, router wiring
    config.py         Settings loaded from env vars
    db.py             SQLite schema + cache/watchlist/timeline queries
    fmp_client.py      Financial Modeling Prep API client
    fed_scraper.py     federalreserve.gov RSS + statement text scraper
    claude_client.py   Claude Haiku summarization
    routers/
      stocks.py        /api/watchlist, /api/fundamentals
      fed.py           /api/fed/timeline, /api/fed/refresh
  requirements.txt
  .env.example
frontend/
  src/
    api.ts             Fetch wrappers for the backend
    types.ts           Shared TS types
    pages/             ComparisonPage, FedTrackerPage
    components/        StockTable
  .env.example
```

## Notes / next steps

- This is local-only by design — no auth, no multi-tenancy. If you later want
  to deploy it, the natural path is: containerize the backend, point
  `VANTAGE_DB_PATH` at a persistent volume, and serve the frontend build
  (`npm run build`) as static files (e.g. behind the same reverse proxy as the
  API, with `VITE_API_BASE_URL` set at build time).
- If you want daily automatic Fed updates instead of the on-demand button,
  add a scheduler (e.g. `APScheduler`) that calls the same refresh logic in
  `app/routers/fed.py` on a timer.
