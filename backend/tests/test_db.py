from datetime import datetime, timedelta, timezone

from app import db


def backdate_market_cache(key: str, seconds: int) -> None:
    """Rewrite a cache row's timestamp so TTL behaviour can be tested without sleeping."""
    stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE market_cache SET fetched_at = ? WHERE cache_key = ?", (stale, key))


class TestWatchlist:
    def test_add_and_list(self):
        db.add_to_watchlist("AAPL")
        db.add_to_watchlist("MSFT")
        assert db.get_watchlist() == ["AAPL", "MSFT"]

    def test_adding_twice_does_not_duplicate(self):
        db.add_to_watchlist("AAPL")
        db.add_to_watchlist("AAPL")
        assert db.get_watchlist() == ["AAPL"]

    def test_remove_keeps_the_shared_fundamentals_cache(self):
        """Removing a ticker must not evict data other watchlists still use.

        This inverts the original behaviour. When there was one global
        watchlist, dropping the cache on removal was tidy housekeeping. Now
        that watchlists are per browser and the cache is shared, evicting on
        removal would let one person cost everyone else four API calls out of
        a 250-a-day budget.
        """
        db.add_to_watchlist("AAPL")
        db.set_cached_fundamentals("AAPL", {"ticker": "AAPL"})
        db.remove_from_watchlist("AAPL")

        assert db.get_watchlist() == []
        assert db.get_cached_fundamentals("AAPL") is not None


class TestFundamentalsCache:
    def test_roundtrip(self):
        db.set_cached_fundamentals("AAPL", {"ticker": "AAPL", "peRatio": 35.4})
        cached = db.get_cached_fundamentals("AAPL")
        assert cached["data"]["peRatio"] == 35.4

    def test_write_replaces_rather_than_duplicating(self):
        db.set_cached_fundamentals("AAPL", {"peRatio": 1})
        db.set_cached_fundamentals("AAPL", {"peRatio": 2})
        assert db.get_cached_fundamentals("AAPL")["data"]["peRatio"] == 2

    def test_miss_returns_none(self):
        assert db.get_cached_fundamentals("NOPE") is None


class TestMarketCache:
    def test_returns_value_inside_ttl(self):
        db.set_market_cache("quotes", [{"symbol": "AAPL"}])
        assert db.get_market_cache("quotes", max_age_seconds=900) == [{"symbol": "AAPL"}]

    def test_returns_none_once_past_ttl(self):
        db.set_market_cache("quotes", [{"symbol": "AAPL"}])
        backdate_market_cache("quotes", seconds=1000)
        assert db.get_market_cache("quotes", max_age_seconds=900) is None

    def test_stale_row_is_still_readable_with_a_longer_ttl(self):
        """The indices route falls back to a week-old copy when FMP is down."""
        db.set_market_cache("indices", ["payload"])
        backdate_market_cache("indices", seconds=3600)

        assert db.get_market_cache("indices", max_age_seconds=900) is None
        assert db.get_market_cache("indices", max_age_seconds=7 * 24 * 3600) == ["payload"]

    def test_overwrite_refreshes_the_timestamp(self):
        db.set_market_cache("quotes", ["old"])
        backdate_market_cache("quotes", seconds=1000)
        db.set_market_cache("quotes", ["new"])
        assert db.get_market_cache("quotes", max_age_seconds=900) == ["new"]

    def test_miss_returns_none(self):
        assert db.get_market_cache("absent", max_age_seconds=900) is None


class TestFedStatements:
    def save(self, statement_id="m1", date="2026-07-29", sentiment="neutral"):
        db.save_fed_statement(
            statement_id=statement_id,
            date=date,
            title="FOMC statement",
            url="https://example.gov/a.htm",
            raw_text="body",
            summary="Held rates steady.",
            sentiment=sentiment,
            key_takeaways=["Rate unchanged"],
        )

    def test_roundtrip_deserialises_takeaways(self):
        self.save()
        [item] = db.get_fed_timeline()
        assert item["key_takeaways"] == ["Rate unchanged"]
        assert item["sentiment"] == "neutral"

    def test_timeline_is_newest_first(self):
        self.save("old", "2026-06-17")
        self.save("new", "2026-07-29")
        assert [i["id"] for i in db.get_fed_timeline()] == ["new", "old"]

    def test_statement_exists_gates_resummarising(self):
        assert db.statement_exists("m1") is False
        self.save("m1")
        assert db.statement_exists("m1") is True

    def test_resaving_updates_rather_than_duplicating(self):
        self.save("m1", sentiment="neutral")
        self.save("m1", sentiment="hawkish")
        timeline = db.get_fed_timeline()
        assert len(timeline) == 1
        assert timeline[0]["sentiment"] == "hawkish"

    def test_limit_is_respected(self):
        for i in range(5):
            self.save(f"m{i}", f"2026-0{i + 1}-01")
        assert len(db.get_fed_timeline(limit=2)) == 2
