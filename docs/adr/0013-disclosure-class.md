# 0013 — Disclosure class: which version a subject receives

## Context
Slice 3 answers *may this subject see this case at all?* Slice 7 produces a redacted
derivative. Neither answers the question between them: **given that someone may see the
case, which version do they get?**

Leaving that gap open is what makes the headline demo hollow. A grantee passes slice
3's case-level filter, so if slice 7 only hands them a redacted PDF they can still read
the removed name from the original's OCR text, its extracted field values, or a search
snippet built over either — because redaction produced a *new version* and the
original's derived text was never touched. That is threat VIC-01, which the coverage
pass called the single most likely real leak in the built system, and slice 7's own
stated acceptance test does not catch it: that test only inspects the PDF.

## Decision
Disclosure is a property of the subject's **relationship to the case**, computed
alongside the authorization decision and gating derived text as well as bytes:

    designation  -> ORIGINAL    the investigating officer works the real document
    grant        -> REDACTED    purpose-limited external access never gets originals
    neither      -> NONE

`infra/disclosure.py` exposes `readable_version_ids`, `readable_ocr_text` and
`readable_fields`. A `REDACTED` subject receives derivatives only; asking for the
parent version id directly returns nothing rather than a 403, so the parent's
existence is not confirmed (threat INS-08).

**Rank is not an input.** There is deliberately no rule of the form "a senior officer
gets the unredacted copy" — that is precisely what makes seniority decisive, which
CLAUDE.md's authorization model forbids.

## Consequences
- CLAUDE.md's "unauthorised roles never receive original bytes on any code path" now
  covers the paths that are not bytes. OCR text is original content in a different
  shape.
- Two questions must both be asked on every document route: may you see the case, and
  which version. Forgetting the second yields a working endpoint that leaks, which is
  why the Sentinel scenario REDACT-03 exists rather than only a unit test.
- Disclosure is currently derived from designation-versus-grant. A future rule keyed
  on the grant's *purpose* (some purposes justifying an original) is a change to this
  one function, not a change scattered across routes.
- The tests assert the original genuinely still contains the names before asserting
  the redacted role cannot reach them. Without that, the control could pass because
  the data was absent rather than because it was withheld.
