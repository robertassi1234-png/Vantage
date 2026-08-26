# Night log

Running record of unattended hardening work. Newest entries at the top.

Ground rules for these sessions:

- A change reaches `main` only when the backend suite, the frontend suite, and
  the production build all pass. Anything red stays on
  `claude/vantage-stock-research-2e92bq`.
- No test is ever weakened or deleted to make a run go green.
- No new features that depend on Financial Modeling Prep endpoints — egress to
  `financialmodelingprep.com` is blocked from the build sandbox, so anything
  API-shaped can only be exercised against mocks.

---

## 2026-08-26 — Iteration 5: per-browser watchlists + quality of life

**Why:** the deployed link showed everyone the same watchlist, because the
original brief specified a single-user tool and the schema had no notion of a
user. Anyone opening the URL could edit your list.

**Per-browser spaces.** Each browser generates a random id (`vantage.space` in
localStorage) and sends it as `X-Vantage-Space`. Watchlists and notes are
scoped to it.

Two deliberate decisions worth recording:

- **Only watchlists are scoped. Prices, fundamentals and Fed summaries stay
  global.** AAPL's P/E is the same number for everyone, so a shared cache means
  a second visitor costs zero extra API calls. Scoping the cache per browser
  would multiply usage by the number of visitors — exactly backwards on a
  250-a-day budget.
- **This is separation, not security.** Anyone holding an id can read that
  watchlist. It stops two people colliding; it does not keep secrets. The
  footer says so plainly rather than implying privacy that isn't there.

Space ids are client-supplied, so they're validated against
`[A-Za-z0-9_-]{1,64}` and fall back to the shared default otherwise — six
hostile inputs are covered, including SQL injection and traversal attempts.

An existing database is migrated in place via `PRAGMA table_info`, since
`CREATE TABLE IF NOT EXISTS` leaves an old table untouched. Existing rows land
in the default space rather than being dropped.

**One test changed meaning, deliberately:**
`test_remove_also_drops_cached_fundamentals` asserted that removing a ticker
evicted its cached numbers. Correct when there was one watchlist; wrong now
that the cache is shared. Rewritten as
`test_remove_keeps_the_shared_fundamentals_cache` with the reasoning in the
docstring — the premise changed by design, so the test was updated rather than
deleted.

**Quality of life** (all zero API cost, chosen with the call budget in mind):

- Theme toggle cycling Auto → Light → Dark, persisted. "Auto" removes the
  attribute so it tracks the OS rather than freezing today's mode.
- The app reopens on the tab you left.
- CSV export of the comparison table. Values are exported raw so they stay
  computable, and any field starting with `=`, `+`, `-` or `@` is prefixed with
  a quote — spreadsheets execute those as formulas, and a negative growth
  figure is the everyday case.
- Per-ticker notes (backend + API; UI still to come).
- A global `:focus-visible` ring, so keyboard users can see where they are.

**Verified:** backend 105 passed · frontend 103 passed · build clean ·
screenshots checked in both themes.

**Notes for the morning:**

- yfinance needs no API key — nothing to sign up for. Adding `yfinance` to
  `requirements.txt` is the whole setup.
- Seven oxlint `set-state-in-effect` warnings now (two new, from the theme and
  tab persistence). Still non-blocking; queued for the bug-hunt pass.

---

## 2026-08-26 — Iteration 4: two real backend bugs

**First production bugs of the night.** Both found by reading the indices route
adversarially, both reproduced with a failing test before any fix, and both
confirmed to fail against the old code (stashed the fix, watched the tests go
red, restored it).

### Bug 1 — a network blip 500'd the whole indices endpoint

`_get` let transport-level exceptions escape. `httpx` raises `ConnectError`,
`ReadTimeout`, `ProxyError` and `HTTPStatusError`, none of which are
`FMPError` — so every `except FMPError` in the codebase silently failed to
catch them. `_sparkline` looked like it degraded gracefully; in reality one
slow sparkline request took down `/api/market/indices` with a 500.

Fixed at the choke point: `_get` now converts transport errors, non-2xx
statuses and malformed JSON bodies into `FMPError`, so callers' existing
graceful degradation actually works. Seven cases pin it.

This surfaced by accident — a test failed with `httpx.ProxyError: 403` instead
of the assertion I expected, because the sandbox blocks outbound requests. The
sandbox restriction turned out to be a useful fault injector.

### Bug 2 — a failed refresh blanked the dashboard for 15 minutes

`fetch_quotes` deliberately drops symbols it can't retrieve rather than
failing the batch, so a total outage returns `[]` rather than raising. The
route didn't treat that as failure: it built four tiles with `price: None` and
**wrote them over a perfectly good cached copy**, so the index row stayed blank
for the full 15-minute TTL even though valid prices had been sitting in the
cache.

