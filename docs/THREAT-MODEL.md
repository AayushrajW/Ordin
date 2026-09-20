# Ordin — threat model

> Models Ordin **as if deployed** in a police department, with every control annotated
> for the maturity it actually has in this build. A control marked `mvp` works and is
> not production-grade; a control marked `none` does not exist and the threat appears
> in [Accepted risks](#accepted-risks).
>
> Companion document: `docs/PLAN.md`. Slice numbers refer to that plan, not to
> `BOOTSTRAP.md`.

---

## Scope

**In scope.** The deployed system: four containers, the documents and case records they
hold, the seven-dimension authorization model, the integrity and anchoring machinery,
the redaction pipeline, and the people who legitimately hold accounts.

**Out of scope.** Physical security of a police station; coercion of an officer;
compromise of a judge's or counsel's own device; the correctness of Indian statutory
procedure itself. Ordin does not replace courts, registries or filing systems, does not
give legal advice, and does not decide guilt or outcomes.

**What this document is not.** It is not a claim of compliance or certification. Ordin
is *aligned to* practices; it is certified against nothing. Where a control is a stub,
this document names the stub.

### Maturity vocabulary

| | meaning |
|---|---|
| `production` | Would survive a real deployment as built. |
| `hardened` | Real control, real tests, known gaps documented. |
| `mvp` | Works, proves the design, not production-grade. Names its `production_adapter`. |
| `none` | Does not exist in this build. Appears in Accepted risks. |

---

## Assets, in priority order

The problem statement comes from a Women Safety Division. That orders this list, and the
order is not decorative — it decides which residual risks are tolerable.

1. **Victim and witness identity.** Name, address, phone, relationships, and anything
   that re-identifies: a father's or husband's name, a station code plus a date, a
   photograph of an identity card. Disclosure here is not a data-protection incident,
   it is a physical-safety incident.
2. **Sealed material.** Judicially restricted content, where unauthorized disclosure has
   direct legal consequence.
3. **Evidential integrity.** The ability to demonstrate that a document is the document
   that was filed, unaltered, and that the custody record is complete.
4. **Case existence and activity.** That a case exists, involves a named person, or is
   being actively worked, is itself sensitive — often more so than its contents.
5. **Availability of the record.** A case record that cannot be produced is a case that
   cannot be prosecuted.

---

## Trust boundaries

```
     Officer's browser            ← untrusted device, trusted-ish session
  ─────────┬────────────
     web (Next.js)                ← renders; enforces nothing
  ─────────┼────────────  ◄══ THE boundary. Everything below re-decides.
     api (FastAPI)                ← subject resolved here; policy evaluated here
  ─────────┼────────────
     worker                       ← NO SUBJECT. Full blob + DB access. See CD-01.
  ─────────┼────────────
     postgres  ·  BlobStore       ← one host, one admin, one trust domain
```

Two properties of this diagram carry most of the risk.

**The worker sits outside the authorization model entirely.** It must: it decrypts every
original in order to OCR it. The seven dimensions do not apply to the single most
privileged component in the system.

**Everything below the API boundary shares one trust domain.** The database, the blobs,
the anchor store, the policy files, the signing key and the clock are all under one
administrative authority on one host. Every control against a privileged insider is
therefore *detective at best*, and several are not even that.

---

## 1. The authorized insider

An officer, clerk or prosecutor with a legitimate account. The highest-likelihood class
by a wide margin, and the one the authorization model is built for.

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **INS-01** | Non-designated officer → read a case they are curious about | Direct `GET` on a case or document id obtained from a colleague, a printed FIR number, or sequential guessing | Designation is decisive and seniority does not imply access; the predicate joins `CaseAssignment` inside the query so the row is never fetched · `mvp` · 3 | A hand-written detail endpoint that fetches by primary key bypasses the composable filter. The filter is opt-in per query, not enforced by the ORM. **PLAN adds single-object GET to slice 3's acceptance tests.** |
| **INS-02** | Records clerk → confirm a named person appears somewhere in the system | Three letters into party autocomplete; repeat to binary-search a spelling. No case is ever opened, so nothing looks like access | Invariant 1 names autocomplete explicitly; the suggestion query itself joins designation and grant · `mvp` · 3 | Scoping is per case, not per party. An insider designated on one case still gets autocomplete over every party attached to it — co-victims, minors, unrelated witnesses. Ordin has no party-level sensitivity dimension. |
| **INS-03** | Any authenticated officer → learn how many cases match a filter they cannot open | Read a result count, last-page number or export row count; diff against a control query | Predicate applied before aggregation, COUNT, pagination and export · `mvp` · 3 | Covers the surfaces built in slice 3. Any *later* aggregate — a Sentinel summary, an accuracy table, a health metric — is a fresh count written outside the filter and re-opens the oracle. |
| **INS-04** | Prosecutor's clerk → confirm a document exists and its lifecycle state | Call `verify()` over guessed ids. The four-state return is itself a rich oracle: it distinguishes a real document from a nonexistent one | **PLAN routes `verify()` through the slice 3 filter and returns `UNAVAILABLE` indistinguishably for "does not exist" and "not yours"** · `mvp` · 4a | Costs operational clarity: a genuinely missing blob and a forbidden one become indistinguishable to a legitimate user too. Accepted deliberately. |
| **INS-05** | Officer holding a copy from outside Ordin → prove it was filed, in which case, by whom | Hash their copy, look it up against the anchor store | Anchor reads authorized like any other case data · `mvp` · 4a | A digest over whole-document bytes is a confirmation oracle *by construction*. Anyone who can submit a hash and learn whether it anchors gets a yes/no on known plaintext. Salting would break offline third-party verification — a genuine design tension, not an oversight. See [AR-4](#accepted-risks). |
| **INS-06** | Insider with a copy and an account on any case → same confirmation, via the write path | Upload into their own sandbox case; if the blob address or idempotency key derives from content, the system dedupes, returns an existing version, or completes suspiciously fast | Idempotency key scoped to `(case_id, upload_id)`, not to content · `mvp` · 2 | Timing alone can still leak even with uniform responses. The ADR required in slice 2 exists for this. |
| **INS-09** | Officer who can assign officers to cases → read a case while leaving a routine-looking record | Designate themselves, read, un-designate. Designation is decisive, so this is completely lawful at every instant | `CaseAssignment` is append-only with `valid_to` compared against now() in the filter, so the cycle stays permanently visible · `mvp` · 2 | **Detective only.** Converts the strongest control into a self-service grant. Prevention needs two-person approval, cut project-wide. |
| **INS-11** | Officer designated on a sealed case, without sealed clearance → read sealed substance | `access_class` protects the version row; the same content is reachable as extracted field values, OCR text, a search snippet or a page preview | **PLAN puts extracted field values and the FTS index in scope for the slice 3 filter** · `mvp` · 3 | Sealing is labelled on the document version, but ordered judicially at case or party level. A correct design seals by join from the case; the version flag should narrow, not be the sole locus. |
| **INS-12** | Transferred officer, still employed → keep reading old cases | Do nothing. Assignments persist; no de-assignment ever happens | `valid_to` on `CaseAssignment` makes revocation a data change · `mvp` · 2 | No administration screen sets it. The capability exists; the process does not. |
| **INS-13** | Suspended officer, account disabled ten minutes ago → exfiltrate before the session dies | Keep using the issued session | Purpose and expiry re-checked server-side each request · `mvp` · 3 | "Re-checked every request" is stated for purpose and expiry only — **not** for designation, clearance, post or account status, and no slice builds account suspension. |
| **INS-14** | External prosecutor with a valid grant → browse the same case for an unrelated reason | Present the grant, declare the same purpose, read beyond what the purpose needed | Purpose bound to a grant, logged with the deciding policy version, expiring · `mvp` · 3 | **No preventive control exists and none can.** Ordin cannot distinguish a truthful purpose from a false one. See [AR-2](#accepted-risks). |

---

## 2. The privileged insider

A DBA, a sysadmin, or anyone holding the host. **This is the class the design protects
against least, and the honesty of the whole project rests on saying so.**

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **PRV-01** | DBA → bulk-read every identity across every organization | Open a database shell and select from the party, case and extracted-field tables. The authorization model lives in the application and is simply absent here | `none` | Complete confidentiality loss including sealed records and cross-organization data that would otherwise need an expiring grant. |
| **PRV-02** | DBA → recover document text without touching encrypted blobs | Blob encryption protects the filesystem; OCR output, extracted field values and the search index are plaintext columns | `none` | State it precisely in the deck: *blobs are encrypted at rest*, never *documents are encrypted*. |
| **PRV-03** | Host shell → read the unredacted original whose derivative is all a role may see | Copy the original's blob straight off the filesystem | `none` · (7 controls what the app serves) | Redaction governs what the application serves, not what exists. Against a host-level actor the original is one filesystem read away. |
| **PRV-06** | DBA → edit the record of their own access so the log stays internally consistent | The chain is an unkeyed digest over the previous row hash. Anyone who can write the table can edit a row and recompute every subsequent hash | Hash chain makes the log tamper-**evident** · `mvp` · 2 | No keyed MAC held off-host, no published head, no external witness. **A chain whose head nobody has seen is a chain you can recompute.** |
| **PRV-07** | DBA → erase the recent past wholesale | Delete the last N audit rows. No recomputation needed: the remaining prefix is still a valid chain | `none` | Tail truncation is undetectable without an externally witnessed head. Cheapest partial fix within scope: periodically externalise the head hash out of band. |
| **PRV-08** | DBA → restore the write access the migration removed | Grant it back, or connect as owner and skip the app role | Two roles, REVOKE in migration · `mvp` · 1, 2 | Owner and superuser are unaffected **by design** — a grant cannot restrain the principal that issues grants. No runtime grant-drift check. |
| **PRV-09** | DBA → change case state, seal class, assignments or field values with no audit trail | Every audit row is written by the application as a side effect of an application action. A direct database write produces none | `none` | **The single most important honest caveat in the design: the hash chain makes the audit log tamper-evident; it does not make the database tamper-evident.** |
| **PRV-10** | DBA → make doctored bytes verify as authentic | The anchor store is a table in the same database. Alter the blob, recompute both digests, update the anchor row | `mvp` · 4a | An anchor under the same administrative control as the artifact it anchors provides **no independent attestation**. Only an external ledger or offsite witness closes this. |

---

## 3. The external network attacker

No account. **Note that the highest-severity entry here is an absence, not a bug:
nothing in `BOOTSTRAP.md` slices 1–12 builds authentication.**

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **EXT-01** | Anyone reaching the API port → read case records with no credential | No authentication slice exists. Slice 3 evaluates seven dimensions over a subject that nothing establishes | **PLAN adds `SimulatedSubjectProvider`, subject resolved server-side from a signed session** · `mvp` · 3 | Declared stub, not an identity provider. Names its `production_adapter`. See [AR-1](#accepted-risks). |
| **EXT-02** | A judge or passerby at the demo → flip to the full-access role and read the unredacted original | Slice 7 is "one document, three roles, one URL". The fast build is a client-side selector sending a role parameter or header the API trusts | **PLAN forbids this explicitly: the role is resolved server-side from the session** · `mvp` · 7 | If built the fast way it silently invalidates slices 3, 7 and 8 at once — Sentinel's unauthorized-access scenario would pass against a forgeable identity. This is the highest-probability real defect in the build. |
| **EXT-03** | Reader of the public submission repo → log in as a seeded supervisor | Slice 2 seeds users across two organizations; seed credentials ship in a public repo | `none` | Seed credentials are indistinguishable from demo data to both the guard hook and a reviewer. Nothing forces demo-time rotation. |
| **EXT-04** | Anyone who finds the login → brute-force an account | No rate limiting, lockout, backoff or CAPTCHA. Removing Redis removed the usual counter store | `none` | A database-backed attempt counter is about the same fifteen lines as the job queue. **Binding published ports to localhost is the higher-value ten seconds** and removes venue-LAN exposure for free. |
| **EXT-05** | Defence-side contractor → enumerate which officers hold accounts | A login that looks the user up and only then verifies a password returns distinguishably, or measurably faster, on a miss | `none` | Uniform response and a constant-time miss branch are both cheap and unowned. |
| **EXT-06** | Unauthenticated party → bypass gating that exists only in the web tier | Read the Next.js bundle, call the API directly | Authorization is enforced at the API, never in the renderer · `mvp` · 3 | Slice 3's tests must cover single-object GET, download, job status, verify and every slice-7 derivative route — not only the four surfaces BOOTSTRAP names. |
| **EXT-07** | Operator of a page an officer visits → read authenticated API responses cross-origin | The two containers are a cross-origin pair, and the fastest 2am fix is a permissive cross-origin policy | `none` | A one-line misconfiguration with a one-line fix that neither the plan nor the guard hook catches. |
| **EXT-08** | Same → drive state-changing actions as that officer | Cookie session plus JSON writes with no anti-forgery token or origin check | `none` | Relaxing the cookie's same-site attribute — a common fix when the two containers stop talking — removes the default protection. |

---

## 4. The document as a malicious input

Anyone who can get a file into intake: a complainant, an accused's counsel, an anonymous
tipster, a forensic lab forwarding a device export.

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **DOC-01** | Submitter → execute code in the reviewing officer's PDF viewer | PDF carrying an open-action, additional-action, embedded script, launch or remote-go-to entry. Nothing server-side runs it; the officer's viewer might | qpdf sanitisation · `mvp` · 4b (Tier C) | Sanitisation is a key-removal allowlist against a format that keeps inventing places to put actions. **4b is Tier C — if it does not land, hostile PDFs are served as-is.** |
| **DOC-02** | Submitter → smuggle an executable past the evidence pipeline | Embedded file or file-attachment annotation. The OCR path never touches embedded streams | `none` (scanner is a declared stub) | Zero malware detection in this build. Embedded content survives into the full-access view even after redaction produces a clean raster. |
| **DOC-03** | Submitter → confirm a case exists and learn when an officer opened it | A remote reference in the document that fires on render in the officer's browser | `mvp` · 11 covers the pipeline only | **Invariant 11 covers the pipeline, not the browser.** No strict content-security policy on document rendering is specified anywhere. |
| **DOC-04** | Submitter → take the worker offline during evaluation | Decompression bomb: small file, thousands-to-one expansion | Size cap and bomb guards · `mvp` · 4b (Tier C) | "Bomb guards" is a phrase in a slice bullet, not a designed control. Streaming-aware decode ceilings are hard to enforce from Python. |
| **DOC-05** | Submitter → exhaust worker memory | Pixel bomb: a few hundred KB on disk, ~10 GB decoded. Tesseract imposes no dimension cap | `none` | A legitimate 600 DPI A3 colour scan is ~100 MP, so the ceiling must sit above real evidence and below the bomb. **On an 8 GB host the OOM killer selects by size and takes Postgres** — where the chain, the queue and the case record live. |
| **DOC-06** | Submitter with a plausible reason to file a large document → monopolise the single worker | A 20,000-page PDF. No bomb, no malformation — just arithmetic | `none` | A page cap is a policy decision with legal consequence: rejecting a genuine 900-page charge sheet is a correctness failure of the product. |
| **DOC-07** | Submitter → permanently disable processing with one upload | Poison pill: the worker crashes mid-parse, the row lock releases, the job retries, it crashes again | Retry count recorded per stage · `mvp` · 5a | Retry count is a *record*, not a *limit*, unless a maximum is enforced. Increment the attempt **before** parsing, not after. |
| **DOC-10** | Attacker with a memory-safety exploit for the PDF or image stack → code execution in the worker | Heap corruption in a C parser reached by a crafted file | `none` | Worker compromise yields every blob in the store — a cross-organization breach that query-level authorization does not touch, because the worker never passes through it. **Highest-impact document-borne threat.** |

### On "prompt injection"

`CLAUDE.md` invariant 6 holds **absolutely** here, for an unusual reason: there is no LLM
anywhere in this build, so there is no instruction sink. Document content cannot reach a
prompt because no prompt exists.

The honest claim is therefore **not** "we defeated prompt injection". It is: *no code
path exists from document content to a decision, and these tests prove it.* Two Sentinel
scenarios assert it. This proves the plumbing, not a future model — every threat in this
class returns the moment a model is added.

There are, however, three real interpreters that untrusted document text does reach, and
invariant 6 does not name them: the **browser** rendering an OCR span; the **search
index**; and the **error path**, where raw parser output can carry document content into
a stored field and back out over the API.

---

## 5. The evidence-integrity and legal adversary

Defence counsel, an opposing party, or an insider making evidence inadmissible. **This
class is won or lost on honest labelling, not on controls.**

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **EVD-01** | Insider with app credentials → alter bytes and still verify | The audit REVOKE covers audit tables; the anchor table is listed as ordinary | **PLAN extends the REVOKE to the anchor table** · `mvp` · 2 | Owner and superuser remain unaffected. See PRV-10. |
| **EVD-03** | Defence counsel cross-examining the custodian — **no technical attack required** | The anchor store, blobs, chain, policy decisions and clock all sit inside one host under one authority. The party asserting integrity is the party that controls every input to the assertion | `none` | **The independent-witness property is absent and cannot be added under "no external network on the demo path".** This is the most important entry in the document. State it in the pitch before a judge states it for you. |
| **EVD-04** | Insider needing a document to predate a deadline → backdate a version or anchor | Timestamps come from the host clock. Stop the stack, set the clock back, upload, anchor, restore | Non-decreasing timestamp check on chain append · `mvp` · 2 | Turns naive backdating into "either tampered or the clock moved", which is weaker than it sounds but much better than nothing. |
| **EVD-05** | Defence expert → have every timestamp discounted | **A hash chain proves order, not time.** The only honest assertion is "row B was appended after row A" | `mvp` · 4a | Any absolute time claim rests on the host clock. Say so on the verification result and on any exported certificate. |
| **EVD-07** | Anyone reading the deck or a generated PDF → mistake a simulated signature for a real one | The signer is a soft key on the same host. No certificate, no hardware token, no binding to a natural person | `SimulatedESignProvider`, naming enforced at the code boundary · `mvp` · 5a | **Naming is enforced in code; UI copy and generated PDF content are not covered by the hook.** The signature block a viewer actually sees is where this claim gets overstated. |
| **EVD-08** | Insider who can run the worker → mint a signature attributed to an officer who never saw the document | The signing key is on the host and gated by no per-user secret | `none` | **Non-repudiation is entirely absent** and needs per-officer keys in hardware. Ordin records an attribution, never a proof of authorship. |
| **EVD-09** | Insider → detach a genuine signature and re-attach it elsewhere | If the signed payload is the digest alone — and "sign → hash → anchor" invites exactly that — the signature binds to nothing | Sign over a structure binding digest, version, case and actor · `mvp` · 5a | Binding prevents replay; it does not create attribution. EVD-08 still stands. |
| **EVD-10** | Insider → bury an inculpatory page rather than alter it | Upload a benign replacement; the original goes superseded and still verifies perfectly; the case view shows the new one | Versions append-only · `hardened` · 4a | **Append-only protects bytes and does nothing for what anyone reads.** Burial works until every document reference in the UI and in exports carries a version id and a supersession marker. |

---

## 6. Victim and witness re-identification

The class that matters most to the sponsor, and the one where the headline demo is most
likely to be defeated.

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **VIC-01** | Redacted-derivative role → recover the removed name **without touching the PDF** | The unredacted OCR text still sits in Postgres as the search path and the source of span offsets. Hit the text endpoint, the field-detail payload, or just search | **PLAN puts extracted field values and the FTS index in scope for the slice 3 filter, with a Sentinel scenario asserting zero hits** · `mvp` · 3, 7 | **Was the most likely real leak in the built system.** Redaction is modelled as a *new version*; the original's derived text has no redaction state at all. If the scenario cannot go green, **search comes out of the role-switch route entirely.** |
| **VIC-02** | Any recipient → read a name `apply_redactions` never removed | The corpus is scanned FIRs — each page is one large image, so every redaction is an *image* redaction, not a text redaction | Rasterize after redaction · `mvp` · 7 | **A text-extraction test cannot see a surviving handwritten name, because handwriting has no text layer either way.** The acceptance test can pass on a derivative where the name is plainly legible. Verify visually at least once. |
| **VIC-03** | Any recipient with a PDF inspector → pull the name from the container, not the page | Document metadata, embedded XMP, outline entries, form field values, attachments and an embedded page thumbnail can each carry the name | Construct a fresh document, clear metadata and outline, insert only rendered pixmaps · `mvp` · 7 | Cheap to close and cheap to test — assert the derivative's metadata and outline are empty. |
| **VIC-04** | Holder of derivative access → read the redaction manifest | `redaction_manifest_hash` implies a stored manifest. The defensible design — logging what was redacted so it can be justified — produces a curated list of exactly the identifying strings | Manifest carries geometry, rule id and a **salted hash** of removed text, never the text; authorized strictly above the derivative · `mvp` · 7 | Serve only the hash on the derivative. |
| **VIC-05** | No attacker — the operator who drew the boxes | NER and any LLM are cut, so region selection is a human dragging boxes plus patterns over OCR spans. A handwritten name, a name in a photographed ID card, a letterhead, or an address that identifies her just as well is never located | `mvp` · 7 | **The largest structural residual in the redaction story.** The derivative is then signed and anchored, so the integrity machinery certifies the leak. See [AR-6](#accepted-risks). |
| **VIC-06** | Derivative-only role → fetch the page preview instead of the document | Thumbnails generated at ingest from the original, served from their own route with its own weaker check | `none` | Every preview must be a version-scoped derivative subject to the same policy, and previews of a redacted document must render from the derivative. |
| **VIC-07** | Ongoing case reader, after lawful disposal → the identity of a victim whose record was destroyed | Crypto-erase destroys the blob key, so `verify()` correctly returns `DISPOSED_ANCHOR_ONLY` — but OCR text, extracted field values and the index are untouched and fully queryable | `none` | **The gap between "we destroyed the document" and "we destroyed the record"**, and a plausible question from a Women Safety panel. Disposal must cascade to derived text. |
| **VIC-08** | External grantee → retain material after expiry | Expiry is re-checked per request, but an in-flight download completes and the browser cache on a shared workstation keeps the raster | `mvp` · 3 | No cache-suppression discipline on document routes, no in-flight revocation, no control over bytes already on disk. |
| **VIC-09** | Records clerk during normal duty → harvest identities of every victim passing through | **Ingestion and verification are upstream of redaction.** Every document is fully readable to whoever verifies it | `none` | Pipeline order guarantees an unredacted window for every document. Redaction can never protect the verifier. |

---

## 7. Supply chain and operations

| ID | Actor → goal | Vector | Control · maturity · slice | Residual |
|---|---|---|---|---|
| **SUP-01** | Maintainer of any transitive Python package → execution in the worker | Dependency install at image build with no hash-pinned lockfile | `none` | The worker touches every original, the blob path, the database credentials and the key provider. Offline networking at *run* time does not help: the compromise arrives at *build* time. |
| **SUP-02** | Squatter holding a name confusable with the redaction library → be imported by slice 7 | The redaction library's import name differs from its distribution name; installing the import name gets an unrelated package | Dependency ADR naming exact distributions · `mvp` · 7 | A wrong-but-present library could make redaction calls silently no-op. **The hook's presentational-masking regex covers CSS only** — a draw-a-rectangle overlay or rasterize-only path passes it. The text-extraction test is the real control. |
| **SUP-03** | Same → own the builder's machine rather than the product | Package build scripts execute at install time with the builder's privileges | `none` | One machine, one builder, no second reviewer, no branch protection. **The guard hook — the strongest control in the build — lives on that machine as an ordinary file.** |
| **SUP-04** | Maintainer of a transitive npm package → exfiltrate from the officer's or judge's browser | The npm tree is the largest dependency set by package count, and it ships code to the one place the offline design does not reach | `none` | Invariant 11 is scoped to the pipeline and has no analogue for the browser. |
| **SUP-06** | Also an evaluator asking what is actually inside the containers | Nothing enumerates what is installed at what version | `none` | A known-vulnerable pin is undetectable, and **the AGPL story rests on memory**. A committed dependency listing is a ten-minute task that also answers a likely judging question. |
| **OPS-01** | The venue network, or its absence | `docker compose up` on a clean machine **pulls**, and the Dockerfiles install packages | `none` | Nothing produces a portable image bundle with a checksum manifest — **and sneakernet is the actual transfer mechanism.** Addressed in PLAN's rehearsal section. |
| **OPS-02** | Anyone achieving execution in the worker → escape onto the host | Containers run as root with the source tree bind-mounted from the host | `none` | Container root writes the host repository: the policy files and the guard hook itself. No user directive, read-only root filesystem, dropped capabilities or separate data volume. |
| **OPS-03** | No attacker — resource exhaustion presenting as an outage | No memory or process limits on the worker; one 8 GB host | `none` | **This one should not be accepted.** Roughly ten lines of compose, and it protects the property BOOTSTRAP says matters most: that the demo degrades rather than disappears. |
| **OPS-04** | No attacker — a restore | No backups, no restore verification, and `fresh` is a one-command total wipe that ships in the image | `none` | A database snapshot without a matching blob snapshot restores into mass `UNAVAILABLE`. A restore of an older dump rolls the chain and the anchors back **together, consistently** — nothing detects that history was truncated. |

---

## 8. Attacks on the authorization model itself

Not on the code — on the seven-dimension design.

| ID | Vector | Control · maturity · slice | Residual |
|---|---|---|---|
| **AZM-01** | **Nothing establishes the subject.** All seven dimensions are evaluated against an asserted principal | `SimulatedSubjectProvider`, server-side session · `mvp` · 3 | See EXT-01, [AR-1](#accepted-risks). |
| **AZM-02** | An officer holding two posts across two organizations collapses the organization dimension — if the evaluator unions posts rather than selecting one | Acting post selected per request, declared, and bound into the persisted decision · `mvp` · 3 | Unspecified in both source documents today. Union is the natural implementation and it is wrong. |
| **AZM-03** | "identity/post" is written as one dimension. It is two. If assignment keys on the person and grants key on the office (or any inconsistent mix), succession either leaks or breaks | Declared subject key per grant type, plus a test that the two do not disagree · `mvp` · 3 | Either choice is defensible; **the unstated choice is the defect.** |
| **AZM-04** | A case transferred to another jurisdiction: the subject's jurisdiction comes from a live posting, the case's from a mutable row, so a past decision cannot be replayed against the values that were live when made | `none` | Needs jurisdiction as a time-bounded association. Out of scope; accepted. |
| **AZM-05** | A cross-organization grant scoped to the case also exposes *other organizations'* work product filed in that case — prosecution notes, court orders, lab reports | `none` | Needs an originating-organization attribute on the document. **Cheap to add in slice 2, invisible if missed.** |
| **AZM-06** | Three dimensions carry independent validity windows. The effective permission must be the intersection; the natural implementation is a union | Explicit all-must-hold combining algorithm, stated in the policy bundle · `mvp` · 3 | **PLAN adds an acceptance test where exactly one clock has lapsed.** BOOTSTRAP's tests are all single-dimension. |
| **AZM-07** | A grant resolving to (grantee, organization) rather than (grantee, case, purpose, expiry) means one lawful grant opens every case in that organization | `mvp` · 2 | Granularity unspecified in both documents. Listed as an open question in PLAN. |
| **AZM-08** | **Fail-closed inverts for a predicate.** Returning DENY on error is unambiguous for a point decision; for a filter, an empty condition list composes to *no restriction* — the natural failure is a **wider** query, not a narrower one | Filter construction fails closed explicitly, with a test · `mvp` · 3 | The most subtle correctness risk in slice 3, and invariant 2's wording does not reach it. |

---

## Invariant coverage

Where `CLAUDE.md`'s invariants are weaker than their wording implies. Only gaps are
listed; the rest hold.

| Invariant | Gap |
|---|---|
| **1** predicate inside the query | Names eight surfaces; slice 3 tested four. Needs single-object GET, download, job status, verify, search and every derivative route. |
| **2** deny by default | Unambiguous for a point decision, **inverted for a predicate** — see AZM-08. |
| **3** declarative policy | Secures *how* a decision is made and leaves *who the subject is* entirely unowned. Also: the policy tests run with no application **and no database**, so they cannot detect that a referenced attribute no longer exists after a migration. |
| **4** no PII on the ledger | Correct, and "Ever." invites reading it as a privacy guarantee when it is a **content** guarantee. The fixed tuple is by construction a complete activity graph. |
| **5** verification returns a state | Four states, one short. A pending anchor is valid per the reliability invariants but has no state, so `UNAVAILABLE` conflates never-anchored, store-unreachable, bytes-missing and denied. **Add `PENDING`.** |
| **6** untrusted document text | Absolute against prompt injection (no model exists) and silent about three real interpreters: the browser, the search index, the error path. |
| **7** provenance on every derived field | Enforced at the Pydantic boundary, which a direct database write never reaches — mirror it as NOT NULL plus a CHECK. **And manual entry produces a field with no source span by construction**, which is exactly what this invariant says must be rejected. That contradiction needs resolving before slice 5a. |
| **8** destructive redaction | **The largest gap.** Phrased in bytes; almost every route to the content is not bytes. Addressed by PLAN's amendment, with a kill-switch. |
| **9** AI output is draft | Core holds. A direct database write still sets a field verified with no human involved. |
| **10** append-only hash-chained audit | **Can be void while its test passes** — a table owner is not subject to REVOKE on its own table. Fixed in slice 1 by two roles. |
| **11** no external network on the demo path | Scoped to the pipeline, read as a property of the system. Does not reach the web container, which ships telemetry and a remote font stylesheet by default — each of which fails visibly at an air-gapped venue. |
| **12** never log content or identifiers | Binds code written deliberately; every real leak here comes from code nobody wrote. The HTTP access log records a search query verbatim; validation errors echo offending values. |
| *rel.* idempotency | Well specified; **the key's derivation is not, and that is the whole risk.** See PLAN open question 3. |
| *rel.* append-only versions | Protects bytes, not what anyone reads. See EVD-10. |
| *rel.* anchor outage | No `PENDING` state and no aging alert, so an indefinitely suppressed anchor is invisible. |
| *rel.* every stage records errors | "Errors" pulls toward persisting raw exception text — the invariant-12 channel — and it is read back over the job-status route. |

---

## Seam threats

Found only by looking *between* classes. Each is real and none belongs to a single slice.

1. **The renderer's cache serves the full-access view to the redacted role.** Slice 7 is
   literally "one document, three roles, one URL", and the Next.js App Router caches on
   the URL. **This defeats the headline demo with no attacker at all.**
2. **The idempotency key suppresses a corrected redaction.** Keyed on
   `(parent_version, stage)`, an operator who spots a missed name and re-runs gets the
   original derivative back. The reliability invariant and the safety requirement point
   in opposite directions here.
3. **The guard hook channels the 3am shortcut.** It blocks the hand-rolled role
   comparison in Python, so the fastest remaining fix is the same condition written
   straight into a SQL `WHERE` clause — which its regexes cannot see.
4. **The worker has no principal.** It signs, anchors and writes audit rows carrying an
   actor id, and it has no subject — so it writes either the enqueuer's id, attributing a
   machine action to a person, or a null, breaking the chain's attribution.
5. **Chain verification and case-scoped audit reads are mutually exclusive as specified.**
   Verifying the chain requires reading every row in sequence, including rows for sealed
   cases and other organizations.
6. **Disposal cannot remove the confirmation oracle.** The anchor must survive so a
   disposed document returns `DISPOSED_ANCHOR_ONLY` rather than `MISMATCH` — and it
   carries the digest of the destroyed plaintext.
7. **The accuracy table is self-referential** if it measures extraction. Addressed in
   PLAN R9: keep OCR error rate, drop extraction precision.
8. **Sentinel competes with the demo for the single worker.** Its tampering and
   duplicate-processing scenarios enqueue real jobs on the live instance, on one 8 GB host.
9. **Sentinel's "actual" field contains real case data by construction** and is rendered
   on a dashboard. It needs its own authorization and a hard binding to synthetic fixtures.
10. **Deterministic sanitisation converges content addresses.** Normalisation strips
    metadata and object ordering by design, so two scans of the same blank statutory form
    from different cases can sanitise to identical bytes — and dedupe across cases.
11. **Nobody specified whether a derivative is itself processed.** It is a first-class
    version, so the pipeline may OCR, extract, index and anchor it — producing a second
    field set for the same document, derived from redacted content.
12. **Transliteration and encoding variants defeat name matching** across redaction
    targeting, the slice 7 test, search and the accuracy comparison simultaneously — so
    the one number that would expose the problem is itself computed wrongly. Normalising
    once at the schema boundary handles the encoding half.

---

## Accepted risks

Each was accepted deliberately, with what would fix it.

**Two have since been answered and are kept rather than deleted**, because what a system
used to accept is part of reading it honestly. They are marked CLOSED and NARROWED below;
everything unmarked still has no answer in this build.

| # | Risk | Why accepted | What would fix it |
|---|---|---|---|
| **AR-1** | ~~**No real authentication.** The subject is a declared stub.~~ **CLOSED 2026-09-20** (ADR 0024): email and password, Argon2id, lockout on the account row. The credential-free switcher survives only under `ORDIN_ENV=dev`, where the API refuses its endpoints outside it. | Was: 3–4 days, solo, consuming the differentiator budget. Cost about half a day in the end, because `require_subject` already re-resolved every dimension server-side and trusted the token for nothing but *who*. | Still not an IdP. An agency deployment binds this to a directory via OIDC; the local table is the `production_adapter` gap that remains. |
| **AR-2** | **Purpose is caller-asserted and unverifiable.** | No technical control can validate a stated reason. | Purpose-scoped volume ceilings and an audit review surface. Say precisely: purpose was asserted, bound, logged and expired on schedule — **after-the-fact accounting, not an in-the-moment block.** |
| **AR-3** | **A privileged insider defeats every control in this document.** Database access bypasses authorization; owner rights bypass the audit REVOKE; host access bypasses redaction and encryption. | Separation of duty needs infrastructure explicitly out of scope. | Off-host key custody, append-only audit storage, and an administrative role that is not the application's role. |
| **AR-4** | **There is no independent witness.** The party asserting integrity controls every input to the assertion. | An external anchor contradicts "no external network on the demo path". | An external ledger, or periodic publication of the chain head to a second party. **Say this before a judge says it for you.** |
| **AR-5** | **Signatures carry no non-repudiation.** The signer is a soft key on the shared host. | Per-officer keys need hardware. | Hardware-backed per-officer keys. Ordin records an attribution, never a proof of authorship. |
| **AR-6** | **Redaction recall is bounded by OCR recall and human attention.** A handwritten name, a photographed ID card or a letterhead is never located. | Closing it needs entity recognition over degraded bilingual scans — explicitly out of build. | Two things that do fit: OCR the finished derivative and diff it against the case's known party names, failing the job if any survives; and route handwriting to manual entry rather than auto-redacting. **"Redaction covers what was located, and located-ness is bounded by OCR recall" reads as expertise, not weakness.** |
| **AR-7** | **Post-release control is zero.** Every grantee gets byte-identical copies, so a leak cannot be attributed; revocation does not reach bytes already delivered. | No technical control survives the file leaving the system. | A per-grant visible watermark at rasterize time (~20 lines), cache suppression on document routes, and binding the grant to an authenticated recipient rather than a bearer link. |
| **AR-8** | **Redaction discloses its own shape.** Box count, position and width against a known form tell the recipient how many names were removed and roughly how long each was. | Inherent to region redaction; normally accepted in legal practice. | Nothing, for the geometry. The avoidable part is the manifest — see VIC-04. |
| **AR-9** | ~~**No rate limiting, lockout or user-enumeration protection.**~~ **NARROWED**: sliding-window limits on session minting, writes and page renders (ADR 0021); account lockout counted on the row after 8 failures (ADR 0024); login, signup and their failure modes return byte-identical responses, asserted by test. | The limiter is **per api process and resets on restart**, and the web tier calls the API from one address, so the per-address bucket is effectively global behind it. That is a narrowing, not a closing. | Limiting in front of the api keyed on the real client address, and published ports bound to localhost. |
| **AR-10** | **No supply-chain integrity**: no lockfile, no dependency listing, no pinned base images. | Pure time budget. The four-container decision removed whole dependency trees, which is a larger real reduction than auditing would have been. | Pin base images by digest, commit a dependency listing, use a deterministic install, record the language-data file hash, and build on a trusted network then carry the images. |
| **AR-11** | **No container hardening or resource limits.** | Hardening is accepted. **The resource limits are not** — see OPS-03. | Non-root user, read-only root filesystem, dropped capabilities; memory and process limits on the worker with the OOM killer biased away from the database. |
| **AR-12** | **Zero malware detection**, and three memory-unsafe parsers over fully attacker-controlled bytes. | The stub is named a stub, so nobody believes scanning happens. Blast radius contained rather than the bug prevented — the right trade at this budget. | A real scanner behind the existing interface, plus per-job process isolation. **The pitch line is exact: Ordin proves the bytes are the bytes that arrived — an authenticity claim, never a safety claim.** Put no shield icon or "scanned" column anywhere in the UI. |
| **AR-13** | **Disposal does not reach derived text**, and crypto-erase cannot be shown to be irreversible. | Key custody separation needs infrastructure that is out of scope. | Scope keys per version so erasure has a bounded radius; cascade disposal to OCR text, extracted fields and the index. **Say "the stored original is crypto-erased", never "the document is destroyed"** — write-ahead logs and backups remain out of reach. |
| **AR-14** | ~~**No revocation propagation and no way to answer "who currently has access to this case, and why".**~~ **ANSWERED 2026-09-20** (ADR 0025): `GET /admin/access` lists both routes live, and revocation takes effect on the next request because no decision is cached. | Was: administration screens out of scope. | The remaining bound is unchanged and worth saying: revocation reaches the system's answers immediately and reaches **nothing already downloaded**, ever (AR-7). |
| **AR-15** | **Two-person approval was cut**, so self-designation, self-issued grants, unilateral erasure and rubber-stamped verification all rest on attribution alone. | A deliberate scope decision. Each is detectable after the fact; none is preventable without approval workflows. | Two cheap partials fit now: append-only assignments with a validity window, and a policy test asserting that issuer and grantee differ. |
| **AR-16** | **Aggregate differencing on authorized counts.** A count taken before and after a sealing order, or one that resolves to a single record, still reveals individual facts. | Minimum cell sizes and query auditing are out of budget. | **Worth stating precisely, because it demonstrates the distinction between the channel that was closed and the one that was not.** |
| **AR-17** | **Bulk export is unmetered.** A designated officer can export every case they hold at 2am, lawfully, with no quota or anomaly detection. | Data-loss prevention is a product in itself. | Quotas and volume anomaly detection. The affordable move now: make bulk export a distinct verb in the audit chain recording row count and filter — **accounting, not prevention.** |
| **AR-19** | **The administration screen lists case references.** An administrator holds no designation and reads no case content, but must pick a case to assign somebody to it — so they see that `VRN-N/2026/0001` exists, in that station, in that year. | Assignment is unusable without it, and it is the narrowest thing that makes assignment possible. Typing a reference blind moves the same knowledge into the administrator's head without removing it. | Scope the administrator to an organization, so the list is bounded by the same dimension everything else is. Cheap, and currently unowned. |
| **AR-18** | **No backups and no restore verification**; `fresh` is a one-command total wipe. | Correct trade-off — `fresh` is required by the clean-machine discipline — but it should be recorded rather than left implicit. | A paired snapshot/restore covering the database and blobs together, run after the last good rehearsal. |

---

## Open questions

Carried from `docs/PLAN.md`; each changes a threat's disposition.

1. **Idempotency key derivation** — decides INS-06, seam 2 and the duplicate-processing
   scenario simultaneously.
2. **Grant granularity** — decides AZM-07.
3. **Time authority** — decides EVD-04 and EVD-05.
4. **Whether a redacted derivative is itself processed** — decides seam 11.
5. **Statutory citations** — nothing in this build cites a section number, and nothing
   should begin to without a source.
