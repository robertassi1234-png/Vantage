"""Twelve Data's responses.

Not reachable from here, so its formats are pinned as fixtures. The one that
matters most is that a refusal arrives as HTTP 200 with the failure in the
body -- read the status code alone and a spent allowance looks like a company
with no data, which is exactly the confusion this provider exists to avoid.
"""

import httpx
import pytest

from app import market_data, provider_health, twelvedata_client, yahoo_client
from app.config import settings
from app.twelvedata_client import TwelveDataError
from app.yahoo_client import YahooError

QUOTE_BATCH = {
    "AAPL": {
        "symbol": "AAPL",
        "name": "Apple Inc",
        "close": "268.40",
        "previous_close": "265.10",
        "change": "3.30",
        "percent_change": "1.24",
        "high": "269.40",
        "low": "264.80",
        "volume": "41234567",
        "fifty_two_week": {"low": "164.08", "high": "290.10"},
    },
    "MSFT": {
        "symbol": "MSFT",
        "name": "Microsoft Corp",
        "close": "512.75",
        "change": "-2.10",
        "percent_change": "-0.41",
        "high": "515.20",
        "low": "508.10",
        "volume": "18234567",
        "fifty_two_week": {"low": "380.00", "high": "530.00"},
    },
}

TIME_SERIES = {
    "meta": {"symbol": "AAPL", "interval": "1day"},
    "values": [
        {"datetime": "2026-08-27", "close": "268.40"},
        {"datetime": "2026-08-26", "close": "267.30"},
        {"datetime": "2026-08-25", "close": "265.10"},
    ],
    "status": "ok",
}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(settings, "twelve_data_api_key", "td_test")


def serve(monkeypatch, payload, status=200):
    async def _get(self, url, params=None, **kwargs):
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)


class TestQuotes:
    async def test_it_reads_a_batch(self, monkeypatch):
        serve(monkeypatch, QUOTE_BATCH)
        quotes = await twelvedata_client.fetch_quotes(["AAPL", "MSFT"])

        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]
        assert quotes[0]["price"] == 268.40
        assert quotes[0]["name"] == "Apple Inc"

    async def test_a_single_symbol_comes_back_bare(self, monkeypatch):
        """One symbol returns the object itself, not a map keyed by symbol."""
        serve(monkeypatch, QUOTE_BATCH["AAPL"])
        [quote] = await twelvedata_client.fetch_quotes(["AAPL"])
        assert quote["symbol"] == "AAPL"

    async def test_it_carries_the_52_week_range(self, monkeypatch):
        """The watchlist draws a position marker from these."""
        serve(monkeypatch, QUOTE_BATCH)
        [apple, _] = await twelvedata_client.fetch_quotes(["AAPL", "MSFT"])

        assert apple["yearLow"] == 164.08
        assert apple["yearHigh"] == 290.10

    async def test_numbers_arrive_as_strings_and_are_parsed(self, monkeypatch):
        serve(monkeypatch, QUOTE_BATCH)
        [apple, _] = await twelvedata_client.fetch_quotes(["AAPL", "MSFT"])
        assert apple["changePercent"] == 1.24

    async def test_one_bad_symbol_does_not_lose_the_batch(self, monkeypatch):
        serve(monkeypatch, {
            "AAPL": QUOTE_BATCH["AAPL"],
            "ZZZZ": {"status": "error", "message": "symbol not found"},
        })
        quotes = await twelvedata_client.fetch_quotes(["AAPL", "ZZZZ"])
        assert [q["symbol"] for q in quotes] == ["AAPL"]

    async def test_index_symbols_are_translated_both_ways(self, monkeypatch):
        """Yahoo writes ^GSPC; Twelve Data writes SPX."""
        serve(monkeypatch, {"SPX": {**QUOTE_BATCH["AAPL"], "symbol": "SPX"}})
        [quote] = await twelvedata_client.fetch_quotes(["^GSPC"])
        assert quote["symbol"] == "^GSPC"

    async def test_an_empty_request_makes_no_call(self, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("should not call the API for nothing")

        monkeypatch.setattr(httpx.AsyncClient, "get", explode)
        assert await twelvedata_client.fetch_quotes([]) == []


class TestHistory:
    async def test_it_returns_oldest_first(self, monkeypatch):
        """It sends newest first; every chart in the app reads the other way."""
        serve(monkeypatch, TIME_SERIES)
        points = await twelvedata_client.fetch_history("AAPL", "1M")

        assert points[0]["date"] == "2026-08-25"
        assert points[-1]["close"] == 268.40

    async def test_an_empty_series_is_an_error_not_a_blank_chart(self, monkeypatch):
        serve(monkeypatch, {"values": [], "status": "ok"})
        with pytest.raises(TwelveDataError):
            await twelvedata_client.fetch_history("ZZZZ", "1Y")


class TestRefusalsArriveAsSuccess:
    async def test_a_spent_allowance_is_an_error(self, monkeypatch):
        serve(monkeypatch, {
            "code": 429,
            "message": "You have run out of API credits for the current minute",
            "status": "error",
        })
        with pytest.raises(TwelveDataError) as excinfo:
            await twelvedata_client.fetch_quotes(["AAPL"])

        assert "rate limit" in str(excinfo.value).lower()

    async def test_a_spent_allowance_benches_the_provider(self, monkeypatch):
        """Worded so the health tracker recognises it; otherwise it is retried
        on every lookup, which is the waste the tracker exists to prevent."""
        serve(monkeypatch, {"code": 429, "message": "run out of API credits", "status": "error"})
        with pytest.raises(TwelveDataError) as excinfo:
            await twelvedata_client.fetch_quotes(["AAPL"])

        assert provider_health.looks_rate_limited(str(excinfo.value))

    async def test_a_bad_key_is_reported(self, monkeypatch):
        serve(monkeypatch, {"code": 401, "message": "Invalid API key", "status": "error"})
        with pytest.raises(TwelveDataError, match="Invalid API key"):
            await twelvedata_client.fetch_quotes(["AAPL"])

    async def test_a_missing_key_never_reaches_the_network(self, monkeypatch):
        monkeypatch.setattr(settings, "twelve_data_api_key", "")

        def explode(*a, **k):
            raise AssertionError("should not call without a key")

        monkeypatch.setattr(httpx.AsyncClient, "get", explode)
        with pytest.raises(TwelveDataError, match="not set"):
            await twelvedata_client.fetch_quotes(["AAPL"])

    async def test_a_transport_failure_becomes_a_provider_error(self, monkeypatch):
        async def boom(self, url, params=None, **kwargs):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx.AsyncClient, "get", boom)
        with pytest.raises(TwelveDataError):
            await twelvedata_client.fetch_quotes(["AAPL"])


