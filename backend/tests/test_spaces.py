import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.space import normalise_space

ALICE = {"X-Vantage-Space": "alice-abc123"}
BOB = {"X-Vantage-Space": "bob-xyz789"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestNormaliseSpace:
    def test_missing_header_uses_the_default_space(self):
        assert normalise_space(None) == "default"
        assert normalise_space("") == "default"

    def test_accepts_a_plain_generated_id(self):
        assert normalise_space("a1b2c3-d4e5") == "a1b2c3-d4e5"

    def test_trims_surrounding_whitespace(self):
        assert normalise_space("  abc123  ") == "abc123"

    @pytest.mark.parametrize(
        "hostile",
        [
            "'; DROP TABLE watchlist; --",
            "../../etc/passwd",
            "a" * 65,
            "has spaces",
            "semi;colon",
            "%27",
        ],
    )
    def test_rejects_anything_unexpected(self, hostile):
        # Client-supplied and therefore untrusted: anything outside the
        # expected alphabet falls back rather than reaching a query.
        assert normalise_space(hostile) == "default"


class TestWatchlistIsolation:
    def test_two_spaces_keep_separate_watchlists(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.post("/api/watchlist", json={"ticker": "TSLA"}, headers=BOB)

        assert client.get("/api/watchlist", headers=ALICE).json() == ["AAPL"]
        assert client.get("/api/watchlist", headers=BOB).json() == ["TSLA"]

    def test_removing_in_one_space_leaves_the_other_alone(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=BOB)

        client.delete("/api/watchlist/AAPL", headers=ALICE)

        assert client.get("/api/watchlist", headers=ALICE).json() == []
        assert client.get("/api/watchlist", headers=BOB).json() == ["AAPL"]

    def test_the_same_ticker_can_exist_in_both_spaces(self, client):
        assert client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE).status_code == 200
        assert client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=BOB).status_code == 200

    def test_a_request_without_a_header_gets_the_default_space(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        assert client.get("/api/watchlist").json() == []

    def test_fundamentals_are_scoped_to_the_calling_space(self, client, monkeypatch):
        from app.routers import stocks as stocks_router

        async def fetch(ticker):
            return {"ticker": ticker, "companyName": f"{ticker} Inc."}

        monkeypatch.setattr(stocks_router, "fetch_fundamentals", fetch)
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.post("/api/watchlist", json={"ticker": "TSLA"}, headers=BOB)

        assert [r["ticker"] for r in client.get("/api/fundamentals", headers=ALICE).json()] == ["AAPL"]
        assert [r["ticker"] for r in client.get("/api/fundamentals", headers=BOB).json()] == ["TSLA"]


class TestSharedCache:
    def test_removing_a_ticker_keeps_the_cached_numbers_for_others(self, client):
        """The price of AAPL is the same for everyone.

        Scoping the cache per space would multiply API calls by the number of
        visitors, which is exactly backwards on a 250-call daily budget.
        """
        db.set_cached_fundamentals("AAPL", {"ticker": "AAPL", "peRatio": 35.4})
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.delete("/api/watchlist/AAPL", headers=ALICE)

        assert db.get_cached_fundamentals("AAPL") is not None


class TestNotes:
    def test_a_note_round_trips(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.put("/api/watchlist/AAPL/note", json={"note": "Watching for a dip"}, headers=ALICE)

        [entry] = client.get("/api/watchlist/entries", headers=ALICE).json()
        assert entry["note"] == "Watching for a dip"

    def test_notes_do_not_leak_between_spaces(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=BOB)
        client.put("/api/watchlist/AAPL/note", json={"note": "alice only"}, headers=ALICE)

        [bob_entry] = client.get("/api/watchlist/entries", headers=BOB).json()
        assert bob_entry["note"] is None

    def test_a_note_can_be_cleared(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        client.put("/api/watchlist/AAPL/note", json={"note": "temp"}, headers=ALICE)
        client.put("/api/watchlist/AAPL/note", json={"note": ""}, headers=ALICE)

        [entry] = client.get("/api/watchlist/entries", headers=ALICE).json()
        assert entry["note"] is None

    def test_entries_include_when_the_ticker_was_added(self, client):
        client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=ALICE)
        [entry] = client.get("/api/watchlist/entries", headers=ALICE).json()
        assert entry["added_at"]


class TestMigration:
    def test_a_pre_spaces_table_is_upgraded_in_place(self):
        """An existing database must not lose its watchlist on upgrade."""
        with db.get_conn() as conn:
            conn.execute("DROP TABLE watchlist")
            conn.execute(
                "CREATE TABLE watchlist (ticker TEXT PRIMARY KEY, added_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO watchlist (ticker, added_at) VALUES ('AAPL', '2026-01-01T00:00:00+00:00')"
            )

        db.init_db()

        assert db.get_watchlist("default") == ["AAPL"]
        assert db.get_watchlist("someone-else") == []
