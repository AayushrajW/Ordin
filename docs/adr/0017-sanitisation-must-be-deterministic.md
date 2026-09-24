# 0017 — Anything upstream of content-addressed storage must be a pure function

> **Corrected 2026-09-21.** The section below headed "It is deterministic, and it is not
> a fixed point" was **wrong**, and wrong in the way that does the most damage: it gave
> every later intermittent failure a ready explanation. See ADR 0030.

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

~~**It is deterministic, and it is not a fixed point.** `sanitise(sanitise(x))` differs
from `sanitise(x)` by a few bytes roughly one specimen in twenty-five, because mupdf
compacts object numbering differently on a second save.~~

**Superseded.** It is deterministic *and* it is a fixed point. The observed divergence
was not mupdf renumbering objects; it was `_TRAILER_ID` matching only one of PDF's two
string syntaxes, so the normalisation silently did nothing whenever mupdf chose the
other. ADR 0030 has the diagnosis. Measured after the fix: 48 corpus files, all fixed
points; one specimen sanitised 60 times across a deliberately dirtied process, one
digest.

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
  test three files away. `test_pipeline_idempotency` asserts the same thing at the
  integration level, where a narrowing of the pattern would otherwise reappear as an
  unexplained duplicate.
- The substitution no longer preserves length — a literal `/ID` is rewritten as hex —
  and that is safe because the trailer sits *after* the cross-reference table it
  describes, so no object offset moves and `startxref` still points where it did.
- **An `/ID` the pattern cannot parse is now a refusal, not a no-op.** Returning the
  document unchanged was the whole defect: a control that looks applied and does
  nothing (invariant 2).
- The general rule now has two instances and should be checked against any third:
  compression, normalisation, thumbnailing, or anything else inserted before the digest
  is taken.
