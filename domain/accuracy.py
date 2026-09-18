"""Character error rate, and the honesty constraints around reporting it.

CER is the standard OCR metric: edit distance between what the engine read and what
was actually there, divided by the length of what was actually there.

    CER = (substitutions + insertions + deletions) / len(truth)

**What makes this number honest here**, and it is worth being explicit because
`docs/PLAN.md` R9 cut the extraction metric for failing exactly these tests:

  - The ground truth is the text placed on the page *before* rendering. Tesseract
    never saw it. Comparing its output to that measures OCR.
  - The pipeline rasterises before reading (docs/adr/0012), so this is OCR over
    pixels, not a text layer compared with itself.
  - Rows recorded as `embedded_text_layer` are **excluded**. Including them would
    score ~0% and drag the average toward a number that means nothing.

**What it is not.** Ten synthetic documents on one machine is a measurement of this
corpus, not a general accuracy claim, and the report says so on its face. CLAUDE.md
forbids fabricated statistics; a real number presented as more general than it is
belongs in the same category.

Pure: no database, no engine, no I/O.
"""
from dataclasses import dataclass


def levenshtein(a: str, b: str) -> int:
    """Edit distance. Two-row dynamic programming; the corpus is small.

    No new dependency for this - it is twenty lines, and `python-Levenshtein` would
    be a C extension in the image for a number computed once.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,        # deletion
                    current[j - 1] + 1,     # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        previous = current
    return previous[-1]


def normalise(text: str) -> str:
    """Collapse whitespace only.

    Deliberately minimal. Lowercasing or stripping punctuation would flatter the
    score by forgiving errors that matter: a name is case-sensitive and a misread
    digit in a phone number is a real error. Whitespace is collapsed because line
    wrapping is a layout artefact of rasterising, not an OCR mistake.
    """
    return " ".join(text.split())


@dataclass(frozen=True)
class Measurement:
    document: str
    language: str
    method: str
    truth_chars: int
    errors: int

    @property
    def cer(self) -> float:
        return self.errors / self.truth_chars if self.truth_chars else 0.0


def measure(document: str, language: str, method: str, truth: str, observed: str) -> Measurement:
    t, o = normalise(truth), normalise(observed)
    return Measurement(
        document=document, language=language, method=method,
        truth_chars=len(t), errors=levenshtein(t, o),
    )


def aggregate(measurements: list[Measurement]) -> dict[str, dict]:
    """Group by language. Weighted by characters, not a mean of per-document rates.

    Averaging per-document CERs would let a short document with one bad word count
    as much as a long clean one, which overstates or understates depending on the
    corpus shape. Total errors over total characters is the figure that means what
    it says.
    """
    buckets: dict[str, dict] = {}
    for m in measurements:
        bucket = buckets.setdefault(
            m.language, {"documents": 0, "truth_chars": 0, "errors": 0}
        )
        bucket["documents"] += 1
        bucket["truth_chars"] += m.truth_chars
        bucket["errors"] += m.errors
    for bucket in buckets.values():
        bucket["cer"] = (
            bucket["errors"] / bucket["truth_chars"] if bucket["truth_chars"] else 0.0
        )
    return buckets


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. Honest about tiny samples: p95 of 10 values is the
    second-worst value, and the report labels it rather than implying a distribution."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[index]
