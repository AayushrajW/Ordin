"""Slice 4b's acceptance criterion: a PDF carrying JavaScript comes out sanitised.

The criterion is necessary and, on its own, too easy to satisfy dishonestly — a
function that returned `b""` would pass it. So these tests assert three things
together: the active content is gone, the *document* is still there, and the bytes the
system stores are the sanitised ones rather than the ones it was handed.

The last of those is the one that would be missed. Sanitising on the way in and then
storing, signing and anchoring the original upload produces a system that is provably
clean and demonstrably serving the file with the JavaScript in it.
"""
import struct
import zlib

import pytest

from infra.blobstore import sha256_bytes
from infra.intake import (
    MAX_BYTES,
    Intake,
    RejectionCode,
    UploadRejected,
    active_constructs,
    sanitise,
)

fitz = pytest.importorskip("fitz")


def _specimen(*, js: bool = False, launch: bool = False, embed: bool = False) -> bytes:
    """A small, real PDF, optionally carrying active content.

    Built with PyMuPDF and then edited at the object level, because the point is a
    file a viewer would actually execute rather than a string that merely contains
    the word JavaScript.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 96), "SPECIMEN - NOT A REAL RECORD", fontsize=12)
    page.insert_text((72, 120), "Complainant Name: Anjali Bhosle", fontsize=11)
    data = doc.tobytes()
    doc.close()

    doc = fitz.open(stream=data, filetype="pdf")
    catalog = doc.pdf_catalog()
    if js:
        action = doc.get_new_xref()
        doc.update_object(
            action, "<< /Type /Action /S /JavaScript /JS (app.alert\\(1\\);) >>"
        )
        doc.xref_set_key(catalog, "OpenAction", f"{action} 0 R")
        names = doc.get_new_xref()
        doc.update_object(
            names, f"<< /JavaScript << /Names [ (boot) {action} 0 R ] >> >>"
        )
        doc.xref_set_key(catalog, "Names", f"{names} 0 R")
    if launch:
        action = doc.get_new_xref()
        doc.update_object(
            action, "<< /Type /Action /S /Launch /F (cmd.exe) >>"
        )
        doc.xref_set_key(catalog, "OpenAction", f"{action} 0 R")
    if embed:
        doc.embfile_add("payload", b"MZ not really an executable", filename="payload.bin")
    out = doc.tobytes()
    doc.close()
    return out


# --- the specimen itself is hostile, or the tests prove nothing ---------------


def test_the_javascript_specimen_really_carries_javascript():
    """Guards against the whole file passing because the fixture was already clean.

    This is the assertion that stopped a token-forgery test in this project from
    silently testing an unmodified token.
    """
    found = active_constructs(_specimen(js=True))
    assert "/JavaScript" in found
    assert "/JS" in found
    assert "/OpenAction" in found
    assert active_constructs(_specimen()) == [] or "/JS" not in active_constructs(_specimen())


# --- the criterion ------------------------------------------------------------


def test_a_pdf_carrying_javascript_comes_out_sanitised():
    result = sanitise(_specimen(js=True))
    assert active_constructs(result.data) == []
    assert "/JavaScript" in result.removed, "the report does not name what was removed"


def test_a_launch_action_is_removed():
    result = sanitise(_specimen(launch=True))
    assert active_constructs(result.data) == []
    assert "/Launch" in result.removed


def test_an_embedded_file_is_removed():
    result = sanitise(_specimen(embed=True))
    assert active_constructs(result.data) == []


def test_the_document_survives_sanitisation():
    """Cleaning must not be deletion. A sanitiser that empties the file also passes
    every test above, so the text has to still be there afterwards."""
    result = sanitise(_specimen(js=True))
    with fitz.open(stream=result.data, filetype="pdf") as doc:
        assert doc.page_count == 1
        text = doc[0].get_text()
    assert "Anjali Bhosle" in text
    assert "SPECIMEN" in text


def test_a_clean_pdf_is_reported_as_unmodified_in_substance():
    """A clean upload still gets rebuilt, and the report says nothing was removed.

    The digest legitimately changes — the file is re-serialised — so `removed` rather
    than `was_modified` is the honest signal about content.
    """
    result = sanitise(_specimen())
    assert result.removed == []
    assert result.pages == 1


# --- what gets stored ---------------------------------------------------------


def test_the_digest_is_of_the_sanitised_bytes(tmp_path):
    """The hash that will be signed and anchored must describe what is kept."""
    hostile = _specimen(js=True)
    result = sanitise(hostile)
    assert result.sha256 == sha256_bytes(result.data)
    assert result.original_sha256 == sha256_bytes(hostile)
    assert result.sha256 != result.original_sha256
    assert result.was_modified


def test_sanitisation_is_deterministic():
    """The property content-addressed storage depends on, and the one that broke.

    mupdf writes a random trailer `/ID` on every save. With that left alone, the same
    upload sanitised to different bytes each time, so `_upsert_version` — which finds
    an existing version by digest — created a new version on every re-upload. The
    idempotency criterion of slice 5a was broken by a hardening step in slice 4b, and
    only the row counts showed it. This asserts the fix directly rather than through
    the pipeline, so a regression names its own cause.
    """
    hostile = _specimen(js=True)
    first, second = sanitise(hostile), sanitise(hostile)
    assert first.data == second.data
    assert first.sha256 == second.sha256
    # If this ever fails *intermittently*, it is the limit of the guarantee rather than
    # a regression: ADR 0017 records that mupdf occasionally compacts object numbering
    # differently in a long-lived process. Back-to-back calls are the tightest case and
    # have been stable. `test_pipeline_idempotency` once asserted the same property far
    # apart in a long process and failed roughly one run in three, in a different test
    # each time — which is how an afternoon disappears if nobody has written this down.


def test_sanitising_an_already_sanitised_file_is_clean_but_not_byte_identical():
    """The limit of the determinism guarantee, asserted rather than assumed.

    Sanitising is deterministic — the same input always gives the same output, which is
    what content-addressed storage requires and what the test above proves. It is **not**
    a fixed point: mupdf's save compacts object numbering differently on a second pass,
    so `sanitise(sanitise(x))` occasionally differs from `sanitise(x)` by a few bytes.
    Reproduced at roughly one specimen in twenty-five.

    An earlier version of this test asserted the fixed point and passed most of the
    time, which is the worst kind of test: it failed once in a full run, in a different
    file each time, and looked like flakiness rather than like a property that was never
    guaranteed.

    Nothing in the system re-ingests its own output, so this costs nothing today. What
    it would cost, if that changed: re-uploading an exported sanitised file could create
    one extra version. Recorded in ADR 0017 rather than left to be rediscovered.
    """
    once = sanitise(_specimen(js=True))
    twice = sanitise(once.data)

    assert twice.removed == [], "a second pass found active content the first left behind"
    assert active_constructs(twice.data) == []
    with fitz.open(stream=twice.data, filetype="pdf") as doc:
        assert doc.page_count == 1
        assert "Anjali Bhosle" in doc[0].get_text()


# --- refusals -----------------------------------------------------------------


def test_a_file_that_is_neither_document_nor_image_is_refused_by_content():
    """A zip, an executable, a spreadsheet: refused on its bytes, whatever it is named."""
    for header, label in ((b"PK\x03\x04", "zip"), (b"MZ\x90\x00", "exe"),
                          (b"hello, this is just text", "text")):
        with pytest.raises(UploadRejected) as raised:
            sanitise(header + b"\x00" * 2048)
        assert raised.value.code is RejectionCode.NOT_A_PDF, label


def test_a_corrupt_image_is_refused_rather_than_half_decoded():
    """Recognised by its header, unreadable in fact. Refusing beats storing a smear."""
    with pytest.raises(UploadRejected) as raised:
        sanitise(b"GIF89a" + b"\x00" * 2048)
    assert raised.value.code is RejectionCode.UNREADABLE


def test_an_empty_upload_is_refused():
    with pytest.raises(UploadRejected) as raised:
        sanitise(b"")
    assert raised.value.code is RejectionCode.EMPTY


def test_an_oversized_upload_is_refused_before_it_is_parsed():
    """Size first, so a hostile file never reaches the parser at all."""
    with pytest.raises(UploadRejected) as raised:
        sanitise(b"%PDF-1.7\n" + b"\x00" * (MAX_BYTES + 1))
    assert raised.value.code is RejectionCode.TOO_LARGE


def test_a_pdf_shaped_file_that_will_not_parse_is_refused():
    with pytest.raises(UploadRejected) as raised:
        sanitise(b"%PDF-1.7\nnot actually a pdf at all\n%%EOF\n")
    assert raised.value.code in {RejectionCode.UNREADABLE, RejectionCode.NOT_A_PDF}


def test_an_encrypted_pdf_is_refused_rather_than_guessed_at():
    doc = fitz.open()
    doc.new_page()
    encrypted = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )
    doc.close()
    with pytest.raises(UploadRejected) as raised:
        sanitise(encrypted)
    assert raised.value.code is RejectionCode.ENCRYPTED


# --- the real corpus still goes through -----------------------------------------


def test_every_fixture_document_passes_intake_unchanged_in_substance():
    """The generator's own documents must survive the gate they will be fed through.

    A hardening step that rejects the project's own corpus is a hardening step nobody
    will leave switched on.
    """
    from pathlib import Path

    corpus = sorted((Path(__file__).resolve().parents[1] / "fixtures" / "corpus").glob("*.pdf"))
    assert corpus, "no fixture corpus - run `python tasks.py fixtures`"
    for pdf in corpus:
        result = sanitise(pdf.read_bytes())
        assert isinstance(result, Intake)
        assert result.removed == [], f"{pdf.name} carried {result.removed}"
        assert result.pages >= 1


# --- photographs ---------------------------------------------------------------


def _page_image(text: str = "Complainant Name: Test Person", fmt: str = "png") -> bytes:
    """A picture of a document page, the way one arrives from a phone or a scanner."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 96), "SPECIMEN - NOT A REAL RECORD", fontsize=12)
    page.insert_text((72, 130), text, fontsize=13)
    data = page.get_pixmap(dpi=200).tobytes(fmt)
    doc.close()
    return data


