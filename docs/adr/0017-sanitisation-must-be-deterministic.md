# 0017 — Anything upstream of content-addressed storage must be a pure function

## Context
Slice 4b put sanitisation inside `Pipeline.run`, before the version is created. The
pipeline's acceptance criterion, from slice 5a, is that running it twice on one upload
yields exactly one version, one field set, one anchor.

It immediately stopped holding. `_upsert_version` finds an existing version by the
digest of its bytes, and mupdf writes a **fresh random second half of the trailer `/ID`
on every save** — so sanitising the same file twice produced different bytes, a
different digest, and a second version. A hardening step in one slice silently broke the
central reliability guarantee of another, and only the row counts showed it.

The same shape of bug appeared a second time the same day: `redact()` draws a random
salt per manifest, so redacting the same fields twice produced two derivatives.

## Decision
**Any transformation upstream of content-addressed storage must be deterministic in its
input.** For sanitisation, `_fix_trailer_id` rewrites `/ID` to a value derived from the
document with its own `/ID` zeroed, so the output is a pure function of the input.

**It is deterministic, and it is not a fixed point.** `sanitise(sanitise(x))` differs
from `sanitise(x)` by a few bytes roughly one specimen in twenty-five, because mupdf
compacts object numbering differently on a second save. Determinism is the property the
system needs and it holds; the fixed point is a property the library does not offer and
is not asserted. Nothing here re-ingests its own output, so it costs nothing today — if
that changes, re-uploading an exported sanitised file would create one extra version.

For redaction the salt is left random, because it is a security property rather than an
implementation detail: it exists to stop a removed-value hash being correlated between
documents. Deduplication there matches on **what was redacted** — an existing derivative
of the same parent whose manifest covers the same rule ids — rather than on the bytes.

## Consequences
- Deriving the identifier from the *upload* would have been deterministic but not
  idempotent, and the difference shows up only much later as a duplicate version. The
  distinction is worth keeping in mind for any future normalisation.
- `test_sanitisation_is_deterministic` asserts the property directly, so a regression
  names its own cause instead of surfacing as a mysterious extra row in an idempotency
  test three files away.
- The fixed-point test that replaced it asserts the *limit*: a second pass is still
  clean and still the same document, without claiming the bytes match. Asserting the
  fixed point was worse than not testing it — it passed most of the time and failed once
  per full run in a different file each time, which reads as flakiness rather than as a
  property that was never guaranteed.
- The substitution preserves length, so no cross-reference offset moves.
- The general rule now has two instances and should be checked against any third:
  compression, normalisation, thumbnailing, or anything else inserted before the digest
  is taken.
