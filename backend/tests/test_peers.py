"""Peer suggestions.

Neither provider's peer endpoint is reachable from here, so the response
shapes are pinned as fixtures and everything above them -- ranking, exclusion,
the provider fallback, and degrading when both are down -- is tested against
those.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db, fmp_client, market_data, peers, yahoo_client
from app.config import settings
from app.fmp_client import FMPError
from app.main import app
from app.yahoo_client import YahooError

ALICE = {"X-Vantage-Space": "alice-abc123"}
OWNER = db.space_owner("alice-abc123")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def yahoo_payload(symbol: str, *peer_symbols: str) -> dict:
    """The shape Yahoo's recommendationsbysymbol endpoint returns."""
    return {
        "finance": {
            "result": [
                {
                    "symbol": symbol,
                    "recommendedSymbols": [
                        {"symbol": p, "score": 0.3} for p in peer_symbols
                    ],
                }
            ],
            "error": None,
        }
    }


def fake_peers(mapping: dict[str, list[str]]):
    async def _fetch(symbol, limit=6):
        return mapping.get(symbol, [])

    return _fetch


class TestYahooParsing:
    async def test_reads_the_recommended_symbols(self, monkeypatch):
        async def _get_json(client, url, **params):
            return yahoo_payload("AAPL", "MSFT", "GOOG")

        monkeypatch.setattr(yahoo_client, "_get_json", _get_json)
        assert await yahoo_client.fetch_peers("AAPL") == ["MSFT", "GOOG"]

    async def test_never_suggests_the_company_itself(self, monkeypatch):
        async def _get_json(client, url, **params):
            return yahoo_payload("AAPL", "AAPL", "MSFT")

        monkeypatch.setattr(yahoo_client, "_get_json", _get_json)
        assert await yahoo_client.fetch_peers("AAPL") == ["MSFT"]

    async def test_an_empty_result_is_not_an_error(self, monkeypatch):
        async def _get_json(client, url, **params):
            return {"finance": {"result": [], "error": None}}

        monkeypatch.setattr(yahoo_client, "_get_json", _get_json)
        assert await yahoo_client.fetch_peers("NOPE") == []

    async def test_a_missing_body_does_not_explode(self, monkeypatch):
        """Yahoo's shapes are undocumented; a surprise must not 500 the route."""
        async def _get_json(client, url, **params):
            return {}

        monkeypatch.setattr(yahoo_client, "_get_json", _get_json)
        assert await yahoo_client.fetch_peers("AAPL") == []

    async def test_a_transport_failure_becomes_a_provider_error(self, monkeypatch):
        async def boom(*a, **k):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx.AsyncClient, "get", boom)
        with pytest.raises(YahooError):
            await yahoo_client.fetch_peers("AAPL")

    async def test_the_limit_is_respected(self, monkeypatch):
        async def _get_json(client, url, **params):
            return yahoo_payload("AAPL", "A", "B", "C", "D")

        monkeypatch.setattr(yahoo_client, "_get_json", _get_json)
        assert len(await yahoo_client.fetch_peers("AAPL", limit=2)) == 2


class TestFmpParsing:
    """FMP has shipped two different shapes for this; both are read."""

    async def test_reads_a_flat_list_of_companies(self, monkeypatch):
        async def _get(client, path, **params):
            return [{"symbol": "MSFT", "companyName": "Microsoft"},
                    {"symbol": "GOOG", "companyName": "Alphabet"}]

        monkeypatch.setattr(fmp_client, "_get", _get)
        assert await fmp_client.fetch_peers("AAPL") == ["MSFT", "GOOG"]

    async def test_reads_the_older_peers_list_shape(self, monkeypatch):
        async def _get(client, path, **params):
            return [{"symbol": "AAPL", "peersList": ["MSFT", "GOOG"]}]

        monkeypatch.setattr(fmp_client, "_get", _get)
        assert await fmp_client.fetch_peers("AAPL") == ["MSFT", "GOOG"]

    async def test_deduplicates_and_drops_the_query_itself(self, monkeypatch):
        async def _get(client, path, **params):
            return [{"peersList": ["MSFT", "msft", "AAPL", "GOOG"]}]

        monkeypatch.setattr(fmp_client, "_get", _get)
        assert await fmp_client.fetch_peers("AAPL") == ["MSFT", "GOOG"]

    async def test_junk_in_the_response_is_skipped(self, monkeypatch):
        async def _get(client, path, **params):
            return ["not a dict", {"symbol": "MSFT"}, None]

        monkeypatch.setattr(fmp_client, "_get", _get)
        assert await fmp_client.fetch_peers("AAPL") == ["MSFT"]

    async def test_a_missing_key_is_reported_not_guessed_at(self, monkeypatch):
        monkeypatch.setattr(settings, "fmp_api_key", "")
        with pytest.raises(FMPError):
            await fmp_client.fetch_peers("AAPL")


