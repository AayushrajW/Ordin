"""Two anchors written at once must not fork the chain.

`infra/audit_log.py` diagnoses this failure for the audit chain and fixes it with
`pg_advisory_xact_lock`. Its comment says "nothing else in the build takes an advisory
lock" — which was true, and was the bug: `LocalAnchorStore.anchor` read the head with a
plain SELECT and inserted, so two appenders that both read head N both wrote
`prev_row_hash = N`.

What that costs is worse than a lost write. `verify_chain` walks by seq and fails at the
second of the two, and every row after it, permanently — the rows are append-only and
`ordin_app` holds no UPDATE or DELETE on them, so there is no repair path. The anchor
store is the mechanism this product is pitched on, and the symptom is it accusing an
untouched store of tampering.

It does not take two workers to reach. `create_redacted_version` anchors a derivative
from the API process while the worker anchors an upload: two processes, nothing in
memory to serialise them.

These tests assert the property over **the rows they themselves write**, not over the
whole table. A dev database that has been through dozens of destructive cycles carries
historical damage that has nothing to do with the code under test, and a test that
demanded a globally intact chain would report that instead.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from infra.anchor import AnchorRow, GENESIS_HASH, LocalAnchorStore, compute_anchor_hash

pytestmark = pytest.mark.requires_db

CONCURRENT = 10


@pytest.fixture
async def engine(live_settings):
    e = create_async_engine(live_settings.owner_dsn)
    yield e
    await e.dispose()


async def _fixture_ids(engine) -> tuple[str, str]:
    async with engine.connect() as conn:
        case_id = (
            await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))
        ).scalar_one()
        actor = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
    return case_id, actor


async def _anchor_one(engine, store, case_id, actor) -> str:
    """One anchor in its own transaction — the way two processes would do it."""
    async with engine.begin() as conn:
        return await store.anchor(
            conn,
            case_id=case_id,
            document_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content_sha256="a" * 64,
            actor_id=actor,
            at=datetime.now(timezone.utc),
        )


async def test_concurrent_anchors_do_not_share_a_predecessor(engine):
    """The fork itself. Ten appenders, ten distinct predecessors, or the chain is cut."""
    case_id, actor = await _fixture_ids(engine)
    store = LocalAnchorStore()

    hashes = await asyncio.gather(
        *[_anchor_one(engine, store, case_id, actor) for _ in range(CONCURRENT)]
    )
    assert len(set(hashes)) == CONCURRENT, "two anchors produced the same row hash"

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT prev_row_hash FROM anchor_record "
                    "ORDER BY seq DESC LIMIT :n"
                ),
                {"n": CONCURRENT},
            )
        ).scalars().all()

    assert len(set(rows)) == CONCURRENT, (
        "two of the anchors written concurrently share a predecessor, so the chain "
        "forked and verify_chain will report tampering on an untouched store"
    )


async def test_the_rows_just_written_form_an_unbroken_chain(engine):
    """Not just distinct predecessors — each row must actually link to the one before,
    and its hash must recompute from its own contents."""
    case_id, actor = await _fixture_ids(engine)
    store = LocalAnchorStore()

    await asyncio.gather(
        *[_anchor_one(engine, store, case_id, actor) for _ in range(CONCURRENT)]
    )

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT seq, case_id, document_id, version_id, content_sha256, "
                    "       actor_id, action, utc_ts, prev_row_hash, row_hash "
                    "FROM anchor_record ORDER BY seq DESC LIMIT :n"
                ),
                {"n": CONCURRENT},
            )
        ).mappings().all()
    rows = list(reversed(rows))

    for earlier, later in zip(rows, rows[1:]):
        assert later["prev_row_hash"] == earlier["row_hash"], (
            f"seq {later['seq']} does not follow seq {earlier['seq']}"
        )

    for row in rows:
        recomputed = compute_anchor_hash(
            row["prev_row_hash"],
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
        assert recomputed == row["row_hash"], (
            f"seq {row['seq']} does not recompute from its own contents — the "
            f"timestamp did not round-trip through timestamptz, or the payload changed"
        )


async def test_anchoring_the_same_version_twice_is_still_idempotent(engine):
    """The lock must not have broken the reliability invariant it sits next to:
    a retry must not produce a second anchor."""
    case_id, actor = await _fixture_ids(engine)
    store = LocalAnchorStore()
    version_id = uuid.uuid4()
    document_id = uuid.uuid4()

    async def once() -> str:
        async with engine.begin() as conn:
            return await store.anchor(
                conn,
                case_id=case_id,
                document_id=document_id,
                version_id=version_id,
                content_sha256="b" * 64,
                actor_id=actor,
                at=datetime.now(timezone.utc),
            )

    first = await once()
    second = await once()
    assert first == second

    async with engine.connect() as conn:
        count = (
            await conn.execute(
                sa.text("SELECT count(*) FROM anchor_record WHERE version_id = :v"),
                {"v": version_id},
            )
        ).scalar_one()
    assert count == 1, "a retry wrote a second anchor"


def test_the_anchor_lock_key_differs_from_the_audit_one():
    """Two independent chains. Sharing a key would make every audit append wait behind
    every anchor, which is a contention point invented for no reason."""
    from infra.anchor import _ANCHOR_CHAIN_LOCK_KEY
    from infra.audit_log import _CHAIN_LOCK_KEY

    assert _ANCHOR_CHAIN_LOCK_KEY != _CHAIN_LOCK_KEY


def test_genesis_is_what_an_empty_chain_starts_from():
    """Belt and braces on the constant the first row commits to."""
    assert GENESIS_HASH == "0" * 64
