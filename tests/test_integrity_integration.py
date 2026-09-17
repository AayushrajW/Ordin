"""Storage, anchoring and verification against a real database and real files.

`test_integrity_states.py` covers the decision logic with nothing running. This covers
the parts that only break in contact with reality: bytes edited on disk, an anchor
written twice, a chain recomputed, and the acceptance criteria as `docs/PLAN.md`
words them —

    mutate bytes on disk -> MISMATCH naming the diverged version;
    dispose -> DISPOSED_ANCHOR_ONLY, not MISMATCH
"""
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.integrity import AnchorFacts, VerificationState, VersionFacts, verify_version
from infra.anchor import GENESIS_HASH, LocalAnchorStore
from infra.blobstore import LocalBlobStore, sha256_bytes

pytestmark = pytest.mark.requires_db

CONTENT = b"SPECIMEN - NOT A REAL RECORD\nComplaint body.\n"
NOW = datetime.now(timezone.utc)


@pytest.fixture
async def ctx(live_settings, tmp_path):
    """A seeded case with one document version, plus a blob store on disk."""
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    blobs = LocalBlobStore(tmp_path / "blobs")
    anchors = LocalAnchorStore()

    async with engine.connect() as conn:
        case_id = (await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))).scalar_one()
        actor_id = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        document_id, version_id = uuid.uuid4(), uuid.uuid4()
        address = blobs.put(CONTENT)

        await conn.execute(
            sa.text("INSERT INTO document (id, case_id, title) VALUES (:i, :c, 'Specimen')"),
            {"i": document_id, "c": case_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO document_version "
                "(id, document_id, version_no, sha256, lifecycle_state, access_class) "
                "VALUES (:i, :d, 1, :h, 'active', 'normal')"
            ),
            {"i": version_id, "d": document_id, "h": address},
        )
        await conn.commit()
        yield conn, blobs, anchors, {
            "case_id": case_id, "document_id": document_id,
            "version_id": version_id, "actor_id": actor_id, "address": address,
        }
    await engine.dispose()


async def facts_for(conn, blobs, anchors, ids, **overrides) -> VersionFacts:
    """Gather what the pure verifier needs, the way a real caller would."""
    row = (
        await conn.execute(
            sa.text("SELECT sha256, lifecycle_state FROM document_version WHERE id = :i"),
            {"i": ids["version_id"]},
        )
    ).mappings().one()
    anchor = await anchors.for_version(conn, str(ids["version_id"]))
    disposed = (
        await conn.execute(
            sa.text("SELECT count(*) FROM disposition WHERE version_id = :i"),
            {"i": ids["version_id"]},
        )
    ).scalar_one()
    base = dict(
        version_id=str(ids["version_id"]),
        lifecycle_state=row["lifecycle_state"],
        recorded_sha256=row["sha256"],
        anchor=AnchorFacts(content_sha256=anchor["content_sha256"]) if anchor else None,
        live_sha256=blobs.digest_of_stored(row["sha256"]),
        disposition_recorded=bool(disposed),
    )
    return VersionFacts(**{**base, **overrides})


# --- blob store ---------------------------------------------------------------

def test_the_same_bytes_get_the_same_address(tmp_path):
    store = LocalBlobStore(tmp_path)
    assert store.put(CONTENT) == store.put(CONTENT) == sha256_bytes(CONTENT)


def test_digest_of_stored_rereads_rather_than_trusting_the_address(tmp_path):
    """The whole point of verify() is catching bytes edited underneath us."""
    store = LocalBlobStore(tmp_path)
    address = store.put(CONTENT)
    store._path(address).write_bytes(b"tampered")
    assert store.digest_of_stored(address) != address


def test_a_missing_blob_reads_as_absent_not_as_an_error(tmp_path):
    store = LocalBlobStore(tmp_path)
    assert store.get("f" * 64) is None
    assert store.digest_of_stored("f" * 64) is None


def test_a_malformed_address_is_refused(tmp_path):
    store = LocalBlobStore(tmp_path)
    with pytest.raises(ValueError):
        store.get("../../etc/passwd")


# --- the acceptance criteria --------------------------------------------------

async def test_an_anchored_unmodified_document_verifies(ctx):
    conn, blobs, anchors, ids = ctx
    await anchors.anchor(
        conn, case_id=ids["case_id"], document_id=ids["document_id"],
        version_id=ids["version_id"], content_sha256=ids["address"],
        actor_id=ids["actor_id"], at=NOW,
    )
    await conn.commit()
    result = verify_version(await facts_for(conn, blobs, anchors, ids))
    assert result.state is VerificationState.VERIFIED


async def test_mutating_bytes_on_disk_gives_mismatch_naming_the_version(ctx):
    """PLAN's acceptance criterion, verbatim."""
    conn, blobs, anchors, ids = ctx
    await anchors.anchor(
        conn, case_id=ids["case_id"], document_id=ids["document_id"],
        version_id=ids["version_id"], content_sha256=ids["address"],
        actor_id=ids["actor_id"], at=NOW,
    )
    await conn.commit()

    blobs._path(ids["address"]).write_bytes(CONTENT + b"\nan extra line nobody authorised")

    result = verify_version(await facts_for(conn, blobs, anchors, ids))
    assert result.state is VerificationState.MISMATCH
    assert result.version_id == str(ids["version_id"]), "MISMATCH did not name the version"


