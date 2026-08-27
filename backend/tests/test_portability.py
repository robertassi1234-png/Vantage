import pytest
from fastapi.testclient import TestClient

from app import alerts as alerts_module
from app import db
from app.main import app

ALICE = {"X-Vantage-Space": "alice-abc123"}
BOB = {"X-Vantage-Space": "bob-xyz789"}


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
        assert client.get("/api/export", headers=ALICE).json()["version"] == 1


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
