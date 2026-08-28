import pytest
from fastapi.testclient import TestClient

from app import alerts as alerts_module
from app import db
from app.main import app

ALICE = {"X-Vantage-Space": "alice-abc123"}
BOB = {"X-Vantage-Space": "bob-xyz789"}

ALICE_OWNER = db.space_owner("alice-abc123")
BOB_OWNER = db.space_owner("bob-xyz789")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def seed(client, headers=ALICE):
    client.post("/api/lists/watch", json={"ticker": "AAPL"}, headers=headers)
    client.post("/api/lists/watch", json={"ticker": "MSFT"}, headers=headers)
    client.post("/api/lists/compare", json={"ticker": "NVDA"}, headers=headers)
    client.put("/api/lists/watch/AAPL/note", json={"note": "waiting for a dip"}, headers=headers)
    client.post(
        "/api/alerts",
        json={"ticker": "AAPL", "direction": "above", "threshold": 320.0},
        headers=headers,
    )


class TestExport:
    def test_includes_both_lists_and_alerts(self, client):
        seed(client)
        body = client.get("/api/export", headers=ALICE).json()

        assert [e["ticker"] for e in body["lists"]["watch"]] == ["AAPL", "MSFT"]
        assert [e["ticker"] for e in body["lists"]["compare"]] == ["NVDA"]
        assert body["alerts"][0]["ticker"] == "AAPL"

    def test_preserves_notes(self, client):
        seed(client)
        body = client.get("/api/export", headers=ALICE).json()
        note = next(e["note"] for e in body["lists"]["watch"] if e["ticker"] == "AAPL")
        assert note == "waiting for a dip"

    def test_exports_only_the_calling_space(self, client):
        seed(client, headers=ALICE)
        body = client.get("/api/export", headers=BOB).json()
        assert body["lists"]["watch"] == []
        assert body["alerts"] == []

    def test_is_stamped_with_a_version(self, client):
        from app.routers.portability import EXPORT_VERSION

        assert client.get("/api/export", headers=ALICE).json()["version"] == EXPORT_VERSION


class TestImport:
    def test_round_trips_into_a_fresh_space(self, client):
        seed(client, headers=ALICE)
        exported = client.get("/api/export", headers=ALICE).json()

        result = client.post("/api/import", json=exported, headers=BOB).json()
        assert result["added"]["watch"] == 2
        assert result["added"]["compare"] == 1
        assert result["alerts_added"] == 1

        assert client.get("/api/lists/watch", headers=BOB).json() == ["AAPL", "MSFT"]
        assert client.get("/api/lists/compare", headers=BOB).json() == ["NVDA"]

    def test_restores_notes(self, client):
        seed(client, headers=ALICE)
        exported = client.get("/api/export", headers=ALICE).json()
        client.post("/api/import", json=exported, headers=BOB)

        entries = client.get("/api/lists/watch/entries", headers=BOB).json()
        note = next(e["note"] for e in entries if e["ticker"] == "AAPL")
        assert note == "waiting for a dip"

    def test_merges_rather_than_replacing_by_default(self, client):
        """Importing on a device that already has tickers must not wipe them."""
        client.post("/api/lists/watch", json={"ticker": "TSLA"}, headers=BOB)
        seed(client, headers=ALICE)
        exported = client.get("/api/export", headers=ALICE).json()

        client.post("/api/import", json=exported, headers=BOB)
        assert set(client.get("/api/lists/watch", headers=BOB).json()) == {
            "TSLA",
            "AAPL",
            "MSFT",
        }

    def test_replace_is_available_but_opt_in(self, client):
        client.post("/api/lists/watch", json={"ticker": "TSLA"}, headers=BOB)
        seed(client, headers=ALICE)
        exported = client.get("/api/export", headers=ALICE).json()

        client.post("/api/import?replace=true", json=exported, headers=BOB)
        assert client.get("/api/lists/watch", headers=BOB).json() == ["AAPL", "MSFT"]

    def test_importing_twice_does_not_duplicate_tickers(self, client):
        seed(client, headers=ALICE)
        exported = client.get("/api/export", headers=ALICE).json()

        client.post("/api/import", json=exported, headers=BOB)
        second = client.post("/api/import", json=exported, headers=BOB).json()

        assert second["added"]["watch"] == 0
        assert client.get("/api/lists/watch", headers=BOB).json() == ["AAPL", "MSFT"]

    def test_a_newer_file_version_is_refused_clearly(self, client):
        resp = client.post(
            "/api/import",
            json={"version": 99, "exported_at": "2026-08-26T00:00:00+00:00", "lists": {}, "alerts": []},
            headers=ALICE,
        )
        assert resp.status_code == 400
        assert "newer version" in resp.json()["detail"]

    def test_an_unknown_list_is_reported_not_silently_dropped(self, client):
        result = client.post(
            "/api/import",
            json={
                "version": 1,
                "exported_at": "2026-08-26T00:00:00+00:00",
                "lists": {"portfolio": [{"ticker": "AAPL"}]},
                "alerts": [],
            },
            headers=ALICE,
        ).json()

        assert any("portfolio" in s for s in result["skipped"])

    def test_a_bad_alert_is_skipped_without_failing_the_import(self, client):
        result = client.post(
            "/api/import",
            json={
                "version": 1,
                "exported_at": "2026-08-26T00:00:00+00:00",
                "lists": {"watch": [{"ticker": "AAPL"}]},
                "alerts": [{"ticker": "MSFT", "direction": "sideways", "threshold": 1}],
            },
            headers=ALICE,
        ).json()

        assert result["added"]["watch"] == 1
        assert result["alerts_added"] == 0
        assert any("MSFT" in s for s in result["skipped"])

    def test_an_empty_file_is_harmless(self, client):
        seed(client, headers=ALICE)
        result = client.post(
            "/api/import",
            json={"version": 1, "exported_at": "2026-08-26T00:00:00+00:00", "lists": {}, "alerts": []},
            headers=ALICE,
        ).json()

        assert result["added"] == {"watch": 0, "compare": 0}
        assert db.get_watchlist(db.space_owner("alice-abc123"), "watch") == ["AAPL", "MSFT"]


