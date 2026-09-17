# Ordin — build plan

> Written for a solo builder with Claude Code, ~3–4 days, no separate on-site event.
> Supersedes the slice ordering in `BOOTSTRAP.md` where the two disagree.
> Companion document: `docs/THREAT-MODEL.md`.

---

## The budget, and the one number that matters

| | hours |
|---|---|
| Usable working hours (3–4 days, solo) | ~34 |
| **Hard stop on coding** | **hour 30** |
| Committed slice work | 30 |
| Rehearsal, module briefs, submission | hours 30–34 |

**At hour 30 coding stops and rehearsal begins with whatever is green.** Not "if
things are going badly" — always. A slice that is 80% done at hour 30 is worth zero
and an unrehearsed demo on a machine that has never run the project is worth less
than zero.

These estimates carry roughly ±20%. The named flex items, in the order they give
way, are: slice 2's entity count, slice 5b's polish, slice 6a's document count.

### Why this is the whole plan and not slices 1–12

Priced honestly for one builder, **slices 1–12 as written cost 59–70 hours.** Three
independent estimates put it at 59, 61 and 69.5. The spine alone (slices 1–6) is
~37.5h — more than the entire budget, before a single differentiator lands.

That makes BOOTSTRAP's escape hatch — *"stop here if time runs out; everything below
is upside"* — not a fallback but the **predicted outcome**: every available hour spent
on the platform every competing team also builds, and none on the four things a judge
would actually remember. That directly inverts CLAUDE.md's own scope discipline:
*the base is the platform, not the deliverable.*

So this plan does not reorder twelve slices. It commits to **eight**, trimmed inside
each, and says plainly what the other four cost and why they are gone.

---

## Build order

Tier A must land or there is no product. Tier B is the pitch. Tier C exists only if
Tier A comes in under estimate — it is not planned work, it is upside.

