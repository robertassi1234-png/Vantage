"""The thesis journal.

The feature is the price stamp, so most of this is about that stamp: that it
is taken once, that it survives, and that nothing recomputes it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.routers import journal as journal_router


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing here should reach a provider unless the test says so."""

    async def unavailable(symbols):
        return []

    monkeypatch.setattr(journal_router, "fetch_quotes", unavailable)


def write(client, ticker="AAPL", **body):
    payload = {"body": "Services margin keeps expanding.", **body}
    return client.post(f"/api/journal/{ticker}", json=payload)


class TestWriting:
    def test_an_entry_keeps_the_price_it_was_written_at(self, client):
        entry = write(client, priceAtWrite=142.3).json()["entry"]
        assert entry["priceAtWrite"] == 142.3
        assert entry["ticker"] == "AAPL"

    def test_the_price_the_page_was_showing_is_used_as_given(self, client, monkeypatch):
        # It is the number the reader was actually looking at when they formed
        # the view. Re-fetching would stamp a different one.
        async def different_price(symbols):
            return [{"symbol": "AAPL", "price": 999.0}]

        monkeypatch.setattr(journal_router, "fetch_quotes", different_price)
        assert write(client, priceAtWrite=142.3).json()["entry"]["priceAtWrite"] == 142.3

    def test_a_price_is_fetched_when_the_page_had_none(self, client, monkeypatch):
        async def quote(symbols):
            return [{"symbol": "AAPL", "price": 244.18}]

        monkeypatch.setattr(journal_router, "fetch_quotes", quote)
        assert write(client).json()["entry"]["priceAtWrite"] == 244.18

    def test_an_entry_is_kept_even_when_no_price_can_be_had(self, client):
        # Losing the thought because a provider was rate limited would be the
        # worse trade of the two.
        entry = write(client).json()["entry"]
        assert entry["priceAtWrite"] is None
        assert entry["body"]

    def test_a_provider_failure_does_not_lose_the_entry(self, client, monkeypatch):
        async def broken(symbols):
            raise RuntimeError("rate limited")

        monkeypatch.setattr(journal_router, "fetch_quotes", broken)
        assert write(client).status_code == 200

    def test_an_empty_entry_is_refused(self, client):
        assert write(client, body="   ").status_code == 400

    def test_entries_come_back_newest_first(self, client):
        for ticker in ("AAPL", "MSFT", "NVDA"):
            write(client, ticker)
        listed = client.get("/api/journal").json()["entries"]
        assert [e["ticker"] for e in listed] == ["NVDA", "MSFT", "AAPL"]

    def test_entries_can_be_narrowed_to_one_company(self, client):
        write(client, "AAPL")
        write(client, "MSFT")
        listed = client.get("/api/journal?ticker=aapl").json()["entries"]
        assert [e["ticker"] for e in listed] == ["AAPL"]

    def test_deleting_leaves_the_rest(self, client):
        write(client, "AAPL")
        write(client, "MSFT")
        entries = client.get("/api/journal").json()["entries"]
        remaining = client.delete(f"/api/journal/{entries[0]['id']}").json()["entries"]
        assert [e["ticker"] for e in remaining] == ["AAPL"]


class TestTags:
    def test_tags_are_kept_with_the_entry(self, client):
        entry = write(client, tags=["thesis", "catalyst"]).json()["entry"]
        assert entry["tags"] == ["thesis", "catalyst"]

    def test_case_is_folded_so_filtering_still_works(self, client):
        # "Risk" and "risk" filtering as two different things would make the
        # filter useless within a week.
        assert write(client, tags=["Risk", "RISK"]).json()["entry"]["tags"] == ["risk"]

    def test_blank_tags_are_dropped(self, client):
        assert write(client, tags=["  ", "risk"]).json()["entry"]["tags"] == ["risk"]

    def test_the_suggested_tags_are_offered_but_not_enforced(self, client):
        body = client.get("/api/journal").json()
        assert body["suggested_tags"] == ["thesis", "risk", "catalyst", "mistake"]
        # A journal nobody can annotate in their own words stops being used.
        assert write(client, tags=["semis-cycle"]).json()["entry"]["tags"] == ["semis-cycle"]


class TestReviewNudge:
    def age(self, owner, entry_id, days):
        from app.engine import connect, q

        when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with connect() as conn:
            conn.execute(
                q("UPDATE journal SET date_written = :d WHERE id = :i"),
                {"d": when, "i": entry_id},
            )

    def test_a_fresh_entry_is_not_nudged(self, client):
        write(client)
        assert client.get("/api/journal").json()["review_due"] == []

    def test_an_old_entry_is_flagged_for_review(self, client):
        # This is what stops the journal becoming a graveyard: an entry is
        # most useful exactly when it has stopped being read.
        entry = write(client).json()["entry"]
        self.age(db.DEFAULT_OWNER, entry["id"], 120)
        assert client.get("/api/journal").json()["review_due"] == [entry["id"]]

    def test_marking_it_reviewed_stops_the_nudge(self, client):
        entry = write(client).json()["entry"]
        self.age(db.DEFAULT_OWNER, entry["id"], 120)
        body = client.post(f"/api/journal/{entry['id']}/reviewed").json()
        assert body["review_due"] == []
        assert body["entries"][0]["reviewedAt"]

    def test_an_entry_just_short_of_the_window_is_left_alone(self, client):
        entry = write(client).json()["entry"]
        self.age(db.DEFAULT_OWNER, entry["id"], journal_router.REVIEW_AFTER_DAYS - 1)
        assert client.get("/api/journal").json()["review_due"] == []

    def test_reviewing_something_already_gone_says_so(self, client):
        assert client.post("/api/journal/nope/reviewed").status_code == 404

    def test_an_unparseable_date_is_not_nudged_about_forever(self, client):
        assert journal_router.is_review_due({"dateWritten": "not a date"}) is False


class TestOwnership:
    def test_entries_are_private_to_their_owner(self, client):
        db.add_journal_entry("space:someone-else", "AAPL", "mine", 100.0, [])
        assert client.get("/api/journal").json()["entries"] == []

    def test_another_owners_entry_cannot_be_deleted(self, client):
        other = db.add_journal_entry("space:someone-else", "AAPL", "mine", 100.0, [])
        client.delete(f"/api/journal/{other['id']}")
        assert db.list_journal("space:someone-else") != []

    def test_signing_in_carries_the_journal_onto_the_account(self, client):
        db.add_journal_entry("space:browser", "AAPL", "thesis", 142.3, ["thesis"])
        moved = db.transfer_owner("space:browser", "user:alice")
        assert moved["journal"] == 1
        carried = db.list_journal("user:alice")
        assert carried[0]["priceAtWrite"] == 142.3
        assert carried[0]["tags"] == ["thesis"]
