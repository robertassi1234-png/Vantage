import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from app import auth, db, mailer
from app.config import settings
from app.engine import is_postgres
from app.space import current_space

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)


class EmailRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    token: str
    # Adopt whatever this browser saved before signing in.
    claim_space: bool = True


class MeResponse(BaseModel):
    signed_in: bool
    email: str | None = None
    # What the server can actually do, so the UI never promises something the
    # deployment isn't set up for.
    accounts_available: bool
    durable_storage: bool
    email_delivery: bool
    reason: str | None = None


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_local_development() -> bool:
    """Whether this server is someone's own machine rather than a real site.

    Judged by where sign-in links point, since that is the address a person
    actually browses to. A deployment always sets it to its public URL.
    """
    try:
        host = urlparse(settings.app_base_url).hostname or ""
    except ValueError:
        return False
    return host in LOCAL_HOSTS


@router.get("/me")
def me(
    vantage_session: str | None = Cookie(default=None),
) -> MeResponse:
    user = auth.user_for_session(vantage_session)
    durable = is_postgres()
    available = settings.allows_credentialed_cors

    # Two ways a deployment can look fine and lose accounts anyway: a cookie
    # the browser refuses to send cross-origin, and a database that is wiped
    # by the next deploy. Better to say so than to sign someone in and forget.
    reason = None
    if not available:
        reason = (
            "Sign-in is off because this server accepts requests from any address. "
            "Set CORS_ORIGINS to your site's address to turn it on."
        )
    elif not durable:
        reason = (
            "This server is using temporary storage, so accounts would be lost on the "
            "next restart. Set DATABASE_URL to a Postgres connection string."
        )
        available = False

    return MeResponse(
        signed_in=user is not None,
        email=user["email"] if user else None,
        accounts_available=available,
        durable_storage=durable,
        # Lets the UI say plainly whether alert emails can actually be sent.
        email_delivery=mailer.is_configured(),
        reason=reason,
    )


@router.post("/request-link")
def request_link(req: EmailRequest) -> dict:
    try:
        token, email = auth.request_magic_link(req.email)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    url = auth.magic_link_url(token)
    try:
        delivered = mailer.send_magic_link(email, url)
    except mailer.EmailError as e:
        log.warning("magic link email failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Couldn't send the sign-in email just now. Please try again shortly.",
        ) from e

    response: dict = {
        "sent": delivered,
        "message": (
            f"Check {email} for your sign-in link."
            if delivered
            else "Email isn't configured on this server, so the link is in the server logs."
        ),
    }
    # Handing the link back in the response is what makes local development
    # possible without a mail account. It must never happen on a public
    # server: the endpoint takes any address and returns a working sign-in
    # link for it, so exposing it would let anyone sign in as anyone.
    if not delivered and is_local_development():
        response["dev_link"] = url
    return response


@router.post("/verify")
def verify(
    req: TokenRequest,
    response: Response,
    space: str = Depends(current_space),
) -> dict:
    try:
        session_token, user_id = auth.redeem_magic_link(req.token)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    moved = {"watchlist": 0, "alerts": 0}
    if req.claim_space:
        moved = db.transfer_owner(db.space_owner(space), db.user_owner(user_id))

    _set_session_cookie(response, session_token)

    auth.purge_expired()
    user = auth.user_for_session(session_token)
    return {"signed_in": True, "email": user["email"] if user else None, "claimed": moved}


def _set_session_cookie(response: Response, session_token: str) -> None:
    """Deployed, the site and the API are on different hosts.

    That makes every API call cross-site, and a Lax cookie is not sent
    cross-site -- signing in would appear to work and then immediately look
    signed out. SameSite=None fixes that but is only honoured over HTTPS, so
    local development (plain http) keeps Lax.
    """
    https = settings.app_base_url.startswith("https")
    response.set_cookie(
        key=auth.SESSION_COOKIE,
        value=session_token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,  # unreadable to JavaScript, so XSS can't lift the session
        samesite="none" if https else "lax",
        secure=https,
        path="/",
    )


@router.post("/signout")
def signout(
    response: Response, vantage_session: str | None = Cookie(default=None)
) -> dict:
    auth.end_session(vantage_session)
    https = settings.app_base_url.startswith("https")
    # The attributes have to match the ones it was set with or the browser
    # keeps the old cookie and sign-out silently does nothing.
    response.delete_cookie(
        auth.SESSION_COOKIE,
        path="/",
        samesite="none" if https else "lax",
        secure=https,
    )
    return {"signed_in": False}
