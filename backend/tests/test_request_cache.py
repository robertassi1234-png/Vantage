import asyncio
from unittest.mock import AsyncMock

import pytest

from app import db, market_data
from app.request_cache import cached_call
from app.fmp_client import FMPError


async def test_simultaneous_requests_share_one_call():
    fetch = AsyncMock(return_value=[{"close": 10}])
    results = await asyncio.gather(*(cached_call("test", ["AAPL"], 60, fetch) for _ in range(20)))
    assert all(result == [{"close": 10}] for result in results)
    assert fetch.await_count == 1


async def test_expired_cache_fetches_again(monkeypatch):
    fetch = AsyncMock(return_value=[1])
    await cached_call("test", [], 60, fetch)
    monkeypatch.setattr(db, "get_market_cache", lambda *args: None)
    await cached_call("test", [], 60, fetch)
    assert fetch.await_count == 2


async def test_empty_results_are_not_cached():
    fetch = AsyncMock(side_effect=[[], [1]])
    assert await cached_call("test", [], 60, fetch) == []
    assert await cached_call("test", [], 60, fetch) == [1]


async def test_failure_does_not_poison_cache():
    fetch = AsyncMock(side_effect=[FMPError("down"), [1]])
    with pytest.raises(FMPError):
        await cached_call("test", [], 60, fetch)
    assert await cached_call("test", [], 60, fetch) == [1]


async def test_overlapping_quote_lists_only_fetch_missing_symbols(monkeypatch):
    fetch = AsyncMock(side_effect=[
        [{"symbol": "AAPL", "price": 10}], [{"symbol": "MSFT", "price": 20}],
    ])
    monkeypatch.setattr(market_data, "_first_success", fetch)
    await market_data.fetch_quotes(["aapl", "AAPL"])
    result = await market_data.fetch_quotes(["MSFT", "AAPL"])
    assert [quote["symbol"] for quote in result] == ["MSFT", "AAPL"]
    assert fetch.call_args_list[1].args[2] == ["MSFT"]


async def test_quote_without_price_is_retried(monkeypatch):
    fetch = AsyncMock(side_effect=[[{"symbol": "AAPL", "price": None}], [{"symbol": "AAPL", "price": 10}]])
    monkeypatch.setattr(market_data, "_first_success", fetch)
    assert await market_data.fetch_quotes(["AAPL"]) == []
    assert (await market_data.fetch_quotes(["AAPL"]))[0]["price"] == 10
