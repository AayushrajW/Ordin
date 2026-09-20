"""Dates, and references to statutory provisions.

The deck says the system extracts "sections, **dates** and parties". There was no date
pattern at all, and section extraction was deliberately absent with a comment explaining
why: an extractor that confidently pulls "Section 354" off a smudged scan is how a wrong
citation acquires a provenance record and the appearance of legal knowledge.

The reconciliation is to detect **a string**, narrowly, and claim nothing about it:

  - only the three named codes, so a generic "Section 12" of a contract is not a
    statutory citation;
  - the value recorded is the reference as written, never an interpretation;
  - it is a draft, so a person confirms it before it is anything (invariant 9).

`test_no_real_looking_statutory_citations` in `test_fixture_corpus.py` still stands, and
this file does not weaken it: the specimen corpus invents no section numbers. These
extractors are tested against strings written here, and against real uploads.
"""
import pytest

from domain.extraction import extract_fields, extract_statutory_references


# --- dates ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,key,value",
    [
        ("Date Of Incident: 12 January 2026", "date_of_incident", "12 January 2026"),
        ("Date of Report: 14/01/2026", "date_of_report", "14/01/2026"),
        ("DATE OF FILING: 2026-02-02", "date_of_filing", "2026-02-02"),
    ],
)
def test_a_labelled_date_is_extracted(line, key, value):
    found = {e.field_key: e.value for e in extract_fields(line)}
    assert found.get(key) == value, found


def test_a_date_carries_a_span_like_every_other_field():
    """A date is evidence about when something happened, not a more certain kind of
    fact. It gets the same provenance as the name on the line above it."""
    text = "Complainant Name: A Person\nDate Of Incident: 12 January 2026\n"
    date = next(e for e in extract_fields(text) if e.field_key == "date_of_incident")
    assert text[date.span_start:date.span_end] == "12 January 2026"


# --- statutory references --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("BNS 74", ["BNS 74"]),
        ("BNS Section 74", ["BNS 74"]),
        ("BNS Sec. 74", ["BNS 74"]),
        ("BNS S.74", ["BNS 74"]),
        ("BNS s 74", ["BNS 74"]),
        ("BNS § 74", ["BNS 74"]),
        ("BNS 74A", ["BNS 74A"]),
    ],
)
def test_the_same_citation_written_six_ways_is_one_citation(text, expected):
    assert [e.value for e in extract_statutory_references(text)] == expected


def test_bnss_is_not_read_as_bns():
    """Alternation is first-match, so an unordered pattern consumes the BNS prefix of
    BNSS and records a different code, a different statute, and a citation the document
    does not contain."""
    found = [e.value for e in extract_statutory_references("charged under BNSS 173")]
    assert found == ["BNSS 173"], found


@pytest.mark.parametrize(
    "text",
    [
        "section 12 of the agreement",
        "see paragraph 3 on page 74",
        "Section 354",
        "the witness is 74 years old",
        "BNSX 173",
    ],
)
def test_a_reference_without_a_named_code_is_not_a_citation(text):
    """The narrowness is the point. A bare 'Section 354' could be a page, a clause or a
    provision, and guessing which is the thing CLAUDE.md forbids."""
    assert extract_statutory_references(text) == []


def test_every_citation_in_a_document_is_recorded_not_only_the_first():
    """A charge sheet cites several provisions. Recording one would silently drop the
    rest, and a dropped citation is invisible in a way a wrong one is not."""
    text = "Offences under BNS 74, BNSS 173 and BSA 63 are made out."
    found = extract_statutory_references(text)
    assert [e.value for e in found] == ["BNS 74", "BNSS 173", "BSA 63"]
    assert len({e.field_key for e in found}) == 3, "keys collided; a citation was lost"


def test_each_citation_points_at_the_text_it_came_from():
    text = "Offences under BNS 74, BNSS 173 and BSA 63 are made out."
    for found in extract_statutory_references(text):
        excerpt = text[found.span_start:found.span_end]
        code, number = found.value.split(" ")
        assert code in excerpt and number in excerpt, (excerpt, found.value)


def test_the_extractor_records_the_reference_and_interprets_nothing():
    """It detects a string. It does not resolve the provision, decide whether it
    applies, or check that the section exists - and the recorded value is the citation,
    never a description of it."""
    found = extract_statutory_references("BNS Section 74")[0]
    assert found.value == "BNS 74", "the value is the citation, not a description of it"
    assert found.extractor_version == "statutory.v1"
    # No field anywhere carries statutory text, a title, or an applicability verdict.
    # If one is ever added, this assertion is where the decision should be argued.
    assert not hasattr(found, "statutory_text")
