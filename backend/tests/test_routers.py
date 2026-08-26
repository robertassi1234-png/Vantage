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


class TestWatchlistRoutes:
    def test_add_normalises_case_and_whitespace(self, client):
        assert client.post("/api/watchlist", json={"ticker": " aapl "}).json() == ["AAPL"]

    def test_blank_ticker_is_rejected(self, client):
        assert client.post("/api/watchlist", json={"ticker": "   "}).status_code == 400

    def test_remove_is_case_insensitive(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert client.delete("/api/watchlist/aapl").json() == []

    def test_removing_absent_ticker_is_a_no_op(self, client):
        assert client.delete("/api/watchlist/GHOST").status_code == 200


class TestFundamentalsRoute:
    def test_serves_from_cache_without_refetching(self, client, monkeypatch):
        db.add_to_watchlist("AAPL")
        db.set_cached_fundamentals("AAPL", FUNDAMENTALS)

        async def explode(ticker):
            raise AssertionError("fresh cache must not trigger an API call")

        monkeypatch.setattr(stocks_router, "fetch_fundamentals", explode)
        [row] = client.get("/api/fundamentals").json()
        assert row["peRatio"] == 35.4
        assert row["stale"] is False

    def test_refresh_true_bypasses_the_cache(self, client, monkeypatch):
        db.add_to_watchlist("AAPL")
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
        db.add_to_watchlist("AAPL")
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
        db.add_to_watchlist("AAPL")

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
        resp = client.get("/api/market/indices?refresh=true")
        assert resp.status_code == 200
        assert resp.json()[0]["price"] == 6000

    def test_indices_fail_loudly_with_no_cache(self, client, monkeypatch):
        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(market_router, "fetch_quotes", boom)
        assert client.get("/api/market/indices?refresh=true").status_code == 502


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
