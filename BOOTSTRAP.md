# Ordin — sprint plan

## START HERE

You are in the project folder. Run `claude`, then copy the block below and paste
it as your first message. That is the whole first step.

```
Read CLAUDE.md. Enter plan mode.

I'm building Ordin for the Smart India Hackathon, problem statement 26190.
I have a few days and I'm working with you rather than a team, so scope
accordingly. Produce two documents and no code yet.

docs/PLAN.md — the build order, as a table: slice, what "done" means for it,
rough hours, what it unblocks. Slices 1-6 in BOOTSTRAP.md are the spine; tell
me if you'd reorder them and why. Add a short "cut, and why" section.

docs/THREAT-MODEL.md — who might attack this system, what they'd be after, and
which part of the design stops them. Anything with no answer gets written down
as an accepted risk.

Ask me anything you need. Challenge my ordering if it's wrong.
```

Read what it gives back and argue with it. That twenty minutes is worth more
than any hour of coding later.

After that, each working session is three commands:

| When | Type | What happens |
|---|---|---|
| Starting up | `/resume` | Reads where you left off, runs the tests, tells you what's next |
| Beginning a piece of work | `/slice 1` | Plans it, writes the test first, then builds it |
| Before you stop | `/wrap` | Makes sure tests pass, commits, writes down where you got to |

**The one rule that matters:** never close a session without running `/wrap`.
If you're running out of time or usage, stop early and wrap. A session that
ends mid-thought with nothing written down costs more than it produced.

---

One builder plus Claude Code. Days, not weeks. Context resets mid-build.

Everything here is shaped around that last constraint: **state lives in files, not
in a context window.** A session that starts cold must be productive in two
minutes, and no session may end with failing tests or uncommitted work.

---

## Session protocol — read this before anything else

**Start of every session:** type `/resume`. It reads `docs/STATUS.md`, the
current slice file, and runs the test suite, then reports where things stand.
Never re-explain the project from memory.

**End of every session, without exception:**
1. All tests green.
2. Everything committed.
3. `docs/STATUS.md` updated — what got done, what is half-done and exactly where,
   what is next, anything surprising.
4. An ADR if a real decision was made.

A session that ends with "I'll finish this next time" and nothing written down
costs more than it produced. If you are running out of window, stop early and
spend the last ten minutes writing STATUS.md properly.

**Slice sizing.** Each slice below is meant to fit in one window with room to
spare. If a slice starts sprawling, split it and record the split in STATUS.md
rather than pushing through.

---

## Setup, once

Superseded by `README.md`, which is where a newcomer should start. The short version:

```bash
python tasks.py setup     # venv, dependencies, .env, fixtures
python tasks.py doctor    # says what is still missing
```

This section used to describe creating the repository and copying files into it by
hand, which was right before the project existed and misleading afterwards. A clone
rehearsal showed a newcomer following it would get nowhere.

The hook is still the part that matters most in a fast build. CLAUDE.md is context the
model drifts from when a session gets long; a PreToolUse hook is deterministic. It
blocks `Blockchain*` naming, `ESignService`, hand-rolled role conditionals, CSS-blur
redaction, committed `.env` files, private keys in source and hosted LLM keys, and it
fails closed on a malformed payload.

Two things learned about it since: it was silently dead for a whole session because
`settings.json` invoked `python3`, which on Windows is a Store alias that exits 49
rather than 2 — `tests/test_ordin_guard.py` now asserts the configured command
actually fires. And it channels the 3am shortcut rather than removing it: blocking a
role conditional in Python pushes the same condition into a SQL `WHERE` clause, where
its regexes cannot see it. Slice 3's tests are the real control there.

## What got cut, and why

Weeks became days and six builders became one, so the earlier plan is wrong in
both directions. Cut outright: OPA and Rego, Redis, MinIO, Vault, ClamAV, Fabric,
NER, any LLM, hybrid search, pgvector, disclosure packages, two-person approval,
retention administration.

Two reversals from earlier, both because the constraint changed rather than
because the earlier reasoning was wrong:

- **OPA out, in-process declarative policy in.** The invariant was never "use
  OPA" — it was that policy is versioned, testable data with logged decisions.
  That survives intact in a YAML-plus-evaluator form at a fraction of the wiring
  cost, and it declares `maturity: mvp` with OPA named as the production adapter.
- **Redis out, Postgres job queue in.** `FOR UPDATE SKIP LOCKED` is about fifteen
  lines and removes a container, a failure mode and a thing to explain.

---

## The spine — slices 1 to 6, non-negotiable

Each has one acceptance test. Write the test first.

**1. Skeleton.** Four containers, `/health` checking each dependency, Alembic
baseline, `tasks.py` (`up`, `down`, `test`, `fresh`; ADR 0007), pytest green, structured logs
with correlation IDs. *Acceptance:* `python tasks.py fresh && python tasks.py up` from a clean clone
gives a green health page.

