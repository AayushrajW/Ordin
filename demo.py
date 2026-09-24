"""Load a demonstrable case file: `python tasks.py demo`.

`seed.py` creates the structure — organizations, posts, users, cases, assignments and
grants. That is what the authorization tests need and it is not a demo: the case list
is real and every case is empty.

This ingests documents through the **real pipeline**, so what a judge opens is a
version produced by the same code path as any other, with real OCR text, real spans
and real draft fields awaiting a human. Nothing here writes a row the application
could not have written.

Three properties it deliberately preserves:

  **Every extracted field is left as a draft.** The demo beat is a person committing
  one. A seeded `verified` row would be a screen that does not execute the real code
  path, which CLAUDE.md names as the thing worse than seed data.

  **One document gets a redacted derivative**, so the role switch has something to
  switch between on a database that has never run Sentinel.

  **Documents are spread across the three seeded cases**, including the sealed one, so
  the case list differs per identity rather than being uniformly empty or uniformly
  full.
"""
import asyncio
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings  # noqa: E402
from infra.anchor import LocalAnchorStore  # noqa: E402
from infra.blobstore import LocalBlobStore
from infra.crypto import EnvironmentMasterKey  # noqa: E402
from infra.esign import SimulatedESignProvider  # noqa: E402
from infra.pipeline import Pipeline  # noqa: E402
from infra.redaction_service import RedactionUnavailable, create_redacted_version  # noqa: E402
from infra.textsource import TesseractOcr, TextSourceUnavailable  # noqa: E402

# Hand-written fixtures only, addressed by slug. The generated variants are for the
# accuracy figure; these are the ones whose content reads sensibly on a screen.
DOC_CLASS_MAP = {
    "complaint": "fir",
    "statement": "statement",
    "witness": "statement",
    "medical": "forensic_report",
    # A property register extract is a register entry, not a laboratory finding. It was
    # mapped to forensic_report, so the completeness engine reported a case as holding a
    # forensic report it does not hold - the one thing that check exists to notice.
    "property": "other",
    "seizure": "other",
}


def infer_doc_class(slug: str) -> str:
    for prefix, cls in DOC_CLASS_MAP.items():
        if slug.startswith(prefix):
            return cls
    return "other"


PLAN = [
    ("VRN-N/2026/0001", ["complaint-0001", "statement-0011", "witness-0003", "seizure-0006", "property-0010"]),
    ("VRN-S/2026/0002", ["complaint-0002"]),
    ("VRN-N/2026/0003", ["complaint-0008-hi", "medical-0005"]),
]
REDACT_IN = "statement-0011.pdf"


async def load_demo() -> int:
    settings = Settings()
    engine = create_async_engine(settings.owner_dsn)
    blob_root = Path(settings.ordin_blob_root)
    if not blob_root.is_absolute():
        blob_root = ROOT / blob_root
    blobs = LocalBlobStore(
        blob_root,
        master=EnvironmentMasterKey.from_setting(
            settings.ordin_master_key.get_secret_value()
        ),
    )

    try:
        ocr = TesseractOcr()
        ocr.available()
    except Exception:  # noqa: BLE001
        pass

    pipeline = Pipeline(
        blobs=blobs,
        text_source=TesseractOcr(),
        signer=SimulatedESignProvider(settings.ordin_session_secret.get_secret_value()),
        anchors=LocalAnchorStore(),
    )

    loaded = 0
    try:
        async with engine.connect() as conn:
            actor = (
                await conn.execute(
                    sa.text("SELECT id FROM app_user WHERE display_name LIKE 'SHO%' LIMIT 1")
                )
            ).scalar_one_or_none()
            if actor is None:
                print("  no seeded users - run `python tasks.py seed` first")
                return 2
    
            for reference, slugs in PLAN:
                case_id = (
                    await conn.execute(
                        sa.text("SELECT id FROM case_record WHERE reference = :r"),
                        {"r": reference},
                    )
                ).scalar_one_or_none()
                if case_id is None:
                    print(f"  case {reference} is not seeded - skipping")
                    continue
    
                for slug in slugs:
                    pdf = ROOT / "fixtures" / "corpus" / f"{slug}.pdf"
                    if not pdf.exists():
                        print(f"  {slug}.pdf missing - run `python tasks.py fixtures`")
                        continue
                    doc_class = infer_doc_class(slug)
                    try:
                        result = await pipeline.run(
                            conn, case_id=case_id, filename=f"{slug}.pdf",
                            data=pdf.read_bytes(), actor_id=actor,
                            doc_class=doc_class,
                        )
                    except TextSourceUnavailable:
                        print("  tesseract is not installed - the demo needs real OCR")
                        return 2
                    failed = [s.stage for s in result.stages if s.error_code]
                    print(
                        f"  {reference}  {slug:<22} v{result.version_id[:8]}"
                        + (f"  FAILED at {', '.join(failed)}" if failed else "")
                    )
                    loaded += 1
    
                    if f"{slug}.pdf" == REDACT_IN:
                        fields = (
                            await conn.execute(
                                sa.text(
                                    "SELECT id FROM extracted_field WHERE version_id = :v "
                                    "AND source_span_start IS NOT NULL"
                                ),
                                {"v": result.version_id},
                            )
                        ).scalars().all()
                        try:
                            made = await create_redacted_version(
                                conn, blobs,
                                parent_version_id=result.version_id,
                                case_id=str(case_id),
                                field_ids=[str(f) for f in fields],
                                actor_id=str(actor),
                            )
                            print(
                                f"  {reference}  redacted derivative        "
                                f"{made['regions']} region(s) removed"
                            )
                        except RedactionUnavailable as exc:
                            # Said out loud rather than swallowed: on a poor scan OCR may
                            # locate nothing, and a demo that silently has no derivative
                            # is a demo whose role switch shows two identical documents.
                            print(f"  redaction produced nothing: {exc}")
    
            await conn.commit()
    
            drafts = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM extracted_field WHERE status = 'draft'")
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    print(f"\n  {loaded} documents ingested, {drafts} fields awaiting a human")
    print("  every field is a draft: committing one is the demo, not the fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(load_demo()))
