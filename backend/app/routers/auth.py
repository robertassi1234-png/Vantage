import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from app import auth, db, mailer
from app.config import settings
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
    email_delivery: bool


@router.get("/me")
def me(
    vantage_session: str | None = Cookie(default=None),
) -> MeResponse:
    user = auth.user_for_session(vantage_session)
    return MeResponse(
        signed_in=user is not None,
        email=user["email"] if user else None,
        # Lets the UI say plainly whether alert emails can actually be sent.
        email_delivery=mailer.is_configured(),
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
    # Without a mail provider there would be no way to sign in at all, which
    # makes local development impossible. Only ever exposed when SMTP is unset.
    if not delivered and not settings.smtp_host:
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
