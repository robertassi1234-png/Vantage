import asyncio

import httpx
import pytest

from app import fmp_client
from app.fmp_client import FMPError


class TestTransportErrorsBecomeFMPErrors:
    """Every failure must leave _get as an FMPError.

    Callers catch FMPError to degrade gracefully -- serving stale prices,
    flagging one row. A raw httpx error escaping turns a single flaky request
    into a 500 for the whole endpoint.
    """

    def stub_client(self, monkeypatch, *, raises=None, response=None):
        class FakeClient:
            async def get(self, url, params=None):
                if raises is not None:
                    raise raises
                return response

        return FakeClient()

    async def test_connect_error_is_wrapped(self, monkeypatch):
        client = self.stub_client(monkeypatch, raises=httpx.ConnectError("no route"))
        with pytest.raises(FMPError, match="Couldn't reach"):
            await fmp_client._get(client, "profile", symbol="AAPL")

    async def test_timeout_is_wrapped(self, monkeypatch):
        client = self.stub_client(monkeypatch, raises=httpx.ReadTimeout("slow"))
        with pytest.raises(FMPError, match="Couldn't reach"):
            await fmp_client._get(client, "profile", symbol="AAPL")

    async def test_proxy_error_is_wrapped(self, monkeypatch):
        client = self.stub_client(monkeypatch, raises=httpx.ProxyError("403 Forbidden"))
        with pytest.raises(FMPError, match="Couldn't reach"):
            await fmp_client._get(client, "profile", symbol="AAPL")

    async def test_server_error_status_is_wrapped(self, monkeypatch):
        request = httpx.Request("GET", "https://financialmodelingprep.com/stable/profile")
        response = httpx.Response(500, request=request, text="boom")
        client = self.stub_client(monkeypatch, response=response)

        with pytest.raises(FMPError, match="returned 500"):
            await fmp_client._get(client, "profile", symbol="AAPL")

    async def test_malformed_body_is_wrapped(self, monkeypatch):
        request = httpx.Request("GET", "https://financialmodelingprep.com/stable/profile")
        response = httpx.Response(200, request=request, text="<html>not json</html>")
        client = self.stub_client(monkeypatch, response=response)

        with pytest.raises(FMPError, match="malformed"):
            await fmp_client._get(client, "profile", symbol="AAPL")

    async def test_rate_limit_keeps_its_specific_message(self, monkeypatch):
        request = httpx.Request("GET", "https://financialmodelingprep.com/stable/profile")
        response = httpx.Response(429, request=request, text="slow down")
        client = self.stub_client(monkeypatch, response=response)

        with pytest.raises(FMPError, match="rate limit"):
            await fmp_client._get(client, "profile", symbol="AAPL")

    async def test_bad_key_keeps_its_specific_message(self, monkeypatch):
        request = httpx.Request("GET", "https://financialmodelingprep.com/stable/profile")
        response = httpx.Response(401, request=request, text="denied")
        client = self.stub_client(monkeypatch, response=response)

        with pytest.raises(FMPError, match="key is missing or invalid"):
            await fmp_client._get(client, "profile", symbol="AAPL")

PROFILE = {
    "symbol": "AAPL",
    "companyName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "price": 309.9,
    "marketCap": 4551611624400,
    "beta": 1.086,
}
RATIOS = {
    "priceToEarningsRatioTTM": 35.37,
    "priceToEarningsGrowthRatioTTM": 1.08,
    "priceToBookRatioTTM": 42.34,
    "priceToSalesRatioTTM": 9.75,
    "debtToEquityRatioTTM": 0.784,
    "currentRatioTTM": 1.003,
    "netProfitMarginTTM": 0.276,
    "operatingProfitMarginTTM": 0.331,
    "dividendYieldTTM": 0.0034,
}
KEY_METRICS = {"evToEBITDATTM": 27.28, "returnOnEquityTTM": 1.371}
GROWTH = {"growthRevenue": 0.064, "growthEPS": 0.2258}


def patch_get(monkeypatch, handler):
    monkeypatch.setattr(fmp_client, "_get", handler)


