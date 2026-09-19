"""Cross-checks on extracted values. Pure, no database.

The cases here are the real ones. On the specimen complaint Tesseract read the case
reference `VRN-N/2026/0001` as `VRN-N/2026/0004` and the phone `0900000101` as
`090000004`, from a clean render, and both arrived as ordinary drafts. These tests
assert that each would now arrive carrying a reason to look twice.
"""
from domain.consistency import Severity, check_field


def codes(anomalies):
    return {a.code for a in anomalies}


def test_the_real_reference_misread_is_flagged_with_the_right_suggestion():
    found = check_field("case_reference", "VRN-N/2026/0004",
                        case_reference="VRN-N/2026/0001", word_confidence=0.96)
    assert codes(found) == {"reference_mismatch"}
    assert found[0].severity is Severity.WARNING
    assert found[0].suggestion == "VRN-N/2026/0001"


def test_a_letter_for_digit_misread_in_a_reference_is_folded_before_comparing():
    found = check_field("case_reference", "VRN-N/2O26/0001",
                        case_reference="VRN-N/2026/0001", word_confidence=None)
    assert found and found[0].suggestion == "VRN-N/2026/0001"


def test_a_genuinely_different_reference_is_information_not_an_error():
    found = check_field("case_reference", "KMR-E/2025/0417",
                        case_reference="VRN-N/2026/0001", word_confidence=None)
    assert codes(found) == {"reference_other_case"}
    assert found[0].severity is Severity.INFO
    assert found[0].suggestion is None, "no suggestion: it may be a real cross-reference"


def test_a_matching_reference_is_silent():
    assert check_field("case_reference", "VRN-N/2026/0001",
                       case_reference="VRN-N/2026/0001", word_confidence=0.99) == []


def test_the_real_phone_misread_is_flagged():
    assert "phone_length" in codes(
        check_field("complainant_phone", "090000004", case_reference=None, word_confidence=None)
    )


def test_a_well_formed_phone_is_silent():
    for number in ("0900000101", "9876543210", "+91 98765 43210"):
        assert check_field("victim_phone", number, case_reference=None,
                           word_confidence=None) == [], number


def test_letters_in_a_phone_number_get_a_folded_suggestion():
    found = check_field("witness_phone", "09OOOOO1O4", case_reference=None, word_confidence=None)
    confusable = [a for a in found if a.code == "confusable_characters"]
    assert confusable and confusable[0].suggestion == "0900000104"


def test_low_ocr_confidence_is_reported_from_the_engine_not_the_pattern():
    found = check_field("victim_name", "Sunita Kale", case_reference=None, word_confidence=0.62)
    assert codes(found) == {"low_ocr_confidence"}
    assert "62%" in found[0].message


def test_a_name_with_digits_is_flagged():
    assert "name_contains_digits" in codes(
        check_field("witness_name", "Pra1kash Iyer", case_reference=None, word_confidence=None)
    )


def test_nothing_here_changes_a_value():
    """Invariant 9: the system proposes; a person commits. A suggestion is only text."""
    value = "VRN-N/2026/0004"
    check_field("case_reference", value, case_reference="VRN-N/2026/0001", word_confidence=None)
    assert value == "VRN-N/2026/0004"
