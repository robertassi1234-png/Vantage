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
from html import escape

from app.config import settings

log = logging.getLogger(__name__)


class EmailError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.smtp_host)


def send(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """Send one message. Returns True if it actually went out.

    The plain-text body is always the real message; `html` is an alternative
    the client may prefer. It exists so a sign-in link arrives as something to
    click rather than a wrapped URL to copy out by hand.
    """
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
    if html:
        message.add_alternative(html, subtype="html")

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
    minutes = settings.magic_link_ttl_minutes
    return send(
        to,
        "Your Vantage sign-in link",
        (
            "Click the link below to sign in to Vantage:\n\n"
            f"{url}\n\n"
            f"The link works once and expires in {minutes} minutes.\n"
            "If you didn't ask to sign in, you can ignore this email — "
            "nobody can get into your account without this link."
        ),
        html=_layout(
            "Sign in to Vantage",
            f'''<p style="margin:0 0 24px">Click the button below to sign in.</p>
            <p style="margin:0 0 24px">
              <a href="{escape(url)}" style="display:inline-block;padding:12px 22px;
                 background:#4f46e5;color:#ffffff;text-decoration:none;border-radius:8px;
                 font-weight:600">Sign in to Vantage</a>
            </p>
            <p style="margin:0 0 8px;color:#6b7080;font-size:13px">
              The link works once and expires in {minutes} minutes.
            </p>
            <p style="margin:0;color:#6b7080;font-size:13px">
              If you didn\u2019t ask to sign in, you can ignore this email — nobody can get
              into your account without this link.
            </p>''',
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
        html=_layout(
            f"{escape(ticker)} has {movement} ${threshold:,.2f}",
            f'''<p style="margin:0 0 8px;font-size:28px;font-weight:700">${price:,.2f}</p>
            <p style="margin:0 0 24px;color:#6b7080">
              {escape(ticker)} has {movement} your target of ${threshold:,.2f}.
            </p>
            <p style="margin:0 0 8px;color:#6b7080;font-size:13px">
              This alert has now been cleared, so you won\u2019t be emailed about it again.
              Set a new one in Vantage if you want to keep watching.
            </p>
            <p style="margin:0;color:#9195a3;font-size:12px">
              This is a price notification, not investment advice.
            </p>''',
        ),
    )


def _layout(heading: str, body_html: str) -> str:
    """One plain card. Inline styles only, since mail clients drop stylesheets."""
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,'
        'Helvetica,Arial,sans-serif;background:#f3f4f8;padding:32px 16px">'
        '<div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:16px;'
        'padding:32px;color:#14161f;line-height:1.6">'
        f'<h1 style="margin:0 0 20px;font-size:20px;font-weight:700">{heading}</h1>'
        f"{body_html}"
        '<p style="margin:28px 0 0;padding-top:16px;border-top:1px solid #e6e8f0;'
        'color:#9195a3;font-size:12px">Vantage</p>'
        "</div></div>"
    )
