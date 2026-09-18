"""Slice 4b's acceptance criterion: a PDF carrying JavaScript comes out sanitised.

The criterion is necessary and, on its own, too easy to satisfy dishonestly — a
function that returned `b""` would pass it. So these tests assert three things
together: the active content is gone, the *document* is still there, and the bytes the
system stores are the sanitised ones rather than the ones it was handed.

The last of those is the one that would be missed. Sanitising on the way in and then
storing, signing and anchoring the original upload produces a system that is provably
clean and demonstrably serving the file with the JavaScript in it.
"""
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


def test_a_non_pdf_is_refused_by_content_not_by_name():
    with pytest.raises(UploadRejected) as raised:
        sanitise(b"GIF89a" + b"\x00" * 2048)
    assert raised.value.code is RejectionCode.NOT_A_PDF


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