def _with_exif(jpeg: bytes, marker: bytes) -> bytes:
    """Splice an APP1 EXIF segment carrying `marker` in after the JPEG's SOI."""
    payload = b"Exif\x00\x00" + marker
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + segment + jpeg[2:]


def test_a_photograph_is_accepted_and_becomes_a_document():
    result = sanitise(_page_image())
    assert result.pages == 1
    assert result.data[:5] == b"%PDF-", "an image upload did not become a PDF"
    assert active_constructs(result.data) == []


def test_every_image_format_the_sniffer_claims_is_actually_accepted():
    for fmt in ("png", "jpg"):
        assert sanitise(_page_image(fmt=fmt)).pages == 1, fmt


def test_the_type_comes_from_the_content_not_the_extension():
    """A file named .pdf that is a PNG is a PNG, and vice versa. Neither is refused for
    its name, and neither is trusted for it."""
    from infra.intake import sniff

    assert sniff(_page_image()) == "png"
    assert sniff(b"%PDF-1.7\n%%EOF\n") == "pdf"


def test_a_photograph_s_exif_never_reaches_the_evidence_store():
    """A phone photo of a complaint carries GPS coordinates — the place it was taken.

    Embedding the original JPEG would carry them inside the image stream, where nothing
    downstream would look. The pixels are decoded and re-encoded instead.
    """
    marker = b"GPS-COORDINATES-OF-A-VICTIMS-HOME"
    hostile = _with_exif(_page_image(fmt="jpg"), marker)
    assert marker in hostile, "the specimen carries no EXIF, so this would prove nothing"

    result = sanitise(hostile)
    assert marker not in result.data, "EXIF survived into the stored document"


