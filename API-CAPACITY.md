# Making Vantage's market-data allowance last

The shared upstream cache reuses each stock quote for 5 minutes across features
and different watchlists, daily history for 12 hours, searches and peers for 24
hours, and fundamentals for at least 1 hour even when Refresh is pressed.
Normal fundamentals page caching remains 24 hours. Concurrent identical work
is coalesced within each backend worker. Empty results and errors are not cached.
This reduces consumption; it does not increase a provider's contractual quota.
For example, 20 simultaneous identical successful history requests now require
one provider-chain execution, verified by an automated test. Actual savings
depend on how many symbols and features are used.

Database cache durability requires a persistent DATABASE_URL. Free Render's
local SQLite file does not survive redeployment. Do not assume a database is
persistent merely because the app has an account or a watchlist.

## More capacity (checked September 5, 2026)

Twelve Data lists Basic at 8 credits/minute and 800/day, but marks it internal
non-display. It is not automatically a license to show prices on this website.
Grow lists 55+ credits/minute, no daily cap, internal display and starts at
$79/month monthly ($66/month equivalent annually). Endpoint and per-symbol
weights still apply. Public/external display requires appropriate business
licensing. Verify coverage and rights before subscribing.

- https://twelvedata.com/pricing
- https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage

Vantage already has a Twelve Data adapter. An appropriately licensed key goes
in the backend's TWELVE_DATA_API_KEY environment variable, never the frontend
or git. Adding a key enables it as a fallback without changing code. No new
subscriptions, keys, or billing changes were made in this update.
