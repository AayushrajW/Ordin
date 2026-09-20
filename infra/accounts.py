"""Creating accounts, and proving which one you are.

This module answers exactly one question — *which `app_user` row is this caller?* — and
then stops. It makes no access decision. The seven-dimension model in `domain/policy.py`
and `infra/authz_sql.py` does that, from the signed token issued afterwards, exactly as
it did when the identity came from a button.

That separation is the reason real login is a small change. Authentication says who you
are; authorization says what that gets you; they were never the same thing here.

**Signup produces an account that can do nothing.** No post, so no organization, no
jurisdiction and no clearance, so no `Subject` can be formed from it and every query
denies (invariant 2). An administrator places the account afterwards. A signup form that
let a caller choose their own organization would hand them the authorization model.

**Failure is deliberately uninformative.** Every unsuccessful outcome shows the same
sentence. "No such account" and "wrong password" are different answers to *does this
person work here*, and an unauthenticated caller must not be able to ask it. The reason
is kept in the structured log, as an enumerated code, for the operator.

**Lockout is on the row, not only in memory.** `api/security.py` already rate-limits per
address, and says of itself that it is per process and resets on restart. A counter on
the account survives both, and is what makes a slow distributed guessing attempt
expensive.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

import sqlalchemy as sa

from infra.passwords import PasswordRejected, hash_password, needs_rehash, verify_password

# Enough attempts that a person mistyping is not locked out; few enough that guessing is
# not a viable strategy against one account.
MAX_FAILED_ATTEMPTS = 8
LOCKOUT = timedelta(minutes=15)

# Verified against when no account matches, so that a missing account and a wrong
# password take the same time. Argon2's own output for a value nobody can present.
_DECOY_HASH = (
    "$argon2id$v=19$m=19456,t=2,p=1$"
    "c29tZXNhbHRmb3J0aW1pbmc$8Qm5YcBl6kCFBPRUCFKkEJBZBKLPmHjMVdqBLMNEvqI"
)


class AuthFailure(StrEnum):
    NO_ACCOUNT = "no_account"
    BAD_PASSWORD = "bad_password"
    LOCKED = "locked"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class AuthResult:
    """Either a user id, or a reason nobody outside the log gets to see."""

    user_id: str | None
    failure: AuthFailure | None = None

    @property
    def ok(self) -> bool:
        return self.user_id is not None


# The one sentence every failure shows. See the module docstring.
GENERIC_FAILURE = "Those credentials do not match an account."


def normalise_email(email: str) -> str:
    """Trim and lower-case. The unique index is on `lower(email)`; this agrees with it."""
    return email.strip().lower()


async def create_account(conn, *, email: str, password: str, display_name: str) -> str:
    """Create an inactive, unplaced account. Returns its id.

    Raises `PasswordRejected` for an unusable password and `ValueError` for an address
    already in use. The caller shows the same message either way for the address case,
    because "already registered" is an account-enumeration oracle on a signup form.
    """
    address = normalise_email(email)
    if not address or "@" not in address:
        raise ValueError("an email address is required")
    if not display_name.strip():
        raise ValueError("a name is required")

    hashed = hash_password(password)  # raises PasswordRejected before touching the db

    existing = (
        await conn.execute(
            sa.text("SELECT 1 FROM app_user WHERE lower(email) = :e"), {"e": address}
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError("that address is already registered")

    row = (
        await conn.execute(
            sa.text(
                "INSERT INTO app_user "
                "  (id, post_id, display_name, clearance_level, is_active, email, password_hash) "
                "VALUES (gen_random_uuid(), NULL, :n, 1, false, :e, :h) "
                "RETURNING id"
            ),
            {"n": display_name.strip(), "e": address, "h": hashed},
        )
    ).scalar_one()
    return str(row)


async def authenticate(conn, *, email: str, password: str, at: datetime | None = None) -> AuthResult:
    """Verify a password and return the account it belongs to.

    Does **not** check that the account holds a post. An account with no post
    authenticates and then finds every case query empty, which is the honest sequence:
    they are who they say they are, and they have been given nothing yet.
    """
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    address = normalise_email(email)

    row = (
        await conn.execute(
            sa.text(
                "SELECT id, password_hash, is_active, failed_attempts, locked_until "
                "FROM app_user WHERE lower(email) = :e"
            ),
            {"e": address},
        )
    ).mappings().one_or_none()

    if row is None:
        # Spend the same time as a real verify, so absence is not detectable by clock.
        verify_password(_DECOY_HASH, password)
        return AuthResult(None, AuthFailure.NO_ACCOUNT)

    if row["locked_until"] is not None and row["locked_until"] > moment:
        return AuthResult(None, AuthFailure.LOCKED)

    if not verify_password(row["password_hash"], password):
        attempts = int(row["failed_attempts"]) + 1
        locks = attempts >= MAX_FAILED_ATTEMPTS
        await conn.execute(
            sa.text(
                "UPDATE app_user SET failed_attempts = :a, locked_until = :l WHERE id = :i"
            ),
            {
                "a": 0 if locks else attempts,
                "l": moment + LOCKOUT if locks else None,
                "i": row["id"],
            },
        )
        return AuthResult(None, AuthFailure.LOCKED if locks else AuthFailure.BAD_PASSWORD)

    if not row["is_active"]:
        # Correct password, dormant account. Counted as a success against the lockout -
        # the password was right - but it is not a login.
        await conn.execute(
            sa.text("UPDATE app_user SET failed_attempts = 0 WHERE id = :i"), {"i": row["id"]}
        )
        return AuthResult(None, AuthFailure.INACTIVE)

    rehashed = hash_password(password) if needs_rehash(row["password_hash"]) else None
    await conn.execute(
        sa.text(
            "UPDATE app_user SET failed_attempts = 0, locked_until = NULL, "
            "last_login_at = :t, password_hash = COALESCE(:h, password_hash) WHERE id = :i"
        ),
        {"t": moment, "h": rehashed, "i": row["id"]},
    )
    return AuthResult(str(row["id"]))


__all__ = [
    "AuthFailure",
    "AuthResult",
    "GENERIC_FAILURE",
    "MAX_FAILED_ATTEMPTS",
    "PasswordRejected",
    "authenticate",
    "create_account",
    "normalise_email",
]
