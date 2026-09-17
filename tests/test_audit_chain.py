"""The audit hash chain, as pure logic.

Security invariant 10: audit rows are append-only and hash-chained via
`prev_row_hash`, with UPDATE and DELETE revoked from the application's database
role. This file tests the chain arithmetic; `test_audit_immutability.py` tests the
grant that makes it stick.

Be precise about what this buys, because the threat model is (PRV-06, PRV-07):

  The chain makes the log tamper-EVIDENT, not tamper-proof, and only for rows
  written through the application. It is an unkeyed digest, so anyone who can
  write the table can edit a row and recompute every hash after it. Deleting the
  tail is undetectable without an externally witnessed head. A direct database
  write produces no audit row at all.

What it does catch is the realistic case: a row altered or removed in place, by
someone who did not also recompute the rest of the chain.
"""
import pytest

from domain.audit import (
    GENESIS_HASH,
    AuditPayload,
    AuditChainStatus,
    compute_row_hash,
    verify_chain,
)
from domain.enums import AuditAction


def payload(seq: int, action: AuditAction = AuditAction.DOCUMENT_VIEWED) -> AuditPayload:
    return AuditPayload(
        case_id=f"case-{seq}",
        actor_id=f"user-{seq}",
        action=action,
        object_type="document",
        object_id=f"doc-{seq}",
        utc_ts=f"2026-09-18T10:0{seq}:00Z",
    )


def build_chain(length: int) -> list[tuple[AuditPayload, str]]:
    rows, prev = [], GENESIS_HASH
    for i in range(length):
        p = payload(i)
        h = compute_row_hash(prev, p)
        rows.append((p, h))
        prev = h
    return rows


# --- the hash itself ---------------------------------------------------------

def test_hash_is_deterministic():
    p = payload(1)
    assert compute_row_hash(GENESIS_HASH, p) == compute_row_hash(GENESIS_HASH, p)


def test_hash_is_a_sha256_hex_digest():
    h = compute_row_hash(GENESIS_HASH, payload(1))
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_changing_any_field_changes_the_hash():
    base = payload(1)
    h = compute_row_hash(GENESIS_HASH, base)
    for field, value in [
        ("case_id", "case-other"),
        ("actor_id", "user-other"),
        ("action", AuditAction.DOCUMENT_EXPORTED),
        ("object_type", "case"),
        ("object_id", "doc-other"),
        ("utc_ts", "2026-09-18T10:99:00Z"),
    ]:
        altered = base.model_copy(update={field: value})
        assert compute_row_hash(GENESIS_HASH, altered) != h, (
            f"altering {field} did not change the row hash"
        )


def test_hash_depends_on_the_predecessor():
    """Without this the rows are independent digests, not a chain."""
    p = payload(1)
    assert compute_row_hash(GENESIS_HASH, p) != compute_row_hash("a" * 64, p)


def test_field_values_cannot_be_shifted_between_fields():
    """A naive concatenation lets 'ab'+'c' and 'a'+'bc' collide."""
    a = payload(1).model_copy(update={"object_type": "doc", "object_id": "ument"})
    b = payload(1).model_copy(update={"object_type": "docum", "object_id": "ent"})
    assert compute_row_hash(GENESIS_HASH, a) != compute_row_hash(GENESIS_HASH, b)


# --- chain verification ------------------------------------------------------

def test_an_untouched_chain_verifies():
    result = verify_chain(build_chain(5))
    assert result.status is AuditChainStatus.VERIFIED
    assert result.broken_at is None


def test_an_empty_chain_verifies():
    assert verify_chain([]).status is AuditChainStatus.VERIFIED


def test_an_altered_row_is_detected_and_located():
    rows = build_chain(5)
    p, h = rows[2]
    rows[2] = (p.model_copy(update={"actor_id": "somebody-else"}), h)
    result = verify_chain(rows)
    assert result.status is AuditChainStatus.BROKEN
    assert result.broken_at == 2, f"expected the break at index 2, got {result.broken_at}"


def test_a_removed_row_in_the_middle_is_detected():
    rows = build_chain(5)
    del rows[2]
    assert verify_chain(rows).status is AuditChainStatus.BROKEN


def test_a_reordered_pair_is_detected():
    rows = build_chain(5)
    rows[1], rows[2] = rows[2], rows[1]
    assert verify_chain(rows).status is AuditChainStatus.BROKEN


def test_a_chain_not_rooted_at_genesis_is_detected():
    """Otherwise a truncated prefix passes as a valid chain of its own."""
    rows = build_chain(5)[2:]
    assert verify_chain(rows).status is AuditChainStatus.BROKEN


def test_tail_truncation_is_NOT_detected_and_that_is_recorded():
    """The honest limit, asserted so nobody claims otherwise in a pitch.

    Deleting from the end leaves a prefix that is a perfectly valid chain. Detecting
    it needs an externally witnessed head, which this build does not have
    (threat PRV-07, accepted risk AR-4).
    """
    rows = build_chain(5)
    assert verify_chain(rows[:3]).status is AuditChainStatus.VERIFIED, (
        "if this now fails, the chain gained a length or head commitment - update "
        "AR-4 in docs/THREAT-MODEL.md, which currently says this is undetectable"
    )
