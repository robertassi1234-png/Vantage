"""Magic-link authentication.

No passwords are stored, so there is nothing to hash badly, no reset flow, and
a database leak yields no credentials. What it does require is care with the
tokens themselves:

- Tokens are generated with `secrets.token_urlsafe`, not `random`.
- Only a SHA-256 hash is stored. A leaked database cannot be used to sign in.
- Comparison goes through the hash lookup, never a string compare of secrets.
- A link is single-use and short-lived, so an old email in an inbox is inert.
- Requests are rate limited per email so the endpoint can't be used to spam
  someone's inbox.
"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app import db
from app.config import settings
from app.engine import connect, q

# Deliberately permissive: the real proof of ownership is receiving the mail.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SESSION_COOKIE = "vantage_session"
MAX_LINKS_PER_EMAIL_PER_HOUR = 5


class AuthError(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalise_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("That doesn't look like an email address.")
    return email


def request_magic_link(email: str) -> tuple[str, str]:
    """Create a single-use sign-in token. Returns (token, email).

    The caller emails the token; it is never persisted in the clear.
    """
    email = normalise_email(email)
    now = _now()

    with connect() as conn:
        recent = conn.execute(
            q("SELECT COUNT(*) AS n FROM login_tokens WHERE email = :e AND created_at > :t"),
            {"e": email, "t": (now - timedelta(hours=1)).isoformat()},
        ).mappings().first()
        if recent and recent["n"] >= MAX_LINKS_PER_EMAIL_PER_HOUR:
            raise AuthError(
                "Too many sign-in links requested for that address. Try again in an hour."
            )

        token = secrets.token_urlsafe(32)
        conn.execute(
            q(
                "INSERT INTO login_tokens (token_hash, email, created_at, expires_at) "
                "VALUES (:h, :e, :c, :x)"
            ),
            {
                "h": _hash(token),
                "e": email,
                "c": now.isoformat(),
                "x": (now + timedelta(minutes=settings.magic_link_ttl_minutes)).isoformat(),
            },
        )

    return token, email


def redeem_magic_link(token: str) -> tuple[str, str]:
    """Consume a sign-in token. Returns (session_token, user_id)."""
    if not token:
        raise AuthError("That sign-in link is missing its code.")

    now = _now()
    token_hash = _hash(token)

    with connect() as conn:
        row = conn.execute(
            q("SELECT email, expires_at, used_at FROM login_tokens WHERE token_hash = :h"),
            {"h": token_hash},
        ).mappings().first()

        # One message for every failure: a distinct "expired" vs "unknown"
        # reply would confirm which tokens exist.
        if row is None or row["used_at"] is not None:
            raise AuthError("That sign-in link has already been used or is no longer valid.")
        if datetime.fromisoformat(row["expires_at"]) < now:
            raise AuthError("That sign-in link has already been used or is no longer valid.")

        conn.execute(
            q("UPDATE login_tokens SET used_at = :u WHERE token_hash = :h"),
            {"u": now.isoformat(), "h": token_hash},
        )

        email = row["email"]
        user = conn.execute(
            q("SELECT id FROM users WHERE email = :e"), {"e": email}
        ).mappings().first()

        if user is None:
            user_id = uuid.uuid4().hex
            conn.execute(
                q("INSERT INTO users (id, email, created_at, last_login_at) "
                  "VALUES (:i, :e, :c, :c)"),
                {"i": user_id, "e": email, "c": now.isoformat()},
            )
        else:
            user_id = user["id"]
            conn.execute(
                q("UPDATE users SET last_login_at = :t WHERE id = :i"),
                {"t": now.isoformat(), "i": user_id},
            )

        session_token = secrets.token_urlsafe(32)
        conn.execute(
            q(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (:h, :u, :c, :x)"
            ),
            {
                "h": _hash(session_token),
                "u": user_id,
                "c": now.isoformat(),
                "x": (now + timedelta(days=settings.session_ttl_days)).isoformat(),
            },
        )

    return session_token, user_id


def user_for_session(session_token: str | None) -> dict | None:
    """Resolve a session cookie to a user, or None."""
    if not session_token:
        return None

    with connect() as conn:
        row = conn.execute(
            q(
                "SELECT s.user_id, s.expires_at, u.email FROM sessions s "
                "JOIN users u ON u.id = s.user_id WHERE s.token_hash = :h"
            ),
            {"h": _hash(session_token)},
        ).mappings().first()

        if row is None or datetime.fromisoformat(row["expires_at"]) < _now():
            return None
        return {"id": row["user_id"], "email": row["email"]}


def end_session(session_token: str | None) -> None:
    if not session_token:
        return
    with connect() as conn:
        conn.execute(
            q("DELETE FROM sessions WHERE token_hash = :h"), {"h": _hash(session_token)}
        )


def purge_expired() -> None:
    """Drop dead tokens and sessions. Cheap, and keeps the tables small."""
    cutoff = _now().isoformat()
    with connect() as conn:
        conn.execute(q("DELETE FROM login_tokens WHERE expires_at < :t"), {"t": cutoff})
        conn.execute(q("DELETE FROM sessions WHERE expires_at < :t"), {"t": cutoff})


def users_with_pending_alerts() -> list[dict]:
    """Accounts that have an untriggered alert, for the scheduled sweep."""
    with connect() as conn:
        rows = conn.execute(
            q(
                "SELECT DISTINCT u.id, u.email FROM users u "
                "JOIN alerts a ON a.owner_id = 'user:' || u.id "
                "WHERE a.triggered_at IS NULL"
            )
        ).mappings()
        return [dict(r) for r in rows]


def magic_link_url(token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/signin?token={token}"


def owner_for(user: dict | None, space_id: str) -> str:
    """Whose rows to read: the account when signed in, else the browser."""
    return db.user_owner(user["id"]) if user else db.space_owner(space_id)
