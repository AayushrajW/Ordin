"""Integrity verification, as pure logic.

Security invariant 5, as amended by docs/adr/0010:

    VERIFIED | MISMATCH | DISPOSED_ANCHOR_ONLY | PENDING | UNAVAILABLE

A state, never a boolean. The reasoning behind that is legal as much as technical: a
lawfully disposed document reported as MISMATCH is not a cosmetic bug, it is a claim
that evidence was tampered with. The same holds for a document that is simply waiting
for its anchor.

The decision function here takes *facts already gathered* and returns a state. It
touches no database and no filesystem, so every branch — including the ones that are
awkward to reach in integration, like a disposed document whose blob still exists — is
testable directly.

CLAUDE.md invariant 4 fixes what an anchor may carry:
`case_id, doc_id, version, sha256, actor_id, action, utc_ts`. No PII, ever. The
`AnchorFacts` shape below is deliberately no wider.
"""
from dataclasses import dataclass
from enum import StrEnum


class VerificationState(StrEnum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    DISPOSED_ANCHOR_ONLY = "DISPOSED_ANCHOR_ONLY"
    PENDING = "PENDING"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class AnchorFacts:
    """What the anchor recorded. Invariant 4's tuple, and nothing more."""

    content_sha256: str
    metadata_sha256: str | None = None


@dataclass(frozen=True)
class VersionFacts:
    """What we know about the version being verified, gathered by the caller."""

    version_id: str
    lifecycle_state: str          # active | superseded | disposed
    recorded_sha256: str          # the digest stored on the version row
    anchor: AnchorFacts | None    # None means never anchored
    live_sha256: str | None       # digest of the bytes on disk now; None if absent
    disposition_recorded: bool = False


@dataclass(frozen=True)
class Verification:
    state: VerificationState
    version_id: str
    detail: str
    """A short, enumerated-ish explanation. Never a driver message, never content."""


def verify_version(facts: VersionFacts) -> Verification:
    """Decide the state. Order matters and is the whole design.

    Disposal is checked **before** the bytes, because a disposed document has no bytes
    by design and checking them first would report MISMATCH for a lawful disposal —
    the exact error invariant 5 names.

    Absence of an anchor is checked before absence of bytes, because a document
    mid-pipeline has a digest and no anchor, and that is normal (ADR 0010).
    """
    # 1. Lawfully disposed. The anchor and the disposition record are what survive.
    if facts.lifecycle_state == "disposed":
        if facts.anchor is None or not facts.disposition_recorded:
            # Disposed with no anchor or no disposition record is not a lawful
            # disposal we can attest to - it is an absence we cannot explain.
            return Verification(
                VerificationState.UNAVAILABLE,
                facts.version_id,
                "disposed without a complete anchor and disposition record",
            )
        return Verification(
            VerificationState.DISPOSED_ANCHOR_ONLY,
            facts.version_id,
            "lawfully disposed; anchor and disposition record verified, bytes not retained",
        )

    # 2. Not yet anchored. Normal, transient, and not a failure (ADR 0010).
    if facts.anchor is None:
        return Verification(
            VerificationState.PENDING,
            facts.version_id,
            "digest recorded; anchor not yet written",
        )

    # 3. Anchored, but the bytes are not there to compare.
    if facts.live_sha256 is None:
        return Verification(
            VerificationState.UNAVAILABLE,
            facts.version_id,
            "anchored, but the stored bytes could not be read",
        )

    # 4. The comparison itself. Both digests must agree: the anchor against the
    #    bytes, and the version row against the anchor. A version row that disagrees
    #    with its own anchor is a divergence even if the bytes match one of them.
    if facts.live_sha256 != facts.anchor.content_sha256:
        return Verification(
            VerificationState.MISMATCH,
            facts.version_id,
            "stored bytes do not match the anchored digest",
        )
    if facts.recorded_sha256 != facts.anchor.content_sha256:
        return Verification(
            VerificationState.MISMATCH,
            facts.version_id,
            "version record does not match the anchored digest",
        )

    return Verification(
        VerificationState.VERIFIED,
        facts.version_id,
        "stored bytes match the anchored digest",
    )
