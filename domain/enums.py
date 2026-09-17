"""Domain vocabulary.

**This package imports no framework.** No FastAPI, no SQLAlchemy, no provider SDKs —
per CLAUDE.md, nothing below the service boundary may. Everything here is pure Python
and testable with no application and no database running, which is also what makes the
state machine and the audit chain unit-testable in isolation.
"""
from enum import StrEnum


class CaseState(StrEnum):
    """Case lifecycle.

    These are deliberately generic procedural states, not Indian statutory stages.
    CLAUDE.md forbids guessing statutory behaviour, and the real workflow for a
    women-safety case under the applicable code has stages this set does not name.
    Transitions live in `domain.case.ALLOWED_TRANSITIONS` as data precisely so that
    replacing this set is an edit to one table rather than a hunt through code.

    Open question carried in docs/STATUS.md: confirm the real stage names and their
    permitted transitions with a source before any of this reaches UI copy.
    """

    REGISTERED = "registered"
    UNDER_INVESTIGATION = "under_investigation"
    FILED = "filed"
    IN_TRIAL = "in_trial"
    CLOSED = "closed"


class LifecycleState(StrEnum):
    """One of the two independent axes a DocumentVersion carries.

    `active` compares live bytes to the anchor; `superseded` verifies the historical
    version; `disposed` verifies the anchor and disposition record only, returning
    DISPOSED_ANCHOR_ONLY. A lawfully disposed document is not a tampered one.
    """

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISPOSED = "disposed"


class AccessClass(StrEnum):
    """The other axis. A document can be sealed *and* superseded simultaneously.

    Note the known gap (threat DIM-07): sealing is ordered judicially at the level of
    a case, a party, or a category of material, but this flag lives on the version.
    Slice 3 must evaluate a seal by join from the case, with this flag narrowing
    further — not as the sole locus.
    """

    NORMAL = "normal"
    SEALED = "sealed"


class PartyRole(StrEnum):
    COMPLAINANT = "complainant"
    VICTIM = "victim"
    WITNESS = "witness"
    ACCUSED = "accused"
    OTHER = "other"


class OrganizationKind(StrEnum):
    """Organization and jurisdiction are separate dimensions, never conflated."""

    POLICE = "police"
    PROSECUTION = "prosecution"
    COURT = "court"
    FORENSIC = "forensic"


class JobStage(StrEnum):
    """Pipeline stages. Enumerated, never a free string.

    The idempotency key is derived from this value (docs/adr/0004), so two spellings
    of the same stage would run the same work twice and defeat the invariant.
    """

    VALIDATE = "validate"
    OCR = "ocr"
    EXTRACT = "extract"
    SIGN = "sign"
    ANCHOR = "anchor"
    REDACT = "redact"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AuditAction(StrEnum):
    """What an audit row records. IDs and decisions only — never content."""

    CASE_CREATED = "case_created"
    CASE_STATE_CHANGED = "case_state_changed"
    DOCUMENT_UPLOADED = "document_uploaded"
    VERSION_CREATED = "version_created"
    DOCUMENT_VIEWED = "document_viewed"
    DOCUMENT_EXPORTED = "document_exported"
    GRANT_ISSUED = "grant_issued"
    GRANT_REVOKED = "grant_revoked"
    ASSIGNMENT_CHANGED = "assignment_changed"
    DISPOSAL_RECORDED = "disposal_recorded"
