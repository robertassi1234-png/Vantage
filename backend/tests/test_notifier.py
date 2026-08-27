"""Alert delivery.

The rule these protect: a crossing is emailed once, to the right address, and
a mail failure never loses the alert.
"""

import pytest
from fastapi.testclient import TestClient

from app import alerts as alerts_module, db, mailer, notifier
from app.config import settings
from app.fmp_client import FMPError
from app.main import app
from tests.test_auth import sign_in

ALICE = {"X-Vantage-Space": "alice-abc123"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound mail instead of sending it."""
    outbox = []

    def fake_send(to, subject, body):
        outbox.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mailer, "send", fake_send)
    return outbox


def priced(price):
    async def quotes(symbols):
        return [{"symbol": symbol, "price": price} for symbol in symbols]

    return quotes


def make_alert(client, headers=ALICE, threshold=320, direction="above"):
    return client.post(
        "/api/alerts",
        json={"ticker": "AAPL", "direction": direction, "threshold": threshold},
        headers=headers,
    ).json()


class TestEmailOnCheck:
    def test_a_signed_in_reader_is_emailed(self, client, monkeypatch, sent):
        sign_in(client)
        make_alert(client)
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))

        body = client.post("/api/alerts/check", headers=ALICE).json()

        assert body["emailed"] == 1
        assert sent[0]["to"] == "alice@example.com"
        assert "AAPL" in sent[0]["subject"]

    def test_an_anonymous_reader_still_gets_the_alert_just_no_email(
        self, client, monkeypatch, sent
    ):
        """No account means no address; the alert fires in the UI regardless."""
        make_alert(client)
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))

        body = client.post("/api/alerts/check", headers=ALICE).json()

        assert len(body["fired"]) == 1
        assert body["emailed"] == 0
        assert sent == []

    def test_an_uncrossed_alert_sends_nothing(self, client, monkeypatch, sent):
        sign_in(client)
        make_alert(client)
        monkeypatch.setattr(notifier, "fetch_quotes", priced(310.0))

        client.post("/api/alerts/check", headers=ALICE)
        assert sent == []

    def test_a_crossing_is_emailed_once_not_on_every_page_load(
        self, client, monkeypatch, sent
    ):
        """The alert stays triggered, so re-checking must not re-mail."""
        sign_in(client)
        make_alert(client)
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))

        client.post("/api/alerts/check", headers=ALICE)
        client.post("/api/alerts/check", headers=ALICE)

        assert len(sent) == 1

    def test_a_mail_failure_does_not_lose_the_alert(self, client, monkeypatch):
        """The crossing is real whether or not the email got out."""
        sign_in(client)
        make_alert(client)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

        def boom(*a, **k):
            raise mailer.EmailError("mailbox full")

        monkeypatch.setattr(mailer, "send", boom)
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))

        body = client.post("/api/alerts/check", headers=ALICE).json()

        assert len(body["fired"]) == 1
        assert body["emailed"] == 0
        assert body["alerts"][0]["triggered_at"] is not None

    def test_a_price_lookup_failure_still_returns_the_alerts(self, client, monkeypatch):
        make_alert(client)

        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(notifier, "fetch_quotes", boom)
        body = client.post("/api/alerts/check", headers=ALICE).json()

        assert len(body["alerts"]) == 1
        assert "rate limited" in body["error"]


class TestSweep:
    def test_the_secret_is_required(self, client, monkeypatch):
        monkeypatch.setattr(settings, "cron_secret", "s3cret")
        assert client.post("/api/notify/sweep").status_code == 401
        assert (
            client.post("/api/notify/sweep", headers={"X-Cron-Secret": "wrong"}).status_code
            == 401
        )

    def test_an_unconfigured_server_says_so_rather_than_running(self, client, monkeypatch):
        monkeypatch.setattr(settings, "cron_secret", "")
        assert client.post("/api/notify/sweep").status_code == 503

    def test_it_fires_alerts_nobody_has_the_app_open_for(
        self, client, monkeypatch, sent
    ):
        """The reason the sweep exists at all."""
        sign_in(client)
        make_alert(client)
        client.post("/api/auth/signout")

        monkeypatch.setattr(settings, "cron_secret", "s3cret")
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))

        body = client.post(
            "/api/notify/sweep", headers={"X-Cron-Secret": "s3cret"}
        ).json()

        assert body["fired"] == 1
        assert body["emailed"] == 1
        assert sent[0]["to"] == "alice@example.com"

    def test_a_second_sweep_does_not_remail(self, client, monkeypatch, sent):
        sign_in(client)
        make_alert(client)
        monkeypatch.setattr(settings, "cron_secret", "s3cret")
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))

        headers = {"X-Cron-Secret": "s3cret"}
        client.post("/api/notify/sweep", headers=headers)
        second = client.post("/api/notify/sweep", headers=headers).json()

        assert second["fired"] == 0
        assert len(sent) == 1

    def test_one_account_is_never_mailed_another_accounts_alert(
        self, client, monkeypatch, sent
    ):
        sign_in(client, email="alice@example.com")
        make_alert(client, threshold=320)
        client.post("/api/auth/signout")

        sign_in(client, email="bob@example.com", headers={"X-Vantage-Space": "bob-1"})
        client.post(
            "/api/alerts",
            json={"ticker": "MSFT", "direction": "above", "threshold": 100},
            headers={"X-Vantage-Space": "bob-1"},
        )
        client.post("/api/auth/signout")

        monkeypatch.setattr(settings, "cron_secret", "s3cret")
        monkeypatch.setattr(notifier, "fetch_quotes", priced(330.0))
        client.post("/api/notify/sweep", headers={"X-Cron-Secret": "s3cret"})

        by_address = {mail["to"]: mail["subject"] for mail in sent}
        assert "AAPL" in by_address["alice@example.com"]
        assert "MSFT" in by_address["bob@example.com"]

    def test_a_provider_outage_is_reported_once_not_per_owner(
        self, client, monkeypatch, sent
    ):
        for email, space in (("a@b.com", "s1"), ("c@d.com", "s2")):
            sign_in(client, email=email, headers={"X-Vantage-Space": space})
            make_alert(client, headers={"X-Vantage-Space": space})
            client.post("/api/auth/signout")

        async def boom(symbols):
            raise FMPError("rate limited")

        monkeypatch.setattr(settings, "cron_secret", "s3cret")
        monkeypatch.setattr(notifier, "fetch_quotes", boom)

        body = client.post(
            "/api/notify/sweep", headers={"X-Cron-Secret": "s3cret"}
        ).json()

        assert body["errors"] == ["rate limited"]
        assert body["fired"] == 0


class TestEmailBody:
    def test_a_below_alert_reads_as_a_fall_not_a_rise(self, client, monkeypatch, sent):
        sign_in(client)
        make_alert(client, direction="below", threshold=320)
        monkeypatch.setattr(notifier, "fetch_quotes", priced(310.0))

        client.post("/api/alerts/check", headers=ALICE)

        assert "fallen below" in sent[0]["subject"]
        assert "310" in sent[0]["body"]

    def test_an_unconfigured_server_logs_instead_of_sending(self, client, monkeypatch):
        """Local development and the test suite must never actually mail anyone."""
        monkeypatch.setattr(settings, "smtp_host", "")
        assert mailer.send("a@b.com", "hi", "body") is False
