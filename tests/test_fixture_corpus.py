"""The fixture pack, and the ground truth that makes it useful.

`docs/PLAN.md` R1 moves this before slice 3 because it is a blocking dependency:
slices 4a, 5a, 7 and 11a all have acceptance tests that need documents to exist, and
BOOTSTRAP does not produce any until slice 6.

The documents matter less than the **sidecar**. Two later slices depend on it:

  slice 11a  OCR character error rate. The sidecar records the exact text placed on
             the page before rendering, which Tesseract never sees - so comparing its
             output against it is genuine ground truth, not a circular measurement.
  slice 7    Destructive redaction. The sidecar records a bounding box for every
             identifying field, so "assert the victim name is absent" has coordinates
             to target and a name to look for.

CLAUDE.md honesty rule: the corpus is visibly synthetic. Fictional names, fictional
station codes, and `SPECIMEN - NOT A REAL RECORD` on every page.
"""
import json

import fitz
import pytest

from fixtures.generate import CORPUS, SPECIMEN_MARK, generate_corpus

pytestmark = pytest.mark.usefixtures("corpus")


@pytest.fixture(scope="session")
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus")
    generate_corpus(out)
    return out


def pdfs(corpus):
    return sorted(corpus.glob("*.pdf"))


def sidecar_for(pdf):
    return json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))


# --- the stated acceptance ---------------------------------------------------

def test_generates_between_8_and_12_documents(corpus):
    assert 8 <= len(pdfs(corpus)) <= 12, f"got {len(pdfs(corpus))}"


def test_every_document_has_a_ground_truth_sidecar(corpus):
    for pdf in pdfs(corpus):
        assert pdf.with_suffix(".json").exists(), f"{pdf.name} has no sidecar"


def test_at_least_one_document_is_in_hindi(corpus):
    languages = {sidecar_for(p)["language"] for p in pdfs(corpus)}
    assert "hin" in languages, f"no Hindi document; languages present: {languages}"
    assert "eng" in languages


def test_specimen_mark_appears_on_every_page(corpus):
    """CLAUDE.md: the corpus must be visibly synthetic, on every generated page."""
    for pdf in pdfs(corpus):
        with fitz.open(pdf) as doc:
            for number, page in enumerate(doc):
                assert SPECIMEN_MARK in page.get_text(), (
                    f"{pdf.name} page {number + 1} has no specimen mark"
                )


# --- the sidecar is what the later slices actually consume -------------------

def test_sidecar_records_the_exact_pre_render_text(corpus):
    """Genuine OCR ground truth: this text existed before any rendering."""
    for pdf in pdfs(corpus):
        side = sidecar_for(pdf)
        assert side["pages"], f"{pdf.name}: no pages recorded"
        for page in side["pages"]:
            assert page["text"].strip(), "a page recorded empty ground-truth text"


def test_ground_truth_text_actually_matches_the_rendered_pdf(corpus):
    """The sidecar must describe the document that was produced, not the intent.

    Compared on a normalised character set: PDF extraction reorders whitespace and
    the point of the sidecar is the characters, which is what CER measures.
    """
    for pdf in pdfs(corpus):
        side = sidecar_for(pdf)
        with fitz.open(pdf) as doc:
            for number, page in enumerate(doc):
                rendered = "".join(page.get_text().split())
                truth = "".join(side["pages"][number]["text"].split())
                assert truth in rendered, (
                    f"{pdf.name} page {number + 1}: sidecar text is not present in the "
                    f"rendered page - the ground truth does not describe the artefact"
                )


def test_every_identifying_field_has_a_bounding_box(corpus):
    """Slice 7 targets these. A field with no box cannot be redacted or asserted on."""
    for pdf in pdfs(corpus):
        side = sidecar_for(pdf)
        assert side["identifying_fields"], f"{pdf.name}: no identifying fields recorded"
        for field in side["identifying_fields"]:
            assert {"label", "value", "page", "bbox"} <= field.keys()
            x0, y0, x1, y1 = field["bbox"]
            assert x1 > x0 and y1 > y0, f"{pdf.name}: degenerate bbox for {field['label']}"


def test_bounding_boxes_land_on_the_value_they_claim(corpus):
    """A box in the wrong place would make slice 7's redaction test pass while leaking.

    This is the assertion that makes the sidecar trustworthy rather than decorative.
    """
    for pdf in pdfs(corpus):
        side = sidecar_for(pdf)
        with fitz.open(pdf) as doc:
            for field in side["identifying_fields"]:
                page = doc[field["page"]]
                found = page.get_text("text", clip=fitz.Rect(field["bbox"]))
                assert field["value"].split()[0] in found, (
                    f"{pdf.name}: bbox for {field['label']!r} does not contain "
                    f"{field['value']!r} - it contains {found.strip()!r}"
                )


def test_at_least_one_victim_or_witness_name_is_marked(corpus):
    """Slice 7's demo asserts a victim name is absent from the redacted derivative."""
    labels = {
        f["label"]
        for pdf in pdfs(corpus)
        for f in sidecar_for(pdf)["identifying_fields"]
    }
    assert {"victim_name", "witness_name"} & labels, f"labels present: {labels}"


# --- honesty -----------------------------------------------------------------

def test_no_real_looking_statutory_citations(corpus):
    """CLAUDE.md forbids guessed section numbers. The fixtures must not invent any."""
    import re

    pattern = re.compile(r"\b(section|sec\.?|u/s)\s*\d+", re.I)
    for pdf in pdfs(corpus):
        for page in sidecar_for(pdf)["pages"]:
            assert not pattern.search(page["text"]), (
                f"{pdf.name} contains a statutory citation; fixtures must not invent "
                f"section numbers (CLAUDE.md)"
            )


def test_generation_is_deterministic(tmp_path):
    """Regenerating must not churn the corpus, or the OCR baseline moves under you."""
    a, b = tmp_path / "a", tmp_path / "b"
    generate_corpus(a)
    generate_corpus(b)
    for pdf in sorted(a.glob("*.pdf")):
        assert (
            json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
            == json.loads((b / pdf.name).with_suffix(".json").read_text(encoding="utf-8"))
        ), f"{pdf.name}: sidecar differs between runs"


def test_corpus_declares_its_own_size():
    assert 8 <= len(CORPUS) <= 12
