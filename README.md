# Vantage

A personal stock research app: compare stock fundamentals side-by-side and track
Fed policy sentiment over time. Works signed out with lists kept per browser;
sign in with an emailed link to carry them across devices and get price alerts
by email.

- **Backend:** Python (FastAPI) + SQLAlchemy over SQLite or Postgres
- **Frontend:** React + TypeScript (Vite)

## Features

0. **Accounts (optional)** — sign in with a link emailed to you and your
   watchlist, notes, comparison list and price alerts follow you to any
   device. Signed out, everything is kept per browser and works the same.
1. **Price alerts** — set a target price on anything you follow; Vantage
   checks on every visit, and emails you when one crosses if a scheduler is
   configured.
2. **Dashboard** — a watchlist showing price, today's move and where each stock
   sits in its 52-week range; stat tiles for the S&P 500, Nasdaq, Dow and
   Russell 2000; and an interactive price chart (1M–5Y) for any watchlist name
   or index. Search accepts company names, not just tickers — typing "apple"
   finds AAPL.
3. **Stock comparison** — add tickers to a watchlist, see PE ratio, EV/EBITDA,
   market cap, revenue/EPS growth, margins, debt/equity, ROE, dividend yield,
   and more in a sortable table. Data from [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs).
   Fundamentals are cached for 24h (configurable) so you don't burn API calls
   on every page load.
4. **Fed policy tracker** — pulls recent FOMC statements from federalreserve.gov
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

