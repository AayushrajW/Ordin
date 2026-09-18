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
python tasks.py up        # postgres in docker; api, worker and web natively
```

`doctor` works on a machine where nothing is set up yet — that is the situation it
exists for. If something is wrong it tells you which thing.

### The three things worth seeing

```bash
python tasks.py sentinel         # 11 security scenarios, each able to go red
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
| Fixtures | 10 synthetic documents, English and Hindi, with ground truth |

272 tests. `python tasks.py test`.

---

## What is deliberately not built

Read `docs/THREAT-MODEL.md` before believing anything above. Its **accepted risks**
section is the honest inventory: no real authentication, no rate limiting, no
independent witness for the anchor chain, no malware scanning, and a privileged
insider defeats most controls in the document. Each is recorded with what would fix
it.

Three claims in particular are narrower than they look, and the code says so where
it makes them:

- **The audit chain is tamper-evident, not tamper-proof.** Unkeyed, so whoever can
  write the table can recompute it; tail truncation is undetectable without an
  externally witnessed head; and it only covers rows the application wrote.
- **`SimulatedESignProvider` records an attribution, not a proof of authorship.** A
  soft key on the shared host, no certificate, no binding to a natural person.
- **Redaction removes what it was told to remove.** Region selection is patterns over
  OCR text plus a human; there is no entity recognition and no LLM, so a handwritten
  name or a photographed ID card is never located. OCR character error rate on Hindi
  is **10%** against 0.34% on English, which bounds this further.

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
| `docs/adr/` | 12 decisions, each with its consequences |
| `docs/modules/` | one page per landed slice, with the questions a judge will ask |
