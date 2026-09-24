# 0031 — Export and disposal: two verbs the vocabulary named and nothing could write

## Context
`AuditAction.DOCUMENT_EXPORTED` and `AuditAction.DISPOSAL_RECORDED` existed from slice 2
with no caller anywhere in the running system. That left two claims hollow.

**Export was not a verb.** Reading a document and taking a copy of it were the same
event, so the difference between an officer working a case and an officer emptying it
was invisible — threat AR-17, whose stated mitigation is deliberately modest:
*make bulk export a distinct verb in the audit chain recording row count and filter —
accounting, not prevention.*

**`DISPOSED_ANCHOR_ONLY` was unreachable.** One of the five states security invariant 5
is built on could not be produced by anything the application could do. An integrity
model with a dead branch in the place that matters most is a model nobody has tested.

## Decision

### Export
`GET /versions/{id}/export` and `GET /cases/{id}/export`. Both record an `export_record`
row and an audit entry.

**The bytes are byte-exact and unwatermarked, and that is the decision.** The page
renderer watermarks with the viewer's name (threat AR-7); the export does not. A
watermark changes the bytes, and changed bytes do not hash to the anchored digest —
which destroys the one property that makes an export evidential. The recipient must be
able to run sha256 on what they were handed and have it match the case record, so the
digest travels in `X-Ordin-SHA256` and the attribution lives in the record instead.
The trade stated plainly: **this build can prove what was taken and by whom; it cannot
mark the copy itself.** AR-7 is unchanged.

**A document that does not verify is never handed over.** A single-version export of a
tampered document is refused. A case export lists it in `manifest.json` with its
integrity state and omits its bytes, counted in `excluded_count` — an export that
silently dropped a mismatched document would be the quietest possible way to lose a
tamper alert.

**`export_record` has no free-text column**, although AR-17's wording invites one. Scope
and disclosure class are enumerated; everything else is a count. A `filter` string is
where a case reference or a search term eventually lands (invariant 12).

**Disclosure decides the contents.** The route uses `readable_version_ids`, the same
function the viewer uses, so a grantee exports derivatives and there is no second code
path to disagree with the first (threat VIC-01).

### Disposal
`POST /versions/{id}/dispose` with an enumerated `basis`. Requires disclosure ORIGINAL —
destroying a document you may only see redacted is not a thing to allow, for the same
reason attesting to one is not (ADR 0014).

**Anchored first, or not at all.** A version with no anchor cannot be disposed.
Destroying bytes you were never able to attest to leaves `verify()` returning
UNAVAILABLE for ever — an absence nobody can explain — and "we destroyed it lawfully"
is a claim that needs the anchor to mean anything.

**The derived text goes with the bytes.** `ocr_text`, `ocr_word` and `extracted_field`
are deleted in the same transaction, which also removes the document from search (the
index is a functional GIN over `ocr_text`). Threat AR-13 named this: a disposal that
left the OCR of a destroyed document searchable would be a disposal in name only.

**The bytes go only if nothing else needs them.** The store is content-addressed, so one
file can back several versions. The address is deleted only when no surviving version
references it. The store cannot see the case record, so the check has to be on the
application side — and nothing would have failed loudly if it were missing: the other
version would simply have started verifying as MISMATCH one day, with no event to point
at.

**The unlink happens after the transaction commits.** A filesystem delete cannot be
rolled back. A disposal recorded with the bytes still present is recoverable; bytes
destroyed with no record is not.

## Consequences
- **Accounting, not prevention.** Nothing here stops a designated officer exporting
  every case they hold. There is no quota and no anomaly detection. AR-17's disposition
  narrows from "unmetered" to "metered per case, unmetered across cases": a case export
  is counted, and `GET /cases` and `/search` are not.
- A case export builds the archive in memory, so it refuses above 50 documents or 32 MB.
  Those are the limits of a 256 MiB container, not a policy, and refusing loudly beats
  being OOM-killed mid-response — which looks to the caller exactly like the export
  succeeding and the connection dropping.

  **The first version of that cap did not bound what it claimed to.** It collected every
  blob into a list and zipped at the end, so the case was held three times over — raw
  bytes, compressed archive, and the copy `getvalue()` makes — and a 64 MB limit on the
  raw bytes could peak near 190 MB. The archive is now written as each document is read
  and the plaintext dropped immediately, so the peak is one document plus the archive
  plus one copy: about 89 MB at 32 MB. A limit that is measured against the wrong
  quantity is not a smaller limit, it is a slower OOM.
- **The export routes have their own rate-limit bucket** (20/min, `api/security.py`).
  They are GETs that do not end in `/page.png`, so they matched no bucket at all: the
  most expensive route in the application, and the one AR-17 is written about, was the
  only unmetered one.
- **Disposal is unilateral.** Two-person approval was cut (AR-15), so it rests on
  attribution, which is why the audit row is written in the same transaction.
- The honest claim is bounded: **the stored original is destroyed.** Write-ahead logs,
  filesystem snapshots and any backup taken before now are out of reach of this code.
  Saying "the document is destroyed" would be a claim this build cannot support.
- **Re-filing a disposed document appends rather than resurrects.** Disposal destroys a
  *version's* copy, not the content of the world: anybody holding the file can upload it
  again, and refusing that would make an erroneous disposal unrecoverable.
  `_upsert_version` ignores disposed rows when it looks for an existing version, so a
  re-upload creates a new version with its own anchor and its own audit row, and the
  disposed one stays disposed.

  This was found the other way round, and the defect was the silence rather than the
  bytes. `_upsert_version` used to call `blobs.put` *before* the lookup, so a re-upload
  wrote the bytes back to the same content address — the address is a digest of the
  plaintext — and then matched the disposed row and returned it. No new version, no new
  audit entry: the disposition record stayed the only account of a document whose bytes
  were back on disk. Nothing could detect it from outside, because `verify_version`
  checks disposal before the bytes (invariant 5, correctly), so the verdict never looks
  at the file.
- **The response no longer claims an erasure it declined to perform.** When another
  surviving version shares the content address the bytes are deliberately kept, and the
  note said "the stored original is destroyed" anyway. The caller repeats what it is
  told, so that sentence is now chosen by what actually happened.
