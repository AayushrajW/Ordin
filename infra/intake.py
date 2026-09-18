"""Upload hardening: what has to be true of bytes before they become evidence.

Slice 4b. Three checks, in order, all of them refusing rather than repairing where
repair would be a guess:

  **Size**, first and cheaply, because everything after it costs memory. A 200 MB
  upload on an 8 GB laptop is an outage, and the reliability invariant about an
  unbounded worker taking Postgres down with it (threat OPS-03) starts here.

  **Type, by content and never by name.** `.pdf` is a claim the uploader makes.
  The magic bytes are the only thing that decides, and a mismatch is a refusal — not
  a conversion, not a best guess.

  **Structure**, by rebuilding the document without the parts that execute. A PDF is
  a programmable container: JavaScript, launch actions, embedded files, additional
  actions on open and on page events, XFA forms. None of that is evidence, all of it
  reaches a viewer, and an evidence system that stores what it was handed is a
  delivery mechanism.

**PLAN said qpdf; this uses PyMuPDF.** Same operation — parse, drop the dangerous
constructs, write a clean file — with no new dependency and no second binary to
install on the demo machine. PyMuPDF is already here for redaction and its licence is
already recorded (ADR 0009). The substitution is ADR 0016.

**The sanitiser verifies its own output.** After rebuilding, it scans the result for
the same constructs it just removed, and raises if any survived. A sanitiser that
returns a document it has not re-checked is a sanitiser that eventually returns an
unsanitised one, quietly — and this build already learned that lesson three times
from controls that looked applied and did nothing.

What this does NOT do: scan for malware. That is `MalwareScanner`, a declared stub
(CLAUDE.md), and stripping active content is not the same claim. A PDF whose *pixels*
are a phishing page passes here, correctly — it carries no executable content.
"""
import re
from dataclasses import dataclass, field
from enum import StrEnum

from infra.blobstore import sha256_bytes

# 25 MB. A scanned 20-page complaint at 300 dpi is comfortably under this; anything
# above it on this hardware is a memory event rather than a document.
MAX_BYTES = 25 * 1024 * 1024

# A page count cap as well as a byte cap: a small, highly compressed file can still
# rasterise into gigabytes of pixmap ("decompression bomb").
MAX_PAGES = 200

PDF_MAGIC = b"%PDF-"

# Constructs that make a PDF do something rather than say something. Matched against
# the object tree as written, so this catches them wherever they are referenced from.
ACTIVE_CONSTRUCTS = (
    "/JavaScript",
    "/JS",
    "/Launch",
    "/EmbeddedFile",
    "/RichMedia",
    "/XFA",
    "/OpenAction",
    "/AA",
    "/SubmitForm",
    "/ImportData",
    "/GoToR",
    "/GoToE",
)

# A key whose value is literally `null` carries nothing. PyMuPDF removes a key by
# setting it to null and the key itself stays in the object, so a scan that did not
# account for this reported every sanitised file as still containing `/OpenAction` -
# and, because the sanitiser refuses to return a file it cannot verify, rejected
# every upload including clean ones. Stripping the null pairs before matching is what
# makes the self-check mean "still reachable" rather than "still mentioned".
_NULLED_KEY = re.compile(
    r"/(?:"
    + "|".join(name.lstrip("/") for name in ACTIVE_CONSTRUCTS)
    + r")\s+null(?![A-Za-z0-9])"
)


class RejectionCode(StrEnum):
    """Enumerated, because the reason is returned to a caller.

    Free text here would eventually carry a filename or a fragment of the document
    into a log or a response body (invariant 12).
    """

    EMPTY = "empty_upload"
    TOO_LARGE = "exceeds_size_limit"
    NOT_A_PDF = "content_is_not_pdf"
    UNREADABLE = "pdf_could_not_be_parsed"
    TOO_MANY_PAGES = "exceeds_page_limit"
    ENCRYPTED = "encrypted_pdf"
    SANITISATION_FAILED = "active_content_survived_sanitisation"


class UploadRejected(ValueError):
    def __init__(self, code: RejectionCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class Intake:
    """Sanitised bytes, and what had to be taken out to get them.

    `sha256` is the digest of the **sanitised** bytes, which is what gets stored,
    signed and anchored. Anchoring the digest of the file as uploaded would anchor
    something that is not the artefact the system holds.
    """

    data: bytes
    sha256: str
    pages: int
    original_sha256: str
    removed: list[str] = field(default_factory=list)

    @property
    def was_modified(self) -> bool:
        return self.sha256 != self.original_sha256


def sniff(data: bytes) -> None:
    """Decide the type from the content. Raises rather than returning a guess."""
    if not data:
        raise UploadRejected(RejectionCode.EMPTY)
    if len(data) > MAX_BYTES:
        raise UploadRejected(RejectionCode.TOO_LARGE)
    # The header is permitted a small offset: some generators emit a few junk bytes
    # first and every reader tolerates it. Beyond that it is not a PDF.
    if PDF_MAGIC not in data[:1024]:
        raise UploadRejected(RejectionCode.NOT_A_PDF)


def active_constructs(data: bytes) -> list[str]:
    """Every executable construct present, by name, deduplicated and sorted.

    Walks the object table rather than searching the raw bytes: object streams are
    compressed, so a grep over the file misses exactly the ones that were hidden.
    """
    import fitz

    found: set[str] = set()
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            for xref in range(1, doc.xref_length()):
                try:
                    body = doc.xref_object(xref, compressed=False)
                except Exception:  # noqa: BLE001 - a broken object is not a finding
                    continue
                body = _NULLED_KEY.sub("", body)
                for marker in ACTIVE_CONSTRUCTS:
                    if marker in body:
                        found.add(marker)
    except Exception as exc:  # noqa: BLE001
        raise UploadRejected(RejectionCode.UNREADABLE) from exc
    return sorted(found)


_TRAILER_ID = re.compile(
    rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]"
)


