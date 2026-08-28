"""Remembering which providers are out of quota.

The behaviour worth protecting: an exhausted provider is asked once, not once
per ticker; a provider that recovers is used again; and one flaky response
never benches a working provider.
"""

import pytest

from fastapi.testclient import TestClient

from app import fmp_client, market_data, provider_health, yahoo_client
from app.main import app
from app.config import settings
from app.fmp_client import FMPError
from app.yahoo_client import YahooError


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def order(monkeypatch):
    def _set(value):
        monkeypatch.setattr(settings, "provider_order", value)
    return _set


def counting(monkeypatch, provider, name, error=None, returns=None):
    """Stub a provider method and count how often it is actually called."""
    calls = []

    async def _call(*args, **kwargs):
        calls.append(args)
        if error:
            raise error
        return returns

    monkeypatch.setattr(provider, name, _call)
    return calls


class TestClassifying:
    @pytest.mark.parametrize(
        "message",
        [
            "FMP API rate limit reached (free tier: 250 calls/day)",
            "Yahoo Finance is rate limiting this address",
            "429 Too Many Requests",
            "You have exceeded your daily quota",
        ],
    )
    def test_a_quota_refusal_is_recognised(self, message):
        assert provider_health.looks_rate_limited(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "Couldn't reach the market data service: timeout",
            "Market data service returned 500",
            "No data found for ticker 'ZZZZ'",
            "",
        ],
    )
    def test_an_ordinary_failure_is_not(self, message):
        """A blip must not bench a working provider."""
        assert provider_health.looks_rate_limited(message) is False

    def test_a_daily_limit_earns_a_long_cooldown(self):
        """Nothing is learned by asking again a minute later."""
        daily = provider_health.cooldown_for("rate limit reached (250 calls/day)")
        burst = provider_health.cooldown_for("429 too many requests")
        assert daily > burst

    def test_a_burst_limit_recovers_quickly(self):
        assert provider_health.cooldown_for("429 too many requests") <= 120


class TestBenching:
    def test_a_provider_starts_available(self):
        assert provider_health.is_available("yahoo") is True

    def test_a_quota_refusal_benches_it(self):
        provider_health.record_failure("fmp", "rate limit reached (250 calls/day)")
        assert provider_health.is_available("fmp") is False

    def test_an_ordinary_failure_does_not(self):
        provider_health.record_failure("fmp", "Market data service returned 500")
        assert provider_health.is_available("fmp") is True

    def test_the_cooldown_expires(self, monkeypatch):
        provider_health.record_failure("fmp", "429 too many requests")
        assert provider_health.is_available("fmp") is False

        later = provider_health._now() + provider_health.BURST_COOLDOWN_SECONDS + 1
        monkeypatch.setattr(provider_health, "_now", lambda: later)
        assert provider_health.is_available("fmp") is True

    def test_a_success_clears_a_bench_early(self):
        """However it happened, a provider that answers is working."""
        provider_health.record_failure("fmp", "rate limit reached (250 calls/day)")
        provider_health.record_success("fmp")
        assert provider_health.is_available("fmp") is True

    def test_providers_are_tracked_separately(self):
        provider_health.record_failure("fmp", "rate limit reached (250 calls/day)")
        assert provider_health.is_available("yahoo") is True


class TestTheChainUsesIt:
    async def test_an_exhausted_provider_is_asked_once_not_once_per_lookup(
        self, monkeypatch, order
    ):
        """The point of the whole module: fifty tickers, one wasted request."""
        order("yahoo,fmp")
        yahoo_calls = counting(
            monkeypatch, yahoo_client, "fetch_quotes",
            error=YahooError("Yahoo Finance is rate limiting this address"),
        )
        counting(monkeypatch, fmp_client, "fetch_quotes", returns=[{"symbol": "AAPL"}])

        for _ in range(5):
            await market_data.fetch_quotes(["AAPL"])

        assert len(yahoo_calls) == 1

    async def test_the_next_provider_serves_the_request(self, monkeypatch, order):
        order("yahoo,fmp")
        counting(monkeypatch, yahoo_client, "fetch_quotes",
                 error=YahooError("rate limit reached (250 calls/day)"))
        counting(monkeypatch, fmp_client, "fetch_quotes", returns=[{"symbol": "AAPL"}])

        assert await market_data.fetch_quotes(["AAPL"]) == [{"symbol": "AAPL"}]
        assert await market_data.fetch_quotes(["MSFT"]) == [{"symbol": "AAPL"}]

    async def test_a_benched_provider_is_used_again_once_it_recovers(
        self, monkeypatch, order
    ):
        order("yahoo,fmp")
        yahoo_calls = counting(monkeypatch, yahoo_client, "fetch_quotes",
                               error=YahooError("429 too many requests"))
        counting(monkeypatch, fmp_client, "fetch_quotes", returns=[{"symbol": "X"}])
        await market_data.fetch_quotes(["AAPL"])

        later = provider_health._now() + provider_health.BURST_COOLDOWN_SECONDS + 1
        monkeypatch.setattr(provider_health, "_now", lambda: later)
        counting(monkeypatch, yahoo_client, "fetch_quotes", returns=[{"symbol": "BACK"}])

        assert await market_data.fetch_quotes(["AAPL"]) == [{"symbol": "BACK"}]
        assert len(yahoo_calls) == 1

    async def test_a_blip_does_not_take_a_provider_out_of_rotation(
        self, monkeypatch, order
    ):
        """One 500 is not a quota problem, and benching on it would be wrong."""
        order("yahoo,fmp")
        yahoo_calls = counting(monkeypatch, yahoo_client, "fetch_quotes",
                               error=YahooError("Yahoo Finance returned 500"))
        counting(monkeypatch, fmp_client, "fetch_quotes", returns=[{"symbol": "X"}])

        await market_data.fetch_quotes(["AAPL"])
        await market_data.fetch_quotes(["MSFT"])

        assert len(yahoo_calls) == 2

    async def test_everything_benched_says_so_rather_than_looking_empty(
        self, monkeypatch, order
    ):
        order("yahoo,fmp")
        counting(monkeypatch, yahoo_client, "fetch_quotes",
                 error=YahooError("rate limit reached (250 calls/day)"))
        counting(monkeypatch, fmp_client, "fetch_quotes",
                 error=FMPError("rate limit reached (250 calls/day)"))

        # The first call reports whichever provider failed last; by the second
        # both are benched, so nothing runs and the message has to explain
        # that rather than looking like "no such ticker".
        with pytest.raises(FMPError):
            await market_data.fetch_quotes(["AAPL"])

        with pytest.raises(FMPError, match="Every data provider is currently rate limited"):
            await market_data.fetch_quotes(["MSFT"])

    async def test_a_genuine_empty_result_is_still_empty(self, monkeypatch, order):
        """A provider that ran and had nothing is not a rate limit."""
        order("yahoo,fmp")
        counting(monkeypatch, yahoo_client, "fetch_quotes", returns=[])
        counting(monkeypatch, fmp_client, "fetch_quotes", returns=[])

        assert await market_data.fetch_quotes(["ZZZZ"]) == []


