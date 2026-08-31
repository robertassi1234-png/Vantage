import pytest
from fastapi.testclient import TestClient

from app import db
from app.fmp_client import FMPError
from app.main import app
from app.routers import market as market_router
from app.routers import stocks as stocks_router

FUNDAMENTALS = {
    "ticker": "AAPL",
    "companyName": "Apple Inc.",
    "peRatio": 35.4,
    "marketCap": 4_551_611_624_400,
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


async def _no_history(symbol, range_key):
    """Stub so sparkline lookups don't reach the network during route tests."""
    return []


class TestWatchlistRoutes:
    def test_add_normalises_case_and_whitespace(self, client):
        assert client.post("/api/lists/watch", json={"ticker": " aapl "}).json() == ["AAPL"]

    def test_blank_ticker_is_rejected(self, client):
        assert client.post("/api/lists/watch", json={"ticker": "   "}).status_code == 400

    def test_remove_is_case_insensitive(self, client):
        client.post("/api/lists/watch", json={"ticker": "AAPL"})
        assert client.delete("/api/lists/watch/aapl").json() == []

    def test_removing_absent_ticker_is_a_no_op(self, client):
        assert client.delete("/api/lists/watch/GHOST").status_code == 200


class TestFundamentalsRoute:
    def test_serves_from_cache_without_refetching(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        db.set_cached_fundamentals("AAPL", FUNDAMENTALS)

        async def explode(ticker):
            raise AssertionError("fresh cache must not trigger an API call")

        monkeypatch.setattr(stocks_router, "fetch_fundamentals", explode)
        [row] = client.get("/api/fundamentals").json()
        assert row["peRatio"] == 35.4
        assert row["stale"] is False

    def test_refresh_true_bypasses_the_cache(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        db.set_cached_fundamentals("AAPL", FUNDAMENTALS)
        calls = []

        async def fetch(ticker):
            calls.append(ticker)
            return {**FUNDAMENTALS, "peRatio": 99.9}

        monkeypatch.setattr(stocks_router, "fetch_fundamentals", fetch)
        [row] = client.get("/api/fundamentals?refresh=true").json()
        assert calls == ["AAPL"]
        assert row["peRatio"] == 99.9

    def test_falls_back_to_stale_cache_when_upstream_fails(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)
        db.set_cached_fundamentals("AAPL", FUNDAMENTALS)

        async def boom(ticker):
            raise FMPError("rate limited")

        monkeypatch.setattr(stocks_router, "fetch_fundamentals", boom)
        [row] = client.get("/api/fundamentals?refresh=true").json()

        # Old numbers beat no numbers, as long as the row is flagged.
        assert row["peRatio"] == 35.4
        assert row["stale"] is True
        assert "rate limited" in row["error"]

    def test_error_row_when_upstream_fails_with_no_cache(self, client, monkeypatch):
        db.add_to_watchlist("AAPL", db.DEFAULT_OWNER, db.COMPARE_LIST)

        async def boom(ticker):
            raise FMPError("bad key")

        monkeypatch.setattr(stocks_router, "fetch_fundamentals", boom)
        [row] = client.get("/api/fundamentals").json()
        assert row["ticker"] == "AAPL"
        assert row["peRatio"] is None
        assert "bad key" in row["error"]

    def test_empty_watchlist_returns_empty_list(self, client):
        assert client.get("/api/fundamentals").json() == []


class TestSearchRoute:
    def test_returns_matches(self, client, monkeypatch):
        async def search(q, limit=8):
            return [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "currency": "USD"}]

        monkeypatch.setattr(stocks_router, "search_symbols", search)
        assert client.get("/api/search?q=apple").json()[0]["symbol"] == "AAPL"

    def test_upstream_failure_surfaces_as_502(self, client, monkeypatch):
        async def boom(q, limit=8):
            raise FMPError("upstream down")

        monkeypatch.setattr(stocks_router, "search_symbols", boom)
        assert client.get("/api/search?q=apple").status_code == 502


class TestMarketRoutes:
    def test_history_rejects_unknown_range(self, client):
        resp = client.get("/api/market/history/AAPL?range=decade")
        assert resp.status_code == 400
        assert "Unknown range" in resp.json()["detail"]

    def test_history_caches_between_calls(self, client, monkeypatch):
        calls = []

        async def fetch(symbol, range_key):
            calls.append(symbol)
            return [{"date": "2026-08-25", "close": 310.0}]

        monkeypatch.setattr(market_router, "fetch_history", fetch)
        client.get("/api/market/history/AAPL?range=1M")
        client.get("/api/market/history/AAPL?range=1M")
        assert calls == ["AAPL"]

    def test_history_ranges_are_cached_separately(self, client, monkeypatch):
        calls = []

        async def fetch(symbol, range_key):
            calls.append(range_key)
            return [{"date": "2026-08-25", "close": 310.0}]

        monkeypatch.setattr(market_router, "fetch_history", fetch)
        client.get("/api/market/history/AAPL?range=1M")
        client.get("/api/market/history/AAPL?range=1Y")
        assert calls == ["1M", "1Y"]

    def test_history_with_no_data_is_404(self, client, monkeypatch):
        async def empty(symbol, range_key):
            return []

        monkeypatch.setattr(market_router, "fetch_history", empty)
        assert client.get("/api/market/history/NOPE?range=1M").status_code == 404

    def test_caret_index_symbols_survive_the_url(self, client, monkeypatch):
        seen = []

        async def fetch(symbol, range_key):
            seen.append(symbol)
            return [{"date": "2026-08-25", "close": 6500.0}]

        monkeypatch.setattr(market_router, "fetch_history", fetch)
        resp = client.get("/api/market/history/%5EGSPC?range=1M")
        assert resp.status_code == 200
        assert seen == ["^GSPC"]

    def test_quotes_requires_symbols(self, client):
        assert client.get("/api/market/quotes").status_code == 422

    def test_quotes_with_blank_list_returns_empty(self, client):
        assert client.get("/api/market/quotes?symbols=%20").json() == []

    def test_indices_serve_stale_cache_when_upstream_fails(self, client, monkeypatch):
        db.set_market_cache("indices", [{"symbol": "^GSPC", "price": 6000}])

        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(market_router, "fetch_quotes", boom)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)
        resp = client.get("/api/market/indices?refresh=true")
        assert resp.status_code == 200
        assert resp.json()[0]["price"] == 6000

    def test_indices_fail_loudly_with_no_cache(self, client, monkeypatch):
        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(market_router, "fetch_quotes", boom)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)
        assert client.get("/api/market/indices?refresh=true").status_code == 502

    def test_empty_quote_batch_does_not_poison_the_cache(self, client, monkeypatch):
        """A total upstream failure must not overwrite good cached prices.

        fetch_quotes drops symbols it can't fetch instead of raising, so an
        outage that kills every symbol returns [] rather than an FMPError. The
        route has to recognise that as failure, or it caches four blank tiles
        over a healthy copy and the dashboard stays empty for the whole TTL.
        """
        good = [{"symbol": "^GSPC", "label": "S&P 500", "price": 6000, "sparkline": []}]
        db.set_market_cache("indices", good)

        async def all_symbols_failed(symbols):
            return []

        monkeypatch.setattr(market_router, "fetch_quotes", all_symbols_failed)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)

        resp = client.get("/api/market/indices?refresh=true")
        assert resp.status_code == 200
        assert resp.json()[0]["price"] == 6000

        # The cached copy must survive for the next reader too.
        assert db.get_market_cache("indices", 900)[0]["price"] == 6000

    def test_empty_quote_batch_with_no_cache_is_502(self, client, monkeypatch):
        async def all_symbols_failed(symbols):
            return []

        monkeypatch.setattr(market_router, "fetch_quotes", all_symbols_failed)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)
        assert client.get("/api/market/indices?refresh=true").status_code == 502

    def test_partial_quote_batch_is_still_served(self, client, monkeypatch):
        """One dead symbol shouldn't cost the other three their prices."""

        async def one_symbol_only(symbols):
            return [
                {
                    "symbol": "^GSPC",
                    "price": 6500,
                    "change": 10,
                    "changePercent": 0.15,
                }
            ]

        monkeypatch.setattr(market_router, "fetch_quotes", one_symbol_only)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)

        body = client.get("/api/market/indices?refresh=true").json()
        by_symbol = {row["symbol"]: row for row in body}
        assert by_symbol["^GSPC"]["price"] == 6500
        assert by_symbol["^IXIC"]["price"] is None


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