class TestInTheChain:
    async def test_it_serves_when_the_keyless_providers_are_blocked(self, monkeypatch):
        """The situation it was added for: shared hosting whose address Yahoo
        throttles and Stooq refuses outright."""
        monkeypatch.setattr(settings, "provider_order", "yahoo,fmp,stooq")
        monkeypatch.setattr(settings, "finnhub_api_key", "")
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "")

        async def yahoo_blocked(symbols):
            raise YahooError("Yahoo Finance is rate limiting this address")

        monkeypatch.setattr(yahoo_client, "fetch_quotes", yahoo_blocked)
        serve(monkeypatch, QUOTE_BATCH)

        quotes = await market_data.fetch_quotes(["AAPL", "MSFT"])
        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]

    async def test_a_key_alone_is_enough_to_get_the_fallback(self, monkeypatch):
        """Adding a key should not also require editing PROVIDER_ORDER."""
        monkeypatch.setattr(settings, "provider_order", "yahoo")
        assert "twelvedata" in market_data._order()


class TestShapeDetection:
    """The response shape is read off the payload, not off how many symbols
    were asked for, so a version that keys a single-symbol reply still works."""

    async def test_a_keyed_single_symbol_reply_is_read(self, monkeypatch):
        serve(monkeypatch, {"AAPL": QUOTE_BATCH["AAPL"]})
        [quote] = await twelvedata_client.fetch_quotes(["AAPL"])
        assert quote["price"] == 268.40

    async def test_a_bare_single_symbol_reply_is_read(self, monkeypatch):
        serve(monkeypatch, QUOTE_BATCH["AAPL"])
        [quote] = await twelvedata_client.fetch_quotes(["AAPL"])
        assert quote["price"] == 268.40

    async def test_a_reply_with_nothing_usable_is_empty_not_a_crash(self, monkeypatch):
        serve(monkeypatch, {"AAPL": {"symbol": "AAPL"}})
        assert await twelvedata_client.fetch_quotes(["AAPL"]) == []
