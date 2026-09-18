# 0016 — Upload sanitisation uses PyMuPDF, not qpdf

## Context
PLAN's slice 4b names qpdf for structural sanitisation. qpdf is a good tool and it is a
second native binary: another thing to install on the demo machine, another thing that
can be missing at a venue, and another licence to record. CLAUDE.md is explicit that a
dependency is stated and asked for rather than added, and that between elegant-and-heavy
and plain-and-light the answer is plain.

PyMuPDF is already a dependency, already recorded with its AGPL implications (ADR 0009),
and already performs the harder version of this operation for redaction: parse the
document, drop what should not be there, write a clean file.

## Decision
`infra/intake.py` sanitises with PyMuPDF. Three checks in order, all refusing rather
than repairing where repair would be a guess:

1. **Size**, first and cheaply, before anything is parsed or held in memory.
2. **Type by content**, from the magic bytes. `.pdf` is a claim the uploader makes.
3. **Structure**, by nulling `OpenAction`, `AA`, `Names`, `AcroForm` and `OCProperties`
   on the catalogue, deleting every annotation, link and embedded file, clearing
   metadata, and saving with `garbage=4, clean=True` so the orphaned action objects are
   collected.

**The sanitiser then re-scans its own output** and raises rather than returning a file
it has not verified. This project has three recorded cases of a control that looked
applied and did nothing; a sanitiser that trusts itself would be the fourth.

Sanitising happens inside `Pipeline.run`, not at the HTTP boundary, so no caller can
create a version from unsanitised bytes — not a route added later, not a fixture loader,
not a test.

## Consequences
- No new dependency, no new binary, nothing extra to install for the demo.
- The digest that is stored, signed and anchored is of the **sanitised** file. Anchoring
  the upload would anchor something the system does not hold.
- The construct scan walks the object table rather than grepping the file, because
  object streams are compressed and a text search misses precisely what was hidden.
- A key set to `null` remains present in the object, so the scan strips `KEY null` pairs
  before matching. Without that the self-check reported every sanitised file as still
  containing `/OpenAction` and rejected clean uploads.
- This is **not** malware scanning. `MalwareScanner` remains a declared stub. A PDF whose
  *pixels* are a phishing page passes here, correctly: it carries no executable content.
