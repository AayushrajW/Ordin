"""Real authentication: proving which account you are.

The session cookie this issues is **byte-identical in kind** to the one the specimen
switcher issues. That is the point. `infra/subject_provider.py` mints a signed token
carrying a user id; `api/deps.require_subject` re-resolves the seven dimensions from the
database on every request and never trusts the token for anything but *who*. So
replacing "click a name" with "present a password" changes one boundary and leaves the
authorization model, the policy evaluator, the SQL filter, the disclosure class and every
Sentinel scenario untouched.

**Signup grants nothing.** It creates an account with no post, which means no
organization, no jurisdiction and no clearance, which means `load_subject` returns None
and every authorized query is empty. An administrator places the account afterwards. The
sequence is honest: you are who you say you are, and you have been given nothing yet.

**Failures are uniform.** Every unsuccessful login returns the same message and the same
status. "No such account" and "wrong password" are different answers to *does this person
work here*, and an unauthenticated caller must not be able to ask it. The enumerated
reason goes to the structured log for the operator, never to the response.

Invariant 12: no handler here logs an email address or a password. `user_id` and an
enumerated outcome only.
"""
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.deps import provider
from infra.accounts import (
    GENERIC_FAILURE,
    AuthFailure,
    authenticate,
    create_account,
)
from infra.authz import load_subject
from infra.passwords import MAX_LENGTH, MIN_LENGTH, PasswordRejected
from sqlalchemy.exc import IntegrityError
from infra.subject_provider import COOKIE_NAME, DEFAULT_LIFETIME

log = logging.getLogger("ordin.api.auth")
router = APIRouter(tags=["auth"], prefix="/auth")


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=MAX_LENGTH)


class StatusOut(BaseModel):
    authenticated: bool
    placed: bool
    display_name: str | None = None
    awaiting_placement: bool = False


def _set_session(request: Request, response: Response, user_id: str) -> None:
    token = provider(request).issue(user_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.ordin_env != "dev",
        max_age=int(DEFAULT_LIFETIME.total_seconds()),
        path="/",
    )


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest, request: Request):
    """Create an account. Issues no session: an unplaced account has nothing to open.

    A duplicate address and a malformed one return the same 400 with the same text, so
    the form cannot be used to discover who already has an account here.
    """
    engine = request.app.state.engine
    try:
        async with engine.begin() as conn:
            user_id = await create_account(
                conn,
                email=body.email,
                password=body.password,
                display_name=body.display_name,
            )
    except PasswordRejected as exc:
        raise HTTPException(status_code=400, detail=f"password {exc}") from None
    except (ValueError, IntegrityError):
        # Deliberately indistinguishable from a rejected address. See the docstring.
        raise HTTPException(
            status_code=400,
            detail="that address cannot be registered",
        ) from None

    log.info("account created", extra={"user_id": user_id})
    return {
        "created": True,
        "awaiting_placement": True,
        "note": (
            "The account exists and holds no post, so it can open nothing until an "
            "administrator places it."
        ),
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    engine = request.app.state.engine
    async with engine.begin() as conn:
        result = await authenticate(conn, email=body.email, password=body.password)

    if not result.ok:
        log.info(
            "login refused",
            extra={"outcome": (result.failure or AuthFailure.BAD_PASSWORD).value},
        )
        raise HTTPException(status_code=401, detail=GENERIC_FAILURE)

    _set_session(request, response, result.user_id)

    async with engine.connect() as conn:
        subject = await load_subject(conn, result.user_id)

    log.info(
        "login",
        extra={"user_id": result.user_id, "placed": subject is not None},
    )
    return {"opened": True, "placed": subject is not None}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"closed": True}


@router.get("/status")
async def status(request: Request) -> StatusOut:
    """Who this cookie is, without requiring that they can open anything.

    `require_subject` refuses an account with no post, which is correct for every other
    route and useless here: after a successful login the person needs to be told they are
    awaiting placement rather than bounced back to the login form for ever.
    """
    user_id = provider(request).parse(request.cookies.get(COOKIE_NAME))
    if not user_id:
        return StatusOut(authenticated=False, placed=False)

    import sqlalchemy as sa

    engine = request.app.state.engine
    async with engine.connect() as conn:
        name = (
            await conn.execute(
                sa.text("SELECT display_name FROM app_user WHERE id = :i"), {"i": user_id}
            )
        ).scalar_one_or_none()
        subject = await load_subject(conn, user_id) if name else None

    if name is None:
        return StatusOut(authenticated=False, placed=False)
    return StatusOut(
        authenticated=True,
        placed=subject is not None,
        display_name=name,
        awaiting_placement=subject is None,
    )
