# Ordin — status

> Rewritten at the end of every session via `/wrap`. Written for a reader with
> no memory of any prior conversation.

## Current slice
None. Planning is complete; no code exists yet. Next action is **slice 1 (Skeleton)**.

## Acceptance criterion for current slice
From `docs/PLAN.md`, slice 1 (~3.5h): `up` / `down` / `test` / `fresh` all work from a
clean clone **on the demo machine**; `/health` checks each dependency; the Alembic
baseline applies and reverses; pytest green; structured logs carry a correlation ID;
**two Postgres roles exist** (owner != app runtime) with separate DSNs per
`docs/adr/0001`; and the guard hook actually fires, with a test asserting a known-bad
payload exits 2. No business logic.

## Test suite state
**There is no test suite yet, and no Makefile — slice 1 creates both.** `make` is also
not installed on this Windows dev machine, which is why PLAN R3 makes the task-runner
choice a slice 1 deliverable rather than an assumption.

What does exist and passes: the guard hook blocks a bad write (exit 2), allows a normal
command (exit 0), and fails closed on a malformed payload (exit 2); `ordin-guard.py`
compiles; `settings.json` is valid JSON.

## Landed this session
- `docs/PLAN.md` — 8-slice build order summing to exactly 30h, reorderings R1-R11,
  cuts, four decision gates, hour-30 hard stop, rehearsal plan.
- `docs/THREAT-MODEL.md` — 8 attacker classes (~60 threats), invariant coverage pass,
  12 seam threats, 18 accepted risks.
- `docs/adr/0001-two-postgres-roles.md`, `0002-simulated-subject-provider.md`,
  `0003-selective-disclosure-deferred.md`.
- Repository initialised; everything committed.

No application code. No dependencies added.

## Half-done, and exactly where
Nothing. No file is partially written and no code path is partially implemented.

## Next concrete action
Run `/slice 1`. Before writing any code, decide open question 1 (idempotency key
derivation) and write its ADR — it is cheap now and expensive after the first job runs.

## Open questions
1. **Idempotency key derivation.** Content-derived collides across cases and leaks
   existence (INS-06); `(case_id, upload_id)` does not; `(parent_version_id, stage)`
   silently suppresses a corrected re-redaction (seam 2). ADR required in slice 2.
2. **Grant granularity.** If `AccessGrant` resolves to (grantee, organization) rather
   than (grantee, case, purpose, expiry), one lawful grant opens every case in that
   organization (AZM-07). Unspecified in CLAUDE.md and BOOTSTRAP.md.
3. **Time authority.** Application clock or database clock. Pick one — the database
   boundary is cheapest and survives container clock skew — and write the ADR.
4. **Is a redacted derivative itself processed** by the pipeline? It is a first-class
   version, so it may be OCR'd, extracted, indexed and anchored, producing a second
   field set derived from redacted content (seam 11).
5. **Invariant 7 vs manual entry.** Manual entry produces a field with no `source_span`
   by construction, which is exactly what invariant 7 says must be rejected at the
   schema boundary. Resolve before slice 5a.
6. **The 1,631-case finding** cited in BOOTSTRAP slice 7 — citation pending from the
   builder. Until supplied it appears in no document, deck or fixture.
7. **Statutory citations.** Slice 10 is cut, so nothing in this build cites a section
   number. If one enters the UI, fixtures or deck it needs a source.
8. Team ID for the SIH submission still unknown (slide 1 placeholder).

## Surprising, and worth not rediscovering
- **The guard hook was not running.** `.claude/settings.json` invokes `python3`, which
  on this Windows machine is the Microsoft Store alias stub: it exits 49, not 2, so
  nothing was blocked. Still unfixed — it is a slice 1 item (one word, plus a test so
  it cannot silently die again). Run the hook with `python`, not `python3`, until then.
- **Invariant 10 can be void while its test passes.** A table owner is not subject to
  REVOKE on its own table, so a single-role compose yields a green audit-immutability
  test that proves nothing. See `docs/adr/0001`.
- **Slices 1-12 as written price at 59-70 hours** against ~34 available (three
  independent estimates). The plan commits to eight trimmed slices, not twelve.
- **The guard hook channels the 3am shortcut.** It blocks a hand-rolled role comparison
  in Python, so the fastest remaining fix is the same condition written directly into a
  SQL WHERE clause, which its regexes cannot see. Slice 3's tests are the real control.
- `BOOTSTRAP.md`'s "Finale shape" section assumes a 36-hour on-site event with evaluator
  visits. That event does not exist; the section is stale (PLAN R11) and has not been
  corrected yet.

## Slices completed
- [ ] 1 Skeleton
- [ ] 2 Domain model
- [ ] 6a Fixture pack
- [ ] 3 Policy + query-level authz
- [ ] 4a Integrity
- [ ] 5a Golden thread, headless
- [ ] 5b Verification UI (minimum)
- [ ] 7 Destructive redaction + role-switch
- [ ] ——— hard stop at hour 30 ———
- [ ] 8 Sentinel dashboard (Tier C)
- [ ] 11a OCR accuracy table (Tier C)
- [ ] 4b Upload hardening (Tier C)
- [ ] 6b Corpus scale-up (Tier C)

Cut: 10 (completeness engine), 11's extraction metric, 12 (selective disclosure).
