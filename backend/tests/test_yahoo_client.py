import httpx
import pytest

from app import yahoo_client
from app.yahoo_client import YahooError

CHART = {
    "chart": {
        "error": None,
        "result": [
            {
                "meta": {
                    "symbol": "AAPL",
                    "longName": "Apple Inc.",
                    "regularMarketPrice": 309.9,
                    "chartPreviousClose": 307.5,
                    "regularMarketDayLow": 306.2,
                    "regularMarketDayHigh": 311.4,
                    "fiftyTwoWeekLow": 224.69,
                    "fiftyTwoWeekHigh": 344.57,
                    "regularMarketVolume": 25666176,
                },
                "timestamp": [1755000000, 1755086400, 1755172800],
                "indicators": {"quote": [{"close": [305.5, None, 309.9]}]},
            }
        ],
    }
}

SEARCH = {
    "quotes": [
        {"symbol": "AAPL", "longname": "Apple Inc.", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
        {"symbol": "AAPL=F", "shortname": "Apple Future", "quoteType": "FUTURE"},
        {"symbol": "APLE", "shortname": "Apple Hospitality", "exchDisp": "NYSE", "quoteType": "EQUITY"},
    ]
}


def patch_json(monkeypatch, payload=None, error=None):
    async def fake(client, url, **params):
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(yahoo_client, "_get_json", fake)


class TestQuotes:
    async def test_derives_change_from_previous_close(self, monkeypatch):
        patch_json(monkeypatch, CHART)
        [quote] = await yahoo_client.fetch_quotes(["AAPL"])

        assert quote["price"] == 309.9
        assert quote["change"] == pytest.approx(2.4)
        assert quote["changePercent"] == pytest.approx(0.78, abs=0.01)

    async def test_carries_the_52_week_range(self, monkeypatch):
        patch_json(monkeypatch, CHART)
        [quote] = await yahoo_client.fetch_quotes(["AAPL"])
        assert quote["yearLow"] == 224.69
        assert quote["yearHigh"] == 344.57

    async def test_missing_previous_close_leaves_change_blank(self, monkeypatch):
        payload = {"chart": {"result": [{"meta": {"symbol": "X", "regularMarketPrice": 10}}]}}
        patch_json(monkeypatch, payload)
        [quote] = await yahoo_client.fetch_quotes(["X"])

        # Better a blank delta than a fabricated one.
        assert quote["price"] == 10
        assert quote["change"] is None
        assert quote["changePercent"] is None

    async def test_zero_previous_close_does_not_divide_by_zero(self, monkeypatch):
        payload = {
            "chart": {
                "result": [
                    {"meta": {"symbol": "X", "regularMarketPrice": 10, "chartPreviousClose": 0}}
                ]
            }
        }
        patch_json(monkeypatch, payload)
        [quote] = await yahoo_client.fetch_quotes(["X"])
        assert quote["changePercent"] is None

    async def test_one_bad_symbol_does_not_fail_the_batch(self, monkeypatch):
        async def fake(client, url, **params):
            if "BAD" in url:
                raise YahooError("no such symbol")
            return CHART

        monkeypatch.setattr(yahoo_client, "_get_json", fake)
        quotes = await yahoo_client.fetch_quotes(["AAPL", "BAD"])
        assert [q["symbol"] for q in quotes] == ["AAPL"]

    async def test_empty_symbol_list_makes_no_request(self, monkeypatch):
        async def explode(client, url, **params):
            raise AssertionError("should not call Yahoo with no symbols")

        monkeypatch.setattr(yahoo_client, "_get_json", explode)
        assert await yahoo_client.fetch_quotes([]) == []


class TestHistory:
    async def test_skips_null_closes_and_sorts_oldest_first(self, monkeypatch):
        patch_json(monkeypatch, CHART)
        points = await yahoo_client.fetch_history("AAPL", "1M")

        # The middle candle is null (a holiday) and must be dropped.
        assert len(points) == 2
        assert [p["close"] for p in points] == [305.5, 309.9]
        assert points[0]["date"] < points[1]["date"]

    async def test_unknown_range_falls_back_to_a_year(self, monkeypatch):
        captured = {}

        async def fake(client, url, **params):
            captured.update(params)
            return CHART

        monkeypatch.setattr(yahoo_client, "_get_json", fake)
        await yahoo_client.fetch_history("AAPL", "banana")
        assert captured["range"] == "1y"

    async def test_yahoo_error_payload_raises(self, monkeypatch):
        patch_json(monkeypatch, {"chart": {"error": {"code": "Not Found"}, "result": None}})
        with pytest.raises(YahooError, match="no data"):
            await yahoo_client.fetch_history("NOPE", "1M")

    async def test_empty_result_raises(self, monkeypatch):
        patch_json(monkeypatch, {"chart": {"result": []}})
        with pytest.raises(YahooError, match="no data"):
            await yahoo_client.fetch_history("NOPE", "1M")


class TestSearch:
    async def test_finds_a_company_by_name(self, monkeypatch):
        patch_json(monkeypatch, SEARCH)
        results = await yahoo_client.search_symbols("apple")
        assert results[0]["symbol"] == "AAPL"
        assert results[0]["name"] == "Apple Inc."

    async def test_filters_out_non_company_instruments(self, monkeypatch):
        patch_json(monkeypatch, SEARCH)
        symbols = [r["symbol"] for r in await yahoo_client.search_symbols("apple")]
        # Futures aren't what someone typing "apple" is looking for.
        assert "AAPL=F" not in symbols
        assert symbols == ["AAPL", "APLE"]

    async def test_blank_query_makes_no_request(self, monkeypatch):
        async def explode(client, url, **params):
            raise AssertionError("should not search for a blank query")

        monkeypatch.setattr(yahoo_client, "_get_json", explode)
        assert await yahoo_client.search_symbols("   ") == []


class TestTransportErrors:
    """Everything must surface as YahooError so the chain can fall through."""

    def stub(self, *, raises=None, response=None):
        class FakeClient:
            async def get(self, url, params=None, headers=None):
                if raises is not None:
                    raise raises
                return response

        return FakeClient()

    async def test_connection_error_is_wrapped(self):
        with pytest.raises(YahooError, match="Couldn't reach"):
            await yahoo_client._get_json(self.stub(raises=httpx.ConnectError("down")), "url")

    async def test_rate_limit_is_named(self):
        request = httpx.Request("GET", "https://query1.finance.yahoo.com/")
        response = httpx.Response(429, request=request, text="slow down")
        with pytest.raises(YahooError, match="rate limiting"):
            await yahoo_client._get_json(self.stub(response=response), "url")

    async def test_malformed_body_is_wrapped(self):
        request = httpx.Request("GET", "https://query1.finance.yahoo.com/")
        response = httpx.Response(200, request=request, text="<html>nope</html>")
        with pytest.raises(YahooError, match="malformed"):
            await yahoo_client._get_json(self.stub(response=response), "url")
