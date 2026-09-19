"""Finding every place an identifying value appears on a page.

**The problem this solves.** Redaction used to cover the labelled fields and nothing
else. A victim's name extracted from "Victim Name: Rukmini Deshmukh" was burned out of
that line — and left intact two lines later in "Ms Deshmukh stated that...". The
derivative then went to a purpose-limited grantee with the surname in the narrative.
Every test passed, because every test checked the field.

This module is deterministic (CLAUDE.md: deterministic over ML, ML over LLM, and there
is no LLM here) and it works in three layers, each catching what the one before misses:

1. **Propagation of known values.** Every identifying value the system already holds —
   extracted fields, and the parties recorded against the case — is searched for across
   the *whole* text, not just where it was labelled:

   - exact token sequences;
   - **OCR-tolerant** sequences, allowing a bounded Damerau-Levenshtein distance per
     token after folding the characters OCR habitually confuses (0/O, 1/l/I, 5/S, 8/B);
   - **partial names** — a surname or a distinctive given name on its own, because
     that is how narrative prose refers back to a person;
   - **street-level address fragments**, because "27 Banyan Cross" identifies a
     household without the locality after the comma;
   - **digit sequences** for phone numbers, ignoring spaces and dashes, and allowing
     one misread digit on long numbers.

2. **Pattern detection of identifiers nobody labelled.** Indian mobile numbers, e-mail
   addresses, PAN, vehicle registrations, and Aadhaar numbers — the last **validated
   by the Verhoeff check digit**, which removes almost every false positive a bare
   12-digit pattern produces. An Aadhaar-shaped number that fails the checksum is
   tried against single OCR digit confusions; if one repair validates, it is reported
   as a probable misread rather than dismissed. Verhoeff is a published check-digit
   scheme, not cryptography, and nothing here invents one.

3. **Merging.** Overlapping findings merge into one span keeping the strongest
   evidence, so a name found both exactly and by a pattern is one region, not two.

**What a finding carries**: kind, span, rule id, confidence, and which field it was
propagated from. **Never the matched text** — findings flow into redaction manifests
and logs, and invariant 12 forbids identifying values in either.

**What it cannot do**, stated rather than discovered: find a name nobody told it about
and no pattern describes. There is no entity recognition in this build. A name that is
neither a recorded party nor a labelled field, and is not a phone, ID or e-mail, is
not found. That is accepted risk AR-6, narrowed substantially here but not closed.
"""
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class FindingKind(StrEnum):
    NAME = "name"
    ADDRESS = "address"
    PHONE = "phone"
    AADHAAR = "aadhaar"
    PAN = "pan"
    EMAIL = "email"
    VEHICLE = "vehicle"
    OTHER = "other"


@dataclass(frozen=True)
class KnownValue:
    """An identifying value the system already holds, and what kind of thing it is."""

    source: str          # field key or "party:<role>"
    value: str
    kind: FindingKind


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    start: int
    end: int
    rule_id: str
    confidence: float
    source: str | None = None
    """Which known value this propagated from, if any. A field key, never a value."""


# --- normalisation ------------------------------------------------------------

# Characters OCR confuses, folded to one representative for *comparison only*. The
# spans reported always index the original text.
_CONFUSABLE = str.maketrans({
    "0": "o", "1": "l", "|": "l", "!": "l", "5": "s", "$": "s", "8": "b",
    "‘": "'", "’": "'", "`": "'",
})

HONORIFICS = frozenset({
    "mr", "mrs", "ms", "miss", "dr", "shri", "sri", "smt", "km", "kumari", "master",
    "श्री", "श्रीमती", "सुश्री", "कुमारी", "डॉ",
})

# Words that must never be treated as a name fragment, however a party is spelled.
# Short and conservative: the failure mode of a long list is missing a real name.
_STOPWORDS = frozenset({
    "the", "and", "that", "this", "with", "from", "have", "been", "were", "which",
    "station", "police", "north", "south", "east", "west", "road", "lane", "street",
    "colony", "nagar", "case", "record", "statement", "complaint", "witness", "victim",
    "officer", "name", "address", "phone", "reference", "specimen", "real",
})

