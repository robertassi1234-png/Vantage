import pytest
from fastapi.testclient import TestClient

from app import alerts as alerts_module
from app.fmp_client import FMPError
from app.main import app
from app import notifier

ALICE = {"X-Vantage-Space": "alice-abc123"}
BOB = {"X-Vantage-Space": "bob-xyz789"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make(client, ticker="AAPL", direction="above", threshold=320.0, headers=ALICE):
    return client.post(
        "/api/alerts",
        json={"ticker": ticker, "direction": direction, "threshold": threshold},
        headers=headers,
    )


class TestValidation:
    def test_rejects_an_unknown_direction(self, client):
        resp = make(client, direction="sideways")
        assert resp.status_code == 400
        assert "above" in resp.json()["detail"]

    @pytest.mark.parametrize("bad", [0, -5])
    def test_rejects_a_non_positive_threshold(self, client, bad):
        assert make(client, threshold=bad).status_code == 400

    def test_rejects_a_blank_ticker(self, client):
        assert make(client, ticker="  ").status_code == 400

    def test_normalises_the_ticker(self, client):
        assert make(client, ticker=" aapl ").json()["ticker"] == "AAPL"


class TestEvaluation:
    def test_above_fires_once_the_price_crosses(self):
        alerts_module.create_alert("s", "AAPL", "above", 320)
        assert alerts_module.evaluate("s", {"AAPL": 319}) == []

        [fired] = alerts_module.evaluate("s", {"AAPL": 321})
        assert fired["ticker"] == "AAPL"
        assert fired["triggered_price"] == 321

    def test_below_fires_once_the_price_drops(self):
        alerts_module.create_alert("s", "AAPL", "below", 300)
        assert alerts_module.evaluate("s", {"AAPL": 301}) == []
        assert len(alerts_module.evaluate("s", {"AAPL": 299})) == 1

    def test_exact_threshold_counts_as_crossed(self):
        alerts_module.create_alert("s", "AAPL", "above", 320)
        assert len(alerts_module.evaluate("s", {"AAPL": 320})) == 1

    def test_an_alert_fires_only_once(self):
        """Otherwise every page load re-announces a price sitting past the line."""
        alerts_module.create_alert("s", "AAPL", "above", 320)
        assert len(alerts_module.evaluate("s", {"AAPL": 330})) == 1
        assert alerts_module.evaluate("s", {"AAPL": 340}) == []

    def test_a_missing_price_leaves_the_alert_pending(self):
        alerts_module.create_alert("s", "AAPL", "above", 320)
        assert alerts_module.evaluate("s", {}) == []
        assert alerts_module.list_alerts("s")[0]["triggered_at"] is None

    def test_a_non_numeric_price_is_ignored(self):
        alerts_module.create_alert("s", "AAPL", "above", 320)
        assert alerts_module.evaluate("s", {"AAPL": None}) == []

    def test_only_pending_tickers_need_quotes(self):
        alerts_module.create_alert("s", "AAPL", "above", 320)
        alerts_module.create_alert("s", "MSFT", "above", 500)
        alerts_module.evaluate("s", {"AAPL": 330})

        # AAPL has fired, so re-checking it would be a wasted API call.
        assert alerts_module.alert_tickers("s") == ["MSFT"]

    def test_alerts_do_not_leak_between_spaces(self):
        alerts_module.create_alert("alice", "AAPL", "above", 320)
        assert alerts_module.evaluate("bob", {"AAPL": 999}) == []


class TestRoutes:
    def test_created_alerts_are_listed(self, client):
        make(client)
        assert len(client.get("/api/alerts", headers=ALICE).json()) == 1

    def test_alerts_are_scoped_to_a_space(self, client):
        make(client, headers=ALICE)
        assert client.get("/api/alerts", headers=BOB).json() == []

    def test_delete_removes_it(self, client):
        alert_id = make(client).json()["id"]
        assert client.delete(f"/api/alerts/{alert_id}", headers=ALICE).json() == []

    def test_one_space_cannot_delete_anothers_alert(self, client):
        alert_id = make(client, headers=ALICE).json()["id"]
        client.delete(f"/api/alerts/{alert_id}", headers=BOB)
        assert len(client.get("/api/alerts", headers=ALICE).json()) == 1

    def test_acknowledge_marks_it_seen(self, client):
        alert_id = make(client).json()["id"]
        [alert] = client.post(f"/api/alerts/{alert_id}/acknowledge", headers=ALICE).json()
        assert alert["acknowledged"] is True

    def test_acknowledging_a_missing_alert_is_404(self, client):
        assert client.post("/api/alerts/nope/acknowledge", headers=ALICE).status_code == 404


class TestCheckRoute:
    def test_no_alerts_means_no_quote_lookup(self, client, monkeypatch):
        async def explode(symbols):
            raise AssertionError("should not fetch quotes with nothing pending")

        monkeypatch.setattr(notifier, "fetch_quotes", explode)
        body = client.post("/api/alerts/check", headers=ALICE).json()
        assert body == {"fired": [], "alerts": [], "checked": 0, "emailed": 0, "error": None}

    def test_a_crossed_alert_fires(self, client, monkeypatch):
        make(client, threshold=320)

        async def quotes(symbols):
            return [{"symbol": "AAPL", "price": 330.0}]

        monkeypatch.setattr(notifier, "fetch_quotes", quotes)
        body = client.post("/api/alerts/check", headers=ALICE).json()

        assert [a["ticker"] for a in body["fired"]] == ["AAPL"]
        assert body["checked"] == 1

    def test_an_uncrossed_alert_does_not_fire(self, client, monkeypatch):
        make(client, threshold=320)

        async def quotes(symbols):
            return [{"symbol": "AAPL", "price": 310.0}]

        monkeypatch.setattr(notifier, "fetch_quotes", quotes)
        assert client.post("/api/alerts/check", headers=ALICE).json()["fired"] == []

    def test_a_price_lookup_failure_still_returns_the_alerts(self, client, monkeypatch):
        """The list is local; only the crossing check needs the network."""
        make(client)

        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(notifier, "fetch_quotes", boom)
        body = client.post("/api/alerts/check", headers=ALICE).json()

        assert len(body["alerts"]) == 1
        assert "rate limited" in body["error"]