class TestSnapshot:
    def test_it_reports_what_is_available(self):
        provider_health.record_failure("fmp", "rate limit reached (250 calls/day)")
        provider_health.record_success("yahoo")

        by_name = {p["name"]: p for p in provider_health.snapshot(["yahoo", "fmp"])}

        assert by_name["yahoo"]["available"] is True
        assert by_name["fmp"]["available"] is False
        assert by_name["fmp"]["cooldown_seconds"] > 0
        assert "250 calls/day" in by_name["fmp"]["reason"]


class TestProviderWordings:
    """Each provider phrases a quota refusal differently, and one that is not
    recognised gets retried on every lookup -- the exact waste this prevents."""

    @pytest.mark.parametrize(
        "message",
        [
            # FMP
            "FMP API rate limit reached (free tier: 250 calls/day)",
            # Yahoo
            "Yahoo Finance is rate limiting this address",
            # Stooq, which answers 200 with plain text
            "Stooq daily request limit exceeded",
            # Common HTTP wordings
            "429 Too Many Requests",
            "You have exceeded your daily quota",
            "API rate limit exceeded for this key",
        ],
    )
    def test_every_provider_phrasing_is_recognised(self, message):
        assert provider_health.looks_rate_limited(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "Couldn't reach Stooq: timeout",
            "Stooq returned 500",
            "Stooq has no history for 'ZZZZ'",
            "No data found for ticker 'ZZZZ'",
        ],
    )
    def test_ordinary_failures_still_are_not(self, message):
        assert provider_health.looks_rate_limited(message) is False


class TestStatusEndpoint:
    """"Why is the table empty?" should have an answer that isn't the logs."""

    def test_it_lists_every_provider(self, client):
        body = client.get("/api/market/providers").json()
        names = {p["name"] for p in body["providers"]}
        assert {"yahoo", "fmp", "stooq", "finnhub", "alphavantage"} <= names

    def test_a_missing_key_reads_differently_from_a_spent_quota(
        self, client, monkeypatch
    ):
        """From outside they look identical, and the fixes are different."""
        monkeypatch.setattr(settings, "finnhub_api_key", "")
        monkeypatch.setattr(settings, "fmp_api_key", "set")
        provider_health.record_failure(
            "fmp", "FMP API rate limit reached (free tier: 250 calls/day)"
        )

        by_name = {p["name"]: p for p in client.get("/api/market/providers").json()["providers"]}

        assert by_name["finnhub"]["configured"] is False
        assert by_name["fmp"]["configured"] is True
        assert by_name["fmp"]["available"] is False

    def test_it_says_how_long_a_bench_lasts(self, client):
        provider_health.record_failure("fmp", "rate limit reached (250 calls/day)")
        by_name = {p["name"]: p for p in client.get("/api/market/providers").json()["providers"]}

        assert by_name["fmp"]["cooldown_seconds"] > 0
        assert "250 calls/day" in by_name["fmp"]["reason"]

    def test_it_counts_what_can_actually_serve_a_request(self, client, monkeypatch):
        monkeypatch.setattr(settings, "finnhub_api_key", "")
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "")
        monkeypatch.setattr(settings, "fmp_api_key", "set")

        # yahoo, fmp and stooq are usable; the two unkeyed ones are not.
        assert client.get("/api/market/providers").json()["healthy"] == 3

    def test_it_shows_which_serve_fundamentals(self, client):
        by_name = {p["name"]: p for p in client.get("/api/market/providers").json()["providers"]}

        assert by_name["fmp"]["serves_fundamentals"] is True
        assert by_name["yahoo"]["serves_fundamentals"] is False


class TestConfiguredDetection:
    def test_a_keyless_provider_is_always_configured(self):
        assert market_data.is_configured("yahoo") is True
        assert market_data.is_configured("stooq") is True

    def test_a_keyed_provider_needs_its_key(self, monkeypatch):
        monkeypatch.setattr(settings, "finnhub_api_key", "")
        assert market_data.is_configured("finnhub") is False

        monkeypatch.setattr(settings, "finnhub_api_key", "fh_test")
        assert market_data.is_configured("finnhub") is True