class TestFetchFundamentals:
    async def test_maps_every_field_from_stable_api(self, monkeypatch):
        async def handler(client, path, **params):
            return {
                "profile": [PROFILE],
                "ratios-ttm": [RATIOS],
                "key-metrics-ttm": [KEY_METRICS],
                "income-statement-growth": [GROWTH],
            }[path]

        patch_get(monkeypatch, handler)
        result = await fmp_client.fetch_fundamentals("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["companyName"] == "Apple Inc."
        assert result["marketCap"] == 4551611624400
        assert result["peRatio"] == 35.37
        assert result["evToEbitda"] == 27.28
        assert result["debtToEquity"] == 0.784
        assert result["returnOnEquity"] == 1.371
        assert result["revenueGrowth"] == 0.064
        assert result["epsGrowth"] == 0.2258
        # Every declared field should resolve; a silent None means a rename slipped through.
        assert None not in result.values()

    async def test_unknown_ticker_raises(self, monkeypatch):
        async def handler(client, path, **params):
            return []

        patch_get(monkeypatch, handler)
        with pytest.raises(FMPError, match="No data found"):
            await fmp_client.fetch_fundamentals("NOPE")

    async def test_missing_key_raises_before_any_request(self, monkeypatch):
        monkeypatch.setattr(fmp_client.settings, "fmp_api_key", "")
        with pytest.raises(FMPError, match="FMP_API_KEY is not set"):
            await fmp_client.fetch_fundamentals("AAPL")


class TestSearchSymbols:
    SYMBOL_HIT = [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}]
    NAME_HITS = [
        {"symbol": "APLE", "name": "Apple Hospitality REIT", "exchange": "NYSE"},
        {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
        {"symbol": "AAPL.NE", "name": "Apple Inc CDR", "exchange": "NEO"},
    ]

    def handler(self):
        async def h(client, path, **params):
            return self.SYMBOL_HIT if path == "search-symbol" else self.NAME_HITS

        return h

    async def test_company_name_finds_ticker(self, monkeypatch):
        patch_get(monkeypatch, self.handler())
        results = await fmp_client.search_symbols("apple")
        assert results[0]["symbol"] == "AAPL"

    async def test_exact_ticker_ranks_first(self, monkeypatch):
        patch_get(monkeypatch, self.handler())
        results = await fmp_client.search_symbols("AAPL")
        assert results[0]["symbol"] == "AAPL"

    async def test_results_are_deduplicated(self, monkeypatch):
        patch_get(monkeypatch, self.handler())
        symbols = [r["symbol"] for r in await fmp_client.search_symbols("apple")]
        assert len(symbols) == len(set(symbols))

    async def test_one_endpoint_failing_still_returns_results(self, monkeypatch):
        async def half_broken(client, path, **params):
            if path == "search-symbol":
                raise FMPError("upstream down")
            return self.NAME_HITS

        patch_get(monkeypatch, half_broken)
        results = await fmp_client.search_symbols("apple")
        assert [r["symbol"] for r in results][0] == "AAPL"

    async def test_blank_query_short_circuits(self, monkeypatch):
        async def explode(client, path, **params):
            raise AssertionError("should not call the API for a blank query")

        patch_get(monkeypatch, explode)
        assert await fmp_client.search_symbols("   ") == []


class TestFetchHistory:
    async def test_parses_bare_list_and_sorts_oldest_first(self, monkeypatch):
        async def handler(client, path, **params):
            return [
                {"date": "2026-08-25", "price": 310.0},
                {"date": "2026-08-22", "price": 305.5},
            ]

        patch_get(monkeypatch, handler)
        points = await fmp_client.fetch_history("AAPL", "1M")
        assert [p["date"] for p in points] == ["2026-08-22", "2026-08-25"]
        assert points[0]["close"] == 305.5

    async def test_parses_nested_historical_shape(self, monkeypatch):
        async def handler(client, path, **params):
            return {"symbol": "AAPL", "historical": [{"date": "2026-08-25", "close": 310.0}]}

        patch_get(monkeypatch, handler)
        points = await fmp_client.fetch_history("AAPL", "1M")
        assert points == [{"date": "2026-08-25", "close": 310.0}]

    async def test_rows_without_usable_values_are_dropped(self, monkeypatch):
        async def handler(client, path, **params):
            return [
                {"date": "2026-08-25", "close": 310.0},
                {"date": "2026-08-24", "close": None},
                {"date": None, "close": 300.0},
                "not-a-dict",
            ]

        patch_get(monkeypatch, handler)
        points = await fmp_client.fetch_history("AAPL", "1M")
        assert points == [{"date": "2026-08-25", "close": 310.0}]

    async def test_unknown_range_falls_back_to_a_year(self, monkeypatch):
        captured = {}

        async def handler(client, path, **params):
            captured.update(params)
            return []

        patch_get(monkeypatch, handler)
        await fmp_client.fetch_history("AAPL", "banana")
        assert "from" in captured and "to" in captured


class TestFetchQuotes:
    QUOTE = [
        {
            "symbol": "^GSPC",
            "name": "S&P 500",
            "price": 6500.1,
            "change": -12.4,
            "changePercentage": -0.19,
            "yearHigh": 6700,
        }
    ]

    async def test_maps_change_percent_spelling(self, monkeypatch):
        async def handler(client, path, **params):
            return self.QUOTE

        patch_get(monkeypatch, handler)
        quotes = await fmp_client.fetch_quotes(["^GSPC"])
        assert quotes[0]["changePercent"] == -0.19
        assert quotes[0]["price"] == 6500.1

    async def test_accepts_legacy_changes_percentage_spelling(self, monkeypatch):
        async def handler(client, path, **params):
            return [{"symbol": "X", "changesPercentage": 1.5, "changes": 2.0, "price": 10}]

        patch_get(monkeypatch, handler)
        quotes = await fmp_client.fetch_quotes(["X"])
        assert quotes[0]["changePercent"] == 1.5
        assert quotes[0]["change"] == 2.0

    async def test_one_bad_symbol_does_not_fail_the_batch(self, monkeypatch):
        async def handler(client, path, **params):
            if params.get("symbol") == "^BAD":
                raise FMPError("no such symbol")
            return self.QUOTE

        patch_get(monkeypatch, handler)
        quotes = await fmp_client.fetch_quotes(["^GSPC", "^BAD"])
        assert [q["symbol"] for q in quotes] == ["^GSPC"]

    async def test_empty_symbol_list_makes_no_request(self, monkeypatch):
        async def explode(client, path, **params):
            raise AssertionError("should not call the API with no symbols")

        patch_get(monkeypatch, explode)
        assert await fmp_client.fetch_quotes([]) == []


class TestQuotesAreBatched:
    """One request for a whole dashboard, not one per tile.

    The free allowance is 250 calls a day. Per-symbol fetching spent it in
    about seven page loads, which is the real reason the app kept running out
    of data rather than anything the reader was doing.
    """

    def calls(self, monkeypatch, responder):
        seen = []

        async def fake_get(client, path, **params):
            seen.append((path, params.get("symbol", "")))
            return responder(params.get("symbol", ""))

        monkeypatch.setattr(fmp_client, "_get", fake_get)
        monkeypatch.setattr(fmp_client.settings, "fmp_api_key", "k")
        return seen

    def row(self, symbol, price=100.0):
        return {"symbol": symbol, "price": price, "change": 1.0, "changePercentage": 1.0}

    def test_a_whole_board_costs_one_request(self, monkeypatch):
        symbols = ["XLK", "XLY", "XLC", "XLV", "XLP", "XLU", "XLF", "XLI", "XLE"]
        seen = self.calls(
            monkeypatch, lambda asked: [self.row(s) for s in asked.split(",")]
        )
        quotes = asyncio.run(fmp_client.fetch_quotes(symbols))

        assert len(seen) == 1
        assert [q["symbol"] for q in quotes] == symbols

    def test_symbols_the_batch_missed_are_asked_for_individually(self, monkeypatch):
        def responder(asked):
            # A service that quietly answers only the first of a list.
            first = asked.split(",")[0]
            return [self.row(first)]

        seen = self.calls(monkeypatch, responder)
        quotes = asyncio.run(fmp_client.fetch_quotes(["AAPL", "MSFT"]))

        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]
        # The batch, then one for what it left out.
        assert len(seen) == 2

    def test_a_refused_batch_falls_back_to_the_old_behaviour(self, monkeypatch):
        def responder(asked):
            if "," in asked:
                raise FMPError("Market data service returned 400")
            return [self.row(asked)]

        seen = self.calls(monkeypatch, responder)
        quotes = asyncio.run(fmp_client.fetch_quotes(["AAPL", "MSFT"]))

        # Same result as before batching existed, for one extra call.
        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]
        assert len(seen) == 3

    def test_a_long_watchlist_splits_rather_than_making_one_huge_url(self, monkeypatch):
        symbols = [f"SYM{i}" for i in range(45)]
        seen = self.calls(
            monkeypatch, lambda asked: [self.row(s) for s in asked.split(",")]
        )
        asyncio.run(fmp_client.fetch_quotes(symbols))
        assert len(seen) == 3

    def test_duplicates_are_asked_for_once(self, monkeypatch):
        seen = self.calls(
            monkeypatch, lambda asked: [self.row(s) for s in asked.split(",")]
        )
        quotes = asyncio.run(fmp_client.fetch_quotes(["AAPL", "aapl", "AAPL"]))
        assert len(quotes) == 1
        assert seen[0][1] == "AAPL"

    def test_a_symbol_nobody_has_is_left_out_rather_than_faked(self, monkeypatch):
        self.calls(monkeypatch, lambda asked: [])
        assert asyncio.run(fmp_client.fetch_quotes(["NOPE"])) == []