class TestPartialQuoteOutages:
    """A provider answering for some symbols and not others.

    The failure this guards is not the tile going blank for one load -- it is
    that the blank was then cached, so a provider recovering changed nothing
    the reader could see until the TTL expired.
    """

    def priced(self, board) -> int:
        return sum(1 for group in board for e in group["entries"] if e["price"] is not None)

    def stub(self, monkeypatch, answered: set[str] | None):
        async def fetch(symbols):
            wanted = symbols if answered is None else [s for s in symbols if s in answered]
            return [
                {"symbol": s, "price": 100.0, "change": 1.0, "changePercent": 1.0}
                for s in wanted
            ]

        monkeypatch.setattr(market_router, "fetch_quotes", fetch)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)

    def test_tiles_keep_their_last_price_when_a_symbol_stops_answering(
        self, client, monkeypatch
    ):
        self.stub(monkeypatch, None)
        before = self.priced(client.get("/api/market/board").json())
        assert before == 13

        self.stub(monkeypatch, {"XLK"})
        after = self.priced(client.get("/api/market/board?refresh=true").json())
        assert after == before

    def test_a_symbol_that_does_answer_gets_the_new_price(self, client, monkeypatch):
        self.stub(monkeypatch, None)
        client.get("/api/market/board")

        async def one_moved(symbols):
            return [{"symbol": "XLK", "price": 250.0, "change": 2.0, "changePercent": 0.8}]

        monkeypatch.setattr(market_router, "fetch_quotes", one_moved)
        board = client.get("/api/market/board?refresh=true").json()
        tiles = {e["symbol"]: e for group in board for e in group["entries"]}
        assert tiles["XLK"]["price"] == 250.0
        assert tiles["XLY"]["price"] == 100.0

    def test_a_carried_tile_keeps_the_change_that_belongs_to_its_price(
        self, client, monkeypatch
    ):
        # A fresh price beside yesterday's change would be a figure that never
        # existed on any day.
        async def full(symbols):
            return [
                {"symbol": s, "price": 100.0, "change": 5.0, "changePercent": 5.3}
                for s in symbols
            ]

        monkeypatch.setattr(market_router, "fetch_quotes", full)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)
        client.get("/api/market/board")

        self.stub(monkeypatch, {"XLK"})
        board = client.get("/api/market/board?refresh=true").json()
        tiles = {e["symbol"]: e for group in board for e in group["entries"]}
        assert (tiles["XLY"]["price"], tiles["XLY"]["change"]) == (100.0, 5.0)

    def test_recovery_is_visible_rather_than_waiting_out_the_cache(
        self, client, monkeypatch
    ):
        self.stub(monkeypatch, {"XLK"})
        client.get("/api/market/board")

        self.stub(monkeypatch, None)
        board = client.get("/api/market/board?refresh=true").json()
        assert self.priced(board) == 13


