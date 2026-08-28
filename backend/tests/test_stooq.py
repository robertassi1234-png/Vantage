"""Stooq's CSV responses.

Nothing here can reach Stooq, so its formats are pinned as fixtures: real
column layouts, its "N/D" placeholder for missing values, and the plain-text
notice it returns instead of a status code when a limit is hit.
"""

import httpx
import pytest

from app import market_data, stooq_client
from app.config import settings
from app.stooq_client import StooqError

QUOTE_CSV = (
    "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
    "AAPL.US,2026-08-27,22:00:04,265.10,269.40,264.80,268.40,41234567\n"
    "MSFT.US,2026-08-27,22:00:04,510.00,515.20,508.10,512.75,18234567\n"
)

HISTORY_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-08-25,262.00,266.00,261.50,265.10,30000000\n"
    "2026-08-26,265.20,268.00,264.00,267.30,31000000\n"
    "2026-08-27,267.50,269.40,264.80,268.40,41234567\n"
)


def serve(monkeypatch, text, status=200):
    """Answer any Stooq request with this body."""
    async def _get(self, url, params=None, **kwargs):
        return httpx.Response(status, text=text)

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)


class TestSymbols:
    def test_a_us_ticker_gets_the_market_suffix(self):
        assert stooq_client.to_stooq_symbol("AAPL") == "aapl.us"

    def test_the_indices_are_mapped_by_name(self):
        """Stooq uses its own index names, not Yahoo's."""
        assert stooq_client.to_stooq_symbol("^GSPC") == "^spx"
        assert stooq_client.to_stooq_symbol("^DJI") == "^dji"

    def test_an_unknown_index_is_refused_rather_than_guessed_at(self):
        with pytest.raises(StooqError):
            stooq_client.to_stooq_symbol("^VIX")

    def test_symbols_round_trip(self):
        for symbol in ("AAPL", "^GSPC", "^IXIC", "^RUT"):
            mapped = stooq_client.to_stooq_symbol(symbol)
            assert stooq_client.from_stooq_symbol(mapped) == symbol


class TestQuotes:
    async def test_it_reads_a_batch(self, monkeypatch):
        serve(monkeypatch, QUOTE_CSV)
        quotes = await stooq_client.fetch_quotes(["AAPL", "MSFT"])

        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]
        assert quotes[0]["price"] == 268.40

    async def test_it_computes_the_move(self, monkeypatch):
        serve(monkeypatch, QUOTE_CSV)
        [apple, _] = await stooq_client.fetch_quotes(["AAPL", "MSFT"])

        assert apple["change"] == pytest.approx(3.30)
        assert apple["changePercent"] == pytest.approx(3.30 / 265.10 * 100)

    async def test_it_reports_the_fields_it_does_not_have_as_missing(self, monkeypatch):
        """Better an honest null than a wrong number."""
        serve(monkeypatch, QUOTE_CSV)
        [apple, _] = await stooq_client.fetch_quotes(["AAPL", "MSFT"])

        assert apple["yearLow"] is None
        assert apple["yearHigh"] is None
        assert apple["marketCap"] is None

    async def test_a_missing_value_does_not_take_the_batch_down(self, monkeypatch):
        serve(
            monkeypatch,
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "AAPL.US,2026-08-27,22:00:04,N/D,N/D,N/D,N/D,N/D\n"
            "MSFT.US,2026-08-27,22:00:04,510.00,515.20,508.10,512.75,18234567\n",
        )
        quotes = await stooq_client.fetch_quotes(["AAPL", "MSFT"])

        assert [q["symbol"] for q in quotes] == ["MSFT"]

    async def test_an_open_of_zero_does_not_divide_by_zero(self, monkeypatch):
        serve(
            monkeypatch,
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "AAPL.US,2026-08-27,22:00:04,0,269.40,264.80,268.40,41234567\n",
        )
        [quote] = await stooq_client.fetch_quotes(["AAPL"])
        assert quote["changePercent"] is None

    async def test_an_empty_request_makes_no_call(self, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("should not call Stooq for nothing")

        monkeypatch.setattr(httpx.AsyncClient, "get", explode)
        assert await stooq_client.fetch_quotes([]) == []

    async def test_an_index_it_cannot_map_is_skipped_not_fatal(self, monkeypatch):
        serve(monkeypatch, QUOTE_CSV)
        quotes = await stooq_client.fetch_quotes(["^VIX", "AAPL", "MSFT"])
        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]


