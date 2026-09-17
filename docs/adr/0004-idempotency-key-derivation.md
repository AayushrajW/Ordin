# 0004 — Idempotency key derivation

## Context
Every processing stage carries an idempotency key, and a retry must not produce a second
version, extraction run, field set, anchor or derivative. The reliability invariant
specifies the requirement and not the derivation — and the derivation silently decides
three security properties that have nothing to do with retries:

- Keyed on content alone, an upload into any case answers "already present" for a
  document held in a case the uploader cannot read. That is a cross-case existence
  oracle (INS-06 in `docs/THREAT-MODEL.md`).
- Keyed on `(parent_version, stage)`, an operator who spots a name the redaction missed
  and re-runs it gets the original flawed derivative back (seam 2).
- Deterministic sanitisation strips metadata and object ordering by design, so two scans
  of the same blank statutory form from different cases can converge to identical bytes
  and collide (seam 10).

## Decision
    key = SHA256(case_id || content_sha256 || operation || params_hash)

- **`case_id`** scopes the key, so an upload can never report "already exists" for a
  document held in another case.
- **`params_hash`** covers the redaction manifest, so a corrected manifest produces a new
  key and cannot return the flawed derivative.
- Together these mean the same blank form scanned into two cases yields two keys.

## Consequences
- Identical bytes are stored twice when filed into two cases. Accepted deliberately:
  **per-case data-encryption keys make cross-case blob deduplication impossible anyway**,
  so scoping the key to the case costs no storage that per-case keys were not already
  costing, and declining to scope it would not have bought dedup back.
- `operation` must be an enumerated stage name, never a free string, or the same work
  under two spellings runs twice.
- Retry semantics are unchanged: same case, same bytes, same stage, same params returns
  the existing result.
