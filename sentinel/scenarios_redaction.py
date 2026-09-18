"""Slice 7's contribution to Sentinel.

These are the claims the pitch opens with, expressed as things that can visibly go
red. The first is the one a judge watches; the third is the one that would actually
have been true if nobody had read the threat model.
"""
import json
from pathlib import Path

from sentinel.registry import Severity, scenario

SLICE = "7"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"
SIDECAR = ROOT / "fixtures" / "corpus" / "complaint-0001.json"


def _regions():
    from infra.redact import Region

    side = json.loads(SIDECAR.read_text(encoding="utf-8"))
    return (
        [
            Region(page_no=f["page"], x0=f["bbox"][0], y0=f["bbox"][1],
                   x1=f["bbox"][2], y1=f["bbox"][3], rule_id=f["label"],
                   removed_text=f["value"])
            for f in side["identifying_fields"]
        ],
        [f["value"] for f in side["identifying_fields"]],
    )


async def _ensure_derivative(ctx) -> None:
    """Make sure a redacted derivative exists, creating one if not.

    Sentinel has to run from a clean database - `fresh && seed && sentinel` is the
    demo sequence, and a scenario that fails because its fixture is absent reports the
    system as broken when it is not. Establishing the precondition is the scenario's
    job; asserting on it afterwards is the test.
    """
    import uuid

    import sqlalchemy as sa

    from infra.redact import redact

    async with ctx.engine.connect() as conn:
        existing = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM document_version "
                    "WHERE derived_from_version_id IS NOT NULL"
                )
            )
        ).scalar_one()
        if existing:
            return

        case_id = (
            await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))
        ).scalar_one()

        document_id, parent_id, derivative_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        regions, names = _regions()
        result = redact(FIXTURE.read_bytes(), regions)

        await conn.execute(
            sa.text("INSERT INTO document (id, case_id, title) VALUES (:i,:c,'Specimen')"),
            {"i": document_id, "c": case_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO document_version (id, document_id, version_no, sha256) "
                "VALUES (:i,:d,1,:h)"
            ),
            {"i": parent_id, "d": document_id, "h": "a" * 64},
        )
        # The original's derived text, which is the thing REDACT-03 must find and
        # then be refused. Without it that scenario would pass vacuously.
        await conn.execute(
            sa.text(
                "INSERT INTO ocr_text (id, version_id, text, method, provider, model) "
                "VALUES (:i,:v,:t,'embedded_text_layer','pymupdf','text-layer')"
            ),
            {"i": uuid.uuid4(), "v": parent_id,
             "t": "Complainant Name: " + names[0] + "\nSpecimen body.\n"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO extracted_field "
                "(id, version_id, case_id, field_key, value, source, source_span_start, "
                " source_span_end, provider, model, status) "
                "VALUES (:i,:v,:c,'complainant_name',:val,'regex',18,:e,'ordin.regex',"
                " 'complainant_name.v1','draft')"
            ),
            {"i": uuid.uuid4(), "v": parent_id, "c": case_id, "val": names[0],
             "e": 18 + len(names[0])},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO document_version (id, document_id, version_no, sha256, "
                " derived_from_version_id, redaction_manifest_hash) "
                "VALUES (:i,:d,2,:h,:p,:m)"
            ),
            {"i": derivative_id, "d": document_id, "h": "b" * 64,
             "p": parent_id, "m": result.manifest_hash},
        )
        await conn.commit()


@scenario(
    id="REDACT-01",
    invariant="8 - redaction is destructive, not presentational",
    setup="Redact the identifying fields from a specimen complaint, then extract text "
          "from the derivative.",
    expected="None of the removed values appear. The glyphs are gone, not covered.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def removed_names_are_absent_from_the_derivative(ctx) -> str:
    from infra.redact import confirm_absent, redact

    regions, names = _regions()
    result = redact(FIXTURE.read_bytes(), regions)
    leaked = confirm_absent(result.pdf_bytes, names)
    assert not leaked, f"still extractable from the derivative: {leaked}"
    return f"{len(names)} values removed; none extractable from the derivative"


@scenario(
    id="REDACT-02",
    invariant="8 - unauthorised roles never receive original bytes on any code path",
    setup="A role holding only the redacted derivative asks for the parent version id, "
          "which the derivative openly references.",
    expected="The parent is not among the versions it may read.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def the_parent_version_is_out_of_reach(ctx) -> str:
    import sqlalchemy as sa

    from infra.disclosure import Disclosure, readable_version_ids

    await _ensure_derivative(ctx)
    async with ctx.engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT id, document_id, derived_from_version_id FROM document_version "
                    "WHERE derived_from_version_id IS NOT NULL LIMIT 1"
                )
            )
        ).mappings().one_or_none()
        if row is None:
            raise AssertionError("no redacted derivative exists to test against")
        allowed = await readable_version_ids(
            conn, document_id=row["document_id"], disclosure=Disclosure.REDACTED
        )

    assert str(row["derived_from_version_id"]) not in allowed, (
        "the redacted role may read the parent version"
    )
    assert str(row["id"]) in allowed, "the redacted role cannot read its own derivative"
    return "parent denied, derivative permitted"


@scenario(
    id="REDACT-03",
    invariant="VIC-01 - the derived text is original content in a different shape",
    setup="A role holding only the derivative reads the ORIGINAL version's OCR text and "
          "extracted field values, which redaction never touched.",
    expected="Nothing. The PDF being clean is not enough.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def the_originals_text_is_not_reachable_from_the_derivative(ctx) -> str:
    import sqlalchemy as sa

    from infra.disclosure import Disclosure, readable_fields, readable_ocr_text

    await _ensure_derivative(ctx)
    async with ctx.engine.connect() as conn:
        parent_id = (
            await conn.execute(
                sa.text(
                    "SELECT derived_from_version_id FROM document_version "
                    "WHERE derived_from_version_id IS NOT NULL LIMIT 1"
                )
            )
        ).scalar_one_or_none()
        if parent_id is None:
            raise AssertionError("no redacted derivative exists to test against")

        # The text must genuinely still hold the names, or this proves nothing.
        full = await readable_ocr_text(conn, version_id=str(parent_id),
                                       disclosure=Disclosure.ORIGINAL)
        assert full, "the original has no OCR text; this scenario is vacuous"

        denied_text = await readable_ocr_text(conn, version_id=str(parent_id),
                                              disclosure=Disclosure.REDACTED)
        denied_fields = await readable_fields(conn, version_id=str(parent_id),
                                              disclosure=Disclosure.REDACTED)

    assert denied_text is None, "the redacted role read the unredacted OCR text"
    assert denied_fields == [], "the redacted role read the extracted field values"
    return "OCR text and field values both withheld while the original retains them"


@scenario(
    id="REDACT-04",
    invariant="VIC-04 - the manifest must not become a curated list of names",
    setup="Inspect the redaction manifest produced alongside the derivative.",
    expected="Geometry, rule ids and salted hashes. No removed text.",
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def the_manifest_holds_no_removed_text(ctx) -> str:
    from infra.redact import redact

    regions, names = _regions()
    result = redact(FIXTURE.read_bytes(), regions)
    blob = json.dumps(result.regions).lower()
    leaked = [n for n in names if n.lower() in blob]
    assert not leaked, f"the manifest contains {leaked}"
    return f"{len(result.regions)} regions recorded as geometry + salted hash only"
