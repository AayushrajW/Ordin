"""The sign stage has to leave something that can be checked.

It computed a full HMAC-SHA256 and returned `signature:{value[:16]}` as the job's
`output_ref`. Nothing else was stored — no signature table, and `output_ref` is written
by `_finish` and read only by `_claim` in the same module. So the case record said a
document was signed, named a provider and a maturity, and held sixty-four bits of a
discarded digest in an internal column nothing reads.

`SimulatedESignProvider.verify` needs the full value **and** the whole `bound_to`
structure including `signed_at`. Neither survived the stage, so the claim was
unfalsifiable — the failure CLAUDE.md names as "never hide a stub behind
plausible-looking output", and the one `infra/redaction_service.py` already states:
"A capability with no persistence path is a capability the product does not have."

The test that matters is `test_the_stored_signature_verifies`: not that a row exists,
but that what was stored can be handed back to the provider and checked.
"""
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from infra.anchor import LocalAnchorStore
from infra.blobstore import LocalBlobStore
from infra.esign import Signature, SimulatedESignProvider
from infra.pipeline import Pipeline
from infra.tables import app_user, case_record
from infra.textsource import EmbeddedTextLayer

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"
SECRET = "test-secret"


@pytest.fixture
async def processed(live_settings, tmp_path):
    """One document through the real pipeline. Returns (engine, version_id)."""
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    async with engine.connect() as conn:
        case_id = (
            await conn.execute(
                sa.select(case_record.c.id).where(
                    case_record.c.reference == "VRN-N/2026/0001"
                )
            )
        ).scalar_one()
        actor = (
            await conn.execute(
                sa.select(app_user.c.id).where(app_user.c.display_name.like("SHO Rahul%"))
            )
        ).scalar_one()
        result = await Pipeline(
            blobs=LocalBlobStore(tmp_path / "blobs"),
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider(SECRET),
            anchors=LocalAnchorStore(),
        ).run(
            conn,
            case_id=case_id,
            filename="complaint-0001.pdf",
            data=FIXTURE.read_bytes(),
            actor_id=actor,
        )
        await conn.commit()
    yield engine, result.version_id
    await engine.dispose()


async def _stored(engine, version_id: str) -> dict:
    async with engine.connect() as conn:
        return dict(
            (
                await conn.execute(
                    sa.text("SELECT * FROM version_signature WHERE version_id = :v"),
                    {"v": version_id},
                )
            ).mappings().one()
        )


async def test_the_sign_stage_persists_a_signature(processed):
    engine, version_id = processed
    row = await _stored(engine, version_id)
    assert len(row["value"]) == 64, "not a full SHA-256 digest"
    assert row["algorithm"] == "HMAC-SHA256"
    assert row["provider"] == "SimulatedESignProvider"
    assert row["maturity"] == "mvp", (
        "the record does not say what signed it, so a simulated signature is "
        "indistinguishable from a real one"
    )


async def test_the_stored_signature_verifies(processed):
    """The point of storing it. Reconstructed from the row alone and handed back.

    If `bound_to` is not persisted in full — `signed_at` is the easy one to drop — this
    fails, because `verify` recomputes the payload from it.
    """
    engine, version_id = processed
    row = await _stored(engine, version_id)

    rebuilt = Signature(
        value=row["value"],
        algorithm=row["algorithm"],
        provider=row["provider"],
        maturity=row["maturity"],
        signed_at=row["signed_at"],
        bound_to={
            "case_id": str(row["case_id"]),
            "document_id": str(row["document_id"]),
            "version_id": str(row["version_id"]),
            "content_sha256": row["content_sha256"],
            "actor_id": str(row["actor_id"]),
            "signed_at": row["signed_at"],
        },
    )
    assert SimulatedESignProvider(SECRET).verify(rebuilt), (
        "the stored signature does not verify against what it says it is bound to"
    )


async def test_a_signature_from_another_key_does_not_verify(processed):
    """And verification still discriminates — otherwise the test above proves nothing."""
    engine, version_id = processed
    row = await _stored(engine, version_id)
    rebuilt = Signature(
        value=row["value"], algorithm=row["algorithm"], provider=row["provider"],
        maturity=row["maturity"], signed_at=row["signed_at"],
        bound_to={
            "case_id": str(row["case_id"]), "document_id": str(row["document_id"]),
            "version_id": str(row["version_id"]), "content_sha256": row["content_sha256"],
            "actor_id": str(row["actor_id"]), "signed_at": row["signed_at"],
        },
    )
    assert not SimulatedESignProvider("a-different-secret").verify(rebuilt)


async def test_it_binds_the_content_digest_of_the_version_it_signed(processed):
    """A signature bound to the wrong document is worse than none."""
    engine, version_id = processed
    row = await _stored(engine, version_id)
    async with engine.connect() as conn:
        sha256 = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"),
                {"v": version_id},
            )
        ).scalar_one()
    assert row["content_sha256"] == sha256


async def test_it_carries_nothing_wider_than_the_anchor_tuple(processed):
    """Invariant 4 fixes what may be bound: case, document, version, digest, actor,
    timestamp. A signature over a filename or a title would put it on the record."""
    engine, version_id = processed
    async with engine.connect() as conn:
        columns = {
            r[0]
            for r in await conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'version_signature'"
                )
            )
        }
    allowed = {
        "id", "version_id", "value", "algorithm", "provider", "maturity",
        "case_id", "document_id", "content_sha256", "actor_id", "signed_at",
    }
    assert columns == allowed, f"unexpected columns: {sorted(columns - allowed)}"


async def test_re_signing_does_not_mint_a_second_signature(processed):
    """The reliability invariant lists anchor, version and derivative. A signature
    belongs in that list: two signatures for one version is two claims about it."""
    engine, version_id = processed
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                sa.text("SELECT count(*) FROM version_signature WHERE version_id = :v"),
                {"v": version_id},
            )
        ).scalar_one()
    assert count == 1


async def test_the_application_cannot_rewrite_a_signature(live_settings, processed):
    """Append-only by grant, not by intention. A signature that can be edited after the
    fact attests to nothing."""
    _, version_id = processed
    app_engine = create_async_engine(live_settings.app_dsn)
    try:
        with pytest.raises(Exception) as caught:
            async with app_engine.begin() as conn:
                await conn.execute(
                    sa.text("UPDATE version_signature SET value = 'rewritten'")
                )
        assert "permission denied" in str(caught.value).lower(), caught.value
    finally:
        await app_engine.dispose()