class TestDisasterRecovery:
    def test_an_export_survives_losing_the_whole_space(self, client):
        """The scenario this exists for: cleared site data, new browser id."""
        seed(client, headers=ALICE)
        exported = client.get("/api/export", headers=ALICE).json()

        for name in db.LIST_NAMES:
            for ticker in db.get_watchlist(db.space_owner("alice-abc123"), name):
                db.remove_from_watchlist(ticker, "alice-abc123", name)
        for alert in alerts_module.list_alerts("alice-abc123"):
            alerts_module.delete_alert("alice-abc123", alert["id"])

        fresh = {"X-Vantage-Space": "alice-new-browser"}
        client.post("/api/import", json=exported, headers=fresh)

        assert client.get("/api/lists/watch", headers=fresh).json() == ["AAPL", "MSFT"]
        assert len(client.get("/api/alerts", headers=fresh).json()) == 1


class TestLotsTravelToo:
    """A backup that silently drops cost basis is worse than no backup.

    The panel offering this says "move your lists between devices". Someone
    who has entered a year of trades will read that as covering them.
    """

    def test_lots_are_exported_with_the_lists(self, client):
        db.add_lot(ALICE_OWNER, "AAPL", 10, 142.3, "2025-03-04")
        exported = client.get("/api/export", headers=ALICE).json()
        assert exported["lots"] == [
            {
                "ticker": "AAPL",
                "shares": 10.0,
                "costPerShare": 142.3,
                "tradeDate": "2025-03-04",
                "note": None,
            }
        ]

    def test_a_split_is_carried_in_the_restated_lots_not_replayed(self, client):
        # The lots already carry the adjustment. Exporting the split as well
        # and replaying it on import would apply it twice, quartering a basis
        # that was already quartered.
        db.add_lot(ALICE_OWNER, "AAPL", 10, 400.0, "2025-01-01")
        db.apply_split(ALICE_OWNER, "AAPL", 4)

        exported = client.get("/api/export", headers=ALICE).json()
        client.post("/api/import", json=exported, headers=BOB)

        restored = db.list_lots(BOB_OWNER)
        assert restored[0]["shares"] == 40
        assert restored[0]["costPerShare"] == 100.0

    def test_lots_round_trip_onto_another_device(self, client):
        db.add_lot(ALICE_OWNER, "AAPL", 10, 100.0, "2025-01-01")
        db.add_lot(ALICE_OWNER, "AAPL", -4, 180.0, "2025-06-01")

        exported = client.get("/api/export", headers=ALICE).json()
        result = client.post("/api/import", json=exported, headers=BOB).json()

        assert result["lots_added"] == 2
        assert [l["shares"] for l in db.list_lots(BOB_OWNER)] == [10, -4]

    def test_a_v1_file_still_imports_as_a_workspace_without_positions(self, client):
        # Files written before positions existed are still good exports of
        # what existed then.
        legacy = {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
            "lists": {"watch": [{"ticker": "AAPL"}]},
            "alerts": [],
        }
        result = client.post("/api/import", json=legacy, headers=BOB).json()
        assert result["lots_added"] == 0
        assert db.get_watchlist(BOB_OWNER, "watch") == ["AAPL"]

    def test_replace_clears_the_old_positions_first(self, client):
        db.add_lot(BOB_OWNER, "TSLA", 5, 200.0, "2024-01-01")
        db.add_lot(ALICE_OWNER, "AAPL", 10, 100.0, "2025-01-01")

        exported = client.get("/api/export", headers=ALICE).json()
        client.post("/api/import?replace=true", json=exported, headers=BOB)

        assert [l["ticker"] for l in db.list_lots(BOB_OWNER)] == ["AAPL"]
