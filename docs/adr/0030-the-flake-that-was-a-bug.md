# 0030 — The flake that was a bug, and the ADR that hid it

## Context
`test_sanitisation_is_deterministic` failed once in a full suite run and passed on its
own. The project had an explanation ready: ADR 0017 recorded that mupdf "compacts object
numbering differently on a second save", that `sanitise` was deterministic but not its
own fixed point, and that a divergence of a few bytes was a documented limit rather than
a regression. Two test docstrings repeated it. A third test had already been weakened to
stop asserting the stronger property.

All of that was wrong.

## The actual cause
A PDF string is written in one of two syntaxes and a writer chooses per value: hex
`<48656c6c6f>` or literal `(Hello)`. mupdf emits a random trailer `/ID` as a literal
when its bytes happen to be mostly printable, and as hex otherwise.

`_TRAILER_ID` matched hex only:

    rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]"

When mupdf chose a literal, `subn` returned `count == 0`, `_fix_trailer_id` returned the
document **unchanged**, the random identifier survived, and the "deterministic"
sanitiser produced different bytes for the same input. One document in roughly thirty,
depending on nothing an observer could see.

Reproduced deliberately by interleaving corpus work between two calls — 31 rounds to
diverge. The captured trailers say it plainly:

    A  /ID[<F6BA470C...><F6BA470C...>]          normalised, both halves derived
    B  /ID[<77C295C2...>( p\325\270U\360O=mdz)] untouched, mupdf's own random value

## Decision
- `_PDF_STRING` matches both syntaxes, with one level of nested parentheses, and output
  is normalised to hex.
- **An `/ID` the pattern cannot parse raises `SANITISATION_FAILED`.** Returning the
  document unchanged is the whole defect: invariant 2 says fail closed, and a
  normalisation that silently no-ops is a control that looks applied and does nothing —
  which `infra/intake.py`'s own docstring warns about three times.
- ADR 0017's "not a fixed point" section is struck through rather than deleted, because
  the wrong reasoning is the part worth keeping.
- The assertion weakened in `test_pipeline_idempotency` is restored, with the history in
  a comment.

Measured after the fix: 48 corpus files, every one a fixed point; one specimen sanitised
60 times across a deliberately dirtied process, one digest.

## Consequences
- **The cost of this was the ADR, not the regex.** A one-line pattern is a twenty-minute
  bug. Having written "not guaranteed" into an architecture decision and two docstrings
  meant every later intermittent failure arrived pre-explained, and the real cause was
  protected by the explanation for weeks. A documented limitation is load-bearing: it
  stops people looking.
- The rule to carry: **an intermittent failure in a pure function is a bug until
  measured otherwise.** "The library is non-deterministic" is a claim that needs a
  reproduction and a captured diff, not a plausible mechanism. The mechanism offered
  here — object renumbering — was plausible, well-known, and not what was happening.
- What this did *not* cost: duplicate versions. `_upsert_version` has keyed on
  `source_sha256` since migration 0008, so a differing sanitised digest produced an
  orphaned blob on re-upload rather than a second version. The reliability invariant
  held; the storage claim did not.
