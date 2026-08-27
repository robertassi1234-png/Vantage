"""Magic-link sign-in.

The security properties are the point of these tests: a link works once, dies
on time, and a stolen database yields nothing usable.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import alerts as alerts_module, auth, db, mailer
from app.config import settings
from app.engine import connect, q
from app.main import app

ALICE = {"X-Vantage-Space": "alice-abc123"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def sign_in(client, email="alice@example.com", headers=ALICE, claim_space=True):
    """Sign a client in and leave it holding a session cookie.

    The token is minted directly rather than read out of a response, so this
    works the same whether or not the test has configured a mail provider.
    Delivery itself is covered by TestRequestLink.
    """
    token, _ = auth.request_magic_link(email)
    return client.post(
        "/api/auth/verify", json={"token": token, "claim_space": claim_space}, headers=headers
    )


class TestRequestLink:
    def test_a_link_is_issued_for_a_valid_address(self, client):
        body = client.post("/api/auth/request-link", json={"email": "alice@example.com"}).json()
        assert "dev_link" in body

    def test_a_malformed_address_is_rejected(self, client):
        assert client.post("/api/auth/request-link", json={"email": "nope"}).status_code == 400

    def test_the_raw_token_is_never_stored(self, client):
        """A leaked database must not hand anyone a working sign-in link."""
        body = client.post("/api/auth/request-link", json={"email": "alice@example.com"}).json()
        token = body["dev_link"].split("token=")[1]

        with connect() as conn:
            stored = [r["token_hash"] for r in conn.execute(q("SELECT token_hash FROM login_tokens")).mappings()]

        assert token not in stored
        assert auth._hash(token) in stored

    def test_requests_are_rate_limited_per_address(self, client):
        """Otherwise the endpoint is a free way to flood someone's inbox."""
        for _ in range(auth.MAX_LINKS_PER_EMAIL_PER_HOUR):
            assert client.post("/api/auth/request-link", json={"email": "a@b.com"}).status_code == 200

        assert client.post("/api/auth/request-link", json={"email": "a@b.com"}).status_code == 400

    def test_the_limit_is_per_address_not_global(self, client):
        for _ in range(auth.MAX_LINKS_PER_EMAIL_PER_HOUR):
            client.post("/api/auth/request-link", json={"email": "a@b.com"})

        assert client.post("/api/auth/request-link", json={"email": "c@d.com"}).status_code == 200

    def test_the_dev_link_disappears_once_email_is_configured(self, client, monkeypatch):
        """It exists only so local development can sign in with no mail provider."""
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(mailer, "send", lambda *a, **k: True)

        body = client.post("/api/auth/request-link", json={"email": "alice@example.com"}).json()
        assert "dev_link" not in body
        assert body["sent"] is True

    def test_a_failing_mail_provider_is_reported_not_swallowed(self, client, monkeypatch):
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

        def boom(*a, **k):
            raise mailer.EmailError("connection refused")

        monkeypatch.setattr(mailer, "send", boom)
        assert client.post("/api/auth/request-link", json={"email": "a@b.com"}).status_code == 502