Optional, and only for accounts and alert emails — see
[Turning on accounts](#turning-on-accounts):

- A Postgres database. [Neon](https://neon.tech)'s free tier works.
- An SMTP provider. [Resend](https://resend.com)'s free tier works.

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
default, see `DATABASE_URL` in `.env`) is created automatically and holds
watchlists, price alerts, accounts, cached fundamentals, and Fed statement
history. Point `DATABASE_URL` at a Postgres connection string instead and the
same code runs unchanged.

Signing in locally needs no mail account: with `SMTP_HOST` unset, the sign-in
link comes back in the response and the account panel offers it as a link to
click.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # defaults to http://localhost:8000, only needed if you change the backend port
npm run dev
```

Open `http://localhost:5173`.

## Where the data comes from

| Data | Provider | Why |
|---|---|---|
| Quotes, price history, search | **Yahoo Finance**, falling back to FMP | No key and no published quota |
| Fundamentals | **FMP** only | Yahoo's fundamentals need an authenticated crumb |
| Fed statements | federalreserve.gov | Public RSS, no key |
| Fed tone summaries | Claude Haiku | Needs Anthropic credit |

Yahoo needs no signup: it's called over plain HTTPS, so there is nothing to
configure. `PROVIDER_ORDER` controls preference — set it to `fmp` alone to turn
Yahoo off entirely if it ever misbehaves.

This is deliberately *not* the `yfinance` package. yfinance would work, but it
pulls in pandas, numpy and curl_cffi (~250MB), which on a free instance means
slower builds and another second or two of cold start. The two endpoints used
here return plain JSON, so `httpx` is enough. The trade-off is that Yahoo's
response shapes are undocumented and can change — hence the FMP fallback.

## Staying inside the FMP free tier

Since Yahoo now serves quotes, history and search, FMP is only used for
fundamentals (4 calls per ticker, cached 24h) and as a fallback. The free plan
allows **250 API calls/day**, and everything is cached in SQLite:

| Data | Cached for | Why |
|---|---|---|
| Fundamentals | 24h (`FUNDAMENTALS_CACHE_HOURS`) | Change at most quarterly |
| Quotes (watchlist + indices) | 15 min | Fresh enough to be useful, cheap enough to browse |
| Price history / sparklines | 12h | Daily closes only change once a day |
| Fed statements | Forever | A published statement never changes |

Normal use lands well under the limit. Clicking **Refresh** bypasses the quote
cache, so hammering it is the one way to burn through calls quickly.

## Usage

- **Stock Comparison tab:** type a ticker and hit Add. Fundamentals are
  fetched once and cached for 24 hours; use "Refresh data" to force a refetch
  of everything on your watchlist (be mindful of the free-tier 250 calls/day
  limit — each ticker refresh costs a handful of calls).
- **Fed Tracker tab:** click "Check for new statements" to pull the latest
  releases from federalreserve.gov and summarize any that aren't already
  cached. Already-summarized statements are skipped, so repeated clicks don't
  re-spend Claude API calls.

## Deploying (Render, free tier)

A `render.yaml` blueprint at the repo root deploys the backend as a web
service and the frontend as a static site in one pass.

The app works immediately after that, with lists kept per browser. Turning on
accounts — one watchlist that follows you between devices, and price alerts
that arrive by email — needs two free services and about ten minutes. See
[Turning on accounts](#turning-on-accounts) below.

**Free tier storage is not persistent.** Render's free web services have no
disk, so without `DATABASE_URL` the SQLite file resets whenever the service
restarts — which happens automatically after ~15 minutes of no traffic. That
is fine for trying the app out, and it is why accounts need a real database.

## Turning on accounts

Three settings, in this order. The app tells you which one is missing: open
the account menu in the header and it names the setting rather than failing
quietly.

### 1. A database that survives restarts

[Neon](https://neon.tech) has a free Postgres tier with no card required and
no 30-day expiry.

1. Sign up, create a project, and copy the connection string it shows you (it
   starts `postgresql://`).
2. In Render, open **vantage-backend → Environment**, set `DATABASE_URL` to
   that string, and save.

Any Postgres works — Supabase, Render's own Postgres, or your own server. The
app rewrites the older `postgres://` prefix that several providers still hand
out, so paste whatever they give you.

### 2. Name your site, so sign-in is allowed

Set `CORS_ORIGINS` to your frontend's exact address, e.g.
`https://vantage-frontend.onrender.com`, and `APP_BASE_URL` to the same value.

This is not optional bookkeeping. Sessions live in a cookie, and allowing a
cookie from *any* origin would let any website you visit read and change your
watchlist. The app refuses to combine the two, so sign-in stays off until
`CORS_ORIGINS` names a real address.

`APP_BASE_URL` is where sign-in links point — the site's address, not the
API's.

### 3. Email delivery

[Resend](https://resend.com) has a free tier of 3,000 emails a month, which
is far more than sign-in links and price alerts will use.

1. Sign up and create an API key.
2. In Render, set:
   - `SMTP_HOST` = `smtp.resend.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USER` = `resend`
   - `SMTP_PASSWORD` = your Resend API key
   - `EMAIL_FROM` = `Vantage <onboarding@resend.dev>` (their shared sending
     address — swap in your own domain later if you verify one)

Any SMTP provider works; SendGrid, Mailgun, Postmark and Gmail all take the
same four settings. Leave them unset and nothing breaks: sign-in links are
written to the server log instead, which is how local development works.

### 4. Alerts while the app is closed (optional)

A price alert is checked whenever you open Vantage. To have one reach you
when you are not looking, something outside the app has to ask it to check —
a free instance is asleep, and a timer inside a sleeping process never fires.

`.github/workflows/price-alerts.yml` does this from GitHub's scheduler, every
30 minutes during US market hours. To enable it, add two repository secrets
under **Settings → Secrets and variables → Actions**:

- `VANTAGE_API_URL` — your backend's address, e.g.
  `https://vantage-backend-mj3p.onrender.com`
- `CRON_SECRET` — the value Render generated for the backend's `CRON_SECRET`
  (Render shows it under Environment)

Without both secrets the workflow exits quietly, so nothing fails while it is
half-configured.

## What accounts change

- **Signed out** — lists key on a per-browser id, exactly as before. Nothing
  about the app requires signing in.
- **Signing in** — whatever that browser already saved moves onto the
  account. Signing in on a second device merges rather than overwrites, so a
  fresh browser can never erase the list you already have.
- **Signed in** — the same watchlist, notes, comparison list and price alerts
  appear on any device, and alerts arrive by email.

Sign-in is a link emailed to you, not a password. Nothing reversible is
stored: only a SHA-256 hash of a single-use token that expires in 20 minutes.
An expired link and an unknown one give the same message, so neither confirms
the other exists, and requests are rate limited per address so the endpoint
cannot be used to flood an inbox.

## Running the tests

```bash
cd backend && .venv/bin/python -m pytest      # backend
cd frontend && npm test                       # frontend
```

The backend suite uses a throwaway SQLite file and needs no server. Because
production runs on Postgres — and SQLite quietly accepts SQL that Postgres
rejects — the same suite can be pointed at a real database:

```bash
VANTAGE_TEST_DATABASE_URL=postgresql://user@localhost/vantage_test \
  .venv/bin/python -m pytest
```

This matters most for the migration code, which rewrites live tables.

## Project layout

```
backend/
  app/
    main.py           FastAPI app, CORS, router wiring
    config.py         Settings loaded from env vars
    engine.py         Database engine, SQLite or Postgres via DATABASE_URL
    db.py             Schema, migrations, watchlist/cache/timeline queries
    auth.py           Magic-link tokens and sessions
    mailer.py         SMTP sending, with a log-only fallback
    notifier.py       Firing alerts and emailing them
    alerts.py         Price alert storage and evaluation
    space.py          Resolves a request to an owner: account or browser
    fmp_client.py      Financial Modeling Prep API client
    fed_scraper.py     federalreserve.gov RSS + statement text scraper
    claude_client.py   Claude Haiku summarization
    routers/
      stocks.py        /api/lists, /api/fundamentals, /api/search
      market.py        /api/market/quotes, /indices, /history
      alerts.py        /api/alerts
      auth.py          /api/auth/me, /request-link, /verify, /signout
      notify.py        /api/notify/sweep, for the scheduler
      portability.py   /api/export, /api/import
      fed.py           /api/fed/timeline, /api/fed/refresh
  requirements.txt
  .env.example
frontend/
  src/
    api.ts             Fetch wrappers for the backend
    types.ts           Shared TS types
    useAccount.ts      Sign-in state and what the server supports
    pages/             DashboardPage, ComparisonPage, FedTrackerPage
    components/        AccountMenu, WatchlistPanel, charts, StockTable
  .env.example
```

## Notes / next steps

- The app is usable signed out, where lists key on a per-browser id. That id
  travels in a header and is separation, not security: anyone holding it can
  read that list. Sign in if you want your watchlist actually private, or
  kept across devices.
- If you want daily automatic Fed updates instead of the on-demand button,
  add a scheduler (e.g. `APScheduler`) that calls the same refresh logic in
  `app/routers/fed.py` on a timer.
