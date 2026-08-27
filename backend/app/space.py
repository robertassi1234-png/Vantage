"""Who a request's data belongs to.

Signed-in requests key on the account, so the same lists appear on every
device. Anonymous requests keep the old per-browser behaviour, so the app
still works without signing up and nobody's existing list disappears.

Both resolve to one `owner_id` string, which is why the watchlist, alert and
comparison routes needed no branching of their own.
"""

import re

from fastapi import Cookie, Header

from app import auth, db

SPACE_HEADER = "X-Vantage-Space"
# Space ids are client-supplied: bound the length and alphabet before they
# reach a query.
VALID_SPACE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def normalise_space(raw: str | None) -> str:
    if not raw:
        return db.DEFAULT_SPACE
    raw = raw.strip()
    return raw if VALID_SPACE.match(raw) else db.DEFAULT_SPACE


async def current_space(x_vantage_space: str | None = Header(default=None)) -> str:
    """The anonymous browser id, regardless of sign-in state."""
    return normalise_space(x_vantage_space)


async def current_user(vantage_session: str | None = Cookie(default=None)) -> dict | None:
    return auth.user_for_session(vantage_session)


async def current_owner(
    x_vantage_space: str | None = Header(default=None),
    vantage_session: str | None = Cookie(default=None),
) -> str:
    """The owner key every data route should read and write under."""
    user = auth.user_for_session(vantage_session)
    if user:
        return db.user_owner(user["id"])
    return db.space_owner(normalise_space(x_vantage_space))
