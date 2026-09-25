"""SimulatedSubjectProvider: a declared stub, with real signing.

ADR 0002. This is not an identity provider and is never called one. What it is: a
server-side signed session, so the seven authorization dimensions are evaluated
against a subject the *server* resolved rather than one the caller asserted.

That distinction is the entire point. Slice 7's demo is "one document, three roles,
one URL", and the cheapest way to build a role switch is a dropdown that sends
`?role=full` or an `X-Role` header. Doing that would silently invalidate slices 3, 7
and 8 at once - Sentinel's unauthorized-access scenario would pass against a forgeable
identity (threat EXT-02). So most of this file tests what the provider REFUSES.

Pure: HMAC over stdlib, no database, no framework. Established library, not custom
cryptography - `hmac` and `hashlib`, with `compare_digest` for the comparison.
"""
from datetime import datetime, timedelta, timezone

import pytest

from infra.subject_provider import SimulatedSubjectProvider

SECRET = "test-secret-not-a-real-one"
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
USER = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def provider():
    return SimulatedSubjectProvider(SECRET)


# --- honesty ------------------------------------------------------------------

def test_it_declares_itself_a_stub(provider):
    """CLAUDE.md: never hide a stub behind plausible-looking output."""
    assert provider.maturity == "mvp"
    assert provider.production_adapter
    assert "SimulatedSubjectProvider" in type(provider).__name__


def test_it_is_not_named_after_the_real_thing():
    """The honesty rule that has its own guard-hook regex for the signer."""
    name = SimulatedSubjectProvider.__name__
    assert not name.startswith("Auth"), name
    assert "Service" not in name, name


# --- the happy path ------------------------------------------------------------

def test_a_token_it_issued_round_trips(provider):
    token = provider.issue(USER, now=NOW)
    assert provider.parse(token, now=NOW) == USER


def test_a_token_is_opaque_about_nothing_it_should_hide(provider):
    """The user id is not secret; the point is that it cannot be CHANGED."""
    token = provider.issue(USER, now=NOW)
    assert provider.parse(token, now=NOW) == USER


# --- what it refuses -----------------------------------------------------------

def reseal(token: str, **claim_overrides) -> str:
    """Rewrite the claims and keep the original signature.

    Written as a helper because the naive version - string-replacing the user id in
    the token - silently does nothing: the payload is base64, so the id never appears
    literally, `.replace` matches nothing, and the "forged" token is the original.
    That test passes against any implementation, including one with no signature
    check at all.
    """
    import base64
    import json

    payload, _, signature = token.rpartition(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims.update(claim_overrides)
    rewritten = (
        base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
        )
        .decode()
        .rstrip("=")
    )
    return f"{rewritten}.{signature}"


def test_a_tampered_user_id_is_rejected(provider):
    """The attack: mint your own session naming somebody else."""
    token = provider.issue(USER, now=NOW)
    forged = reseal(token, sub="99999999-9999-9999-9999-999999999999")
    assert forged != token, "the helper did not actually change the token"
    assert provider.parse(forged, now=NOW) is None


def test_a_token_signed_with_another_secret_is_rejected(provider):
    other = SimulatedSubjectProvider("a-different-secret")
    assert provider.parse(other.issue(USER, now=NOW), now=NOW) is None


def test_an_expired_token_is_rejected(provider):
    token = provider.issue(USER, now=NOW, lifetime=timedelta(hours=1))
    assert provider.parse(token, now=NOW + timedelta(hours=2)) is None


def test_a_token_expiring_later_is_still_accepted(provider):
    token = provider.issue(USER, now=NOW, lifetime=timedelta(hours=2))
    assert provider.parse(token, now=NOW + timedelta(hours=1)) == USER


@pytest.mark.parametrize(
    "junk",
    ["", ".", "..", "not-a-token", "a.b", "a.b.c.d", "x" * 500, "null", "{}"],
)
def test_malformed_tokens_deny_rather_than_raise(provider, junk):
    """Invariant 2. A parse error is a denial, never a 500 and never a pass."""
    assert provider.parse(junk, now=NOW) is None


def test_none_is_rejected(provider):
    assert provider.parse(None, now=NOW) is None


def test_an_unsigned_payload_is_rejected(provider):
    """The 'alg: none' shape of mistake: a payload with the signature stripped."""
    token = provider.issue(USER, now=NOW)
    assert provider.parse(token.rpartition(".")[0], now=NOW) is None
    assert provider.parse(token.rpartition(".")[0] + ".", now=NOW) is None


def test_the_signature_covers_the_expiry_too(provider):
    """Otherwise an expired token is revived by editing its own expiry."""
    token = provider.issue(USER, now=NOW, lifetime=timedelta(hours=1))
    revived = reseal(token, exp=int((NOW + timedelta(days=365)).timestamp()))
    assert revived != token
    assert provider.parse(revived, now=NOW + timedelta(hours=2)) is None


def test_a_non_ascii_token_returns_none_rather_than_raising():
    """The docstring's "never raises" promise, asserted instead of trusted.

    `hmac.compare_digest` raises TypeError when either `str` argument holds a character
    above U+007F, and that call sat outside the try block. Starlette decodes the Cookie
    header as latin-1, so one byte in 0x80-0xFF reached it as a non-ASCII string and
    every authenticated route answered 500 instead of 401 - reproduced over a raw socket
    against a real server, not just in a unit test.

    A malformed token is an unauthenticated request. Treating it as a fault turns a
    probe into a denial of service and tells the prober exactly where parsing stops,
    which is the reasoning the docstring already gives and the code did not honour.
    """
    provider = SimulatedSubjectProvider("secret")
    for token in (
        "YWJj.\u00e9\u00e9\u00e9",      # high latin-1 bytes in the signature
        "\u00e9.\u00e9",                 # and in the payload
        "aaa.\udce9",                    # a lone surrogate, as surrogateescape yields
        "YWJj.\u0000",                   # a NUL
        "\N{SNOWMAN}.\N{SNOWMAN}",       # well outside latin-1
    ):
        assert provider.parse(token) is None, f"{token!r} did not return None"


def test_a_valid_token_still_round_trips_after_the_bytes_comparison():
    """The guard above must not have been bought by breaking the normal path."""
    provider = SimulatedSubjectProvider("secret")
    assert provider.parse(provider.issue("user-1")) == "user-1"


def test_a_token_signed_with_another_secret_is_refused():
    """And the comparison still compares. Encoding to bytes could have made every
    signature match if the two sides were encoded differently."""
    issued = SimulatedSubjectProvider("secret-a").issue("user-1")
    assert SimulatedSubjectProvider("secret-b").parse(issued) is None
