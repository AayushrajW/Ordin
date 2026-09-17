# Ordin

Case-centric evidence intelligence for Indian legal & investigation agencies.
SIH 2026, Problem Statement 26190 (MHA / NCRB Women Safety Division). Team Valora.

**The product is the case record, not the document store.** A document only has
meaning as evidence that a statutory transition in a case legitimately occurred.
Anything that treats this as a generic DMS with hashing bolted on is off-thesis.

---

## Non-goals

Ordin does not replace courts, police registries or official filing systems; does
not give legal advice; does not decide guilt, liability or outcomes; never lets an
LLM make a final statutory, access, retention or completeness decision; never puts
document contents or PII on a public ledger; and **never implements custom
cryptography** — use established libraries only.

---

## Cost and hardware constraints — hard limits

Built by students for a hackathon. These are not preferences.

- **Everything is free.** No paid APIs, no cloud accounts, no trial credits, no
  expiring licence. If it needs a credit card, it is out.
- **Everything runs offline** on one 8 GB laptop from `docker compose up`.
  Budget: four containers.
- **No component may need a multi-gigabyte model or signature download** to
  function. Anything that does goes behind an interface with a maturity-declaring
  stub.
- Licences must permit public source and hackathon submission — prefer
  Apache-2.0, MIT, BSD; flag anything AGPL or source-available before adding it.
- Between elegant-and-heavy and plain-and-light, take plain. A component that
  will not start on a judge's machine has negative value.

---

## Security invariants — never violate these

1. **Authorization predicates are applied inside the data query, never after** —
   before scoring, ranking, pagination, aggregation, COUNT, export, autocomplete
   and embedding retrieval. Post-filtering leaks through result counts, page
   behaviour and suggestion lists. Autocomplete is the worst offender: three
   letters must never surface a name from an unauthorised case.
2. **Deny by default, fail closed.** An authorization error, an evaluator error or an
   unmatched rule denies. Never degrade open.
3. **Authorization is declarative data, not code.** Versioned policy files,
   unit-tested without the app running; every decision logs the policy ID that
   decided it. Hand-rolled `if user.role == "supervisor"` is forbidden anywhere.
4. **No PII on the ledger. Ever.** A transaction carries exactly:
   `case_id, doc_id, version, sha256, actor_id, action, utc_ts`.
5. **Integrity verification returns a state, never a boolean:**
   `VERIFIED | MISMATCH | DISPOSED_ANCHOR_ONLY | PENDING | UNAVAILABLE`. A lawfully
   disposed document is not a tampered one — reporting MISMATCH for it is both a
   correctness bug and a legal misrepresentation. By the same reasoning a document
   awaiting its anchor is not a missing one: `PENDING` exists so that the normal
   transient state does not collapse into `UNAVAILABLE`, which already means the
   bytes are gone, the store is unreachable, or the caller may not see it at all.
   (Amended in `docs/adr/0010`; the original invariant named four states.)
6. **OCR and extracted text are untrusted data, never instructions.** Document
   content never enters a prompt, triggers a tool call, changes workflow state,
   or influences a completeness or authz decision.
7. **Every AI-derived field carries** `source_span` (char offsets into the OCR
   text), `confidence`, `source` (regex|ner|llm|human), `provider`, `model` and
   `prompt_version`. No span means the field is rejected at the schema boundary.
8. **Redaction is destructive** — a derivative with regions burned into the
   raster and the text layer stripped. Never CSS blur, opacity or client-side
   masking. Unauthorised roles never receive original bytes on any code path.
9. **AI output is always `status=draft`.** Only an explicit human commit
   transitions a field to `verified`. No pipeline stage may write `verified`.
10. **Audit rows are append-only and hash-chained** (`prev_row_hash`); the app DB
    role has no UPDATE or DELETE grant on audit tables, enforced in the migration.
11. **No external network calls on the demo path** — the pipeline runs with
    networking disabled.
12. **Never log** document content, victim/witness identifiers, keys or raw OCR
    text. Log IDs and decisions only.

---

## Reliability invariants

- **Every processing stage is idempotent and carries an idempotency key.** A
  retry must not produce a second ExtractedField, version, anchor or derivative.
  This is a test, not an intention.
- **Originals are never overwritten or mutated.** Versions are append-only.
- **An anchor outage never corrupts case state.** Anchoring is a separate
  retryable stage; a case with a pending anchor is valid.
- **Core workflows function with no LLM available.** Deterministic extraction
  plus manual entry is a complete path, not a degraded one.
- Every stage records status, provider, maturity, timestamps, errors, retry
  count, input version and output reference.

---

## Authorization model

Seven dimensions. Roles grant capabilities; they are not the model.

```
identity/post x organization x jurisdiction x case designation
              x clearance x purpose x time-bounded grant
```

