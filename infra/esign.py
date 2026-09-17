"""SimulatedESignProvider — a soft signer, named so nobody mistakes it for one.

CLAUDE.md's honesty rule is explicit and has its own guard-hook regex:

    Never name a stand-in after the real thing. The soft PKCS#11 signer is
    `SimulatedESignProvider`, not `ESignService`.

**What this signature is worth, stated plainly** (threats EVD-07, EVD-08):

  - The key is a soft key on the same host as the application, gated by no per-user
    secret. Anyone who can invoke this provider can mint any signature it can make.
  - There is no certificate, no hardware token, and no binding to a natural person.
  - It therefore records an **attribution**, never a proof of authorship.
    Non-repudiation is absent and cannot be built at this scope; it needs per-officer
    keys in hardware.

That has to appear in UI copy and in any generated PDF, not just here. The guard hook
enforces the class name; it cannot enforce what a signature block says on screen, and
that is where this claim usually gets overstated.

**What it does do correctly:** the signature covers a *structure*, not a bare digest.
Signing the digest alone (the golden thread reads "sign -> hash -> anchor", which
invites exactly that) produces a signature that can be detached and re-attached to a
different document, version or case (threat EVD-09). Binding prevents replay; it does
not create attribution.
"""
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Signature:
    value: str
    algorithm: str
    provider: str
    maturity: str
    signed_at: str
    bound_to: dict


class SimulatedESignProvider:
    """A soft HMAC signer. Not an e-signature service. See the module docstring."""

    maturity = "mvp"
    production_adapter = "a PKCS#11 hardware token issued to the signing officer"
    algorithm = "HMAC-SHA256"

    def __init__(self, secret) -> None:
        value = getattr(secret, "get_secret_value", lambda: secret)()
        self._key = str(value).encode("utf-8")

    def _payload(self, *, case_id: str, document_id: str, version_id: str,
                 content_sha256: str, actor_id: str, signed_at: str) -> bytes:
        # Canonical JSON so the same facts always produce the same bytes.
        return json.dumps(
            {
                "case_id": str(case_id),
                "document_id": str(document_id),
                "version_id": str(version_id),
                "content_sha256": content_sha256,
                "actor_id": str(actor_id),
                "signed_at": signed_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def sign(self, *, case_id: str, document_id: str, version_id: str,
             content_sha256: str, actor_id: str, at: datetime) -> Signature:
        signed_at = at.isoformat()
        bound_to = {
            "case_id": str(case_id),
            "document_id": str(document_id),
            "version_id": str(version_id),
            "content_sha256": content_sha256,
            "actor_id": str(actor_id),
            "signed_at": signed_at,
        }
        payload = self._payload(**bound_to)
        return Signature(
            value=hmac.new(self._key, payload, hashlib.sha256).hexdigest(),
            algorithm=self.algorithm,
            provider=type(self).__name__,
            maturity=self.maturity,
            signed_at=signed_at,
            bound_to=bound_to,
        )

    def verify(self, signature: Signature) -> bool:
        """Recompute and compare in constant time.

        Verifying against `signature.bound_to` is the point: a signature presented
        alongside a *different* version id recomputes to a different value, so
        detaching and re-attaching it fails here rather than silently passing.
        """
        expected = hmac.new(self._key, self._payload(**signature.bound_to), hashlib.sha256)
        return hmac.compare_digest(expected.hexdigest(), signature.value)
