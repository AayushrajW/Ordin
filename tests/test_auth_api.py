"""The authentication surface (docs/PLAN-PRODUCT.md P2).

Three claims are defended here, in order of how badly they would hurt if wrong.

1. **A person who signs up can see nothing.** Not fewer cases — nothing. Signup creates
   an account with no post, so `load_subject` forms no Subject and every authorized
   query is empty. A signup form that placed its own caller would hand them the
   authorization model, and it would look exactly like a working feature.
2. **The specimen switcher does not exist in production.** `POST /session` issues a
   session for any seeded identity with no credential. Next to a real login, in a
   deployment, that is a complete authentication bypass. It must 404 when
   `ORDIN_ENV` is not `dev` — not be hidden from the UI, which is not a control: this
   repository is public.
3. **Failure says nothing.** A wrong password and an unknown address are the same
   response, because the difference answers *does this person work here* to a caller who
   has proved nothing.
"""
import uuid

import httpx
import pytest
from pydantic import SecretStr
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from infra.subject_provider import COOKIE_NAME

pytestmark = pytest.mark.requires_db

GOOD = "correct horse battery staple"


def _address() -> str:
    return f"{uuid.uuid4().hex[:12]}@specimen.invalid"


@pytest.fixture
async def api(live_settings):
    import seed as seed_module

    await seed_module.seed()
    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, engine
    await engine.dispose()


# --- signup grants nothing ------------------------------------------------------


async def test_signup_succeeds_and_says_the_account_is_unplaced(api):
    client, _ = api
    response = await client.post(
        "/auth/signup",
        json={"email": _address(), "password": GOOD, "display_name": "New Person"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["awaiting_placement"] is True


async def test_signup_issues_no_session(api):
    """An account that can open nothing has no session to open."""
    client, _ = api
    response = await client.post(
        "/auth/signup",
        json={"email": _address(), "password": GOOD, "display_name": "New Person"},
    )
    assert COOKIE_NAME not in response.cookies


async def test_a_signed_up_account_cannot_log_in_until_it_is_activated(api):
    client, _ = api
    address = _address()
    await client.post(
        "/auth/signup",
        json={"email": address, "password": GOOD, "display_name": "Dormant"},
    )
    response = await client.post("/auth/login", json={"email": address, "password": GOOD})
    assert response.status_code == 401, "a dormant account logged in"


async def test_an_activated_but_unplaced_account_sees_nothing_at_all(api):
    """The central claim of this file.

    The password is right, the account is live, and it holds no post. Authentication
    has happened and has granted nothing.
    """
    client, engine = api
    address = _address()
    await client.post(
        "/auth/signup",
        json={"email": address, "password": GOOD, "display_name": "Unplaced"},
    )
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE app_user SET is_active = true WHERE lower(email) = :e"),
            {"e": address},
        )

    login = await client.post("/auth/login", json={"email": address, "password": GOOD})
    assert login.status_code == 200, login.text
    assert login.json()["placed"] is False

    # The session is real, and it opens nothing.
    assert (await client.get("/cases")).status_code == 401
    assert (await client.get("/cases/count")).status_code == 401

    # And the person is told why, rather than bounced to the login form for ever.
    status = await client.get("/auth/status")
    assert status.status_code == 200
    body = status.json()
    assert body["authenticated"] is True
    assert body["placed"] is False
    assert body["awaiting_placement"] is True


# --- failure is uniform ---------------------------------------------------------


async def test_a_wrong_password_and_an_unknown_address_are_indistinguishable(api):
    client, engine = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Real"}
    )
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE app_user SET is_active = true WHERE lower(email) = :e"),
            {"e": address},
        )

    wrong = await client.post("/auth/login", json={"email": address, "password": "nope12345678"})
    missing = await client.post("/auth/login", json={"email": _address(), "password": GOOD})

    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json(), (
        "the response distinguishes a wrong password from an unknown address, which "
        "lets an unauthenticated caller enumerate who has an account here"
    )


async def test_signup_does_not_reveal_that_an_address_is_taken(api):
    client, _ = api
    address = _address()
    first = await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "First"}
    )
    assert first.status_code == 201
    second = await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Second"}
    )
    malformed = await client.post(
        "/auth/signup", json={"email": "not-an-address", "password": GOOD, "display_name": "X"}
    )
    assert second.status_code == malformed.status_code == 400
    assert second.json() == malformed.json(), (
        "a duplicate address is distinguishable from a rejected one, so the signup "
        "form is an account-enumeration oracle"
    )


async def test_a_short_password_is_refused_with_a_reason(api):
    """Password quality is the one thing worth being specific about: the person is
    choosing it, and a generic refusal leaves them guessing."""
    client, _ = api
    response = await client.post(
        "/auth/signup",
        json={"email": _address(), "password": "short", "display_name": "X"},
    )
    assert response.status_code == 422 or response.status_code == 400


# --- the switcher must not exist in production ----------------------------------


async def test_the_specimen_switcher_is_refused_outside_dev(live_settings):
    """`POST /session` takes no credential. In a deployment that is a bypass."""
    import seed as seed_module

    await seed_module.seed()
    # A real session secret as well as a production environment: `create_app` now calls
    # `refuse_unsafe_production`, which will not build an application on the template
    # value (ADR 0027). That guard firing here is it working, not a test fixture detail.
    production = live_settings.model_copy(
        update={
            "ordin_env": "production",
            # SecretStr, not str: `model_copy(update=...)` bypasses validation, so a
            # plain string would stay a plain string and the guard would meet the
            # wrong type rather than the wrong value.
            "ordin_session_secret": SecretStr(
                "a-real-session-secret-of-sufficient-length-for-production"
            ),
            # Production also refuses to start without encryption at rest (ADR 0028).
            "ordin_master_key": SecretStr("b3JkaW4tdGVzdC1tYXN0ZXIta2V5LTMyLWJ5dGVzISE"),
        }
    )
    app = create_app(production)
    engine = create_async_engine(production.app_dsn)
    app.state.engine = engine
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            switched = await client.post(
                "/session", json={"user_id": "00000000-0000-0000-0000-000000000000"}
            )
            listed = await client.get("/demo/subjects")
        assert switched.status_code == 404, "the credential-free switcher answered in production"
        assert listed.status_code == 404, "production listed the specimen identities"
    finally:
        await engine.dispose()


async def test_the_specimen_switcher_still_works_in_dev(api):
    """The demo depends on it. It must survive being confined, not be removed."""
    client, _ = api
    assert (await client.get("/demo/subjects")).status_code == 200


# --- logout ---------------------------------------------------------------------


async def test_logout_clears_the_session(api):
    client, engine = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Person"}
    )
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE app_user SET is_active = true WHERE lower(email) = :e"),
            {"e": address},
        )
    await client.post("/auth/login", json={"email": address, "password": GOOD})
    assert (await client.get("/auth/status")).json()["authenticated"] is True

    await client.post("/auth/logout")
    assert (await client.get("/auth/status")).json()["authenticated"] is False
