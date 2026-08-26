import pytest

from app import market_data
from app.fmp_client import FMPError
from app.yahoo_client import YahooError

YAHOO_QUOTE = [{"symbol": "AAPL", "price": 309.9, "name": "Apple Inc."}]
FMP_QUOTE = [{"symbol": "AAPL", "price": 308.0, "name": "Apple Inc."}]


@pytest.fixture
def order(monkeypatch):
    def _set(value: str):
        monkeypatch.setattr(market_data.settings, "provider_order", value)

    return _set


def stub(monkeypatch, provider: str, func: str, *, returns=None, raises=None):
    async def fake(*args, **kwargs):
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setattr(market_data.PROVIDERS[provider], func, fake)


class TestProviderOrder:
    async def test_prefers_the_first_provider(self, monkeypatch, order):
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "fetch_quotes", returns=YAHOO_QUOTE)
        stub(monkeypatch, "fmp", "fetch_quotes", returns=FMP_QUOTE)

        # Yahoo has no quota; spending an FMP call while it works is waste.
        assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 309.9

    async def test_order_is_configurable(self, monkeypatch, order):
        order("fmp,yahoo")
        stub(monkeypatch, "yahoo", "fetch_quotes", returns=YAHOO_QUOTE)
        stub(monkeypatch, "fmp", "fetch_quotes", returns=FMP_QUOTE)

        assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 308.0

    async def test_unknown_names_are_ignored(self, monkeypatch, order):
        order("bloomberg,yahoo")
        stub(monkeypatch, "yahoo", "fetch_quotes", returns=YAHOO_QUOTE)
        assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 309.9

    async def test_an_empty_setting_still_works(self, monkeypatch, order):
        order("")
        stub(monkeypatch, "fmp", "fetch_quotes", returns=FMP_QUOTE)
        assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 308.0


class TestFallback:
    async def test_falls_through_when_the_first_provider_fails(self, monkeypatch, order):
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "fetch_quotes", raises=YahooError("rate limited"))
        stub(monkeypatch, "fmp", "fetch_quotes", returns=FMP_QUOTE)

        assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 308.0

    async def test_falls_through_on_an_empty_result(self, monkeypatch, order):
        # Yahoo answering "nothing" shouldn't cost the user their data if FMP
        # can still supply it.
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "fetch_quotes", returns=[])
        stub(monkeypatch, "fmp", "fetch_quotes", returns=FMP_QUOTE)

        assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 308.0

    async def test_raises_when_every_provider_fails(self, monkeypatch, order):
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "fetch_quotes", raises=YahooError("down"))
        stub(monkeypatch, "fmp", "fetch_quotes", raises=FMPError("also down"))

        # Routers catch FMPError, so the chain normalises onto it.
        with pytest.raises(FMPError):
            await market_data.fetch_quotes(["AAPL"])

    async def test_returns_empty_when_nobody_has_data_but_nobody_errored(
        self, monkeypatch, order
    ):
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "fetch_quotes", returns=[])
        stub(monkeypatch, "fmp", "fetch_quotes", returns=[])
        assert await market_data.fetch_quotes(["AAPL"]) == []

    async def test_history_falls_back_too(self, monkeypatch, order):
        order("yahoo,fmp")
        points = [{"date": "2026-08-25", "close": 310.0}]
        stub(monkeypatch, "yahoo", "fetch_history", raises=YahooError("down"))
        stub(monkeypatch, "fmp", "fetch_history", returns=points)

        assert await market_data.fetch_history("AAPL", "1M") == points

    async def test_search_falls_back_too(self, monkeypatch, order):
        order("yahoo,fmp")
        matches = [{"symbol": "AAPL", "name": "Apple Inc."}]
        stub(monkeypatch, "yahoo", "search_symbols", raises=YahooError("down"))
        stub(monkeypatch, "fmp", "search_symbols", returns=matches)

        assert await market_data.search_symbols("apple") == matches


class TestShortCircuits:
    async def test_no_symbols_means_no_provider_call(self, monkeypatch, order):
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "fetch_quotes", raises=AssertionError("should not run"))
        assert await market_data.fetch_quotes([]) == []

    async def test_blank_search_means_no_provider_call(self, monkeypatch, order):
        order("yahoo,fmp")
        stub(monkeypatch, "yahoo", "search_symbols", raises=AssertionError("should not run"))
        assert await market_data.search_symbols("  ") == []


class TestFundamentals:
    async def test_fundamentals_never_go_to_yahoo(self, monkeypatch, order):
        """Yahoo's fundamentals need an authenticated crumb, so FMP owns them.

        They're cached for 24h and were never the source of quota pressure.
        """
        order("yahoo,fmp")
        stub(monkeypatch, "fmp", "fetch_fundamentals", returns={"ticker": "AAPL"})
        assert (await market_data.fetch_fundamentals("AAPL"))["ticker"] == "AAPL"