| # | Slice | "Done" means | h | Unblocks | Tier |
|---|---|---|---|---|---|
| 1 | **Skeleton** | `up` / `down` / `test` / `fresh` all work from a clean clone on the **demo** machine; `/health` checks each dependency; Alembic baseline applies and reverses; pytest green; structured logs carry a correlation ID; **two Postgres roles exist** (owner ≠ app runtime) with separate DSNs; the guard hook actually fires | 3.5 | everything | A |
| 2 | **Domain model** | Migrations run clean both ways; seed loads 3 cases across 2 organizations; a test proves the **app role cannot UPDATE an audit row** and that test would fail if the REVOKE were removed; `CaseAssignment` carries `valid_to`; `ProcessingJob` carries an idempotency key whose derivation is written down in an ADR | 3.5 | 3, 4a, 5a | A |
| 6a | **Fixture pack** | A generator emits 8–12 fictional documents, English + at least one Hindi, `SPECIMEN — NOT A REAL RECORD` on every page, each with a ground-truth sidecar recording the exact pre-render text and the bounding boxes of every identifying field | 2.0 | 4a, 5a, 7, 11a | A |
| 3 | **Policy + query-level authorization** | Versioned YAML policies; a pure evaluator unit-tested with no app and no database running; seven dimensions; deny by default. A composable filter pushes authorization into the SQL `WHERE` clause. Tests assert a **smaller count — not a filtered page** — for list, COUNT, export, autocomplete, **single-object GET, and full-text search**. Denial tests: non-designated officer, expired grant, cross-organization read, unclearanced sealed read, and **one case where exactly one of the three validity clocks has lapsed**. `ExtractedField` values and the FTS index are **in scope for the filter**. Every decision persists the policy ID that decided it. Ships `SimulatedSubjectProvider` (see below). Opens the Sentinel scenario registry | 7.0 | 4a, 5, 7, 8 | A |
| 4a | **Integrity** | Content-addressed immutable versions behind `BlobStore`; SHA-256 over bytes **and** over canonical metadata JSON; `LocalAnchorStore`; `verify()` returns `VERIFIED \| MISMATCH \| DISPOSED_ANCHOR_ONLY \| UNAVAILABLE` **and runs through the slice 3 filter**, returning `UNAVAILABLE` indistinguishably for "does not exist" and "not yours". Acceptance: mutate bytes on disk → MISMATCH naming the diverged version; dispose → DISPOSED_ANCHOR_ONLY, never MISMATCH | 3.5 | 5a, 7 | A |
| 5a | **Golden thread, headless** | `upload → validate → version → OCR → text layer + char-offset-to-bbox map → regex extract → sign → hash → anchor`, every stage a `ProcessingJob` with an idempotency key. Anchoring separately retryable. Low OCR confidence or handwriting → `requires_manual_entry`. Acceptance: running the pipeline twice on one upload yields exactly one version, one extraction run, one field set, one anchor | 5.0 | 5b, 7 | A |
| 5b | **Verification UI (minimum)** | Case list, document view, and a verify-and-commit screen: draft fields left, scan right. A human commit is the only thing that writes `verified`. Ugly is fine | 2.5 | 7 | A |
| 7 | **Destructive redaction + role-switch** | PyMuPDF `add_redact_annot` + `apply_redactions` removes content, then rasterize; derivative is a first-class version with `derived_from_version_id`, its own `sha256` and `redaction_manifest_hash`. One document, three roles, one URL: full, redacted, expiring external grant — **the role resolved server-side from the session, never from a request parameter or header**. Acceptance: extract text from the derivative and assert the victim name is absent; **and** assert the parent version id is denied to the redacted role; **and** the Sentinel search scenario below is green | 3.0 | 8 | B |
| | | **— hard stop at hour 30 —** | **30.0** | | |
| 8 | Sentinel dashboard | The scenarios already accrued during slices 3–7, rendered on one page with id, invariant, setup, expected, actual, severity, timestamp, pass/fail | 1.5 | — | C |
| 11a | OCR accuracy table | OCR character error rate by language against the generator's pre-render text. One command, one table | 1.0 | — | C |
| 4b | Upload hardening | Content sniffing, size cap, qpdf sanitisation. Acceptance: a PDF carrying JavaScript comes out sanitised | 2.5 | — | C |
| 5b+ | Span highlighting | Clicking a verified field highlights its source span in the scan | 1.5 | — | C |
| 6b | Corpus scale-up | Generator scaled toward 40–60 documents with a light degradation pass | 1.5 | — | C |

---

## Where I would reorder BOOTSTRAP.md, and why

**R1 — Split slice 6; move the fixtures to position 3.** *Blocking dependency.*
Slices 4, 5, 7 and 11 all have acceptance tests that require documents to exist. Slice
6 does not deliver documents until after all of them. In a test-first plan the corpus
generator is the most upstream work in the project and it is scheduled sixth. Split it:
fixtures early (6a), scale-up late and optional (6b). *Three independent reviews reached
this conclusion without knowledge of each other.*

**R2 — Two Postgres roles into slice 1.** *Blocking dependency.* In a default compose,
one role both owns the schema (Alembic runs as it) and serves the application — and **a
table owner is not subject to REVOKE on its own table.** Invariant 10's audit-immutability
test would go green while proving nothing. This is a compose-and-DSN change in slice 1,
not a migration change in slice 2. Extend the same REVOKE to `AnchorRecord`, which slice 2
currently lists as an ordinary table.

**R3 — Decide the task runner before slice 1's acceptance test.** *Blocking dependency.*
`make` is not native on Windows and the demo machine is a different box. Either require
Git Bash + GNU make explicitly, or replace the Makefile with a `tasks.ps1`. Also fix the
hook's interpreter (below) and add `.gitattributes` enforcing LF.

**R4 — Split slice 4.** *Blocking dependency.* As written it bundles envelope encryption,
content-addressing, dual hashing, upload hardening, crypto-erase and four-state verify —
~7h, which breaks BOOTSTRAP's own one-window rule. Only 4a gates the golden thread. Move
`LocalAnchorStore` into 4a; slice 5 currently assumes it already exists.

