# 0014 — Writing is narrower than reading: attestation requires ORIGINAL disclosure

## Context
Slice 5b adds the first write a court would care about: a human commits a
machine-extracted value to `verified`. Invariant 9 has been enforced by
`ck_verified_names_a_human` since migration 0006, but nothing in the running system
could perform the commit — a constraint proving that only a human *may* write
`verified` while no human *can*.

The obvious authorization for the new route is the one every other route uses: may
this subject read this case? That is wrong, and wrong in a way that passes every test
written so far. A purpose-limited grantee passes the case filter by design (ADR 0013),
so a commit route checking only case access would let them sign off on the contents of
a document they are forbidden to read. They would be attesting to text they have never
lawfully seen, and the row would name them as having done so.

The same reasoning covers uploading and redacting: both are assertions about the case
file made by someone the case file does not belong to.

## Decision
Reading is gated by the disclosure class. **Writing requires `Disclosure.ORIGINAL`.**

`_require_original()` guards `POST /fields/{id}/verify`, `POST /versions/{id}/fields`,
`POST /versions/{id}/redact` and `POST /cases/{id}/documents`. A subject without it
receives the same 404 as for a case that does not exist.

A field's bounding boxes are gated the same way: a rectangle is a claim about where a
value sits on the original page, and handing it to someone who may not read that page
leaks position and length — VIC-01 one level of indirection out.

## Consequences
- The rule is stated once and applied at four call sites, rather than being re-derived
  per route. Sentinel VERIFY-02 watches it against the running system.
- A grantee cannot correct an error they can see in a derivative. That is the right
  trade for this build and it is a real limitation: the route for "the external
  prosecutor noticed the extractor misread a date" is to tell someone designated.
- Verifying twice is not a second attestation. The UPDATE is guarded on
  `status = 'draft'`, so the first author keeps the row.
- A correction writes a **new** `source='human'` row rather than updating the machine's.
  The extracted value is the record of what the extractor produced, and overwriting it
  destroys the evidence that the extractor needs fixing.
- Superseding an earlier *human* value does overwrite it, and authorship follows the
  latest writer. Version history for hand-entered values is not modelled in this build;
  the chain records that each entry happened and who made it, not what it replaced.
