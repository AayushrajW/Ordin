# 07 — Destructive redaction and the role switch

> Status: complete (`aa3a9b1`). This is the slice the pitch opens with.

## What it does

Removes identifying regions from a document and produces a derivative that is a
first-class version, carrying `derived_from_version_id`, its own `sha256` and a
`redaction_manifest_hash`. Which version a subject receives depends on their
relationship to the case: designation gets the original, a purpose-limited grant gets
the derivative.

## Why this design

**Remove, rasterise, rebuild — three steps, all load-bearing.** `apply_redactions`
deletes the content under each rectangle rather than covering it, because a black box
leaves the glyphs one copy-paste away. Rasterising removes whatever the PDF retained
that text extraction does not reveal, and makes the operation identical on a scanned
page where redaction is an image operation anyway. Rebuilding into a fresh document
means no inherited metadata, XMP, outline or embedded thumbnail can carry the name
independently — tested by poisoning the source metadata first and asserting it does not
survive.

**The manifest never stores what it removed.** The defensible-sounding design — log the
redacted strings so the redaction can be justified later — produces a curated list of
exactly the identifying values, which is a worse artefact than the original: shorter,
and composed entirely of names. Regions carry geometry, a rule id, and a per-manifest
salted hash. Useless for discovery, sufficient for confirming a name you already hold,
and not cross-referenceable between documents.

**The leak the stated acceptance criterion misses.** PLAN says "extract text from the
derivative and assert the victim name is absent". That is necessary and not sufficient:
redaction produces a *new version*, so the original's OCR text, extracted field values
and search snippets are untouched. A grantee passes the case-level filter and reads the
removed name from the text endpoint instead of the PDF. `infra/disclosure.py` closes it
(ADR 0013), and the tests assert the original genuinely still holds the names before
asserting the redacted role cannot reach them — otherwise the control could pass
because the data was absent rather than withheld.

## The two questions a judge will ask

**"How do I know the name is really gone and not just hidden?"**

Extract the text from the derivative yourself — Sentinel scenario REDACT-01 does
exactly that in front of you and reports how many values were removed and how many were
still extractable. The page is an image with no text layer at all, because the
derivative is rebuilt from rendered pixels. And the original is untouched: a test
asserts the source file still contains every value, so the derivative is a new artefact
rather than a destroyed one.

**"What does this miss?"**

Everything it was not told to remove, and the module says so. Region selection is
patterns over OCR text plus a human dragging boxes — there is no entity recognition and
no LLM — so a handwritten name, a name inside a photographed ID card, or a letterhead is
never located and therefore never covered. That is accepted risk AR-6. It is bounded
further by OCR recall: measured character error rate is 0.34% on English and **10% on
Hindi**, so redaction targeting is materially less reliable on Devanagari documents. And
the derivative is then signed and anchored, which means the integrity machinery
certifies whatever leaked. Redaction covers what was located, and located-ness is
bounded by what the OCR could read.
