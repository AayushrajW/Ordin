"""Which version of a document a subject receives, and what else that implies.

Slice 7's demo is "one document, three roles, one URL". This is the function that
makes the three roles differ, and it exists separately from the case-level filter
because they answer different questions:

    slice 3's filter   may this subject see this CASE at all?
    this module        given that they may, WHICH VERSION do they get?

**Threat VIC-01 lives in the gap between those two.** A grantee who may see the case
passes the slice 3 filter. If the only thing slice 7 does is hand them a redacted PDF,
they can still read the *unredacted* OCR text from `ocr_text`, the extracted field
values, and any search snippet built over them - because redaction produced a new
version and the original's derived text was never touched. The coverage pass called
this the single most likely real leak in the built system, and slice 7's stated
acceptance test (extract text from the derivative, assert the name is absent) does not
catch it, because it only inspects the PDF.

So disclosure is a property of the subject's *relationship to the case*, and it gates
the derived text as well as the bytes:

    designation  -> original      the investigating officer works the real document
    grant        -> redacted      purpose-limited external access never gets originals

CLAUDE.md: "Unauthorised roles never receive original bytes on any code path." The
OCR text of the original is original content in a different shape.
"""
from dataclasses import dataclass
from enum import StrEnum

import sqlalchemy as sa

from domain.subject import CaseFacts, Subject


class Disclosure(StrEnum):
    ORIGINAL = "original"
    REDACTED = "redacted"
    NONE = "none"


@dataclass(frozen=True)
class DisclosureDecision:
    disclosure: Disclosure
    reason: str

    @property
    def may_read_original(self) -> bool:
        return self.disclosure is Disclosure.ORIGINAL


def disclosure_for(subject: Subject, case: CaseFacts) -> DisclosureDecision:
    """Decide the disclosure class. Fails closed.

    Deliberately does not consider rank. CLAUDE.md is explicit that roles grant
    capabilities and are not the model, and "the senior officer gets the unredacted
    copy" is precisely the rule that makes seniority decisive.
    """
    if case.assignment_active:
        return DisclosureDecision(Disclosure.ORIGINAL, "designated-on-case")
    if case.grant_active and not case.grant_is_self_issued:
        return DisclosureDecision(Disclosure.REDACTED, "purpose-limited-grant")
    return DisclosureDecision(Disclosure.NONE, "no-route")


async def readable_version_ids(conn, *, document_id: str, disclosure: Disclosure) -> list[str]:
    """The version ids this disclosure class may receive, for one document.

    A redacted subject gets derivatives only. Asking for the parent id directly
    returns nothing rather than 403, so the parent's existence is not confirmed
    (threat INS-08 asks for exactly this negative test).
    """
    if disclosure is Disclosure.NONE:
        return []

    if disclosure is Disclosure.ORIGINAL:
        rows = (
            await conn.execute(
                sa.text("SELECT id FROM document_version WHERE document_id = :d"),
                {"d": document_id},
            )
        ).scalars().all()
    else:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM document_version "
                    "WHERE document_id = :d AND derived_from_version_id IS NOT NULL"
                ),
                {"d": document_id},
            )
        ).scalars().all()
    return [str(r) for r in rows]


async def readable_ocr_text(conn, *, version_id: str, disclosure: Disclosure) -> str | None:
    """OCR text, gated by disclosure class.

    This is the VIC-01 control. The original's OCR text is original content, and a
    subject restricted to a derivative does not get it in any shape - not as text, not
    as a field value, not as a search snippet.
    """
    if disclosure is not Disclosure.ORIGINAL:
        is_derivative = (
            await conn.execute(
                sa.text(
                    "SELECT derived_from_version_id IS NOT NULL FROM document_version "
                    "WHERE id = :v"
                ),
                {"v": version_id},
            )
        ).scalar_one_or_none()
        if not is_derivative:
            return None

    return (
        await conn.execute(
            sa.text("SELECT text FROM ocr_text WHERE version_id = :v"), {"v": version_id}
        )
    ).scalar_one_or_none()


async def readable_fields(conn, *, version_id: str, disclosure: Disclosure) -> list[dict]:
    """Extracted field values, gated the same way and for the same reason."""
    if disclosure is not Disclosure.ORIGINAL:
        is_derivative = (
            await conn.execute(
                sa.text(
                    "SELECT derived_from_version_id IS NOT NULL FROM document_version "
                    "WHERE id = :v"
                ),
                {"v": version_id},
            )
        ).scalar_one_or_none()
        if not is_derivative:
            return []

    rows = (
        await conn.execute(
            sa.text(
                "SELECT field_key, value, status FROM extracted_field WHERE version_id = :v"
            ),
            {"v": version_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