def test_an_enormous_image_is_refused_before_it_is_rasterised():
    from infra.intake import MAX_PIXELS, pdf_from_image

    doc = fitz.open()
    # A page whose pixmap would exceed the cap, rendered small and claimed large.
    page = doc.new_page(width=2000, height=2000)
    page.insert_text((10, 20), "x")
    huge = page.get_pixmap(dpi=340).tobytes("png")
    doc.close()
    # Read the size from the header rather than decoding it. Building the pixmap here
    # just to size it allocated ~267 MB inside the test, on the 8 GB laptop whose
    # memory this cap exists to defend.
    from infra.intake import declared_pixel_size

    declared = declared_pixel_size(huge)
    assert declared is not None, "specimen header unreadable"
    if declared[0] * declared[1] <= MAX_PIXELS:
        pytest.skip("could not build an image over the pixel cap cheaply")
    with pytest.raises(UploadRejected) as raised:
        pdf_from_image(huge)
    assert raised.value.code is RejectionCode.TOO_MANY_PIXELS


def test_a_photograph_survives_the_sanitiser_intact_enough_to_read():
    """The point of accepting photographs is that OCR can still read them afterwards."""
    from infra.textsource import TesseractOcr

    if not TesseractOcr.available():
        pytest.skip("tesseract not installed")
    result = sanitise(_page_image("Complainant Name: Rukmini Deshmukh"))
    outcome = TesseractOcr(languages="eng").extract(result.data)
    assert "Rukmini" in outcome.text, outcome.text[:200]


