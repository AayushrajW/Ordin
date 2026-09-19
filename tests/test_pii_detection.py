"""The detection engine, tested without a database or an application.

The headline test is the first one. Before this module, redaction covered labelled
fields only, so a name repeated in the narrative survived into the derivative that a
purpose-limited grantee receives. That is the leak this engine exists to close, and the
test states it in the form a reviewer would check: every mention, not just the label.
"""
from domain.pii import (
    FindingKind,
    KnownValue,
    detect,
    edit_distance,
    verhoeff_check_digit,
    verhoeff_valid,
)

STATEMENT = (
    "SPECIMEN - NOT A REAL RECORD\n"
    "Victim Statement\n"
    "Victim Name: Rukmini Deshmukh\n"
    "Victim Phone: 0900000111\n"
    "Victim Address: 27 Banyan Cross, Vranaspur North\n"
    "The statement of Ms Rukmini Deshmukh was recorded at her request.\n"
    "Ms Deshmukh stated that she had been followed on three occasions.\n"
    "She asked to be contacted only on 0900000111 and not at 27 Banyan Cross.\n"
    "Rukmini identified the vehicle as a grey two-wheeler.\n"
)

KNOWN = [
    KnownValue("victim_name", "Rukmini Deshmukh", FindingKind.NAME),
    KnownValue("victim_phone", "0900000111", FindingKind.PHONE),
    KnownValue("victim_address", "27 Banyan Cross, Vranaspur North", FindingKind.ADDRESS),
]


def covered(text: str, findings) -> str:
    """The text with every finding blanked, which is what a reader of the derivative sees."""
    chars = list(text)
    for f in findings:
        for i in range(f.start, f.end):
            chars[i] = "#"
    return "".join(chars)


def test_every_mention_is_found_not_only_the_labelled_one():
    findings = detect(STATEMENT, KNOWN)
    residue = covered(STATEMENT, findings)
    for fragment in ("Rukmini", "Deshmukh", "0900000111", "Banyan"):
        assert fragment not in residue, f"{fragment!r} survives in: {residue}"


def test_the_rest_of_the_page_is_left_alone():
    """Over-redaction is a failure too: a derivative with nothing left is useless."""
    residue = covered(STATEMENT, detect(STATEMENT, KNOWN))
    for fragment in ("stated that she had been followed", "grey two-wheeler", "Statement"):
        assert fragment in residue


def test_a_finding_never_carries_the_value_it_matched():
    """Findings flow into manifests and logs. Invariant 12 forbids values in either."""
    for finding in detect(STATEMENT, KNOWN):
        assert not hasattr(finding, "text")
        assert "Rukmini" not in repr(finding) and "0900000111" not in repr(finding)


def test_ocr_confusions_are_absorbed():
    text = "Ms Desbmukh and Ms Deshrnukh were named, and R0kmini once."
    findings = detect(text, KNOWN[:1], patterns=False)
    residue = covered(text, findings)
    assert "Desbmukh" not in residue, "one substituted letter should still match"
    assert "Deshrnukh" not in residue, "rn read for m is the classic OCR confusion"


def test_short_names_get_no_tolerance():
    """'Ram' fuzzily matched would redact 'Ran', 'Rum' and 'Rao' across the page."""
    text = "Ram arrived. The case ran long. Rao was absent."
    findings = detect(text, [KnownValue("witness_name", "Ram Iyer", FindingKind.NAME)],
                      patterns=False)
    residue = covered(text, findings)
    assert "ran long" in residue and "Rao" in residue


def test_a_lowercase_common_word_is_not_taken_for_a_surname():
    text = "Victim Name: Asha Patil\nThe patil of the village was present."
    findings = detect(text, [KnownValue("victim_name", "Asha Patil", FindingKind.NAME)],
                      patterns=False)
    assert "patil of the village" in covered(text, findings)


def test_phone_numbers_match_through_spacing_and_misread_digits():
    text = "Call 090 000 0111 or 09000O0111; the office line is 0900000999."
    findings = detect(text, [KnownValue("victim_phone", "0900000111", FindingKind.PHONE)],
                      patterns=False)
    residue = covered(text, findings)
    assert "090 000 0111" not in residue
    assert "09000O0111" not in residue
    assert "0900000999" in residue, "a different number must not be swallowed"


def test_devanagari_names_are_found_exactly():
    text = "शिकायतकर्ता मीरा जोशी ने कथन दिया। जोशी ने बताया।"
    findings = detect(text, [KnownValue("complainant_name", "मीरा जोशी", FindingKind.NAME)],
                      patterns=False)
    residue = covered(text, findings)
    assert "मीरा" not in residue and "जोशी" not in residue


# --- identifiers nobody labelled --------------------------------------------------


def _specimen_aadhaar() -> str:
    """All nines plus a computed check digit: checksum-valid and obviously synthetic."""
    stem = "99999999999"
    return stem + verhoeff_check_digit(stem)


def test_verhoeff_round_trips():
    number = _specimen_aadhaar()
    assert verhoeff_valid(number)
    assert not verhoeff_valid(number[:-1] + str((int(number[-1]) + 1) % 10))


def test_an_aadhaar_number_is_found_and_checksum_validated():
    number = _specimen_aadhaar()
    text = f"ID produced: {number[:4]} {number[4:8]} {number[8:]}."
    findings = [f for f in detect(text, []) if f.kind is FindingKind.AADHAAR]
    assert len(findings) == 1
    assert findings[0].rule_id == "pattern.aadhaar.verhoeff"


def test_a_misread_aadhaar_digit_is_still_reported():
    """Failing the checksum after a scan is a reason for suspicion, not dismissal."""
    number = _specimen_aadhaar()
    broken = number[:5] + ("6" if number[5] != "6" else "5") + number[6:]
    findings = [f for f in detect(f"ID {broken}", []) if f.kind is FindingKind.AADHAAR]
    assert findings, "an Aadhaar-shaped number disappeared because its checksum failed"
    assert findings[0].rule_id in {"pattern.aadhaar.ocr_repaired", "pattern.aadhaar_shaped"}


def test_other_identifiers_are_found():
    text = "Mail a.person@example.org, PAN ABCPE1234F, vehicle MH 12 AB 1234, mobile 9876543210."
    kinds = {f.kind for f in detect(text, [])}
    assert {FindingKind.EMAIL, FindingKind.PAN, FindingKind.VEHICLE, FindingKind.PHONE} <= kinds


def test_a_case_reference_is_not_mistaken_for_an_identifier():
    """Redacting the case number from a case document serves nobody."""
    text = "Reference: VRN-N/2026/0001 filed at Vranaspur North."
    assert detect(text, []) == []


# --- the arithmetic ---------------------------------------------------------------


def test_edit_distance_counts_a_transposition_as_one():
    assert edit_distance("deshmukh", "dehsmukh", 2) == 1


def test_edit_distance_stops_early_past_its_limit():
    assert edit_distance("abcdefgh", "zzzzzzzz", 1) == 2


def test_detection_is_deterministic():
    assert detect(STATEMENT, KNOWN) == detect(STATEMENT, KNOWN)
