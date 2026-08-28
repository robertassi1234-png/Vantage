"""Fundamentals falling through to another provider.

This is the path that actually ran out: fundamentals were FMP-only, four calls
a ticker against a 250-a-day allowance, so the comparison table simply stopped
working partway through a session. Neither new provider is reachable from
here, so their response shapes are pinned as fixtures.
"""

import httpx
import pytest

from app import (
    alphavantage_client,
    finnhub_client,
    fmp_client,
    market_data,
    provider_health,
)
from app.alphavantage_client import AlphaVantageError
from app.config import settings
from app.finnhub_client import FinnhubError
from app.fmp_client import FMPError

FINNHUB_PROFILE = {
    "name": "Apple Inc",
    "finnhubIndustry": "Technology",
    "marketCapitalization": 4_100_000,  # millions
}

FINNHUB_METRICS = {
    "metric": {
        "peTTM": 34.2,
        "pegTTM": 2.1,
        "psTTM": 9.4,
        "pbQuarterly": 58.3,
        "beta": 1.24,
        "netProfitMarginTTM": 26.4,
        "operatingMarginTTM": 31.8,
        "roeTTM": 147.2,
        "revenueGrowthTTMYoy": 6.1,
        "epsGrowthTTMYoy": 9.7,
        "totalDebt/totalEquityQuarterly": 1.45,
        "currentRatioQuarterly": 0.87,
        "dividendYieldIndicatedAnnual": 0.44,
    }
}

ALPHA_OVERVIEW = {
    "Symbol": "AAPL",
    "Name": "Apple Inc",
    "Sector": "TECHNOLOGY",
    "Industry": "ELECTRONIC COMPUTERS",
    "MarketCapitalization": "4100000000000",
    "PERatio": "34.2",
    "PEGRatio": "2.1",
    "EVToEBITDA": "25.4",
    "PriceToBookRatio": "58.3",
    "PriceToSalesRatioTTM": "9.4",
    "Beta": "1.24",
    "ProfitMargin": "0.264",
    "OperatingMarginTTM": "0.318",
    "ReturnOnEquityTTM": "1.472",
    "QuarterlyRevenueGrowthYOY": "0.061",
    "QuarterlyEarningsGrowthYOY": "0.097",
    "DividendYield": "0.0044",
}


def serve_json(monkeypatch, payload, status=200):
    async def _get(self, url, params=None, **kwargs):
        body = payload(url, params) if callable(payload) else payload
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "fh_test")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "av_test")


class TestFinnhubShape:
    async def test_it_maps_into_the_tables_fields(self, monkeypatch, keys):
        serve_json(
            monkeypatch,
            lambda url, params: FINNHUB_METRICS if "metric" in url else FINNHUB_PROFILE,
        )
        row = await finnhub_client.fetch_fundamentals("AAPL")

        assert row["ticker"] == "AAPL"
        assert row["companyName"] == "Apple Inc"
        assert row["peRatio"] == 34.2

    async def test_market_cap_is_converted_from_millions(self, monkeypatch, keys):
        """Finnhub reports it in millions; the table formats raw dollars."""
        serve_json(
            monkeypatch,
            lambda url, params: FINNHUB_METRICS if "metric" in url else FINNHUB_PROFILE,
        )
        row = await finnhub_client.fetch_fundamentals("AAPL")
        assert row["marketCap"] == 4_100_000 * 1_000_000

    async def test_percentages_become_fractions(self, monkeypatch, keys):
        """Finnhub says 26.4 for a 26.4% margin; the app stores 0.264."""
        serve_json(
            monkeypatch,
            lambda url, params: FINNHUB_METRICS if "metric" in url else FINNHUB_PROFILE,
        )
        row = await finnhub_client.fetch_fundamentals("AAPL")

        assert row["netProfitMargin"] == pytest.approx(0.264)
        assert row["returnOnEquity"] == pytest.approx(1.472)

    async def test_a_field_it_lacks_is_none_not_a_guess(self, monkeypatch, keys):
        """A partial row beats no row; the table renders a dash for a gap."""
        serve_json(
            monkeypatch,
            lambda url, params: {"metric": {"peTTM": 34.2}} if "metric" in url
            else FINNHUB_PROFILE,
        )
        row = await finnhub_client.fetch_fundamentals("AAPL")

        assert row["peRatio"] == 34.2
        assert row["evToEbitda"] is None
        assert row["currentRatio"] is None

    async def test_a_missing_key_is_reported(self, monkeypatch):
        monkeypatch.setattr(settings, "finnhub_api_key", "")
        with pytest.raises(FinnhubError, match="not set"):
            await finnhub_client.fetch_fundamentals("AAPL")

    async def test_a_429_reads_as_a_rate_limit(self, monkeypatch, keys):
        serve_json(monkeypatch, {}, status=429)
        with pytest.raises(FinnhubError) as excinfo:
            await finnhub_client.fetch_fundamentals("AAPL")
        assert provider_health.looks_rate_limited(str(excinfo.value))