_TOKEN = re.compile(r"[0-9A-Za-zÀ-ɏऀ-ॿ]+(?:['.\-][0-9A-Za-zÀ-ɏऀ-ॿ]+)*")


def _fold(token: str) -> str:
    """Comparison form. Both sides are folded identically, so over-folding a legitimate
    "rn" in a real name costs nothing: it is folded the same way wherever it appears.
    `rn` read for `m` and `vv` for `w` are the two confusions a character map cannot
    express, because they change the length."""
    folded = unicodedata.normalize("NFC", token).casefold().translate(_CONFUSABLE)
    return folded.replace("rn", "m").replace("vv", "w")


@dataclass(frozen=True)
class _Tok:
    text: str
    folded: str
    start: int
    end: int


def tokenize(text: str) -> list[_Tok]:
    return [_Tok(m.group(), _fold(m.group()), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _is_devanagari(token: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in token)


def edit_distance(a: str, b: str, limit: int) -> int:
    """Optimal-string-alignment (restricted Damerau-Levenshtein), bounded.

    Transpositions count as one edit because OCR and typists both swap adjacent
    characters. Bounded so a comparison between two long, unrelated tokens stops as soon
    as it cannot come in under the limit — this runs for every token on the page.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous2: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        best = current[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if (
                previous2 is not None and i > 1 and j > 1
                and ca == b[j - 2] and a[i - 2] == cb
            ):
                current[j] = min(current[j], previous2[j - 2] + 1)
            best = min(best, current[j])
        if best > limit:
            return limit + 1
        previous2, previous = previous, current
    return previous[-1]


def tolerance(token: str) -> int:
    """How many edits a token may absorb and still be the same word.

    Short tokens get none: "Ram" one edit away is "Ran", "Rum", "Rao" — a tolerance
    there redacts half the page. Devanagari gets none as well: a single-matra edit
    changes the word, and OCR errors in that script are not the same confusions.
    """
    if _is_devanagari(token) or len(token) <= 4:
        return 0
    if len(token) <= 8:
        return 1
    return 2


# --- layer 1: propagation of known values ----------------------------------------


def _match_sequence(tokens: list[_Tok], needle: list[str], fuzzy: bool) -> list[tuple[int, int, int]]:
    """(first token index, last token index, total edits) for each occurrence."""
    hits: list[tuple[int, int, int]] = []
    n = len(needle)
    if n == 0 or n > len(tokens):
        return hits
    for i in range(len(tokens) - n + 1):
        edits = 0
        for k, want in enumerate(needle):
            have = tokens[i + k].folded
            if have == want:
                continue
            if not fuzzy:
                edits = -1
                break
            limit = tolerance(want)
            if limit == 0:
                edits = -1
                break
            distance = edit_distance(have, want, limit)
            if distance > limit:
                edits = -1
                break
            edits += distance
        if edits >= 0:
            hits.append((i, i + n - 1, edits))
    return hits


def _propagate_name(tokens: list[_Tok], known: KnownValue) -> list[Finding]:
    parts = [t.folded for t in tokenize(known.value) if t.folded not in HONORIFICS]
    if not parts:
        return []
    found: list[Finding] = []
    covered: set[int] = set()

    for i, j, edits in _match_sequence(tokens, parts, fuzzy=True):
        rule = "propagate.exact" if edits == 0 else "propagate.ocr_tolerant"
        found.append(Finding(
            known.kind, tokens[i].start, tokens[j].end, rule,
            0.99 if edits == 0 else max(0.6, 0.9 - 0.08 * edits), known.source,
        ))
        covered.update(range(i, j + 1))

    # A surname or distinctive given name on its own — how prose refers back.
    if len(parts) >= 2:
        for index, token in enumerate(tokens):
            if index in covered:
                continue
            for part in parts:
                if part in _STOPWORDS or len(part) < 4:
                    continue
                if _is_devanagari(part):
                    same = token.folded == part
                else:
                    # Capitalised in the source: prose names a person with a capital.
                    if not token.text[:1].isupper():
                        continue
                    limit = tolerance(part)
                    same = edit_distance(token.folded, part, limit) <= limit
                if same:
                    found.append(Finding(
                        known.kind, token.start, token.end, "propagate.partial_name",
                        0.8, known.source,
                    ))
                    break
    return found


def _propagate_address(tokens: list[_Tok], known: KnownValue) -> list[Finding]:
    found: list[Finding] = []
    whole = [t.folded for t in tokenize(known.value)]
    for i, j, edits in _match_sequence(tokens, whole, fuzzy=True):
        found.append(Finding(
            known.kind, tokens[i].start, tokens[j].end,
            "propagate.exact" if edits == 0 else "propagate.ocr_tolerant",
            0.97 if edits == 0 else 0.8, known.source,
        ))
    # House number and street, without the locality after the first comma. That
    # fragment alone locates a household.
    street = [t.folded for t in tokenize(known.value.split(",")[0])]
    if 2 <= len(street) < len(whole):
        for i, j, edits in _match_sequence(tokens, street, fuzzy=True):
            found.append(Finding(
                known.kind, tokens[i].start, tokens[j].end, "propagate.address_street",
                0.9 if edits == 0 else 0.75, known.source,
            ))
    return found


_DIGIT_RUN = re.compile(r"(?<![0-9A-Za-z])[0-9OoIlS|][0-9OoIlS|\s\-]{6,20}[0-9OoIlS|](?![0-9A-Za-z])")
_DIGIT_FOLD = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5"})


def _digits(text: str) -> str:
    return "".join(ch for ch in text.translate(_DIGIT_FOLD) if ch.isdigit())


def _propagate_number(text: str, known: KnownValue) -> list[Finding]:
    want = _digits(known.value)
    if len(want) < 6:
        return []
    found: list[Finding] = []
    for match in _DIGIT_RUN.finditer(text):
        have = _digits(match.group())
        if have == want:
            found.append(Finding(known.kind, match.start(), match.end(),
                                 "propagate.exact", 0.99, known.source))
        elif len(want) >= 9 and len(have) >= len(want) - 1 and edit_distance(have, want, 1) <= 1:
            # One misread, dropped or doubled digit on a long number is an OCR error
            # far more often than it is a different number.
            found.append(Finding(known.kind, match.start(), match.end(),
                                 "propagate.ocr_tolerant", 0.8, known.source))
    return found


# --- layer 2: identifiers nobody labelled ---------------------------------------

# Verhoeff tables, as published. A check digit, not a cipher.
_V_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6), (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4), (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_V_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2), (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_V_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff_valid(number: str) -> bool:
    check = 0
    for i, ch in enumerate(reversed(number)):
        check = _V_D[check][_V_P[i % 8][int(ch)]]
    return check == 0


def verhoeff_check_digit(number: str) -> str:
    """The digit that makes `number + digit` valid. Used by tests to build specimens."""
    check = 0
    for i, ch in enumerate(reversed(number)):
        check = _V_D[check][_V_P[(i + 1) % 8][int(ch)]]
    return str(_V_INV[check])


# Digits OCR mistakes for one another, used only to *repair* a failing checksum.
_DIGIT_CONFUSIONS = {
    "0": "86", "1": "7", "3": "8", "5": "6", "6": "58", "7": "1", "8": "063", "9": "4",
    "4": "9",
}

_AADHAAR = re.compile(r"(?<![0-9])[2-9]\d{3}[ \-]?\d{4}[ \-]?\d{4}(?![0-9])")
_MOBILE = re.compile(r"(?<![0-9])(?:\+91[ \-]?|0)?[6-9]\d{4}[ \-]?\d{5}(?![0-9])")
_EMAIL = re.compile(r"(?<![\w.])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![\w])")
# Fourth letter encodes the holder type; restricting it removes most false matches.
_PAN = re.compile(r"(?<![A-Z0-9])[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z](?![A-Z0-9])")
_VEHICLE = re.compile(r"(?<![A-Z0-9])[A-Z]{2}[ \-]?\d{1,2}[ \-]?[A-Z]{1,3}[ \-]?\d{4}(?![A-Z0-9])")


def _aadhaar_findings(text: str) -> list[Finding]:
    found: list[Finding] = []
    for match in _AADHAAR.finditer(text):
        digits = _digits(match.group())
        if len(digits) != 12:
            continue
        if verhoeff_valid(digits):
            found.append(Finding(FindingKind.AADHAAR, match.start(), match.end(),
                                 "pattern.aadhaar.verhoeff", 0.97))
            continue
        repaired = any(
            verhoeff_valid(digits[:i] + alt + digits[i + 1:])
            for i, ch in enumerate(digits)
            for alt in _DIGIT_CONFUSIONS.get(ch, "")
        )
        # Reported either way: a 12-digit number grouped 4-4-4 is identifying whether
        # or not its checksum survived the scan. The rule id records which it was.
        found.append(Finding(
            FindingKind.AADHAAR, match.start(), match.end(),
            "pattern.aadhaar.ocr_repaired" if repaired else "pattern.aadhaar_shaped",
            0.85 if repaired else 0.55,
        ))
    return found


def _pattern_findings(text: str) -> list[Finding]:
    found = _aadhaar_findings(text)
    for pattern, kind, rule, confidence in (
        (_MOBILE, FindingKind.PHONE, "pattern.mobile_in", 0.9),
        (_EMAIL, FindingKind.EMAIL, "pattern.email", 0.95),
        (_PAN, FindingKind.PAN, "pattern.pan", 0.93),
        (_VEHICLE, FindingKind.VEHICLE, "pattern.vehicle_in", 0.8),
    ):
        for match in pattern.finditer(text):
            found.append(Finding(kind, match.start(), match.end(), rule, confidence))
    return found


# --- layer 3: merge -----------------------------------------------------------


def merge(findings: list[Finding]) -> list[Finding]:
    """Collapse overlapping findings into one, keeping the strongest evidence."""
    ordered = sorted(findings, key=lambda f: (f.start, -f.end))
    merged: list[Finding] = []
    for finding in ordered:
        if merged and finding.start < merged[-1].end:
            last = merged[-1]
            keep = last if last.confidence >= finding.confidence else finding
            merged[-1] = Finding(
                keep.kind, last.start, max(last.end, finding.end), keep.rule_id,
                max(last.confidence, finding.confidence), keep.source,
            )
        else:
            merged.append(finding)
    return merged


def detect(text: str, known: list[KnownValue], *, patterns: bool = True) -> list[Finding]:
    """Every identifying span in `text`. Deterministic; the same input, the same output."""
    tokens = tokenize(text)
    found: list[Finding] = []
    for value in known:
        if not value.value or not value.value.strip():
            continue
        if value.kind is FindingKind.PHONE or (
            value.kind is FindingKind.OTHER and len(_digits(value.value)) >= 6
        ):
            found.extend(_propagate_number(text, value))
        elif value.kind is FindingKind.ADDRESS:
            found.extend(_propagate_address(tokens, value))
        else:
            found.extend(_propagate_name(tokens, value))
    if patterns:
        found.extend(_pattern_findings(text))
    return merge(found)


def kind_for_field(field_key: str) -> FindingKind | None:
    """Which identifying kind a field key denotes, or None if it is not identifying.

    Case references and officer names are deliberately not identifying here: redacting
    the case number from a case document serves nobody, and officers act in an
    official capacity.
    """
    if field_key.startswith("officer_") or field_key == "case_reference":
        return None
    if field_key.endswith("_name"):
        return FindingKind.NAME
    if field_key.endswith("_address"):
        return FindingKind.ADDRESS
    if field_key.endswith("_phone"):
        return FindingKind.PHONE
    return None