**R5 — Split slice 5 and run 5a → 5b → 7.** *Strong.* Redaction needs the text layer and
bbox map from 5a; it does not need span highlighting. Keeping 5b minimal gets slice 7 —
the pitch opener — inside the budget instead of just outside it.

**R6 — Authentication does not exist anywhere in slices 1–12.** *Blocking.* All seven
dimensions are evaluated against a subject that nothing establishes. Within this budget
the honest answer is a declared stub, not a real identity provider:

> `SimulatedSubjectProvider`, `maturity: mvp`, `production_adapter` naming a real IdP.
> The subject is resolved **server-side from a signed session**, never from a request
> parameter or header. It ships with an explicit accepted risk in the threat model.

The naming matters: per CLAUDE.md's honesty rules this is never called an auth service.
Slice 7's role-switch actively pressures toward a client-side role selector, which would
silently invalidate the demo value of slices 3, 7 and 8 at once — Sentinel's
"unauthorized access" scenario would pass against a forgeable identity.

**R7 — Sentinel is a registry, not a slice.** *Structural.* Open the scenario registry in
slice 3 and have each subsequent slice contribute its own scenario as it lands (~10 min
each, already priced in). Only the dashboard page is separate work. Sentinel then cannot
be the thing that runs out of time.

**R8 — Reframe slice 9.** *Honesty.* With no LLM anywhere in the build there is no
instruction sink, so "we defeated prompt injection" is not a claim this system can make.
The honest and stronger claim is: **no code path exists from document content to a
decision, and here are the tests that prove it.** Two Sentinel scenarios, near-zero
marginal cost. Note the limit out loud: this proves the plumbing, not a future model.

**R9 — Cut slice 11's extraction metric, keep the OCR metric.** *Honesty.* Precision and
recall for regex extractors written against documents the same generator produced measure
agreement with themselves, not accuracy. OCR character error rate is different in kind:
the generator's pre-render text is genuine ground truth because Tesseract never saw it.
Keep CER, drop extraction precision/recall, and say why in the table's own caption.

**R10 — Cut slice 12 for budget.** *Not for the cryptography rule.* A Merkle tree built
on `hashlib` is composing standard primitives, which is exactly what CLAUDE.md's
non-goal permits; the rule targets implementing primitives, not using them. Slice 12 is
cut because it was priced at 6–8h and there are zero hours after the hard stop. If it is
ever built, it declares `maturity: mvp` and claims content binding only — never
unlinkability, and never that withheld-unit count and boundaries are concealed, because
by construction they are not.

**R11 — `BOOTSTRAP.md` "Finale shape" is stale.** It is written for a 36-hour on-site
event with three or four evaluator visits. That event does not exist. Following it would
misallocate the last day. Per CLAUDE.md's end-of-session rule, correct the file.

---

## Fix in slice 1: the guard hook is not running

`.claude/settings.json` invokes the hook with `python3`. On the Windows dev machine that
resolves to the Microsoft Store alias stub, which prints an install message and **exits
49, not 2** — so nothing is blocked. Verified directly.

BOOTSTRAP calls the hook *"the part that matters most in a fast build"*. That is currently
false on the dev machine. It is a one-word edit (`python3` → `python`, or an explicit
interpreter path) plus a test that a known-bad payload exits 2, which belongs in the suite
so the hook cannot silently die again.

Two known limits worth writing down rather than discovering at 3am:

- The hook's regexes read Python source. **A designation or organization condition written
  directly into a SQL `WHERE` clause is invisible to it** — and because the hook blocks the
  Python form, it actively channels the 3am shortcut into the SQL form. Slice 3's tests are
  the real control here; the hook is a backstop.
- A session-signing secret written as a compose default or a settings-class default is
  neither an environment file nor a private key, so the hook does not see it either.

---

