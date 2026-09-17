"""Audit hash chain.

Security invariant 10. Each row commits to its predecessor, so altering or removing a
row in place breaks every hash after it.

**What this is worth, stated precisely**, because overstating it is the exact failure
the honesty rules exist to prevent:

  - It is tamper-EVIDENT, not tamper-proof. The digest is unkeyed, so anyone who can
    write the table can alter a row and recompute the rest (threat PRV-06). The
    control that makes this bite is the REVOKE in the migration plus the two database
    roles from docs/adr/0001 — not the arithmetic here.
  - It covers only rows the application wrote. A direct database UPDATE produces no
    audit row at all (PRV-09).
  - Truncating the tail is undetectable. The remaining prefix is a valid chain, and
    catching that needs an externally witnessed head, which this build does not have
    (PRV-07, accepted risk AR-4). There is a test asserting this limitation so it
    cannot quietly stop being true without someone noticing.

Invariant 12 applies to what goes in: IDs, actions and timestamps only. No document
content, no party names, no free text from an untrusted source.

Naming note: the types below are prefixed `AuditChain` rather than `Chain`. The guard
hook blocks class names beginning `Chain`, to keep ledger vocabulary away from
anything that is not the Fabric adapter. The prefix satisfies that and is more
specific anyway — this is the audit chain, not a general one.
"""
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from domain.enums import AuditAction

# The chain root. A row whose prev_row_hash is this is the first row, and
# verify_chain requires it — otherwise a truncated prefix verifies as its own chain.
GENESIS_HASH = "0" * 64


class AuditPayload(BaseModel):
    """The committed fields of an audit row.

    Identifiers only. If a field here ever needs to hold free text, that is a signal
    to reconsider rather than to widen the model.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    actor_id: str
    action: AuditAction
    object_type: str
    object_id: str
    utc_ts: str  # ISO-8601, UTC, string form so the digest is stable across drivers


class AuditChainStatus(StrEnum):
    VERIFIED = "verified"
    BROKEN = "broken"


@dataclass(frozen=True)
class AuditChainVerification:
    status: AuditChainStatus
    broken_at: int | None = None
    detail: str | None = None


def _canonical(prev_row_hash: str, payload: AuditPayload) -> bytes:
    """Deterministic bytes for one row.

    JSON with sorted keys and explicit separators rather than concatenation: joining
    fields end to end lets values shift across boundaries, so ("doc", "ument") and
    ("docum", "ent") would collide. There is a test for exactly that.
    """
    return json.dumps(
        {
            "prev": prev_row_hash,
            "case_id": payload.case_id,
            "actor_id": payload.actor_id,
            "action": payload.action.value,
            "object_type": payload.object_type,
            "object_id": payload.object_id,
            "utc_ts": payload.utc_ts,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_row_hash(prev_row_hash: str, payload: AuditPayload) -> str:
    return hashlib.sha256(_canonical(prev_row_hash, payload)).hexdigest()


def verify_chain(rows: Sequence[tuple[AuditPayload, str]]) -> AuditChainVerification:
    """Recompute the chain and report the first index that does not match.

    `rows` is in insertion order, each entry the payload and the stored row hash.
    """
    prev = GENESIS_HASH
    for index, (payload, stored_hash) in enumerate(rows):
        expected = compute_row_hash(prev, payload)
        if expected != stored_hash:
            return AuditChainVerification(
                status=AuditChainStatus.BROKEN,
                broken_at=index,
                detail="row hash does not match its contents and predecessor",
            )
        prev = stored_hash
    return AuditChainVerification(status=AuditChainStatus.VERIFIED)
