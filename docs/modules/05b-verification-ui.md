# 05b — The verification screen, and span highlighting

> Status: complete. Tier A, deferred by PLAN's hour-20 gate and built last.

## What it does

Case list, document view, and the screen where a person commits a machine-extracted
value to `verified`: draft fields on the left, the scan on the right, and the selected
field's OCR word boxes drawn over the page. Plus the two writes that go with it — a
correction, and a value typed by hand when OCR produced nothing — and a redact button
that turns the located fields into a derivative.

It is the slice that makes invariant 9 true of the *product* rather than only of the
database. `ck_verified_names_a_human` has refused an unattributed `verified` since
migration 0006; until this existed, nobody could perform the attestation it describes.

## Why this design

**Writing is narrower than reading** (ADR 0014). Reading is gated by the disclosure
class, so a purpose-limited grantee reads derivatives. Verifying, correcting, uploading
and redacting all require `ORIGINAL`, because each is an assertion about a document —
and letting someone vouch for text they may not lawfully read is both an authorization
bug and a nonsense. A commit route that checked only case access would have passed every
test written before this slice.

**A correction is a new row, not an update.** The machine said one thing and a human says
another; overwriting the extracted value destroys the only record of what the extractor
actually produced, which is the evidence that the extractor needs correcting. The human
value is `source='human'` with no span, because inventing one would make invariant 7's
provenance a lie (ADR 0011).

**No JavaScript, and no Server Actions** (ADR 0018). Selection lives in the URL, writes
are form posts, redirects are relative. This began as a framework-idiom implementation
and was refused at runtime by an origin check that no test would have caught — the
failure appears only when somebody clicks. What replaced it is simpler, works in any
browser, and survives being reached by IP address.

**The provenance tuple is on the screen.** Source, provider, model, confidence and the
character span are rendered beside each field. A judge asking "where did this come from?"
should not need a database client.

## The two questions a judge will ask

**"Could the system have marked that verified by itself?"**

No, and not by policy — by constraint. `status='verified'` requires a non-null
`verified_by`, so no pipeline stage can write it without naming a person. Press the
button and one append-only, hash-chained audit row appears naming who did it; Sentinel
VERIFY-01 performs exactly that sequence in front of you and reports that nothing was
verified until the human acted. Press it as the prosecutor instead and you get the same
404 as for a case that does not exist, with the field still a draft (VERIFY-02).

**"How do I know the highlight is really where that text came from?"**

It is the same record the redaction uses. The field carries character offsets into the
OCR text; `ocr_word` carries both those offsets and the rectangle each word occupied, so
the highlight is a range query rather than a second source of truth. Click "redact" and
the regions burned out of the page are those same rectangles — there is no second
coordinate system that could disagree with what you were shown.

And the limit, which this screen makes visible rather than hides: on the specimen
complaint the extractor reads the complainant's **name** correctly and gets the **phone
number and the case reference wrong**, because Tesseract misreads digits even on a clean
render. Those arrive as drafts and a human fixes them. That is not a defect in the demo,
it is the argument for the demo.
