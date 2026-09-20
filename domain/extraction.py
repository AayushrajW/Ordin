"""Deterministic field extraction.

CLAUDE.md: "Deterministic extraction over ML, ML over LLM. The LLM is last, for the
unstructured residue only." There is no LLM in this build at all, so this is the whole
extraction layer, and it is deliberately boring: labelled patterns over OCR text.

Every match carries the **character span it came from**, because invariant 7 requires
a machine field to point at its source and ADR 0011 makes that a database constraint.
The span is what slice 5b highlights and what slice 7 turns into a rectangle to redact.

Pure: no database, no framework, no I/O. The patterns are data, testable directly.

A note on what this is not. OCR text is untrusted input (invariant 6). These patterns
read it; nothing here interprets it as an instruction, changes workflow state, or
influences an authorization decision. A pattern can only ever produce a candidate
value with a span, which a human then confirms.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Extractor:
    """One labelled pattern.

    `key` is the field it produces. `pattern` must contain a group named `value`,
    which is what gets extracted - the span reported is that group's, not the whole
    match, so the label ("Complainant Name:") is never part of the field.
    """

    key: str
    pattern: re.Pattern
    version: str


@dataclass(frozen=True)
class Extraction:
    field_key: str
    value: str
    span_start: int
    span_end: int
    extractor_version: str
    confidence: float


def _labelled(key: str, label: str, version: str = "v1") -> Extractor:
    """A `Label: value` line, which is how the fixture forms are laid out.

    The value stops at end of line so a missing value cannot swallow the next field -
    a greedy pattern here would capture half the document and report it as a name.
    """
    return Extractor(
        key=key,
        pattern=re.compile(
            rf"{label}\s*[:\-]\s*(?P<value>[^\n\r]{{1,120}}?)\s*(?=\n|\r|$)",
            re.IGNORECASE,
        ),
        version=version,
    )


EXTRACTORS: tuple[Extractor, ...] = (
    _labelled("complainant_name", r"Complainant\s+Name"),
    _labelled("complainant_address", r"Complainant\s+Address"),
    _labelled("complainant_phone", r"Complainant\s+Phone"),
    _labelled("victim_name", r"Victim\s+Name"),
    _labelled("victim_address", r"Victim\s+Address"),
    _labelled("victim_phone", r"Victim\s+Phone"),
    _labelled("witness_name", r"Witness\s+Name"),
    _labelled("witness_address", r"Witness\s+Address"),
    _labelled("witness_phone", r"Witness\s+Phone"),
    _labelled("officer_name", r"Officer\s+Name"),
    _labelled("case_reference", r"Reference"),
    # Dates. The deck says the system extracts "sections, dates and parties" and there
    # was no date pattern at all. These are labelled lines like every other field, so
    # they inherit the same span, confidence and human-commit path - a date is evidence
    # about when something happened, and nothing here should treat it as more certain
    # than the name on the line above it.
    _labelled("date_of_incident", r"Date\s+of\s+Incident"),
    _labelled("date_of_report", r"Date\s+of\s+Report"),
    _labelled("date_of_filing", r"Date\s+of\s+Filing"),
)

# A reference to a provision of one of the three named codes.
#
# **This detects a string. It does not know what the provision says**, and it must never
# be made to look as though it does. CLAUDE.md forbids guessing section numbers, and the
# risk it is guarding against is not detection - it is a system that reads "Section 354"
# off a smudged scan and gives that reading a provenance record, a confidence score and
# the appearance of legal knowledge.
#
# So the rule is narrow on purpose:
#
#   - only BNS, BNSS and BSA, named explicitly. A generic `Section \d+` would match a
#     page number, a paragraph reference, or a clause of a contract.
#   - the value recorded is the reference as written, never an interpretation.
#   - it is a draft like every other extracted field, so a person confirms it before it
#     is anything at all (invariant 9).
#
# What it deliberately still does not do: resolve the reference to statutory text,
# decide whether the provision applies, or check that the section exists. Each of those
# needs an authoritative corpus that this build does not have, and inventing one would
# be worse than the gap.
STATUTORY_REFERENCE = re.compile(
    # BNSS before BNS: alternation is first-match, so `BNS` would otherwise consume
    # the prefix of `BNSS 173` and record it as BNS 173 - a different code, a
    # different statute, and a citation the document does not contain.
    r"\b(?P<code>BNSS|BNS|BSA)\b\s*"
    # The section marker, all of it optional: "BNS 74", "BNS s 74", "BNS Sec. 74",
    # "BNS Section 74", "BNS S.74" and "BNS \u00a7 74" are the same citation written six
    # ways, and Indian legal writing uses "S." as often as "Section".
    r"(?:\u00a7|[Ss](?:ec(?:tion)?)?\.?)?\s*"
    r"(?P<number>\d{1,3}[A-Z]?)\b"
)


def extract_statutory_references(text: str) -> list[Extraction]:
    """Every reference to a BNS, BNSS or BSA provision, as drafts.

    Multiple per document, unlike the labelled fields: a charge sheet cites several
    provisions and recording only the first would silently drop the rest. The key
    carries an index so each keeps its own span and its own human decision.
    """
    found: list[Extraction] = []
    for index, match in enumerate(STATUTORY_REFERENCE.finditer(text)):
        found.append(
            Extraction(
                field_key=f"statutory_reference_{index + 1}",
                # As written, normalised only in spacing. Not interpreted.
                value=f"{match.group('code')} {match.group('number')}",
                span_start=match.start(),
                span_end=match.end(),
                extractor_version="statutory.v1",
                # A pattern matched. It is not a measure of whether the citation is
                # correct, and there is no model here that could estimate that.
                confidence=1.0,
            )
        )
    return found

# A statutory reference extractor now exists - see STATUTORY_REFERENCE above - and it
# is deliberately narrower than the thing this comment used to refuse. It detects a
# reference to a named code and records it as a draft. It does not resolve the
# provision, does not decide whether it applies, and does not check that it exists.


def extract_fields(text: str) -> list[Extraction]:
    """Run every extractor. First match per key wins; order follows EXTRACTORS.

    Confidence is fixed at 1.0 for a deterministic pattern: the pattern either matched
    or it did not. That is honest - a made-up 0.87 would imply a calibrated model
    where there is a regular expression. OCR confidence is recorded separately, on the
    OCR result, because it measures a different thing.
    """
    found: list[Extraction] = []
    seen: set[str] = set()

    for extractor in EXTRACTORS:
        if extractor.key in seen:
            continue
        match = extractor.pattern.search(text)
        if not match:
            continue
        value = match.group("value").strip()
        if not value:
            continue
        start, end = match.span("value")
        found.append(
            Extraction(
                field_key=extractor.key,
                value=value,
                span_start=start,
                span_end=end,
                extractor_version=f"{extractor.key}.{extractor.version}",
                confidence=1.0,
            )
        )
        seen.add(extractor.key)

    return found


def span_to_boxes(words, start: int, end: int) -> list[tuple[float, float, float, float]]:
    """Every word rectangle overlapping a character span.

    This is the bridge from "characters 142-155 of the OCR text" to "these pixels on
    the page". Slice 5b highlights them; slice 7 redacts them.

    Overlap rather than containment: a span may begin mid-word after OCR joins or
    splits tokens, and a word half-covered by a name still shows the name.
    """
    return [
        (w.x0, w.y0, w.x1, w.y1)
        for w in words
        if w.char_start < end and w.char_end > start
    ]
