"""Destructive redaction.

Security invariant 8:

    Redaction is destructive — a derivative with regions burned into the raster and
    the text layer stripped. Never CSS blur, opacity or client-side masking.
    Unauthorised roles never receive original bytes on any code path.

So this does three things in order, and all three matter:

  1. `add_redact_annot` + `apply_redactions` — PyMuPDF *removes* the content under
     the rectangle rather than drawing over it. Drawing a black box leaves the glyphs
     addressable underneath, which is the classic failure: the name is one
     copy-paste away (threat RED-01).

  2. **Rasterise.** Even after `apply_redactions`, a PDF can retain content in ways
     text extraction does not reveal, and a scanned page is an image where redaction
     is an image operation anyway (threat RED-02, VIC-02). Rendering each page to
     pixels and rebuilding the document from those pixels removes the entire question.

  3. **Rebuild the container.** Document metadata, XMP, outline, form fields and
     embedded thumbnails can each carry the name independently of the page content
     (threat VIC-03). The derivative is constructed as a *new* document containing
     only rendered pixmaps, so there is no inherited container to forget to clean.

What this does not do, and the threat model says so plainly: it removes what it was
*told* to remove. Region selection is patterns over OCR text plus a human dragging
boxes - there is no NER and no LLM - so a handwritten name, a name in a photographed
ID card, or a letterhead is never located and therefore never covered (VIC-05,
accepted risk AR-6). The derivative is then signed and anchored, which means the
integrity machinery certifies whatever leaked. That belongs in the pitch.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass

import fitz

RASTER_DPI = 150


@dataclass(frozen=True)
class Region:
    """One rectangle to remove, and what selected it."""

    page_no: int
    x0: float
    y0: float
    x1: float
    y1: float
    rule_id: str
    removed_text: str
    """Held only long enough to hash. Never persisted - see docs/adr and the migration."""


@dataclass(frozen=True)
class RedactionResult:
    pdf_bytes: bytes
    salt: str
    manifest_hash: str
    regions: list[dict]
    """Geometry, rule id and a salted hash. Deliberately no text."""


def _hash_removed(salt: str, text: str) -> str:
    return hashlib.sha256(f"{salt}|{text}".encode("utf-8")).hexdigest()


def redact(pdf_bytes: bytes, regions: list[Region], *, dpi: int = RASTER_DPI) -> RedactionResult:
    """Produce a redacted derivative and its manifest.

    The returned bytes are a new document built from rendered pixels. The original is
    untouched: originals are never overwritten or mutated.
    """
    if not regions:
        raise ValueError("refusing to produce a 'redacted' derivative with no regions")

    salt = secrets.token_hex(16)

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        # 1. Remove the content under each rectangle.
        for region in regions:
            page = source[region.page_no]
            page.add_redact_annot(
                fitz.Rect(region.x0, region.y0, region.x1, region.y1), fill=(0, 0, 0)
            )
        for page in source:
            # images=True also scrubs image content intersecting the rectangle, which
            # is what makes this work on a scanned page rather than only on text.
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

        # 2 and 3. Rebuild from pixels, into a fresh container.
        derivative = fitz.open()
        try:
            for page in source:
                pixmap = page.get_pixmap(dpi=dpi)
                new_page = derivative.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(new_page.rect, pixmap=pixmap)

            # Nothing inherited: no metadata, no outline, no form fields.
            derivative.set_metadata({})
            derivative.set_toc([])
            out = derivative.tobytes(garbage=4, deflate=True)
        finally:
            derivative.close()
    finally:
        source.close()

    manifest_regions = [
        {
            "page_no": r.page_no,
            "x0": round(r.x0, 2), "y0": round(r.y0, 2),
            "x1": round(r.x1, 2), "y1": round(r.y1, 2),
            "rule_id": r.rule_id,
            "removed_hash": _hash_removed(salt, r.removed_text),
        }
        for r in regions
    ]
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_regions, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return RedactionResult(
        pdf_bytes=out, salt=salt, manifest_hash=manifest_hash, regions=manifest_regions
    )


def confirm_absent(pdf_bytes: bytes, values: list[str]) -> list[str]:
    """Extract text from a derivative and report any of `values` still present.

    Used as a post-condition on the redaction job rather than only as a test. The
    threat model's honest caveat applies: this proves the *text layer* is clean, and
    a handwritten name has no text layer either way, so a green result here is not a
    guarantee the page is visually clean (threat RED-02).
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
    lowered = text.lower()
    return [v for v in values if v and v.lower() in lowered]
