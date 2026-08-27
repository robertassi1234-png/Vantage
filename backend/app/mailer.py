"""Outbound email over plain SMTP.

SMTP rather than a vendor SDK so Resend, SendGrid, Mailgun, Postmark or a
personal Gmail all work by changing environment variables, with no code change
and no library pinned to one provider.

With SMTP_HOST unset, messages are logged instead of sent. That keeps local
development and the whole test suite free of signups and of any risk of
actually mailing someone.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger(__name__)


class EmailError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.smtp_host)


def send(to: str, subject: str, body: str) -> bool:
    """Send one plain-text message. Returns True if it actually went out."""
    if not is_configured():
        log.info(
            "Email not configured; would have sent to %s\nSubject: %s\n%s", to, subject, body
        )
        return False

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, context=ssl.create_default_context()
            ) as server:
                _login_and_send(server, message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.starttls(context=ssl.create_default_context())
                _login_and_send(server, message)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"Couldn't send email: {e}") from e

    return True


def _login_and_send(server, message: EmailMessage) -> None:
    if settings.smtp_user:
        server.login(settings.smtp_user, settings.smtp_password)
    server.send_message(message)


def send_magic_link(to: str, url: str) -> bool:
    return send(
        to,
        "Your Vantage sign-in link",
        (
            "Click the link below to sign in to Vantage:\n\n"
            f"{url}\n\n"
            f"The link works once and expires in {settings.magic_link_ttl_minutes} minutes.\n"
            "If you didn't ask to sign in, you can ignore this email — "
            "nobody can get into your account without this link."
        ),
    )


def send_alert(to: str, ticker: str, direction: str, threshold: float, price: float) -> bool:
    movement = "risen above" if direction == "above" else "fallen below"
    return send(
        to,
        f"{ticker} has {movement} ${threshold:,.2f}",
        (
            f"{ticker} has {movement} your target of ${threshold:,.2f}.\n\n"
            f"Latest price: ${price:,.2f}\n\n"
            "This alert has now been cleared, so you won't be emailed about it again. "
            "Set a new one in Vantage if you want to keep watching.\n\n"
            "This is a price notification, not investment advice."
        ),
    )