def _declared_size_image(kind: str, width: int, height: int) -> bytes:
    """A header claiming `width` x `height`, with no pixel data behind it.

    This is the discriminator the test below needs. A real decompression bomb is a
    *valid* image, so the only thing that can refuse one cheaply is reading the
    declared dimensions before decoding. These specimens are deliberately
    undecodable: an implementation that decodes first reports UNREADABLE, one that
    reads the header first reports TOO_MANY_PIXELS. Nothing large is ever allocated,
    so the test is safe to run on the 8 GB laptop it exists to protect.
    """
    if kind == "png":
        ihdr = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + ihdr
            + struct.pack(">I", zlib.crc32(ihdr))
        )
    if kind == "gif":
        # GIF dimensions are 16-bit, so 65535 square is the largest it can claim.
        return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00"
    if kind == "bmp":
        return (
            b"BM"
            + struct.pack("<IHHI", 0, 0, 0, 54)
            + struct.pack("<IiiHH", 40, width, height, 1, 24)
        )
    raise AssertionError(f"no specimen builder for {kind}")


@pytest.mark.parametrize(
    "kind,width,height",
    [("png", 50_000, 50_000), ("gif", 65_535, 65_535), ("bmp", 50_000, 50_000)],
)
def test_a_declared_pixel_count_over_the_cap_is_refused_without_decoding(kind, width, height):
    """The cap must bind *before* the pixels are decoded, not after.

    `MAX_BYTES` caps an upload at 25 MB, which does not bound the decoded size at all:
    deflate reduces a uniform field to almost nothing, so 25 MB of PNG is billions of
    pixels and gigabytes of pixmap. Measuring after `fitz.Pixmap()` has already decoded
    is measuring the damage, not preventing it — and threat OPS-03 is precisely that an
    unbounded worker gets the OOM killer to take postgres down with it.
    """
    from infra.intake import pdf_from_image

    specimen = _declared_size_image(kind, width, height)
    assert len(specimen) < 1024, "the specimen must be tiny, or it proves nothing"

    with pytest.raises(UploadRejected) as raised:
        pdf_from_image(specimen)

    assert raised.value.code is RejectionCode.TOO_MANY_PIXELS, (
        f"{kind}: refused as {raised.value.code.value}, but the header declares "
        f"{width}x{height} - so it was decoded before it was measured"
    )