- **Organization** (police department, prosecution, court) and **jurisdiction**
  (geographic) are separate. Cross-organization access always requires an
  explicit, purpose-limited, expiring grant — never a role.
- **Case designation** is decisive. Seniority does not imply access to a case you
  are not assigned to.
- **Sealed records** require authorization beyond ordinary clearance.
- Purpose and expiry are re-checked server-side on every request.

---

## Document lifecycle

Two independent axes — a document can be sealed *and* superseded.

```
lifecycle_state:  active | superseded | disposed
access_class:     normal | sealed
```

`active` compares live bytes to the anchor; `superseded` verifies the historical
version; `disposed` verifies anchor and disposition record only, returning
`DISPOSED_ANCHOR_ONLY`. A redacted derivative is a first-class version carrying
`derived_from_version_id`, its own `sha256` and `redaction_manifest_hash`.

---

## Honesty rules — these carry from the pitch deck

- **Never name a stand-in after the real thing.** The soft PKCS#11 signer is
  `SimulatedESignProvider`, not `ESignService`.
- **The local hash-chain is not a blockchain.** Class name `LocalAnchorStore`;
  only the Fabric adapter may use ledger or chain vocabulary.
- **Every provider declares `maturity`**: `mvp | hardened | production`, with a
  `production_adapter` naming its replacement. Never hide a stub behind
  plausible-looking output.
- **No fabricated statistics, compliance claims or certifications** anywhere,
  fixtures and UI copy included. Standards are "aligned to", never "certified".
- **Synthetic corpus is visibly synthetic**: fictional names and station codes,
  `SPECIMEN — NOT A REAL RECORD` on every generated page.
- Seed data is fine; **a screen that does not execute the real code path is not.**

---

## Stack — decided, do not re-litigate

**Four containers.** postgres 16 · api (FastAPI, Python 3.11) · worker · web
(Next.js + TypeScript + Tailwind). No Redis: the job queue is a Postgres table
with `FOR UPDATE SKIP LOCKED`, which is fewer moving parts and one less thing to
explain at 3am.

- **Policy is declarative data evaluated in-process** — versioned YAML policy
  files, a small pure evaluator, `pytest` over policies with no app running, and
  every decision persisted with the policy ID that decided it. Declares
  `maturity: mvp`, `production_adapter: OPA`. This is a deliberate downgrade
  from OPA for a days-long build: the invariant is that policy is versioned
  testable data, and that survives. Rego debugging at 2am does not.
- **Blob storage is the local filesystem** behind a `BlobStore` interface.
- **OCR is Tesseract 5 with `hin+eng`**, three preprocessing steps only: deskew,
  Sauvola binarize, DPI normalise. No engine comparison, no tuning rabbit hole.
- **Redaction is PyMuPDF** `add_redact_annot` + `apply_redactions`, which removes
  the underlying content rather than covering it, then rasterize. AGPL — fine for
  a public hackathon submission; note it in the dependency ADR.
- **Interfaces with local implementations first:** `BlobStore`, `KeyProvider`,
  `LedgerAdapter` (`LocalAnchorStore` / `FabricLedger` stub), `SignatureProvider`
  (`SimulatedESignProvider`), `MalwareScanner` (stub).
- **Not in this build at all:** Redis · OPA · MinIO · Vault · ClamAV · Fabric ·
  pgvector · any LLM · OpenSearch · NER · hybrid search · retention
  administration. Postgres full-text search is the retrieval path.
- SQLAlchemy 2.0 async + Alembic. **The domain layer imports no framework** — no
  FastAPI, SQLAlchemy or provider SDKs below the service boundary, and no
  business rules in controllers.

---

## Conventions

- **Write the acceptance test before the implementation.** A slice is done when
  its test is green and committed.
- Pydantic v2 at every edge; no dicts crossing module boundaries. Migrations
  immutable once committed. Conventional commits, small, at each green test.
- Every architecture decision in `docs/adr/NNNN-title.md` (~15 lines).
- **Do not add a dependency without asking.** State purpose, licence, RAM cost,
  alternative considered, and production replacement path.

---

## Scope discipline

- Build **the golden thread** first, end to end and ugly:
  `upload -> OCR -> extract -> human verify -> sign -> hash -> anchor -> verify`.
- **The base is the platform, not the deliverable.** It is what every competing
  team also builds. Time budgeted for the differentiating slices is protected —
  never spent polishing the base or building administration screens.
- Deterministic extraction over ML, ML over LLM. The LLM is last, for the
  unstructured residue only.
- If a task needs more than one session, stop and write a plan file first.

---

## Working with me

- Plan mode for anything touching authz, crypto or the ledger. Wait for approval.
- On any ambiguity in legal or statutory behaviour, **ask** — never guess section
  numbers or deadline periods. Every statutory reference cites a source in a comment.
- End of session: summarise what changed, and update this file if a decision here
  is now wrong.