## Cut, and why

| Cut | Why |
|---|---|
| **Slice 12, selective disclosure** | 6–8h against zero hours after the hard stop. Cut for budget alone — a Merkle tree over `hashlib` is standard composition, not custom cryptography. |
| **Slice 10, completeness engine** | 3.5h, and blocked on statutory citations CLAUDE.md forbids guessing. It also introduces a disclosure channel it does not address: a case-wide completeness flag tells a narrowly-authorized reader what the case contains without letting them read it. |
| **Slice 11's extraction precision/recall** | Structurally self-referential. Retained: OCR CER, which is genuine. |
| **Envelope encryption + crypto-erase (part of 4b)** | Protects against a stolen disk, not against anyone holding a database connection — OCR text and extracted field values sit in Postgres in plaintext either way. Keep the `KeyProvider` interface, declare the maturity, do not claim encryption at rest in the deck. |
| **Full 40–60 document corpus** | No judge sees document 13 through 60. Fixtures do the same work for tests and demo. |
| **Two-person approval, retention administration, disclosure packages, NER, any LLM, Redis, OPA, MinIO, Vault, ClamAV, Fabric, pgvector** | Already cut in BOOTSTRAP; unchanged. |

---

## Decision gates

| At | Check | If not |
|---|---|---|
| Hour 12 | Slice 3 green | Cut slice 2's entity set to the 8 the golden thread needs and re-plan. Slice 3 is the intellectual core; it does not get trimmed. |
| Hour 20 | Slice 4a green, 5a started | Cut 5b to a read-only document view and go straight to 7. The pitch opener must exist. |
| Hour 26 | Slice 7 started | Stop 5b wherever it is and start 7 now. |
| **Hour 30** | **Anything** | **Stop coding. Rehearse.** |
| — | Slice 3's search predicate cannot be made green over `ExtractedField` and the FTS index | **Full-text search comes out of the role-switch route entirely.** A search box that leaks a redacted name is worse than no search box. |

---

## Rehearsal, hours 30–34

Non-negotiable, and the reason the hard stop exists.

1. **Two full clean-machine runs on the demo machine**, from `git clone` forward, not
   from a warm Docker cache. Every failure you will have at the finale shows up on the
   second clean run.
2. `docker compose up` **pulls**, and the Dockerfiles install packages. If the venue
   network is unreliable, produce a `docker save` bundle with a checksum manifest and
   carry it. Sneakernet is the actual transfer mechanism; plan for it before you need it.
3. Module briefs in `docs/modules/NN-name.md` for whatever landed: what it does, why this
   design, the two questions a judge will ask and the answers.
4. Rehearse the opening sixty seconds — role-switch privacy demo — until it needs no
   narration.

---

## Open questions

1. **Statutory citations.** Slice 10 is cut, so nothing in this build cites a section
   number. If any statutory reference enters the UI, fixtures or deck, it needs a source
   per CLAUDE.md. Flagging now so it is not improvised at the deadline.
2. **The 1,631-case finding.** Cited in BOOTSTRAP slice 7 and carried into the pitch.
   Citation pending from the builder. Until supplied it appears nowhere — no bare number,
   per the no-fabricated-statistics rule.
3. **Idempotency key derivation.** Decides several security properties at once and will
   otherwise be decided in thirty seconds at 3am. Derived from content it collides across
   cases and leaks existence; scoped to `(case_id, upload_id)` it does not. Scoped to
   `(parent_version_id, stage)` it silently suppresses a corrected re-redaction. Write the
   ADR in slice 2, before the first job runs.
4. **Time authority.** Two plausible clocks (application and database). Pick one — the
   database boundary is cheapest and survives container clock skew — and record it in an
   ADR. A hash chain proves order, never time.
5. **Grant granularity.** If `AccessGrant` resolves to (grantee, organization) rather than
   (grantee, case, purpose, expiry), one lawful grant for one case silently opens every
   case in that organization. Unspecified in both documents today.
