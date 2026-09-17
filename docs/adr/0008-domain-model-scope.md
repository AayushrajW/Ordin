# 0008 — Domain model scope, and generic case states

## Context
`BOOTSTRAP.md` slice 2 lists 16 entities. `docs/PLAN.md` trims the slice to ~10 on the
grounds that the budget is ~34 solo hours and the spine alone was priced at the whole
of it. Two questions had to be answered concretely: which entities, and what the case
state machine's states are actually called.

The second is delicate. Ordin is built for Indian legal and investigation agencies, and
CLAUDE.md is explicit that statutory behaviour is never guessed — every statutory
reference cites a source. Case workflow stages sit close enough to that line to matter.

## Decision

**Twelve entities now.** organization, jurisdiction, post, app_user, case_record, party,
case_assignment, document, document_version, processing_job, access_grant, audit_event.

Four deferred, each to the slice that owns its shape rather than to "later":

| Deferred | To | Why |
|---|---|---|
| Clearance | — | Collapsed to `clearance_level` + `clearance_valid_to` on `app_user`. A level and a validity window; a table adds a join for nothing at this scale. |
| PolicyDecision | slice 3 | Slice 3 writes it and should decide its columns. |
| ExtractedField | slice 5a | Invariant 7 requires `source_span`, and there is an open question about manual entry producing a field with none. Answer it before freezing the schema. |
| AnchorRecord | slice 4a | Belongs with `verify()` and `LocalAnchorStore`. |

**Case states are deliberately generic**: `registered → under_investigation → filed →
in_trial → closed`, with `closed` reachable from any open state and terminal. They are
procedural placeholders, not the statutory stages of an Indian women-safety
prosecution, and `domain/case.py` says so in the code.

Transitions live in `ALLOWED_TRANSITIONS` as **data**, for the same reason
authorization policy does: the part most likely to be wrong should be reviewable,
diffable and unit-testable without the application running.

`case` and `user` are SQL reserved words, so the tables are `case_record` and
`app_user`. Quoting reserved identifiers everywhere is a papercut that eventually gets
forgotten in one raw query.

## Consequences
- Slice 3 has everything it needs: all seven authorization dimensions have a column or
  a table, and the seed carries a lapsed assignment, an expired grant and a lapsed
  clearance so the three independent validity clocks can be tested separately.
- **The state names are an open question, recorded in `docs/STATUS.md`.** They must be
  confirmed against a source before they appear in UI copy, a fixture or the deck.
  Because transitions are data, that confirmation is an edit to one table.
- Deferring `ExtractedField` means slice 5a inherits the invariant-7-versus-manual-entry
  question. That is the right place for it; it is not the right question to answer by
  accident in a migration.
- Twelve entities is still more than a hackathon strictly needs. The trim that would
  hurt least next is `party`, but it is what the redaction demo targets, so it stays.