Now an empty batch takes the same path as an exception — serve the stale copy
if there is one, otherwise return an honest 502 — and never overwrites the
cache. A partial batch is still served, so one dead symbol doesn't cost the
other three their prices.

**Also:** the four sparkline lookups now run through `asyncio.gather` instead
of sequentially, and `StockTable` gained 16 cases (numeric-vs-lexical sorting,
blanks staying last in *both* directions, no mutation of the rows prop).

**Verified:** backend 85 passed · frontend 88 passed · build clean.

**Notes for the morning:** the empty-`<th>` cells in the table's group header
row have no accessible name — queued for the accessibility pass.

---

## 2026-08-26 — Iteration 3: TickerSearch behaviour

**Added:** `src/components/TickerSearch.test.tsx` — 13 cases covering debounce
(a burst of keystrokes makes one request), keyboard navigation including
wrap-around, Escape, click-to-select, and the fallback that still lets an exact
ticker through when the search endpoint is down.

The one that matters most: **a slow response for an earlier query must not
overwrite a newer one**. The component already guards this with a request
sequence number; there is now a test that fails if that guard is removed.

**Test-harness notes** (no production code changed this iteration):

- Fake timers plus `userEvent` deadlock — 11 of 12 cases timed out on the first
  attempt. `userEvent` awaits internally on timers the fake clock had frozen.
  Rewritten to use real timers; the debounce is only 220ms so the whole file
  still runs in ~5s.
- Test-level waits are wrapped in `act()` via a `settle()` helper, so the state
  updates the debounce fires are flushed by React instead of warning. Latency
  simulated *inside* a mocked request deliberately is not wrapped — that models
  the network, not a render pass.

**Verified:** frontend 72 passed · backend 75 passed · build clean.

**Notes for the morning:** no production bugs found. The async guards in
`TickerSearch` were already correct; they are now pinned by tests.

---

## 2026-08-26 — Iteration 2: test coverage for the untested units

**Added** (59 frontend tests total, up from 19):

- `src/api.test.ts` — cold-start retry budget, error translation, URL encoding.
  Confirms a `404` is *not* retried (it's an answer, not a cold start) while a
  network failure is retried twice and then reported as a waking server.
- `src/components/PriceChart.test.tsx` — `niceStep` / `axisTicks` snapping, plus
  rendering guards: a flat series, a single point, and a NaN range all render
  without `NaN` or `Infinity` reaching the SVG path.
- `src/components/WatchlistPanel.test.tsx` — 52-week marker position, including
  a price that has broken above a stale `yearHigh` (clamps to 100%) and a
  zero-width range (marker omitted rather than dividing by zero).

**Changed:** `niceStep` and `axisTicks` are now exported from `PriceChart.tsx`
so the axis maths can be tested directly rather than through rendered output.

**Verified:** frontend 59 passed · backend 75 passed · `npm run build` clean.

**Notes for the morning:**

- The build type-checks test files (`tsconfig.app.json` includes all of `src`),
  which caught a real typing mistake in the fetch mocks. Worth keeping.
- No production bugs found this iteration — the edge cases probed (flat series,
  zero-width range, missing quote fields) were all already handled correctly.

---

## 2026-08-26 — Iteration 1: test infrastructure

**Added:** pytest for the backend (75 cases) and Vitest for the frontend (19),
plus `.github/workflows/ci.yml` running both on every push.

Coverage targets the logic most likely to break silently: the FMP field mapping
that already broke once when the v3 API was retired, cache TTL boundaries,
search ranking, and the error paths a user actually sees (out-of-credit
Anthropic response, sleeping backend, upstream failure falling back to stale
data).

**Changed:** test config moved to `vitest.config.ts`. Vitest pins its own copy
of Vite (7.x) while the project runs Vite 8, so declaring `test` inside
`vite.config.ts` made the two copies' plugin types collide under `tsc -b`. That
config also skips `@vitejs/plugin-react`, which only supplies Fast Refresh —
esbuild picks the JSX transform up from tsconfig on its own.

**Verified:** frontend 19 passed · backend 75 passed · build clean.

**Notes for the morning:**

- `oxlint` reports five `react(set-state-in-effect)` warnings
  (`ComparisonPage`, `DashboardPage`, `FedTrackerPage`, `TickerSearch`,
  `PriceChart`). Non-blocking, queued for the bug-hunt pass.
- Still unverified against live data: the index symbols `^GSPC`, `^IXIC`,
  `^DJI`, `^RUT`. If the index tiles are empty in the morning, that's the first
  thing to check.
