"""Password hashing. Argon2id, with parameters chosen for the machine this runs on.

CLAUDE.md: "never implements custom cryptography - use established libraries only."
This module is a thin wrapper over `argon2-cffi` and contains no cryptography of its
own. Its whole job is to hold the parameters in one place, with the reasoning attached,
and to expose two functions.

**Why the parameters are not the library defaults.** argon2-cffi defaults to 64 MiB of
memory per hash. The api container is capped at 256 MiB in docker-compose, so a handful
of simultaneous logins would push it into the OOM killer - which is threat OPS-03 wearing
a different hat, and a denial of service reachable from an unauthenticated endpoint.
These are OWASP's minimum recommended Argon2id parameters instead: 19 MiB, two passes,
one lane. Lower than a server with memory to spare should use, and stated here rather
than discovered later.

**Rehashing.** `needs_rehash` reports when a stored hash was made with weaker parameters
than the current ones, so raising them later upgrades accounts as people log in rather
than requiring a reset. The caller does that on a successful verify.

Invariant 12: nothing here logs, and no function in it takes a logger. A password must
not reach a log on success, on failure, or in a traceback - which is also why
`verify` returns a bool and raises nothing carrying the input.
"""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP minimum for Argon2id: 19 MiB, t=2, p=1. See the module docstring for why the
# library's larger default is wrong for a 256 MiB container.
_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,  # KiB
    parallelism=1,
)

# Long enough to matter, short enough that the hash cost cannot be used as a weapon:
# Argon2 hashes its input regardless of length, and an unbounded field lets a caller
# post a very large body to a pre-authentication endpoint.
MIN_LENGTH = 12
MAX_LENGTH = 1024


class PasswordRejected(Exception):
    """The password is unusable. Carries a reason for the person, never the value."""


def check_quality(password: str) -> None:
    """Refuse the passwords that are certainly bad. Raises `PasswordRejected`.

    Deliberately only length. Composition rules - a digit, a symbol, a capital - are
    known to produce predictable passwords and are not applied. Length is the property
    that actually helps.
    """
    if len(password) < MIN_LENGTH:
        raise PasswordRejected(f"must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordRejected(f"must be at most {MAX_LENGTH} characters")


def hash_password(password: str) -> str:
    """Hash for storage. The salt is generated inside the library, per hash."""
    check_quality(password)
    return _HASHER.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Is this the password behind that hash?

    `stored_hash` is allowed to be None - a seeded specimen identity has no password -
    and that case returns False like any other mismatch. It does **not** raise, because
    a distinct error for "this account cannot log in" would tell an unauthenticated
    caller which accounts exist.
    """
    if not stored_hash:
        return False
    try:
        return _HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash predates the current parameters."""
    try:
        return _HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False