class TestVerify:
    def test_signing_in_reports_the_address(self, client):
        assert sign_in(client).json()["email"] == "alice@example.com"

    def test_me_reflects_the_session(self, client):
        assert client.get("/api/auth/me").json()["signed_in"] is False
        sign_in(client)
        assert client.get("/api/auth/me").json()["email"] == "alice@example.com"

    def test_a_link_works_only_once(self, client):
        body = client.post("/api/auth/request-link", json={"email": "a@b.com"}).json()
        token = body["dev_link"].split("token=")[1]

        assert client.post("/api/auth/verify", json={"token": token}).status_code == 200
        assert client.post("/api/auth/verify", json={"token": token}).status_code == 400

    def test_an_expired_link_is_refused(self, client):
        body = client.post("/api/auth/request-link", json={"email": "a@b.com"}).json()
        token = body["dev_link"].split("token=")[1]

        with connect() as conn:
            conn.execute(
                q("UPDATE login_tokens SET expires_at = :x"),
                {"x": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
            )

        assert client.post("/api/auth/verify", json={"token": token}).status_code == 400

    def test_expired_and_unknown_links_are_indistinguishable(self, client):
        """A different message would confirm which tokens exist."""
        body = client.post("/api/auth/request-link", json={"email": "a@b.com"}).json()
        token = body["dev_link"].split("token=")[1]
        with connect() as conn:
            conn.execute(
                q("UPDATE login_tokens SET expires_at = :x"),
                {"x": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
            )

        expired = client.post("/api/auth/verify", json={"token": token}).json()["detail"]
        unknown = client.post("/api/auth/verify", json={"token": "made-up"}).json()["detail"]
        assert expired == unknown

    def test_signing_in_twice_reuses_the_account(self, client):
        sign_in(client)
        client.post("/api/auth/signout")
        sign_in(client)

        with connect() as conn:
            count = conn.execute(q("SELECT COUNT(*) AS n FROM users")).mappings().first()["n"]
        assert count == 1

    def test_the_session_cookie_is_not_readable_by_javascript(self, client):
        response = sign_in(client)
        assert "httponly" in response.headers["set-cookie"].lower()

    def test_signing_out_ends_the_session(self, client):
        sign_in(client)
        client.post("/api/auth/signout")
        assert client.get("/api/auth/me").json()["signed_in"] is False

    def test_a_session_from_a_deleted_row_stops_working(self, client):
        sign_in(client)
        with connect() as conn:
            conn.execute(q("DELETE FROM sessions"))
        assert client.get("/api/auth/me").json()["signed_in"] is False


class TestClaimingAnonymousData:
    def test_the_browser_list_moves_onto_the_account(self, client):
        client.post("/api/lists/watch", json={"ticker": "AAPL"}, headers=ALICE)
        assert sign_in(client).json()["claimed"]["watchlist"] == 1
        assert client.get("/api/lists/watch", headers=ALICE).json() == ["AAPL"]

    def test_declining_to_claim_leaves_the_browser_list_alone(self, client):
        client.post("/api/lists/watch", json={"ticker": "AAPL"}, headers=ALICE)
        sign_in(client, claim_space=False)

        assert client.get("/api/lists/watch", headers=ALICE).json() == []
        client.post("/api/auth/signout")
        assert client.get("/api/lists/watch", headers=ALICE).json() == ["AAPL"]

    def test_a_second_device_does_not_clobber_the_account_list(self, client):
        """Signing in on a fresh browser must not erase what the account holds."""
        client.post("/api/lists/watch", json={"ticker": "AAPL"}, headers=ALICE)
        sign_in(client)
        client.post("/api/auth/signout")

        other = {"X-Vantage-Space": "alice-phone"}
        client.post("/api/lists/watch", json={"ticker": "MSFT"}, headers=other)
        sign_in(client, headers=other)

        assert sorted(client.get("/api/lists/watch", headers=other).json()) == ["AAPL", "MSFT"]

    def test_alerts_are_claimed_too(self, client):
        client.post(
            "/api/alerts",
            json={"ticker": "AAPL", "direction": "above", "threshold": 300},
            headers=ALICE,
        )
        assert sign_in(client).json()["claimed"]["alerts"] == 1
        assert len(client.get("/api/alerts", headers=ALICE).json()) == 1

    def test_the_same_list_appears_on_a_different_browser(self, client):
        """The whole point of accounts: another device, same watchlist."""
        client.post("/api/lists/watch", json={"ticker": "AAPL"}, headers=ALICE)
        sign_in(client)

        assert client.get(
            "/api/lists/watch", headers={"X-Vantage-Space": "some-other-browser"}
        ).json() == ["AAPL"]


class TestSignedOutIsolation:
    def test_one_account_cannot_see_another(self, client):
        sign_in(client, email="alice@example.com")
        client.post("/api/lists/watch", json={"ticker": "AAPL"})
        client.post("/api/auth/signout")

        sign_in(client, email="bob@example.com", headers={"X-Vantage-Space": "bob-1"})
        assert client.get("/api/lists/watch").json() == []


class TestHousekeeping:
    def test_purge_drops_dead_rows_and_keeps_live_ones(self, client):
        sign_in(client)
        client.post("/api/auth/request-link", json={"email": "live@example.com"})

        with connect() as conn:
            conn.execute(
                q("INSERT INTO login_tokens (token_hash, email, created_at, expires_at) "
                  "VALUES ('dead', 'x@y.com', '2020-01-01T00:00:00+00:00', "
                  "'2020-01-01T00:00:00+00:00')")
            )

        auth.purge_expired()

        with connect() as conn:
            rows = conn.execute(q("SELECT token_hash FROM login_tokens")).mappings().all()
            sessions = conn.execute(q("SELECT COUNT(*) AS n FROM sessions")).mappings().first()

        assert "dead" not in {r["token_hash"] for r in rows}
        # The used sign-in token and the unused one both survive: purging is
        # about expiry, and a used token is already inert.
        assert len(rows) == 2
        assert sessions["n"] == 1


class TestSetupReadiness:
    """Two ways a deployment can look fine and quietly lose accounts."""

    def test_temporary_storage_is_reported(self, client):
        """SQLite on a free instance is wiped by the next deploy."""
        body = client.get("/api/auth/me").json()
        assert body["durable_storage"] is False
        assert body["accounts_available"] is False
        assert "DATABASE_URL" in body["reason"]

    def test_a_wildcard_origin_disables_sign_in(self, client, monkeypatch):
        """Cookies plus any-origin would let any site read the watchlist."""
        monkeypatch.setattr(settings, "cors_origins", "*")
        body = client.get("/api/auth/me").json()
        assert body["accounts_available"] is False
        assert "CORS_ORIGINS" in body["reason"]

    def test_a_configured_server_reports_ready(self, client, monkeypatch):
        monkeypatch.setattr(settings, "cors_origins", "https://vantage.example.com")
        monkeypatch.setattr("app.routers.auth.is_postgres", lambda: True)

        body = client.get("/api/auth/me").json()
        assert body["accounts_available"] is True
        assert body["reason"] is None

    def test_email_delivery_is_reported_separately(self, client, monkeypatch):
        assert client.get("/api/auth/me").json()["email_delivery"] is False
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        assert client.get("/api/auth/me").json()["email_delivery"] is True


class TestCorsOrigins:
    def test_a_bare_hostname_is_read_as_https(self, monkeypatch):
        """What someone pastes when copying their site's address."""
        monkeypatch.setattr(settings, "cors_origins", "vantage.onrender.com")
        assert settings.cors_origin_list == ["https://vantage.onrender.com"]

    def test_a_trailing_slash_is_tolerated(self, monkeypatch):
        monkeypatch.setattr(settings, "cors_origins", "https://vantage.onrender.com/")
        assert settings.cors_origin_list == ["https://vantage.onrender.com"]

    def test_a_wildcard_never_allows_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "cors_origins", "*")
        assert settings.allows_credentialed_cors is False

    def test_naming_an_origin_allows_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "cors_origins", "https://a.com, http://localhost:5173")
        assert settings.allows_credentialed_cors is True
        assert settings.cors_origin_list == ["https://a.com", "http://localhost:5173"]