class TestAlphaVantageShape:
    async def test_it_maps_into_the_tables_fields(self, monkeypatch, keys):
        serve_json(monkeypatch, ALPHA_OVERVIEW)
        row = await alphavantage_client.fetch_fundamentals("AAPL")

        assert row["companyName"] == "Apple Inc"
        assert row["peRatio"] == 34.2
        assert row["marketCap"] == 4_100_000_000_000

    async def test_shouted_sector_names_are_tidied(self, monkeypatch, keys):
        serve_json(monkeypatch, ALPHA_OVERVIEW)
        row = await alphavantage_client.fetch_fundamentals("AAPL")
        assert row["sector"] == "Technology"

    async def test_its_ratios_are_already_fractions(self, monkeypatch, keys):
        serve_json(monkeypatch, ALPHA_OVERVIEW)
        row = await alphavantage_client.fetch_fundamentals("AAPL")
        assert row["netProfitMargin"] == pytest.approx(0.264)

    async def test_the_literal_string_none_is_treated_as_missing(self, monkeypatch, keys):
        serve_json(monkeypatch, {**ALPHA_OVERVIEW, "PERatio": "None"})
        row = await alphavantage_client.fetch_fundamentals("AAPL")
        assert row["peRatio"] is None

    async def test_a_spent_allowance_is_an_error_not_an_empty_company(
        self, monkeypatch, keys
    ):
        """It answers 200 and puts the refusal in the body, so it must be read."""
        serve_json(monkeypatch, {"Note": "Thank you for using Alpha Vantage! "
                                         "Our standard API rate limit is 25 requests per day"})
        with pytest.raises(AlphaVantageError) as excinfo:
            await alphavantage_client.fetch_fundamentals("AAPL")

        assert provider_health.looks_rate_limited(str(excinfo.value))

    async def test_a_bad_key_notice_is_surfaced(self, monkeypatch, keys):
        serve_json(monkeypatch, {"Information": "Invalid API call"})
        with pytest.raises(AlphaVantageError, match="Invalid API call"):
            await alphavantage_client.fetch_fundamentals("AAPL")


