"""Checking an extracted value against everything else the system knows.

A regular expression can only say "this text followed that label". It cannot say the
value is *wrong* — and on the specimen complaint it was: Tesseract read the case
reference `VRN-N/2026/0001` as `VRN-N/2026/0004` and the phone number `0900000101` as
`090000004`, on a clean render, and both arrived as confident drafts. A human might
commit them without looking twice.

These checks turn what the system already knows into questions for that human:

- **Reference cross-check.** The document is filed in a case whose reference is known.
  An extracted reference one or two characters away from it is almost certainly an OCR
  misread, and the correct value is offered as a *suggestion*. Further away, it may be
  a genuine cross-reference to another case, and is reported as that instead.
- **Phone shape.** Indian numbers are ten digits, with an optional `0` or `+91` prefix.
  Nine or thirteen digits means one was dropped or doubled.
- **Confusable characters.** Letters that OCR substitutes for digits (O, I, l, S, B)
  inside a value that should be numeric, with the folded value suggested.
- **Names containing digits**, which are almost always scan noise.
- **Low OCR confidence** on the words the value was read from, taken from the engine's
  per-word scores rather than from the pattern — a pattern either matched or it did
  not, and presenting that as 100% confidence was misleading.

**Nothing here changes a value.** Invariant 9: AI output is draft, and only a human
commit verifies. A suggestion is a button a person may press, which records a
`source='human'` value under their name. The system proposes; it does not decide.
Pure: no framework, no database.
"""
import re
from dataclasses import dataclass
from enum import StrEnum

from domain.pii import edit_distance


class Severity(StrEnum):
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Anomaly:
    code: str
    severity: Severity
    message: str
    suggestion: str | None = None


# A word below this is one the engine itself was unsure of.
LOW_CONFIDENCE = 0.80

_CONFUSABLE_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1",
                                    "S": "5", "B": "8", "Z": "2"})


def _normalise_reference(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def check_reference(value: str, case_reference: str | None) -> list[Anomaly]:
    if not case_reference:
        return []
    have, want = _normalise_reference(value), _normalise_reference(case_reference)
    if have == want:
        return []
    # Fold letter-for-digit confusions in the serial part before measuring.
    folded = have.translate(_CONFUSABLE_DIGITS) if re.search(r"\d", have) else have
    distance = edit_distance(folded, want, 3)
    if distance <= 2:
        noun = "character" if distance == 1 else "characters"
        return [Anomaly(
            "reference_mismatch", Severity.WARNING,
            f"Differs from this case's reference by {distance} {noun} — "
            f"almost certainly an OCR misread.",
            case_reference,
        )]
    return [Anomaly(
        "reference_other_case", Severity.INFO,
        "Refers to a different case reference. It may be a genuine cross-reference; "
        "confirm before committing.",
    )]


def check_phone(value: str) -> list[Anomaly]:
    found: list[Anomaly] = []
    if re.search(r"[OoIlSB|]", value) and re.search(r"\d", value):
        folded = value.translate(_CONFUSABLE_DIGITS)
        found.append(Anomaly(
            "confusable_characters", Severity.WARNING,
            "Contains letters OCR commonly reads in place of digits.",
            folded,
        ))
        value = folded
    digits = re.sub(r"\D", "", value)
    well_formed = (
        len(digits) == 10
        or (len(digits) == 11 and digits.startswith("0"))
        or (len(digits) == 12 and digits.startswith("91"))
    )
    if not well_formed:
        found.append(Anomaly(
            "phone_length", Severity.WARNING,
            f"{len(digits)} digits — an Indian number has ten, so one was probably "
            f"dropped or doubled by the scan. Check the page.",
        ))
    return found


def check_name(value: str) -> list[Anomaly]:
    if re.search(r"\d", value):
        return [Anomaly(
            "name_contains_digits", Severity.WARNING,
            "Names rarely contain digits; this is most likely scan noise.",
            re.sub(r"\s{2,}", " ", re.sub(r"\d", "", value)).strip() or None,
        )]
    return []


def check_confidence(word_confidence: float | None) -> list[Anomaly]:
    if word_confidence is None or word_confidence >= LOW_CONFIDENCE:
        return []
    return [Anomaly(
        "low_ocr_confidence", Severity.WARNING,
        f"The OCR engine was unsure of this text (lowest word "
        f"{word_confidence * 100:.0f}%). Read it against the page before committing.",
    )]


def check_field(
    field_key: str, value: str, *, case_reference: str | None,
    word_confidence: float | None,
) -> list[Anomaly]:
    """Every anomaly for one extracted value. Empty means nothing to flag."""
    found: list[Anomaly] = []
    if field_key == "case_reference":
        found += check_reference(value, case_reference)
    elif field_key.endswith("_phone"):
        found += check_phone(value)
    elif field_key.endswith("_name"):
        found += check_name(value)
    found += check_confidence(word_confidence)
    return found