class TestHistory:
    async def test_it_reads_the_series_oldest_first(self, monkeypatch):
        serve(monkeypatch, HISTORY_CSV)
        points = await stooq_client.fetch_history("AAPL", "1M")

        assert points[0]["date"] == "2026-08-25"
        assert points[-1]["close"] == 268.40

    async def test_an_empty_series_is_an_error_not_a_blank_chart(self, monkeypatch):
        serve(monkeypatch, "Date,Open,High,Low,Close,Volume\n")
        with pytest.raises(StooqError):
            await stooq_client.fetch_history("ZZZZ", "1Y")


class TestFailures:
    async def test_the_over_limit_notice_is_recognised(self, monkeypatch):
        """Stooq answers 200 with plain text, so the body has to be read."""
        serve(monkeypatch, "Exceeded the daily hits limit")
        with pytest.raises(StooqError, match="limit exceeded"):
            await stooq_client.fetch_quotes(["AAPL"])

    async def test_that_notice_benches_the_provider(self, monkeypatch):
        """It has to read as a rate limit, or the cooldown never applies."""
        from app import provider_health

        serve(monkeypatch, "Exceeded the daily hits limit")
        try:
            await stooq_client.fetch_quotes(["AAPL"])
        except StooqError as e:
            assert provider_health.looks_rate_limited(str(e))

    async def test_a_429_is_reported(self, monkeypatch):
        serve(monkeypatch, "", status=429)
        with pytest.raises(StooqError, match="rate limiting"):
            await stooq_client.fetch_quotes(["AAPL"])

    async def test_a_transport_failure_becomes_a_provider_error(self, monkeypatch):
        async def boom(self, url, params=None, **kwargs):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx.AsyncClient, "get", boom)
        with pytest.raises(StooqError):
            await stooq_client.fetch_quotes(["AAPL"])


class TestInTheChain:
    async def test_stooq_serves_when_the_others_are_spent(self, monkeypatch):
        """The whole point: a working watchlist instead of an empty one."""
        from app import fmp_client, yahoo_client
        from app.fmp_client import FMPError
        from app.yahoo_client import YahooError

        monkeypatch.setattr(settings, "provider_order", "yahoo,fmp,stooq")

        async def yahoo_down(symbols):
            raise YahooError("Yahoo Finance is rate limiting this address")

        async def fmp_down(symbols):
            raise FMPError("FMP API rate limit reached (free tier: 250 calls/day)")

        monkeypatch.setattr(yahoo_client, "fetch_quotes", yahoo_down)
        monkeypatch.setattr(fmp_client, "fetch_quotes", fmp_down)
        serve(monkeypatch, QUOTE_CSV)

        quotes = await market_data.fetch_quotes(["AAPL", "MSFT"])
        assert [q["symbol"] for q in quotes] == ["AAPL", "MSFT"]

    async def test_it_is_only_reached_last(self, monkeypatch):
        """Its data is coarser, so a working provider is always preferred."""
        from app import yahoo_client

        monkeypatch.setattr(settings, "provider_order", "yahoo,fmp,stooq")

        async def yahoo_up(symbols):
            return [{"symbol": "AAPL", "name": "Apple Inc.", "price": 268.4}]

        monkeypatch.setattr(yahoo_client, "fetch_quotes", yahoo_up)

        def explode(*a, **k):
            raise AssertionError("Stooq must not be called while Yahoo works")

        monkeypatch.setattr(httpx.AsyncClient, "get", explode)
        [quote] = await market_data.fetch_quotes(["AAPL"])
        assert quote["name"] == "Apple Inc."
