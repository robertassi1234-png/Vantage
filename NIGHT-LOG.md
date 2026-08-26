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