class TestTheChain:
    async def test_finnhub_covers_for_a_spent_fmp_allowance(self, monkeypatch, keys):
        """The failure that motivated all of this."""
        async def fmp_spent(ticker):
            raise FMPError("FMP API rate limit reached (free tier: 250 calls/day)")

        async def finnhub_up(ticker):
            return {"ticker": ticker, "companyName": "Apple Inc", "peRatio": 34.2}

        monkeypatch.setattr(fmp_client, "fetch_fundamentals", fmp_spent)
        monkeypatch.setattr(finnhub_client, "fetch_fundamentals", finnhub_up)

        row = await market_data.fetch_fundamentals("AAPL")
        assert row["companyName"] == "Apple Inc"

    async def test_it_falls_all_the_way_to_the_last_provider(self, monkeypatch, keys):
        async def spent(ticker):
            raise FMPError("rate limit reached")

        async def finnhub_spent(ticker):
            raise FinnhubError("Finnhub rate limit reached (free tier: 60 calls/minute)")

        async def alpha_up(ticker):
            return {"ticker": ticker, "companyName": "Apple Inc"}

        monkeypatch.setattr(fmp_client, "fetch_fundamentals", spent)
        monkeypatch.setattr(finnhub_client, "fetch_fundamentals", finnhub_spent)
        monkeypatch.setattr(alphavantage_client, "fetch_fundamentals", alpha_up)

        assert (await market_data.fetch_fundamentals("AAPL"))["companyName"] == "Apple Inc"

    async def test_a_spent_provider_is_skipped_next_time(self, monkeypatch, keys):
        calls = []

        async def fmp_spent(ticker):
            calls.append(ticker)
            raise FMPError("FMP API rate limit reached (free tier: 250 calls/day)")

        async def finnhub_up(ticker):
            return {"ticker": ticker, "companyName": "Apple Inc"}

        monkeypatch.setattr(fmp_client, "fetch_fundamentals", fmp_spent)
        monkeypatch.setattr(finnhub_client, "fetch_fundamentals", finnhub_up)

        for ticker in ("AAPL", "MSFT", "GOOG"):
            await market_data.fetch_fundamentals(ticker)

        assert calls == ["AAPL"]

    async def test_an_unkeyed_provider_is_simply_skipped(self, monkeypatch):
        """Running with only FMP configured must behave exactly as before."""
        monkeypatch.setattr(settings, "finnhub_api_key", "")
        monkeypatch.setattr(settings, "alpha_vantage_api_key", "")

        async def fmp_up(ticker):
            return {"ticker": ticker, "companyName": "Apple Inc"}

        monkeypatch.setattr(fmp_client, "fetch_fundamentals", fmp_up)
        assert (await market_data.fetch_fundamentals("AAPL"))["companyName"] == "Apple Inc"

    async def test_everything_spent_reports_the_last_reason(self, monkeypatch, keys):
        async def spent(ticker):
            raise FMPError("rate limit reached (250 calls/day)")

        for provider in (fmp_client, finnhub_client, alphavantage_client):
            monkeypatch.setattr(provider, "fetch_fundamentals", spent)

        with pytest.raises(FMPError):
            await market_data.fetch_fundamentals("AAPL")

    async def test_fmp_is_still_preferred_while_it_works(self, monkeypatch, keys):
        """It carries the most complete row, so it stays first."""
        async def fmp_up(ticker):
            return {"ticker": ticker, "companyName": "From FMP"}

        def explode(ticker):
            raise AssertionError("must not reach a fallback while FMP works")

        monkeypatch.setattr(fmp_client, "fetch_fundamentals", fmp_up)
        monkeypatch.setattr(finnhub_client, "fetch_fundamentals", explode)

        assert (await market_data.fetch_fundamentals("AAPL"))["companyName"] == "From FMP"

    async def test_a_key_alone_is_enough_to_get_a_fallback(self, monkeypatch, keys):
        """Adding a key should not also require editing PROVIDER_ORDER."""
        monkeypatch.setattr(settings, "provider_order", "yahoo,fmp,stooq")

        async def fmp_spent(ticker):
            raise FMPError("rate limit reached (250 calls/day)")

        async def finnhub_up(ticker):
            return {"ticker": ticker, "companyName": "Apple Inc"}

        monkeypatch.setattr(fmp_client, "fetch_fundamentals", fmp_spent)
        monkeypatch.setattr(finnhub_client, "fetch_fundamentals", finnhub_up)

        assert (await market_data.fetch_fundamentals("AAPL"))["companyName"] == "Apple Inc"
