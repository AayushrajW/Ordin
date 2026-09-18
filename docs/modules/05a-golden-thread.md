# 05a — The golden thread

> Status: complete (`553b40d`). Fixture corpus (6a, `29b8bf4`) covered here too.

## What it does

`upload → version → OCR → extract → sign → anchor`, every stage a `ProcessingJob`
carrying the idempotency key from ADR 0004. OCR is real Tesseract over a rasterised
page. Extraction is labelled patterns producing values with character spans. Signing is
`SimulatedESignProvider`. Anchoring is last and separately retryable.

The fixture corpus feeding it is 10 fictional documents — 8 English, 2 Hindi — each
with a ground-truth sidecar recording the exact pre-render text and a bounding box for
every identifying field. `SPECIMEN — NOT A REAL RECORD` on every page, at head and
foot so a crop cannot remove it.

## Why this design

**Idempotency is the database's property, not the pipeline's.** The job key is UNIQUE,
`ocr_text.version_id` is UNIQUE, `extracted_field` is UNIQUE per (version, key,
source), `anchor_record.version_id` is UNIQUE. The pipeline's job is to notice the
conflict and skip. The acceptance test counts rows before and after rather than
inspecting control flow — a pipeline that skips correctly and one that simply did not
run twice look identical from the inside.

**The key is case-scoped** (ADR 0004). Keyed on content alone, uploading a document you
already hold into your own sandbox case would report "already processed" for a copy
held in a case you cannot read — a cross-case existence oracle.

**OCR rasterises first** (ADR 0012). The fixtures are born-digital, so reading their
text layer would be faster and would make the accuracy figure a string compared with
itself.

**Provenance is enforced by CHECK constraints**, not by Pydantic — which a direct
INSERT never reaches. A machine field with no span is refused; a human field must name
its author; nothing reaches `verified` without naming a human.

**The sidecar's boxes are verified, not assumed.** A test opens each PDF, clips to each
recorded rectangle, and asserts the extracted text contains the value the sidecar
claims. A box in the wrong place would let slice 7's redaction test go green while the
name stayed legible.

## The two questions a judge will ask

**"What happens if the pipeline runs twice?"**

Exactly one version, one OCR run, one field set, one anchor. Three runs give the same
answer, and so does a run that failed at OCR and then succeeded — with the retry
counted, because "retry count" is one of the things the reliability invariant requires
recorded. A failed stage stops the thread: there is no anchor for a document whose text
was never read.

**"Can the system mark something verified on its own?"**

No — and not by policy, by constraint. `status = 'verified'` requires a non-null
`verified_by`, so a pipeline stage physically cannot write it without naming a human. A
test asserts the pipeline emits nothing but drafts. Low-confidence OCR extracts
*nothing at all* and routes to manual entry: a page a human must read is not a page to
run patterns over and call draft evidence.