class TestBlanksAreNeverCached:
    """A board with no prices on it is not a cheap board, it is no board.

    Cached, it is served for a full TTL without asking any provider -- so the
    moment a provider recovers is invisible, which is exactly how a dashboard
    stays blank long after the outage that blanked it.
    """

    def all_priced(self, board) -> int:
        return sum(1 for group in board for e in group["entries"] if e["price"] is not None)

    def stub(self, monkeypatch, fetch):
        monkeypatch.setattr(market_router, "fetch_quotes", fetch)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)

    async def _priceless(self, symbols):
        return [{"symbol": s, "price": None, "change": None} for s in symbols]

    async def _good(self, symbols):
        return [
            {"symbol": s, "price": 100.0, "change": 1.0, "changePercent": 1.0} for s in symbols
        ]

    def test_a_blank_round_does_not_overwrite_older_real_prices(self, client, monkeypatch):
        self.stub(monkeypatch, self._good)
        client.get("/api/market/board")

        self.stub(monkeypatch, self._priceless)
        assert self.all_priced(client.get("/api/market/board?refresh=true").json()) == 13

    def test_a_blank_board_is_not_served_as_a_cache_hit(self, client, monkeypatch):
        # With nothing ever cached, a blank round must not become the answer
        # every visitor gets for the next fifteen minutes.
        self.stub(monkeypatch, self._priceless)
        client.get("/api/market/board")

        calls = []

        async def counted(symbols):
            calls.append(symbols)
            return await self._good(symbols)

        self.stub(monkeypatch, counted)
        board = client.get("/api/market/board").json()

        assert calls, "a blank board was served instead of asking a provider again"
        assert self.all_priced(board) == 13

    def test_recovery_reaches_the_reader_on_the_next_load(self, client, monkeypatch):
        self.stub(monkeypatch, self._priceless)
        client.get("/api/market/board")
        self.stub(monkeypatch, self._good)
        assert self.all_priced(client.get("/api/market/board").json()) == 13

    def test_a_blank_board_still_renders_its_labels(self, client, monkeypatch):
        # The section has to keep existing during an outage: a vanished
        # feature reads as one that was never built.
        self.stub(monkeypatch, self._priceless)
        board = client.get("/api/market/board").json()
        assert [g["group"] for g in board] == ["Growth", "Defensive", "Cyclical", "Global & other"]