_NEUTRAL_ID = b"0" * 32


def _fix_trailer_id(pdf: bytes) -> bytes:
    """Make the output a pure function of the document, and its own fixed point.

    **This is load-bearing, not tidiness.** mupdf writes a fresh random second half of
    the trailer `/ID` on every save, so sanitising one file twice produced different
    bytes and therefore a different digest. Storage here is content-addressed, so that
    meant re-uploading a document created a second version every single time — exactly
    what slice 5a's acceptance criterion forbids, broken by a hardening step that
    looked unrelated to it.

    The identifier is derived from the document with its own `/ID` zeroed, so
    sanitising an already-sanitised file reproduces it exactly. Deriving it from the
    *upload* instead would be deterministic but not idempotent, and the difference
    only shows up as a duplicate version much later.

    `xref_set_key` on the trailer does not survive the save, so the substitution is
    made on the bytes afterwards. It is one well-defined edit to a dictionary this
    function has just written itself, and it preserves length, so no offset moves.
    """
    neutral, count = _TRAILER_ID.subn(
        b"/ID[<" + _NEUTRAL_ID + b"><" + _NEUTRAL_ID + b">]", pdf
    )
    if count == 0:
        # No /ID at all: nothing to normalise, and the output is already stable.
        return pdf
    identifier = sha256_bytes(neutral)[:32].upper().encode("ascii")
    return _TRAILER_ID.sub(b"/ID[<" + identifier + b"><" + identifier + b">]", neutral)


def sanitise(data: bytes) -> Intake:
    """Sniff, strip, rebuild, and re-check. Fails closed at every step."""
    import fitz

    sniff(data)
    original_sha256 = sha256_bytes(data)

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise UploadRejected(RejectionCode.UNREADABLE) from exc

    try:
        if doc.needs_pass or doc.is_encrypted:
            # Not decrypted with a guessed password. An encrypted document the system
            # cannot read is a refusal, not a puzzle.
            raise UploadRejected(RejectionCode.ENCRYPTED)
        if doc.page_count > MAX_PAGES:
            raise UploadRejected(RejectionCode.TOO_MANY_PAGES)

        removed = active_constructs(data)

        catalog = doc.pdf_catalog()
        for key in ("OpenAction", "AA", "Names", "AcroForm", "OCProperties"):
            try:
                doc.xref_set_key(catalog, key, "null")
            except Exception:  # noqa: BLE001 - absent keys are the normal case
                pass

        for page in doc:
            # Annotations and links are where per-object actions live. They carry no
            # evidentiary content in this system — the text and the pixels do — so
            # they go wholesale rather than being inspected one at a time.
            for annot in list(page.annots()):
                page.delete_annot(annot)
            for index in range(len(page.get_links()) - 1, -1, -1):
                page.delete_link(page.get_links()[index])
            try:
                doc.xref_set_key(page.xref, "AA", "null")
            except Exception:  # noqa: BLE001
                pass

        for name in list(
            doc.embfile_names() if hasattr(doc, "embfile_names") else []
        ):
            try:
                doc.embfile_del(name)
            except Exception:  # noqa: BLE001
                pass

        doc.set_metadata({})
        doc.del_xml_metadata()

        # **Determinism, and it is load-bearing.** mupdf writes a fresh random second
        # half of the trailer /ID on every save, so sanitising the same file twice
        # produced different bytes and therefore a different digest. Storage here is
        # content-addressed, so that meant re-uploading one document created a second
        # version every time — the exact thing slice 5a's acceptance criterion forbids,
        # broken by a hardening step. Deriving /ID from the upload's own digest makes
        # the output a pure function of the input, which is what content-addressing
        # requires of anything upstream of it.
        # garbage=4 drops every object nothing references any more, which is what
        # actually removes the action objects the keys above stopped pointing at.
        # clean=True runs mupdf's own sanitiser over the content streams.
        cleaned = doc.tobytes(garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    cleaned = _fix_trailer_id(cleaned)

    survivors = active_constructs(cleaned)
    if survivors:
        # Refuse rather than store something described as sanitised. The caller gets
        # a code; the survivors are not echoed back, because the names of constructs
        # in a hostile file are the attacker's text.
        raise UploadRejected(RejectionCode.SANITISATION_FAILED)

    with __import__("fitz").open(stream=cleaned, filetype="pdf") as out:
        pages = out.page_count

    return Intake(
        data=cleaned,
        sha256=sha256_bytes(cleaned),
        pages=pages,
        original_sha256=original_sha256,
        removed=removed,
    )
