"""LocalAnchorStore — a local hash-chained record of document digests.

**The name is the point.** CLAUDE.md's honesty rules:

    The local hash-chain is not a blockchain. Class name `LocalAnchorStore`; only the
    Fabric adapter may use ledger or chain vocabulary.

So this is an anchor store. It is not a ledger, not a chain in the marketing sense,
and not distributed. The guard hook enforces the class-name half of that rule; this
docstring covers the half a regex cannot.

**What it is worth, precisely.** Each anchor commits to its predecessor, so altering
one in place breaks every anchor after it. That makes the record tamper-*evident* to
anyone holding an earlier copy of the head. It does not make it tamper-proof:

  - The digest is unkeyed, so whoever can write the table can recompute the rest
    (threat PRV-06).
  - Truncating the tail leaves a valid prefix and is undetectable without an
    externally witnessed head (PRV-07, accepted risk AR-4).
  - The anchor store sits in the same database, under the same administrator, as the
    artefact it anchors. An anchor under the same control as the thing it attests
    provides no independent attestation (PRV-10, AR-4). That is the honest limit and
    the pitch must state it before a judge does.

**Invariant 4** fixes the payload: `case_id, doc_id, version, sha256, actor_id,
action, utc_ts`. No PII. The insert below writes exactly that and the chain columns.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa

GENESIS_HASH = "0" * 64

# One arbitrary, stable key identifying "the anchor chain" to Postgres. Distinct from
# `infra/audit_log._CHAIN_LOCK_KEY`: the two chains are independent, and sharing a key
# would make every audit append wait behind every anchor for no reason.
_ANCHOR_CHAIN_LOCK_KEY = 8_713_302


@dataclass(frozen=True)
class AnchorRow:
    case_id: str
    document_id: str
    version_id: str
    content_sha256: str
    actor_id: str
    action: str
    utc_ts: str


def compute_anchor_hash(prev_row_hash: str, row: AnchorRow) -> str:
    """Deterministic digest over the invariant-4 tuple plus the predecessor.

    Canonical JSON rather than concatenation, for the same reason the audit chain
    uses it: joining fields end to end lets values shift across boundaries.
    """
    payload = json.dumps(
        {
            "prev": prev_row_hash,
            "case_id": row.case_id,
            "document_id": row.document_id,
            "version_id": row.version_id,
            "content_sha256": row.content_sha256,
            "actor_id": row.actor_id,
            "action": row.action,
            "utc_ts": row.utc_ts,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class LocalAnchorStore:
    """Appends anchors and reads them back. Not a ledger; see the module docstring."""

    maturity = "mvp"
    production_adapter = "FabricLedger (a Hyperledger Fabric adapter), unbuilt"

    async def head_hash(self, conn) -> str:
        """The most recent anchor's hash, or the genesis value."""
        value = (
            await conn.execute(
                sa.text("SELECT row_hash FROM anchor_record ORDER BY seq DESC LIMIT 1")
            )
        ).scalar_one_or_none()
        return value or GENESIS_HASH

    async def anchor(
        self,
        conn,
        *,
        case_id: str,
        document_id: str,
        version_id: str,
        content_sha256: str,
        actor_id: str,
        at: datetime,
        action: str = "anchor",
    ) -> str:
        """Append one anchor and return its hash.

        Idempotent per version: anchoring twice returns the existing anchor rather
        than writing a second one. A retry must not produce a second anchor
        (reliability invariant), and the UNIQUE constraint on version_id is what
        actually enforces it.
        """
        # **Serialise appenders, for the reason `infra/audit_log.py` already gives.**
        #
        # Appending means reading the current head and committing to it. Two appenders
        # that both read head N both write `prev_row_hash = N`, and `verify_chain` walks
        # by seq and fails at the second one - reporting the anchor store as broken, for
        # ever, with no repair path: the rows are append-only and ordin_app holds no
        # UPDATE or DELETE on them.
        #
        # That is a false accusation of tampering against an untouched store, on the one
        # mechanism this product is pitched on. The audit chain was given
        # `pg_advisory_xact_lock` for exactly this and its comment says "nothing else in
        # the build takes an advisory lock" - which was true, and was the bug. A separate
        # key, because the two chains are independent and serialising them against each
        # other would be a needless contention point.
        #
        # It does not take two workers. `create_redacted_version` anchors a derivative
        # from the API process while the worker anchors an upload: two processes, no
        # in-process serialisation to fall back on.
        await conn.execute(
            sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ANCHOR_CHAIN_LOCK_KEY}
        )

        existing = (
            await conn.execute(
                sa.text(
                    "SELECT row_hash FROM anchor_record WHERE version_id = :v"
                ),
                {"v": version_id},
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        row = AnchorRow(
            case_id=str(case_id),
            document_id=str(document_id),
            version_id=str(version_id),
            content_sha256=content_sha256,
            actor_id=str(actor_id),
            action=action,
            utc_ts=at.isoformat(),
        )
        prev = await self.head_hash(conn)
        row_hash = compute_anchor_hash(prev, row)

        await conn.execute(
            sa.text(
                "INSERT INTO anchor_record "
                "(case_id, document_id, version_id, content_sha256, actor_id, action, "
                " utc_ts, prev_row_hash, row_hash) "
                "VALUES (:case_id, :document_id, :version_id, :content_sha256, :actor_id, "
                "        :action, :utc_ts, :prev, :row_hash)"
            ),
            {
                "case_id": row.case_id,
                "document_id": row.document_id,
                "version_id": row.version_id,
                "content_sha256": row.content_sha256,
                "actor_id": row.actor_id,
                "action": row.action,
                "utc_ts": at,
                "prev": prev,
                "row_hash": row_hash,
            },
        )
        return row_hash

    async def for_version(self, conn, version_id: str) -> dict | None:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT content_sha256, row_hash, prev_row_hash, utc_ts "
                    "FROM anchor_record WHERE version_id = :v"
                ),
                {"v": version_id},
            )
        ).mappings().one_or_none()
        return dict(row) if row else None

    async def verify_chain(self, conn) -> tuple[bool, int | None]:
        """Recompute every anchor. Returns (intact, first broken seq).

        Reads every row by design: this is a whole-store integrity check, not a
        case-scoped read. The coverage pass noted that chain verification and
        case-scoped audit reads are mutually exclusive (seam 5) - so this is an
        operator action, never something a case-scoped API route may call.
        """
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT seq, case_id, document_id, version_id, content_sha256, "
                    "       actor_id, action, utc_ts, prev_row_hash, row_hash "
                    "FROM anchor_record ORDER BY seq"
                )
            )
        ).mappings().all()

        prev = GENESIS_HASH
        for row in rows:
            expected = compute_anchor_hash(
                prev,
                AnchorRow(
                    case_id=str(row["case_id"]),
                    document_id=str(row["document_id"]),
                    version_id=str(row["version_id"]),
                    content_sha256=row["content_sha256"],
                    actor_id=str(row["actor_id"]),
                    action=row["action"],
                    utc_ts=row["utc_ts"].isoformat(),
                ),
            )
            if expected != row["row_hash"] or prev != row["prev_row_hash"]:
                return False, row["seq"]
            prev = row["row_hash"]
        return True, None