**2. Domain model.** Organization, Jurisdiction, User, Post, Clearance, Case,
Party, CaseAssignment, Document, DocumentVersion, ProcessingJob, ExtractedField,
AccessGrant, PolicyDecision, AuditEvent, AnchorRecord. Case is a state machine.
DocumentVersion carries `lifecycle_state` and `access_class` as independent axes.
ProcessingJob carries an idempotency key. AuditEvent is hash-chained and the
migration REVOKEs UPDATE/DELETE from the app role. *Acceptance:* migrations run
clean both ways, seed loads 3 cases across 2 organizations, and a test proves the
app role cannot UPDATE an audit row.

**3. Policy and query-level authorization.** Versioned YAML policies, a pure
evaluator, seven dimensions, deny by default. A composable filter that pushes
authorization into the SQL WHERE clause. *Acceptance:* separate tests asserting a
smaller *count* — not a filtered page — for list, COUNT, export and autocomplete;
plus denial tests for non-designated officer, expired grant, cross-organization
read and unclearanced sealed read.

**4. Storage and integrity.** Envelope encryption behind `KeyProvider`,
content-addressed immutable versions, SHA-256 over bytes and over canonical
metadata JSON, upload hardening (sniffing, size cap, qpdf sanitisation, bomb
guards), crypto-erase. `verify()` returns `VERIFIED | MISMATCH |
DISPOSED_ANCHOR_ONLY | UNAVAILABLE`. *Acceptance:* mutate bytes on disk → MISMATCH
naming the diverged version; dispose → DISPOSED_ANCHOR_ONLY, not MISMATCH; a PDF
carrying JavaScript comes out sanitised.

**5. Golden thread.** `upload → validate → OCR → regex extract → human verify →
sign → hash → anchor → verify`, every stage a ProcessingJob with an idempotency
key. Verification UI: draft left, scan right, clicking a field highlights its
source span. Low OCR confidence or handwriting → `requires_manual_entry`.
Anchoring is separately retryable. *Acceptance:* a fresh scan walks the whole path
in the UI with no hand-edited row, and running the pipeline twice on one upload
yields exactly one version, one extraction run, one field set, one anchor.

**6. Synthetic corpus.** A generator producing 40–60 fictional documents, English
and Hindi, `SPECIMEN — NOT A REAL RECORD` on every page, with a light degradation
pass on a handful. *Acceptance:* one command populates a demo database from empty.

**With slices 1–6 green you have a defensible product.** Stop here if time runs
out; everything below is upside, taken strictly in order.

---

## Differentiators — in priority order, take what fits

**7. Destructive redaction + role-switch.** PyMuPDF `apply_redactions` to remove
content, then rasterize; derivative is a first-class version with
`derived_from_version_id` and `redaction_manifest_hash`. One document, three
roles, one URL: full, redacted, expiring external grant. *Acceptance:* extract
text from the derivative and assert the victim name is absent. **This is the
single highest-value slice after the spine** — it is the demo that opens your
pitch and it maps straight onto the 1,631-case finding.

**8. Ordin Sentinel.** Six scenarios minimum: unauthorized access,
cross-organization read, sealed record, tampering, duplicate processing,
redaction leakage. Each records id, invariant, setup, expected, actual, severity,
timestamp, pass/fail. One dashboard page. Cheap, and it converts every security
claim from an assertion into a green tick a judge can watch turn red.

**9. Prompt-injection suite.** A document whose OCR text contains
instruction-shaped content; assert it cannot trigger a tool call, change workflow
state or influence an authz decision. Two hours, and near-zero competing teams
will have it.

**10. Completeness engine.** YAML rule packs against case state, each rule
carrying `basis_type: statutory | procedural` and citing its basis and triggering
fact. Flags, never blocks. One case type, five or six rules.

**11. Mini evaluation table.** OCR CER on the corpus by language, regex extraction
precision/recall against generated ground truth (the generator knows the right
answers, so ground truth is free), stage latency p50/p95. One command, one table.

**12. Selective disclosure.** Salted Merkle commitments over disclosable units so
a redacted copy still verifies against the anchor. The strongest idea in the
design and the most likely to eat a day without landing. Self-contained and
highly testable, which suits Claude Code well — but it goes last, and it is
droppable without apology.

---

## Module briefs — for the other five

As each slice lands, write `docs/modules/NN-name.md`: one page, what it does, why
this design, the two questions a judge will ask and the answers. Six briefs by
the end. That is what makes the system teachable in an evening rather than
resident only in your head.

---

## Finale shape

**There is no separate 36-hour on-site event.** The build is ~34 usable hours, solo,
across three to four days, and it ends at a submission rather than at a bench where
evaluators visit repeatedly. Plan accordingly: there is no "ship a visible increment
between visits" rhythm to exploit, and no second chance to correct a first impression.

**Coding stops at hour 30.** See `docs/PLAN.md` for the build order and the decision
gates leading up to it. A slice that is eighty percent done at hour 30 is worth zero;
the last four hours are worth more spent on rehearsal than on one more feature.

**The demo machine is not the dev machine.** Everything is rehearsed on the machine
that will actually be used, from a clean clone, twice. Every failure you will have
shows up on the second clean run. Note that bringing the stack up *pulls* images and
installs packages — if the network cannot be relied on, carry a saved image bundle
with a checksum manifest rather than discovering the problem live.

Open with sixty seconds of demo, not slides: the role-switch privacy demo first, then
the tamper test, then Sentinel going red and green. Rehearse the opening until it
needs no narration.