async def test_disposal_gives_disposed_anchor_only_not_mismatch(ctx):
    """The other half of the acceptance criterion, and the one with legal weight."""
    conn, blobs, anchors, ids = ctx
    await anchors.anchor(
        conn, case_id=ids["case_id"], document_id=ids["document_id"],
        version_id=ids["version_id"], content_sha256=ids["address"],
        actor_id=ids["actor_id"], at=NOW,
    )
    # Dispose: the bytes go, the anchor and the disposition record stay.
    blobs._path(ids["address"]).unlink()
    await conn.execute(
        sa.text("UPDATE document_version SET lifecycle_state = 'disposed' WHERE id = :i"),
        {"i": ids["version_id"]},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO disposition (id, version_id, disposed_by, basis) "
            "VALUES (:i, :v, :u, 'retention_expiry')"
        ),
        {"i": uuid.uuid4(), "v": ids["version_id"], "u": ids["actor_id"]},
    )
    await conn.commit()

    result = verify_version(await facts_for(conn, blobs, anchors, ids))
    assert result.state is VerificationState.DISPOSED_ANCHOR_ONLY, (
        f"a lawful disposal reported as {result.state} - CLAUDE.md calls reporting "
        f"MISMATCH here a legal misrepresentation"
    )


async def test_an_unanchored_version_is_pending(ctx):
    """ADR 0010, against the real database: no anchor row yet."""
    conn, blobs, anchors, ids = ctx
    result = verify_version(await facts_for(conn, blobs, anchors, ids))
    assert result.state is VerificationState.PENDING


# --- anchoring ----------------------------------------------------------------

async def test_anchoring_twice_produces_one_anchor(ctx):
    """A retry must not produce a second anchor (reliability invariant)."""
    conn, _, anchors, ids = ctx
    first = await anchors.anchor(
        conn, case_id=ids["case_id"], document_id=ids["document_id"],
        version_id=ids["version_id"], content_sha256=ids["address"],
        actor_id=ids["actor_id"], at=NOW,
    )
    second = await anchors.anchor(
        conn, case_id=ids["case_id"], document_id=ids["document_id"],
        version_id=ids["version_id"], content_sha256=ids["address"],
        actor_id=ids["actor_id"], at=NOW,
    )
    await conn.commit()
    count = (
        await conn.execute(
            sa.text("SELECT count(*) FROM anchor_record WHERE version_id = :v"),
            {"v": ids["version_id"]},
        )
    ).scalar_one()
    assert first == second and count == 1


async def test_the_first_anchor_chains_from_genesis(ctx):
    conn, _, anchors, ids = ctx
    await conn.execute(sa.text("DELETE FROM anchor_record"))
    await conn.commit()
    assert await anchors.head_hash(conn) == GENESIS_HASH


async def test_the_chain_verifies_and_detects_an_edited_anchor(ctx):
    conn, _, anchors, ids = ctx
    await anchors.anchor(
        conn, case_id=ids["case_id"], document_id=ids["document_id"],
        version_id=ids["version_id"], content_sha256=ids["address"],
        actor_id=ids["actor_id"], at=NOW,
    )
    await conn.commit()

    intact, broken_at = await anchors.verify_chain(conn)
    assert intact and broken_at is None

    # Edit a digest in place, as an owner or superuser could (threat PRV-10).
    await conn.execute(
        sa.text("UPDATE anchor_record SET content_sha256 = :h WHERE version_id = :v"),
        {"h": "c" * 64, "v": ids["version_id"]},
    )
    await conn.commit()

    intact, broken_at = await anchors.verify_chain(conn)
    assert not intact and broken_at is not None


async def test_the_anchor_carries_no_field_outside_invariant_4(ctx):
    conn, _, _, _ = ctx
    columns = {
        r[0]
        for r in (
            await conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'anchor_record'"
                )
            )
        ).all()
    }
    allowed = {
        "seq", "case_id", "document_id", "version_id", "content_sha256",
        "actor_id", "action", "utc_ts", "prev_row_hash", "row_hash",
    }
    assert columns == allowed, f"unexpected columns on the anchor: {columns - allowed}"


async def test_the_app_role_cannot_rewrite_an_anchor(live_settings):
    """Same REVOKE reasoning as audit_event."""
    engine = create_async_engine(live_settings.app_dsn)
    async with engine.connect() as conn:
        granted = {
            r[0].upper()
            for r in (
                await conn.execute(
                    sa.text(
                        "SELECT privilege_type FROM information_schema.role_table_grants "
                        "WHERE table_name = 'anchor_record' AND grantee = current_user"
                    )
                )
            ).all()
        }
    await engine.dispose()
    assert "INSERT" in granted and "SELECT" in granted
    assert "UPDATE" not in granted and "DELETE" not in granted
