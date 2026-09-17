# 0010 — `verify()` gains a fifth state: `PENDING`

## Context
CLAUDE.md security invariant 5 fixes the return of `verify()` at four states:
`VERIFIED | MISMATCH | DISPOSED_ANCHOR_ONLY | UNAVAILABLE`. Its reasoning is exact and
worth preserving: a lawfully disposed document is not a tampered one, and reporting
MISMATCH for it is both a correctness bug and a legal misrepresentation.

The same reasoning applies one state further along, and the invariant does not reach
it. CLAUDE.md's reliability invariants say:

> An anchor outage never corrupts case state. Anchoring is a separate retryable
> stage; **a case with a pending anchor is valid.**

A document that has been uploaded and hashed but not yet anchored is therefore a
*normal* state — the expected state, briefly, for every document. With four states it
has nowhere to be reported, so it collapses into `UNAVAILABLE`, which already means
three other things: the blob is missing, the anchor store is unreachable, and (by
deliberate choice, to avoid an existence oracle) the caller is not permitted to see
this document at all.

"Not yet anchored" and "the bytes are gone" are opposite situations. One is a document
progressing normally; the other is an incident. Conflating them is the same class of
error invariant 5 was written to prevent — it just sits one square over.

## Decision
`verify()` returns **five** states:

    VERIFIED | MISMATCH | DISPOSED_ANCHOR_ONLY | PENDING | UNAVAILABLE

`PENDING` means: the version exists, its digest is recorded, and no anchor has been
written yet. It is not a failure and must not be rendered as one.

`UNAVAILABLE` keeps its remaining meanings, including the deliberate conflation of
"does not exist" with "not yours" (threat INS-04). That conflation stays — it is
load-bearing, and `PENDING` does not weaken it, because a caller who cannot see a
document never reaches a state computation at all.

**CLAUDE.md invariant 5 is amended to match**, as CLAUDE.md itself instructs: "update
this file if a decision here is now wrong."

## Consequences
- A pending anchor renders as *pending*, not as an error, so the demo does not show a
  red state for a document behaving correctly.
- An anchor that never arrives becomes visible as an aging `PENDING` rather than
  hiding among genuine `UNAVAILABLE`s. The coverage pass noted an indefinitely
  suppressed anchor is otherwise invisible; this does not add an alert, but it makes
  one possible later without another state change.
- Five states is one more thing to explain. Accepted: the alternative is a four-state
  answer that is wrong for the most common transient condition in the system.
- Anything consuming `verify()` must handle `PENDING` explicitly. There is exactly one
  consumer today, which is why this is decided now rather than after slice 5a wires
  the pipeline to it.
