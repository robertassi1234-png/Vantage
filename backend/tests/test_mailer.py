"""Email delivery.

The transport matters more than it looks. Hosting providers block outbound
SMTP ports to deter spam, and most free tiers do, so a send that is perfectly
configured still times out. These pin the behaviour that HTTPS is used when it
can be, that SMTP still works where it is allowed, and that a failure says
something an operator can act on.
"""

import httpx
import pytest

from app import mailer
from app.config import settings


@pytest.fixture
def resend(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "email_from", "Vantage <alerts@example.com>")


def capture(monkeypatch, status=200, body=None):
    """Record the HTTPS request instead of making it."""
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, json=json, timeout=timeout)
        return httpx.Response(status, json=body if body is not None else {"id": "abc"})

    monkeypatch.setattr(mailer.httpx, "post", fake_post)
    return sent


class TestTransportChoice:
    def test_https_is_used_when_a_key_is_available(self, monkeypatch, resend):
        sent = capture(monkeypatch)

        def no_smtp(*a, **k):
            raise AssertionError("SMTP must not be used when HTTPS is available")

        monkeypatch.setattr(mailer.smtplib, "SMTP", no_smtp)
        assert mailer.send("a@b.com", "hi", "body") is True
        assert sent["url"] == mailer.RESEND_ENDPOINT

    def test_an_existing_smtp_setup_supplies_the_key(self, monkeypatch):
        """A deployment timing out on a blocked port starts working untouched.

        The Resend key is already present as the SMTP password; there is no
        reason to make someone paste it a second time under another name.
        """
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(settings, "smtp_host", "smtp.resend.com")
        monkeypatch.setattr(settings, "smtp_password", "re_from_smtp")

        assert mailer.resend_api_key() == "re_from_smtp"

    def test_another_provider_is_left_on_smtp(self, monkeypatch):
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(settings, "smtp_host", "smtp.sendgrid.net")
        monkeypatch.setattr(settings, "smtp_password", "SG.something")

        assert mailer.resend_api_key() == ""

    def test_a_resend_host_without_a_key_shaped_password_stays_on_smtp(self, monkeypatch):
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(settings, "smtp_host", "smtp.resend.com")
        monkeypatch.setattr(settings, "smtp_password", "not-an-api-key")

        assert mailer.resend_api_key() == ""

    def test_an_explicit_key_wins_over_the_smtp_password(self, monkeypatch):
        monkeypatch.setattr(settings, "resend_api_key", "re_explicit")
        monkeypatch.setattr(settings, "smtp_host", "smtp.resend.com")
        monkeypatch.setattr(settings, "smtp_password", "re_from_smtp")

        assert mailer.resend_api_key() == "re_explicit"

    def test_nothing_configured_still_logs_rather_than_sending(self, monkeypatch):
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(settings, "smtp_host", "")
        assert mailer.send("a@b.com", "hi", "body") is False

    def test_a_key_alone_counts_as_configured(self, monkeypatch, resend):
        assert mailer.is_configured() is True


class TestTheRequest:
    def test_it_carries_the_key_as_a_bearer_token(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send("a@b.com", "hi", "body")
        assert sent["headers"]["Authorization"] == "Bearer re_test_key"

    def test_it_sends_the_address_subject_and_text(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send("a@b.com", "Your link", "click here")

        assert sent["json"]["to"] == ["a@b.com"]
        assert sent["json"]["subject"] == "Your link"
        assert sent["json"]["text"] == "click here"
        assert sent["json"]["from"] == "Vantage <alerts@example.com>"

    def test_html_is_included_when_there_is_some(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send("a@b.com", "hi", "text", html="<p>rich</p>")
        assert sent["json"]["html"] == "<p>rich</p>"

    def test_no_html_key_when_there_is_none(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send("a@b.com", "hi", "text")
        assert "html" not in sent["json"]

    def test_it_does_not_hang_forever(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send("a@b.com", "hi", "body")
        assert sent["timeout"] == 15

    def test_the_sign_in_link_goes_out_over_https(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send_magic_link("a@b.com", "https://vantage.example/signin?token=abc")
        assert "signin?token=abc" in sent["json"]["text"]

    def test_an_alert_goes_out_over_https(self, monkeypatch, resend):
        sent = capture(monkeypatch)
        mailer.send_alert("a@b.com", "AAPL", "above", 320.0, 331.25)
        assert "AAPL" in sent["json"]["subject"]
        assert "331.25" in sent["json"]["text"]


class TestFailures:
    def test_the_providers_own_reason_is_surfaced(self, monkeypatch, resend):
        """"Domain not verified" and "bad key" need different fixes."""
        capture(monkeypatch, status=403, body={"message": "The domain is not verified."})

        with pytest.raises(mailer.EmailError, match="domain is not verified"):
            mailer.send("a@b.com", "hi", "body")

    def test_an_unparseable_error_still_reports_the_status(self, monkeypatch, resend):
        def fake_post(url, headers=None, json=None, timeout=None):
            return httpx.Response(500, text="<html>oops</html>")

        monkeypatch.setattr(mailer.httpx, "post", fake_post)
        with pytest.raises(mailer.EmailError, match="500"):
            mailer.send("a@b.com", "hi", "body")

    def test_an_unreachable_service_is_an_email_error(self, monkeypatch, resend):
        def boom(*a, **k):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(mailer.httpx, "post", boom)
        with pytest.raises(mailer.EmailError, match="Couldn't reach"):
            mailer.send("a@b.com", "hi", "body")

    def test_a_blocked_smtp_port_names_the_way_out(self, monkeypatch):
        """The failure that started this: a timeout tells an operator nothing.

        A blocked port is not a credentials problem and no retry fixes it, so
        the message points at the transport that does work.
        """
        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(settings, "smtp_port", 587)

        def timeout(*a, **k):
            raise TimeoutError("timed out")

        monkeypatch.setattr(mailer.smtplib, "SMTP", timeout)
        with pytest.raises(mailer.EmailError, match="RESEND_API_KEY"):
            mailer.send("a@b.com", "hi", "body")