class TestProviderFallback:
    async def test_fmp_covers_for_a_yahoo_outage(self, monkeypatch):
        async def yahoo_down(symbol, limit=6):
            raise YahooError("rate limited")

        async def fmp_up(symbol, limit=6):
            return ["MSFT"]

        monkeypatch.setattr(yahoo_client, "fetch_peers", yahoo_down)
        monkeypatch.setattr(fmp_client, "fetch_peers", fmp_up)
        assert await market_data.fetch_peers("AAPL") == ["MSFT"]

    async def test_both_down_raises_rather_than_returning_nothing(self, monkeypatch):
        async def down(symbol, limit=6):
            raise YahooError("nope")

        monkeypatch.setattr(yahoo_client, "fetch_peers", down)
        monkeypatch.setattr(fmp_client, "fetch_peers", down)
        with pytest.raises(FMPError):
            await market_data.fetch_peers("AAPL")


class TestRanking:
    async def test_a_peer_shared_by_two_holdings_outranks_a_lone_one(self, monkeypatch):
        """Shared peers are the more useful suggestion, so they come first."""
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        db.add_to_watchlist("MSFT", OWNER, db.COMPARE_LIST)

        monkeypatch.setattr(
            peers, "fetch_peers",
            fake_peers({"AAPL": ["GOOG", "DELL"], "MSFT": ["GOOG", "ORCL"]}),
        )
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        result = await peers.suggest(OWNER)
        assert [s["symbol"] for s in result["suggestions"]][0] == "GOOG"
        assert result["suggestions"][0]["count"] == 2

    async def test_it_says_which_holdings_a_suggestion_came_from(self, monkeypatch):
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["MSFT"]}))
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        [suggestion] = (await peers.suggest(OWNER))["suggestions"]
        assert suggestion["because_of"] == ["AAPL"]

    async def test_nothing_already_being_compared_is_suggested(self, monkeypatch):
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        db.add_to_watchlist("MSFT", OWNER, db.COMPARE_LIST)

        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["MSFT", "GOOG"]}))
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        symbols = [s["symbol"] for s in (await peers.suggest(OWNER))["suggestions"]]
        assert "MSFT" not in symbols
        assert "GOOG" in symbols

    async def test_nothing_on_the_watchlist_is_suggested_either(self, monkeypatch):
        """Suggesting something already followed is noise, separate list or not."""
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        db.add_to_watchlist("GOOG", OWNER, db.WATCH_LIST)

        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["GOOG", "ORCL"]}))
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        symbols = [s["symbol"] for s in (await peers.suggest(OWNER))["suggestions"]]
        assert symbols == ["ORCL"]

    async def test_an_empty_comparison_list_asks_for_nothing(self, monkeypatch):
        called = []

        async def track(symbol, limit=6):
            called.append(symbol)
            return []

        monkeypatch.setattr(peers, "fetch_peers", track)
        result = await peers.suggest(OWNER)

        assert result["suggestions"] == []
        assert called == []

    async def test_one_seed_failing_does_not_lose_the_others(self, monkeypatch):
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        db.add_to_watchlist("BROKEN", OWNER, db.COMPARE_LIST)

        async def flaky(symbol, limit=6):
            if symbol == "BROKEN":
                raise FMPError("no data")
            return ["MSFT"]

        monkeypatch.setattr(peers, "fetch_peers", flaky)
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        result = await peers.suggest(OWNER)
        assert [s["symbol"] for s in result["suggestions"]] == ["MSFT"]
        assert result["error"] is None

    async def test_every_seed_failing_is_reported(self, monkeypatch):
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)

        async def down(symbol, limit=6):
            raise FMPError("rate limited")

        monkeypatch.setattr(peers, "fetch_peers", down)
        result = await peers.suggest(OWNER)

        assert result["suggestions"] == []
        assert "Couldn't look up peers" in result["error"]

    async def test_a_long_list_does_not_spend_a_call_per_row(self, monkeypatch):
        for i in range(20):
            db.add_to_watchlist(f"T{i}", OWNER, db.COMPARE_LIST)

        called = []

        async def track(symbol, limit=6):
            called.append(symbol)
            return []

        monkeypatch.setattr(peers, "fetch_peers", track)
        await peers.suggest(OWNER)
        assert len(called) == peers.MAX_SEEDS

    async def test_the_number_of_suggestions_is_capped(self, monkeypatch):
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        monkeypatch.setattr(
            peers, "fetch_peers", fake_peers({"AAPL": [f"P{i}" for i in range(20)]})
        )
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        result = await peers.suggest(OWNER)
        assert len(result["suggestions"]) == peers.MAX_SUGGESTIONS


