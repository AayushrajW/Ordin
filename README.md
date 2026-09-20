# Ordin

Case-centric evidence intelligence for Indian legal and investigation agencies.
SIH 2026, problem statement 26190 (MHA / NCRB Women Safety Division). Team Valora.

**The product is the case record, not the document store.** A document only has
meaning as evidence that a statutory transition in a case legitimately occurred.

---

## Running it

Needs [Docker](https://docs.docker.com/get-docker/), Python 3.11, and
[Tesseract 5](https://github.com/tesseract-ocr/tesseract) with the `eng` and `hin`
language packs. Node 20+ if you want the web tier.

```bash
python tasks.py setup     # venv, dependencies, .env, fixtures
python tasks.py doctor    # says what is still missing, and what to do about it
python tasks.py demo      # fresh database, seed, and documents through the real pipeline
python tasks.py admin --email you@example.org --password '<at least 12 characters>'
python tasks.py up        # postgres in docker; api, worker and web natively
```

Then open **http://127.0.0.1:3001**.

**To sign in there are two doors, and they are not the same door.**

`/login` is real: an email, a password, Argon2id, lockout on the account row. Signing in
grants *nothing* on its own — a new account holds no post, so no organization, no
jurisdiction and no clearance, and every case query comes back empty until an
administrator places it. That is the system working, not a fault.

`/specimen` is the identity switcher, which checks no credential. It is how you see
"same URL, three identities" in one click, and the API **refuses its endpoints entirely**
unless `ORDIN_ENV=dev` — hiding it from the UI would not be a control, because this
repository is public.

`tasks.py admin` closes the bootstrap hole every administration system has: the screen
that creates administrators requires an administrator. Put the same values in `.env` as
`ORDIN_ADMIN_EMAIL` / `ORDIN_ADMIN_PASSWORD` and `demo` will restore the account after it
reseeds, rather than locking you out of your own system. An administrator holds an
administrative *post*, carries no case designation, and therefore reads no evidence.

`demo` is what turns a correct-but-empty case list into something worth looking at.

`doctor` works on a machine where nothing is set up yet — that is the situation it
exists for. If something is wrong it tells you which thing.

### The three things worth seeing

```bash
python tasks.py sentinel         # 19 security scenarios, each able to go red
python tasks.py evaluate         # OCR accuracy and latency, with its caveats
python tasks.py verify-compose   # all four containers, inside 8 GB
```

`sentinel` is the one to run first. Every scenario names the invariant it protects,
what was set up, what was expected, and what actually happened — so a claim like
"three letters of a victim's name never surface from a case you cannot open" is
something you watch pass rather than something we assert.

---

## What is actually built

| | |
|---|---|
| Skeleton | four containers, `/health` checking each dependency, two Postgres roles |
| Domain model | 12 tables, case state machine, hash-chained append-only audit |
| Authorization | versioned YAML policy, seven dimensions, predicate inside every query |
| Integrity | content-addressed storage, `LocalAnchorStore`, five-state `verify()` |
| Golden thread | upload → OCR → extract → sign → anchor, idempotent |
| Redaction | destructive, rasterised, with the derived text closed off too |
| Verification UI | draft fields beside the scan; the human commit that writes `verified` |
| Intake | PDFs **and photographs** — re-encoded, so EXIF and GPS never reach the store |
| Voice | reads a screen aloud; never speaks a name; cannot commit or redact |
| Accounts | password login (Argon2id); signing in grants nothing until an administrator places you |
| Sentinel | 19 scenarios, rendered on a page and re-run live on every load |
| Upload hardening | content sniffing, size cap, structural sanitisation before storage |
| Fixtures | 48 synthetic documents, English and Hindi, 10 of them degraded scans |

398 tests. `python tasks.py test`.

---

## What is deliberately not built

Read `docs/THREAT-MODEL.md` before believing anything above. Its **accepted risks**
section is the honest inventory: no independent witness for the anchor chain, no
malware scanning, no entity recognition, and a privileged insider defeats most
controls in the document. Each is recorded with what would fix it.

Two entries there are now narrower than when they were written. **Authentication is
real** (ADR 0024) — accepted risk AR-1 described a switcher that checked no
credential, and that switcher is now refused outside `ORDIN_ENV=dev`. **Rate limiting
exists** (AR-9), narrowed rather than closed: it is per api process and resets on
restart, which `api/security.py` states about itself.

Three claims in particular are narrower than they look, and the code says so where
it makes them:

- **The audit chain is tamper-evident, not tamper-proof.** Unkeyed, so whoever can
  write the table can recompute it; tail truncation is undetectable without an
  externally witnessed head; and it only covers rows the application wrote.
- **`SimulatedESignProvider` records an attribution, not a proof of authorship.** A
  soft key on the shared host, no certificate, no binding to a natural person.
- **Redaction removes what it was told to remove.** Region selection is patterns over
  OCR text plus a human; there is no entity recognition and no LLM, so a handwritten
  name or a photographed ID card is never located. OCR bounds it further: character
  error rate is **2.2% on clean renders and 27.3% on degraded scans**, and **23.5% on
  Hindi**. Redaction is least reliable exactly where the documents are worst — which
  is why it now finds every mention of a known value, including OCR-mangled ones,
  rather than only the labelled line.
- **Upload hardening strips active content; it is not malware scanning.** A PDF's
  JavaScript, launch actions and embedded files are removed and the result is
  re-checked before storage. Nothing inspects what the document *says*.

Nothing here claims a certification or a compliance status. Standards are "aligned
to", never "certified", and no statistic appears that was not measured by a command
in this repository.

---

## Documents

| | |
|---|---|
| `CLAUDE.md` | the invariants, the decided stack, and the non-goals |
| `docs/PLAN.md` | build order, budget, and what was cut |
| `docs/THREAT-MODEL.md` | 8 attacker classes, invariant coverage, accepted risks |
| `docs/STATUS.md` | where the build actually is, written for a cold start |
| `docs/adr/` | 24 decisions, each with its consequences |
| `docs/PLAN-PRODUCT.md` | the work from demo to deployable, and what was actually true |
| `docs/modules/` | one page per landed slice, with the questions a judge will ask |
