"""Appending to the audit chain.

`domain/audit.py` has computed the hashes since slice 2 and nothing in the running
system called it: the chain was verified by tests over rows the tests themselves
inserted. Slice 5b is the first action worth recording — a person taking
responsibility for a value — so this is where the application starts writing.

Two things here are load-bearing.

**The advisory lock.** Appending means reading the current head and committing to it.
Two concurrent appends that both read head *N* would both write `prev_row_hash = N`,
producing a fork that `verify_chain` reports as broken at the second row — a
correctness failure that looks exactly like tampering, which is the worst possible
false positive for this table. `pg_advisory_xact_lock` serialises appenders for the
remainder of the transaction. It is a Postgres primitive, not a scheme: CLAUDE.md
forbids inventing cryptography, and it would equally forbid inventing concurrency
control.

**The timestamp is committed as a string.** The digest covers `utc_ts` in ISO-8601,
and the column is `timestamptz`, so the two must round-trip identically or every
verification fails. The value is generated here rather than by `now()` for that
reason: a server-side default would be committed to under one rendering and read back
under another.

Invariant 4 governs what may go in — `case_id, actor_id, action, object_type,
object_id, utc_ts` and nothing else. There is no parameter here for a note, and
adding one would be the change that puts a party name on the chain.
"""
from datetime import datetime, timezone

import sqlalchemy as sa

from domain.audit import GENESIS_HASH, AuditPayload, compute_row_hash
from domain.enums import AuditAction

# One arbitrary, stable key identifying "the audit chain" to Postgres. Any appender
# in any process takes the same lock; nothing else in the build takes an advisory lock.
_CHAIN_LOCK_KEY = 8_713_301


async def append_audit(
    conn,
    *,
    case_id: str,
    actor_id: str,
    action: AuditAction,
    object_type: str,
    object_id: str,
    at: datetime | None = None,
) -> str:
    """Append one row and return its hash. Never updates; the grant forbids it."""
    await conn.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})

    prev = (
        await conn.execute(
            sa.text("SELECT row_hash FROM audit_event ORDER BY seq DESC LIMIT 1")
        )
    ).scalar_one_or_none() or GENESIS_HASH

    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = AuditPayload(
        case_id=str(case_id),
        actor_id=str(actor_id),
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        utc_ts=moment.isoformat(),
    )
    row_hash = compute_row_hash(prev, payload)

    await conn.execute(
        sa.text(
            "INSERT INTO audit_event "
            "(case_id, actor_id, action, object_type, object_id, utc_ts, "
            " prev_row_hash, row_hash) "
            "VALUES (:c, :a, :act, :ot, :oi, :ts, :prev, :hash)"
        ),
        {
            "c": payload.case_id,
            "a": payload.actor_id,
            "act": payload.action.value,
            "ot": payload.object_type,
            "oi": payload.object_id,
            "ts": moment,
            "prev": prev,
            "hash": row_hash,
        },
    )
    return row_hash