class TestNames:
    async def test_a_suggestion_carries_a_name_and_price(self, monkeypatch):
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["MSFT"]}))

        async def quotes(symbols):
            return [{"symbol": "MSFT", "name": "Microsoft", "price": 410.0,
                     "changePercent": 1.2}]

        monkeypatch.setattr(peers, "fetch_quotes", quotes)
        [suggestion] = (await peers.suggest(OWNER))["suggestions"]

        assert suggestion["name"] == "Microsoft"
        assert suggestion["price"] == 410.0

    async def test_a_failed_quote_lookup_still_suggests_the_ticker(self, monkeypatch):
        """The name is decoration; the ticker is the suggestion."""
        db.add_to_watchlist("AAPL", OWNER, db.COMPARE_LIST)
        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["MSFT"]}))

        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(peers, "fetch_quotes", boom)
        [suggestion] = (await peers.suggest(OWNER))["suggestions"]

        assert suggestion["symbol"] == "MSFT"


class TestRoute:
    def test_the_route_returns_suggestions(self, client, monkeypatch):
        client.post("/api/lists/compare", json={"ticker": "AAPL"}, headers=ALICE)
        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["MSFT"]}))
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        body = client.get("/api/peers", headers=ALICE).json()
        assert [s["symbol"] for s in body["suggestions"]] == ["MSFT"]
        assert body["based_on"] == ["AAPL"]

    def test_suggestions_do_not_leak_between_spaces(self, client, monkeypatch):
        client.post("/api/lists/compare", json={"ticker": "AAPL"}, headers=ALICE)
        monkeypatch.setattr(peers, "fetch_peers", fake_peers({"AAPL": ["MSFT"]}))
        monkeypatch.setattr(peers, "fetch_quotes", _no_quotes)

        other = client.get("/api/peers", headers={"X-Vantage-Space": "bob-xyz"}).json()
        assert other["suggestions"] == []

    def test_a_provider_outage_is_a_200_with_a_message_not_a_500(self, client, monkeypatch):
        """The comparison table must keep working when suggestions can't load."""
        client.post("/api/lists/compare", json={"ticker": "AAPL"}, headers=ALICE)

        async def down(symbol, limit=6):
            raise FMPError("rate limited")

        monkeypatch.setattr(peers, "fetch_peers", down)
        response = client.get("/api/peers", headers=ALICE)

        assert response.status_code == 200
        assert response.json()["error"] is not None


async def _no_quotes(symbols):
    return []
