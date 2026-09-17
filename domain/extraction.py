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
    _labelled("witness_name", r"Witness\s+Name"),
    _labelled("witness_address", r"Witness\s+Address"),
    _labelled("witness_phone", r"Witness\s+Phone"),
    _labelled("officer_name", r"Officer\s+Name"),
    _labelled("case_reference", r"Reference"),
)

# Deliberately absent: any pattern for a statutory section number. CLAUDE.md forbids
# guessing them, and an extractor that confidently pulls "Section 354" out of a
# smudged scan is how a wrong citation acquires a provenance record.


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
