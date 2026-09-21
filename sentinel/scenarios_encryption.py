"""Encryption at rest, as claims that can go red.

The deck says documents stay encrypted off-chain. Before ADR 0028 that was false, and
the failure was invisible: everything worked, and document bytes sat readable in
`var/blobs` for anybody with a shell on the host.

**A note on how the first version of CRYPT-01 was wrong**, because it is the more useful
lesson. It pushed the specimen statement through the pipeline and searched the stored
file for the victim's name. That search finds nothing **even with encryption switched
off**, because a PDF keeps its text in a deflate-compressed stream rather than as
literal bytes — so the scenario would have gone green against a completely plaintext
store. It only failed because it also asserted it had proved something, and could not.

So the claim is split into the two things that are separately checkable:

  CRYPT-01  a blob whose plaintext genuinely contains a name is unreadable on disk,
            and reads back correctly through the store
  CRYPT-03  the file the real pipeline wrote is actually sealed, so the property above
            applies to the path documents really take
"""
import uuid
from pathlib import Path

import sqlalchemy as sa

from sentinel.registry import Severity, scenario

SLICE = "encryption"
ROOT = Path(__file__).resolve().parents[1]
STATEMENT = ROOT / "fixtures" / "corpus" / "statement-0011.pdf"

SECRET = b"Victim Name: Rukmini Deshmukh, 27 Banyan Cross"


async def _sign_in(ctx, key: str) -> None:
    response = await ctx.client.post("/session", json={"user_id": ctx.ids[key]})
    assert response.status_code == 200, f"could not open a session: {response.text}"


def _require_key(ctx) -> None:
    if not getattr(ctx.blobs, "encrypted", False):
        # Not a broken scenario: the claim is false. ORDIN_MASTER_KEY is unset, so
        # every document is being written in plaintext.
        raise AssertionError(
            "no master key is configured, so blobs are written in plaintext. "
            "Generate one with `python tasks.py newkey` and set ORDIN_MASTER_KEY."
        )


def _path_for(ctx, address: str) -> Path:
    return ctx.blobs.root / address[:2] / address[2:4] / address


@scenario(
    id="CRYPT-01",
    invariant="Encryption at rest - stored bytes are unreadable on disk",
    setup=(
        "Store a document whose plaintext literally contains a victim's name and "
        "street, then read the file back off the filesystem and search it."
    ),
    expected=(
        "The name does not appear in the stored bytes, and the same document still "
        "reads back correctly through the store."
    ),
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def stored_bytes_are_not_readable(ctx) -> str:
    _require_key(ctx)

    plaintext = SECRET + b" " + uuid.uuid4().bytes
    address = ctx.blobs.put(plaintext)
    raw = _path_for(ctx, address).read_bytes()

    # The precondition, asserted rather than assumed: if the plaintext did not contain
    # the name, finding nothing on disk would prove nothing at all.
    assert b"Rukmini" in plaintext, "the specimen carries no name; this would prove nothing"

    leaked = [v for v in (b"Rukmini", b"Deshmukh", b"Banyan") if v in raw]
    assert not leaked, (
        f"the stored file contains {[v.decode() for v in leaked]} in cleartext. Anyone "
        "with a shell on this host, a copy of the backup, or the disk can read it."
    )
    assert ctx.blobs.get(address) == plaintext, (
        "the store cannot read back what it just wrote, so this passed by destroying "
        "the document rather than by protecting it"
    )
    return (
        f"{len(raw)} bytes on disk, none of them the victim's name; the document reads "
        "back byte-identical through the store"
    )


@scenario(
    id="CRYPT-03",
    invariant="Encryption at rest applies to the path documents actually take",
    setup=(
        "Push the specimen victim statement through the real pipeline and inspect the "
        "file it produced."
    ),
    expected="The stored file carries the envelope header, so it was sealed.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def the_pipeline_writes_sealed_blobs(ctx) -> str:
    from infra.anchor import LocalAnchorStore
    from infra.crypto import is_sealed
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    import fitz

    _require_key(ctx)
    await _sign_in(ctx, "officer")
    cases = (await ctx.client.get("/cases?limit=50")).json()
    assert cases, "the officer can see no case at all"

    # **Unique bytes every run, deliberately.** The store is content-addressed, so
    # `put` returns early when the address already exists — and the specimen statement
    # was stored before encryption was switched on. Re-ingesting it would find that
    # plaintext blob, return its address without writing, and report the pipeline as
    # broken when what it had actually found is that **enabling encryption does not
    # re-encrypt what is already stored**. True, documented in ADR 0028, and not what
    # this scenario is for: this one watches the write path for a regression.
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 96), f"SPECIMEN - NOT A REAL RECORD {uuid.uuid4()}")
    unique = document.tobytes()
    document.close()

    async with ctx.engine.begin() as conn:
        actor = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        result = await Pipeline(
            blobs=ctx.blobs,
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("sentinel"),
            anchors=LocalAnchorStore(),
        ).run(
            conn,
            case_id=uuid.UUID(cases[0]["id"]),
            filename=f"crypt-{uuid.uuid4().hex[:8]}.pdf",
            data=unique,
            actor_id=actor,
        )
    assert result.ok, "the pipeline failed on the specimen"

    raw = _path_for(ctx, result.content_sha256).read_bytes()
    assert is_sealed(raw), (
        "the pipeline wrote an unsealed blob. The store encrypts when asked directly, "
        "and the path documents actually travel does not."
    )
    # And the digest still matches, so encryption has not broken verify().
    assert ctx.blobs.digest_of_stored(result.content_sha256) == result.content_sha256, (
        "the stored document no longer verifies against its own address"
    )
    return (
        f"the pipeline's stored file is sealed ({len(raw)} bytes) and still verifies "
        "against the anchored digest"
    )


@scenario(
    id="CRYPT-02",
    invariant="5 - an altered document is refused, and reported as MISMATCH not missing",
    setup=(
        "Flip a single bit in a stored encrypted file, then ask the store for its "
        "digest the way verify() does."
    ),
    expected=(
        "A digest is returned and it does not equal the address, so verify() reports "
        "MISMATCH. It is never None, which would mean the bytes are gone."
    ),
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def a_tampered_blob_is_a_mismatch_not_a_disappearance(ctx) -> str:
    _require_key(ctx)

    address = ctx.blobs.put(b"specimen bytes for the tamper check " + uuid.uuid4().bytes)
    path = _path_for(ctx, address)

    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))

    digest = ctx.blobs.digest_of_stored(address)
    assert digest is not None, (
        "a tampered document reported as MISSING. 'The bytes are gone' and 'the bytes "
        "were altered' are different answers, and only one of them is a tamper alert"
    )
    assert digest != address, "a tampered document reported as matching its anchor"
    return "one flipped bit produced a digest that cannot match the anchor: MISMATCH"
