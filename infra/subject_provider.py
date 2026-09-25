"""SimulatedSubjectProvider — a declared stub for authentication.

docs/adr/0002. `BOOTSTRAP.md` contains no authentication slice, so all seven
authorization dimensions were being evaluated against a subject that nothing
established. A real identity provider does not fit the budget; asserting the subject
from the request does not fit the threat model. This is the honest middle: a
server-side signed session, named so nobody mistakes it for an IdP.

**Never called an auth service**, per CLAUDE.md's rule against naming a stand-in after
the real thing. It declares `maturity = "mvp"` and names its production replacement.

What it buys: the subject is resolved from a signature the server made, so a caller
cannot name themselves. What it does not buy, and what the threat model records as
accepted risks: no credential of any kind (AR-1), no rate limiting or lockout (AR-9),
no revocation propagation beyond expiry (AR-14). Anyone who can reach the endpoint can
request a session as any seeded identity - it is a demo switcher with a real signature,
not a login.

Cryptography is `hmac` + `hashlib` from the standard library, compared with
`hmac.compare_digest`. CLAUDE.md forbids implementing cryptography, not using it.
"""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

COOKIE_NAME = "ordin_session"
DEFAULT_LIFETIME = timedelta(hours=8)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SimulatedSubjectProvider:
    """Issues and verifies signed session tokens. Not an identity provider."""

    maturity = "mvp"
    production_adapter = "an OIDC identity provider bound to the agency directory"

    def __init__(self, secret) -> None:
        # Accepts SecretStr or str; the value is never logged or returned.
        value = getattr(secret, "get_secret_value", lambda: secret)()
        self._key = str(value).encode("utf-8")

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).digest())

    def issue(
        self,
        user_id: str,
        *,
        now: datetime | None = None,
        lifetime: timedelta = DEFAULT_LIFETIME,
    ) -> str:
        now = now or datetime.now(timezone.utc)
        payload = _b64(
            json.dumps(
                {"sub": str(user_id), "exp": int((now + lifetime).timestamp())},
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        return f"{payload}.{self._sign(payload)}"

    def parse(self, token: str | None, *, now: datetime | None = None) -> str | None:
        """Return the user id, or None. Never raises, never partially trusts.

        Every failure path returns None (invariant 2). A malformed token is not an
        error to surface - it is an unauthenticated request, and treating it as a 500
        would turn a probe into a denial-of-service and leak that parsing got further
        on some inputs than others.
        """
        if not token or not isinstance(token, str):
            return None
        payload, separator, signature = token.rpartition(".")
        if not separator or not payload or not signature:
            return None

        # Constant-time: a byte-by-byte comparison leaks the signature through timing.
        #
        # **Compared as bytes, because `compare_digest` RAISES on non-ASCII `str`.**
        # Starlette decodes the Cookie header as latin-1, so a single byte in 0x80-0xFF
        # arrives here as a non-ASCII string and the comparison threw TypeError -
        # outside the try below, so it escaped `require_subject` and turned every
        # authenticated route into a 500 for anyone who sent one. That is precisely the
        # failure the docstring above promises cannot happen: "never raises", and "a 500
        # would turn a probe into a denial-of-service".
        #
        # Encoding to bytes keeps the comparison constant-time and makes the whole input
        # domain representable. `surrogateescape` is the errors mode that cannot itself
        # raise on a latin-1 round trip; the signature we compute is pure hex, so a
        # non-ASCII candidate simply fails to match, which is the correct answer.
        if not hmac.compare_digest(
            self._sign(payload).encode("ascii"),
            signature.encode("utf-8", "surrogateescape"),
        ):
            return None

        try:
            claims = json.loads(_unb64(payload))
            subject = claims["sub"]
            expires_at = int(claims["exp"])
        except Exception:  # noqa: BLE001 - any malformed payload is simply not a session
            return None

        now = now or datetime.now(timezone.utc)
        if expires_at <= int(now.timestamp()):
            return None
        if not isinstance(subject, str) or not subject:
            return None
        return subject
