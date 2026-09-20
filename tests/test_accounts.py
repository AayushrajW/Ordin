"""Real accounts (docs/PLAN-PRODUCT.md P2).

The security claim this file defends is not "login works". It is that **authentication
grants nothing**: a person who proves who they are still has no organization, no
jurisdiction and no clearance until an administrator places them, and therefore sees
nothing at all.

That is the property a signup form quietly destroys. A form that let a caller pick their
own organization would hand them the authorization model, and the failure would look
exactly like a working feature.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from infra.accounts import (
    MAX_FAILED_ATTEMPTS,
    AuthFailure,
    authenticate,
    create_account,
)
from infra.passwords import (
    MIN_LENGTH,
    PasswordRejected,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.requires_db

GOOD = "correct horse battery staple"


def _address() -> str:
    return f"{uuid.uuid4().hex[:12]}@specimen.invalid"


# --- hashing, no database ------------------------------------------------------


def test_a_hash_does_not_contain_the_password():
    secret = "a password nobody should find"
    stored = hash_password(secret)
    assert secret not in stored
    assert stored.startswith("$argon2id$"), stored[:32]


def test_the_same_password_hashes_differently_every_time():
    """A per-hash salt. Identical hashes would reveal which accounts share a password."""
    assert hash_password(GOOD) != hash_password(GOOD)


def test_verify_accepts_the_password_and_rejects_everything_else():
    stored = hash_password(GOOD)
    assert verify_password(stored, GOOD)
    assert not verify_password(stored, GOOD + " ")
    assert not verify_password(stored, "")


def test_an_account_with_no_password_cannot_be_logged_into():
    """The seeded specimen identities have `password_hash IS NULL`.

    None must behave as a mismatch rather than raising, or the distinct error tells an
    unauthenticated caller which accounts exist.
    """
    assert not verify_password(None, GOOD)


def test_a_short_password_is_refused():
    with pytest.raises(PasswordRejected):
        hash_password("x" * (MIN_LENGTH - 1))


# --- signup --------------------------------------------------------------------


async def test_signup_creates_an_account_that_can_do_nothing(live_settings):
    """The central claim. Authentication grants no access whatsoever."""
    engine = create_async_engine(live_settings.app_dsn)
    try:
        async with engine.begin() as conn:
            user_id = await create_account(
                conn, email=_address(), password=GOOD, display_name="Specimen Person"
            )
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT post_id, is_active, clearance_level "
                        "FROM app_user WHERE id = :i"
                    ),
                    {"i": user_id},
                )
            ).mappings().one()

        assert row["post_id"] is None, (
            "signup gave the account a post - so an organization, a jurisdiction and a "
            "place in the authorization model, chosen by the caller"
        )
        assert row["is_active"] is False, "signup produced an account that is already live"
    finally:
        await engine.dispose()


async def test_an_address_cannot_be_registered_twice_in_a_different_case(live_settings):
    engine = create_async_engine(live_settings.app_dsn)
    address = _address()
    try:
        async with engine.begin() as conn:
            await create_account(
                conn, email=address, password=GOOD, display_name="First"
            )
        async with engine.begin() as conn:
            with pytest.raises(ValueError):
                await create_account(
                    conn, email=address.upper(), password=GOOD, display_name="Second"
                )
    finally:
        await engine.dispose()


# --- authentication ------------------------------------------------------------


async def _activate(conn, user_id: str) -> None:
    await conn.execute(
        sa.text("UPDATE app_user SET is_active = true WHERE id = :i"), {"i": user_id}
    )


async def test_the_right_password_authenticates_an_active_account(live_settings):
    engine = create_async_engine(live_settings.app_dsn)
    address = _address()
    try:
        async with engine.begin() as conn:
            user_id = await create_account(
                conn, email=address, password=GOOD, display_name="Specimen"
            )
            await _activate(conn, user_id)
            result = await authenticate(conn, email=address, password=GOOD)
        assert result.ok and result.user_id == user_id
    finally:
        await engine.dispose()


async def test_an_inactive_account_does_not_authenticate_even_with_the_right_password(
    live_settings,
):
    """A freshly signed-up account. Correct password, still not a login."""
    engine = create_async_engine(live_settings.app_dsn)
    address = _address()
    try:
        async with engine.begin() as conn:
            await create_account(conn, email=address, password=GOOD, display_name="Dormant")
            result = await authenticate(conn, email=address, password=GOOD)
        assert not result.ok
        assert result.failure is AuthFailure.INACTIVE
    finally:
        await engine.dispose()


async def test_a_wrong_password_and_an_unknown_address_both_fail(live_settings):
    engine = create_async_engine(live_settings.app_dsn)
    address = _address()
    try:
        async with engine.begin() as conn:
            user_id = await create_account(
                conn, email=address, password=GOOD, display_name="Specimen"
            )
            await _activate(conn, user_id)
            wrong = await authenticate(conn, email=address, password="not the password")
            missing = await authenticate(conn, email=_address(), password=GOOD)

        assert not wrong.ok and wrong.failure is AuthFailure.BAD_PASSWORD
        assert not missing.ok and missing.failure is AuthFailure.NO_ACCOUNT
    finally:
        await engine.dispose()


async def test_repeated_wrong_passwords_lock_the_account(live_settings):
    """The lock is on the row, so it survives an api restart and is not per process."""
    engine = create_async_engine(live_settings.app_dsn)
    address = _address()
    try:
        async with engine.begin() as conn:
            user_id = await create_account(
                conn, email=address, password=GOOD, display_name="Specimen"
            )
            await _activate(conn, user_id)

            for _ in range(MAX_FAILED_ATTEMPTS):
                await authenticate(conn, email=address, password="wrong")

            # Even the correct password now fails, which is the point of a lockout.
            result = await authenticate(conn, email=address, password=GOOD)
            assert not result.ok
            assert result.failure is AuthFailure.LOCKED

            # And it lifts once the window passes.
            later = datetime.now(timezone.utc) + timedelta(hours=1)
            after = await authenticate(conn, email=address, password=GOOD, at=later)
            assert after.ok
    finally:
        await engine.dispose()