class TestTheBoardCostsLess:
    """Which parts of the market are leading is context, not a ticker tape.

    The whole point of the free tier being 250 calls a day is that nothing
    should be refetched more often than it changes.
    """

    def test_the_board_is_kept_longer_than_the_headline_indices(self, client):
        assert market_router.BOARD_TTL_SECONDS > market_router.QUOTE_TTL_SECONDS

    def test_a_second_load_inside_the_window_asks_nobody(self, client, monkeypatch):
        calls = []

        async def counted(symbols):
            calls.append(symbols)
            return [
                {"symbol": s, "price": 100.0, "change": 1.0, "changePercent": 1.0}
                for s in symbols
            ]

        monkeypatch.setattr(market_router, "fetch_quotes", counted)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)

        client.get("/api/market/board")
        client.get("/api/market/board")
        assert len(calls) == 1

    def test_the_thirteen_symbols_go_out_as_one_request(self, client, monkeypatch):
        # Batched at the client, so the whole board is one call rather than
        # thirteen. This is the difference between seven page loads a day and
        # a hundred.
        batches = []

        async def counted(symbols):
            batches.append(list(symbols))
            return [
                {"symbol": s, "price": 100.0, "change": 1.0, "changePercent": 1.0}
                for s in symbols
            ]

        monkeypatch.setattr(market_router, "fetch_quotes", counted)
        monkeypatch.setattr(market_router, "fetch_history", _no_history)

        client.get("/api/market/board")
        assert len(batches) == 1
        assert len(batches[0]) == 13


class TestADayOfUse:
    """What a dashboard actually costs, in provider calls.

    Pinned because this is the difference between the app working and the app
    being out of data by lunchtime, and because it is invisible: nothing fails
    when a page quietly asks for one symbol at a time.
    """

    def cost(self, client, monkeypatch, paths: list[str]) -> dict:
        from app import fmp_client

        calls = []

        async def counted(http, path, **params):
            calls.append(path)
            if path == "quote":
                return [
                    {"symbol": s, "price": 100.0, "change": 1.0, "changePercentage": 1.0}
                    for s in params["symbol"].split(",")
                ]
            return []

        monkeypatch.setattr(fmp_client, "_get", counted)
        monkeypatch.setattr(fmp_client.settings, "fmp_api_key", "k")
        for path in paths:
            client.get(path)
        return {
            "quotes": sum(1 for p in calls if p == "quote"),
            "history": sum(1 for p in calls if "historical" in p),
        }

    def test_a_cold_dashboard_asks_for_quotes_twice_not_seventeen_times(
        self, client, monkeypatch
    ):
        # Seventeen symbols: four indices and thirteen sector tiles. One
        # request each spent a 250-call allowance in about seven page loads.
        cost = self.cost(client, monkeypatch, ["/api/market/indices", "/api/market/board"])
        assert cost["quotes"] == 2

    def test_a_warm_dashboard_asks_for_nothing(self, client, monkeypatch):
        cost = self.cost(
            client,
            monkeypatch,
            ["/api/market/indices", "/api/market/board"] * 4,
        )
        assert cost["quotes"] == 2
        assert cost["history"] == 17

    def test_a_watchlist_is_one_request_however_long_it_is(self, client, monkeypatch):
        symbols = ",".join(f"SYM{i}" for i in range(15))
        cost = self.cost(client, monkeypatch, [f"/api/market/quotes?symbols={symbols}"])
        assert cost["quotes"] == 1
