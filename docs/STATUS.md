# Ordin — status

> Rewritten at the end of every session via `/wrap`. Written for a reader with no
> memory of any prior conversation.

## Start here

```bash
python tasks.py setup     # venv, dependencies, .env, fixtures — safe to re-run
python tasks.py doctor    # says what is missing and what to type; works on a bare clone
python tasks.py demo      # fresh database, seed, and documents ingested through the pipeline
python tasks.py up        # postgres in docker; api, worker and web native
```

Then open **http://127.0.0.1:3001** and pick a specimen identity.

`README.md` is the entry point. This file is the state of the build.

## Current slice

**None. PLAN is complete.** Every slice in the build order is built, including the
Tier C items that were listed as optional.

## What a demo looks like

1. `python tasks.py demo` — four documents ingested through the real pipeline, one with
   a redacted derivative, fourteen fields left as drafts.
2. `python tasks.py up`, then http://127.0.0.1:3001.
3. **SI Kavya Raut** (designated): sees one case of three, opens the complaint, sees the
   original with draft fields and their provenance. Clicking a field highlights the OCR
   words it was read from. Pressing *Verify* is the only thing in the system that writes
   `verified`, and it names her.
4. **PP Arjun Nair** (purpose-limited grant, other organization): same URL, receives the
   redacted derivative only. The original's version id returns 404 when named directly,
   and so does its OCR text.
5. **PP Meera Nadkarni** (live grant, lapsed clearance): sees nothing. Three validity
   clocks intersect rather than union.
6. **/sentinel** — fifteen scenarios run live against the application on every load.
   Break something on purpose and reload to watch a critical row go red.

## Test suite state

**377 passing, 0 skipped, 0 failing** (`python tasks.py test`), plus
`tests/test_ordin_guard.py` (7 tests, standalone). Sentinel **19/19**, twice back to
back. Compose path verified at **234 MiB**.

**Do not run two suites against one database.** A session-scoped guard in
`tests/conftest.py` refuses the second one with an explanation — see *Surprising*
below, because this was the "unexplained flake" for weeks.

`pytest -q` **hides the pass count** — `pyproject.toml` already sets `-q` in addopts, so
a second one makes it `-qq`. Use `tasks.py test`.

## Landed this session

- **Redesigned UI.** A design system (ink chrome, archival paper, brass for authority),
  an identity chooser, a case dashboard, case pages that explain *why* you can see them,
  a three-pane document workbench, and a Sentinel security console. Server-rendered,
  no client JavaScript required.
- **Detection engine** (`domain/pii.py`, ADR 0020). Every mention of an identifying
  value across the whole page — narrative, OCR-mangled, surname-only — plus Aadhaar
  with Verhoeff validation, PAN, mobile, e-mail, vehicle. Redaction of the specimen
  statement went from 3 labelled lines to 16 regions. Preview before burning.
- **Consistency engine** (`domain/consistency.py`). Flags the real OCR misreads —
  a reference one character off its case, a phone with a digit missing — and offers
  the correction as a button a person must press. Real per-word OCR confidence
  replaces the pattern's hardcoded 1.0.
- **Hardening** (ADR 0021). Verify-on-read, per-viewer watermark, audit row per view,
  rate limits, hardened headers on API and web, cross-site refusal on form routes.
  Sentinel REDACT-05, INTEG-01, SEC-01, SEC-02.

- **Slice 5b — verification UI** (Tier A). Case list, case view, the verify-and-commit
  screen with provenance on the page, corrections, manual entry, and the redact action.
  The human commit invariant 9 describes was until now unreachable.
- **Slice 5b+ — span highlighting.** Selecting a field highlights the OCR word boxes it
  was read from, positioned as percentages of the page so the overlay tracks any width.
- **Slice 8 — Sentinel dashboard.** Runs the scenarios live on every load; never renders
  a stored result (ADR 0015).
- **Slice 4b — upload hardening.** Size cap, content sniffing, structural sanitisation
  with PyMuPDF rather than qpdf (ADR 0016), inside `Pipeline.run` so no caller can skip
  it. The sanitiser re-scans its own output and refuses rather than lying.
- **Slice 6b — corpus scale-up.** 48 seeded documents, 10 of them degraded scans.
- **`infra/audit_log.py`** — the first thing in the build that writes the audit chain,
  serialised by a Postgres advisory lock so two appenders cannot fork it.
- **`infra/redaction_service.py`** — slice 7 had the algorithm and no persistence path.
  Redaction is now a product action driven by the field spans 5b+ computes.
- **`worker/intake_queue.py`** — the Postgres queue CLAUDE.md decided on and nothing
  had built. The upload route versions and answers 202; the worker claims with
  `FOR UPDATE SKIP LOCKED` and runs the thread (ADR 0019). The api keeps no OCR engine.
- **`demo.py` / `tasks.py demo`** — one command from clean checkout to a case file.
- ADRs 0014–0019. Module briefs 04b, 05b, 06b, 08. Migration 0008.

## Intake: what the system accepts

**PDFs and photographs.** PNG, JPEG, TIFF, GIF and BMP are accepted on their magic
bytes and wrapped into a one-page document; the pixels are re-encoded, so EXIF — camera,
owner, GPS — never reaches the store (ADR 0022). Anything else is refused on content,
whatever it is named. Encrypted PDFs are refused rather than guessed at. Caps: 25 MB,
200 pages, 80 megapixels.

A photograph goes through the same path as everything else — sanitise, version, queue,
OCR, extract, sign, anchor — and the worker picks it up within one tick, about ten
seconds.

## Voice assistant

Reads the current screen aloud and takes a fixed set of spoken commands (ADR 0022).
**It never speaks a name, number or address**, and it **cannot commit a value or burn a
redaction** — a misheard word must not write evidence. Speech output is on-device;
speech input uses the browser's recogniser, which streams audio to its vendor, so it is
**off by default** behind a switch that says so.

This machine has en-US and en-GB voices installed and no en-IN, so it speaks in en-GB.
In an embedded preview pane with no voices at all, the panel reports that the engine did
not start rather than appearing to work.

## Half-done, and exactly where

**Nothing is half-done.** Working tree committed, 325 tests green, no partially written
file and no partially implemented code path.

## Measured, 2026-09-19

OCR character error rate, real Tesseract over rasterised pages, 48-document corpus:

| language | documents | chars | errors | CER |
|---|---|---|---|---|
| eng | 37 | 15770 | 560 | **3.55%** |
| hin | 11 | 4151 | 976 | **23.51%** |

| condition | documents | chars | errors | CER |
|---|---|---|---|---|
| clean renders | 37 | 15528 | 335 | **2.16%** |
| degraded scans | 11 | 4393 | 1201 | **27.34%** |

Latency p50 1.16s, p95 2.42s. Four containers: 317 MiB total (measured after the
worker gained real work; it was 206 MiB when the worker only beat).

**Three findings to say out loud rather than bury:**

- **Degradation costs an order of magnitude.** 2.16% on clean renders against 27.34% on
  a mild synthetic degradation — tilt, 120 dpi, speckle, no text layer. The earlier
  0.34% headline was true of ten clean renders and is not a claim about real intake.
- **Hindi is roughly six times worse than English** and was ten times worse on the clean
  corpus. Any bilingual claim carries that number.
- **Tesseract misreads digits on clean pages.** On the specimen complaint it reads the
  complainant's name correctly and gets the phone number and the case reference wrong.
  Those arrive as drafts for a human to fix, which is the argument for the human commit
  rather than an embarrassment.

All three compound accepted risk AR-6: redaction targeting depends on locating a value
in OCR text, so it is least reliable exactly where the documents are worst.

## Second full recheck, 2026-09-20 (afternoon)

Whole repo re-read, whole suite re-run, whole demo re-rehearsed, on a database and a
Docker installation rebuilt from nothing.

| step | result |
|---|---|
| migrations from an **empty** database | all 8 clean — a path never exercised before, because the volume always pre-existed |
| `python tasks.py test` | **377 passed**, 162s then 137s |
| `python tasks.py demo` | 5 documents, 16-region derivative, 18 drafts |
| Officer: dashboard → case → workbench | 1 case of 3; both real OCR misreads flagged |
| Commit a suggested correction | verified by a person; machine reading kept, superseded; counts 4→3, flags 2→1 |
| Redaction preview → burn | 8 mentions / 16 regions, 5 outside the labelled lines; burn deduped |
| Redacted derivative | **Verified**, anchored #3 |
| Grantee: same URL, original version id | derivative only; v1 absent from the selector; no custody trail |
| Lapsed clearance: document named directly | "It does not exist, or you may not receive it — deliberately indistinguishable" |
| Sentinel, browser | **19/19 twice** (13:49:59, 13:50:13) |
| `verify-compose` | four containers, web green, telemetry off, **234 MiB**, torn down |

**Both fixes from the first rehearsal held**: a corrected draft is no longer counted as
awaiting review, and a redacted derivative is anchored at birth.

**One real bug found, fixed, committed (`253e0cc`, ADR 0023).** The image pixel cap ran
*after* `fitz.Pixmap()` had decoded the whole image. `MAX_BYTES` caps the upload at 25 MB
and does not bound the decoded size, so a 25 MB PNG decodes to gigabytes and exhausts the
worker's 256 MB limit — threat OPS-03. The cap is now applied to the dimensions the header
declares. The test that should have caught it was named
`test_an_enormous_image_is_refused_before_it_is_rasterised`, passed, and asserted nothing
about the ordering: it decoded the specimen itself to decide what to expect.

**`fitz.image_profile` is broken in PyMuPDF 1.26.7** — the binding passes a `bytes` to
`fz_recognize_image_format`, which rejects it on every input. Hence the hand-written
header parser. A control that cannot run is worse than none: it reads as present.

## Docker: the install on this machine is not trustworthy

Docker Desktop 4.91.0 on Windows 11 build 26200 failed to start for hours. Its Ingest
server creates `%LOCALAPPDATA%\Docker\run\sailor-ingest.sock`, then cannot rename it
aside, and aborts — leaving the socket behind, which is exactly what breaks the next
start. Error 1920, `ERROR_CANT_ACCESS_FILE`; even `fsutil reparsepoint query` failed,
with no Docker process running.

**Ruled out by experiment**: stale files, Docker's data and settings, the WSL distro,
driver state, the shell it is started from, and antivirus (Windows Defender only, no
third-party filter driver). It survived a reboot, a full wipe of all three Docker
directories and `wsl --unregister docker-desktop`.

What cleared it was the builder resetting Docker Desktop manually from its own dialog.
**Reinstall Docker Desktop before the event** — `docker compose up` is the demo path.

## Rehearsal record, 2026-09-20

Run twice, end to end, **using `python tasks.py …` exactly as the README says** — which
is what found the first fault, because every previous run had used
`.venv\Scripts\python.exe tasks.py` instead.

| step | result |
|---|---|
| `python tasks.py demo` | 5 documents, 16-region derivative, 18 drafts, **18s** |
| `python tasks.py up` | api + worker + web ready in **4s** |
| Officer: dashboard → case → workbench | flags the two real OCR misreads |
| Commit a suggested correction | human value verified; machine reading kept, superseded |
| Redaction preview → burn | 8 mentions / 16 regions; 5 outside the labelled lines |
| Grantee: same URL | redacted derivative only; no original, no custody trail |
| Lapsed clearance: same URL | "Not available", identical to a case that does not exist |
| Sentinel, browser and CLI | **19/19** |

**Rehearsal 1 found four faults; all are fixed and committed.**

1. **`python tasks.py` was broken for anyone but me.** The runner imported the
   application in whatever interpreter started it, and `python` on this machine is 3.10
   with none of the project's packages. It now hands over to the venv.
2. **A corrected draft stayed flagged.** After a person committed a suggested value, the
   machine's wrong reading was still counted as awaiting review — the screen asking them
   to resolve what they had just resolved. It is kept as evidence, marked superseded.
3. **Redacted derivatives were never anchored.** The worker's queue skips derivatives and
   nothing else wrote one, so the copy a grantee receives reported PENDING for ever.
   Anchored at birth now.
4. **The handover guard leaked through the environment**, so the test suite could not
   exercise it. The guard is the interpreter path, which cannot be inherited.

And two things that hid faults rather than being faults:

- **`tasks.py test` hid the names of failing tests.** `-r` replaces pytest's default
  report characters rather than adding to them, so `-rs` listed skips and dropped
  failures: a run could end "1 failed, 365 passed" and name nothing. Now `-rfEs`.
- **uvicorn's reloader on Windows kept the old process serving** after logging a reload,
  so an API change appeared not to take effect. Restart `tasks.py up` when in doubt.

**Known cosmetic noise:** inside an embedded browser pane, Next's hot-reload WebSocket
cannot connect and logs console errors. It is development-only — `next start`, the demo
path, has no such socket — and it is not the Content-Security-Policy, which was
widened for it and made no difference.

## Environment — verified, do not re-derive

- Docker Desktop 29.8.0. Installs **per-user** to `%LOCALAPPDATA%\Programs\DockerDesktop`.
- WSL2 capped at 1.86 GB by `~/.wslconfig`.
- **This stack is namespaced end to end**: compose project `ordin-build`, containers
  `ordin-build-*`, volume `ordin_build_pgdata`, postgres `127.0.0.1:5434`, api 8001,
  web 3001 — **in both paths**. The native dev loop used to run the web on 3000, which
  belongs to the second checkout; `tasks.py up` now passes the port explicitly.
- Python **3.11.9** in `.venv`. The machine also has 3.10 and 3.13; always use
  `.venv/Scripts/python.exe`.
- Tesseract 5.5.0 with `eng` and `hin`.
- `var/blobs/` holds document bytes for the dev loop. Gitignored; regenerated by
  `tasks.py demo`.

## WARNING — a divergent duplicate of this project exists

`D:\Legal Assistant` is the old path of this checkout. It was **copied, not moved**, and
a second session then built in it independently — slices 3–7 work, uncommitted, forked
from `91a46b5`.

**This tree is the project**, by the builder's decision. The other has been left
untouched; deleting it is the builder's call.

## Open questions

1. **Time authority.** Application clock or database clock. Pick one — the database
   boundary is cheapest — and write the ADR. A hash chain proves order, never time
   (threat EVD-05).
2. **Is a redacted derivative itself processed** by the pipeline? It is a first-class
   version, so it could be OCR'd, extracted and anchored, producing a second field set
   derived from redacted content. Currently it is not, by omission rather than decision.
3. **Case state names are placeholders.** `registered / under_investigation / filed /
   in_trial / closed` are generic procedural stages, not confirmed Indian statutory ones
   (ADR 0008). Check against a source before they appear in the deck.
4. **The 1,631-case finding** cited in BOOTSTRAP slice 7 — citation still pending. It
   appears in no document, deck or fixture until supplied.
5. **Statutory citations.** Nothing in this build cites a section number, and no
   extractor pattern matches one.
6. Team ID for the SIH submission still unknown.

## Surprising, and worth not rediscovering

- **Redaction left the victim's name in the narrative.** Field-only redaction burned
  "Victim Name: …" and nothing else; the surname two lines later reached the grantee.
  Every test passed because every test checked the labelled field. REDACT-05 now reads
  the derivative and looks everywhere.
- **A tamper test tampered nothing — again.** INTEG-01 first replaced a word in the raw
  PDF bytes; the text lives in a compressed stream, so nothing changed and the scenario
  went red for its own sake. It now flips a bit and asserts the bytes differ first.
- **uvicorn's reloader on Windows can keep the old process serving** after logging a
  reload. If an API change seems not to take, restart `tasks.py up`.
- **Docker Desktop failed to start after the machine restarted**: a stale
  `sailor-ingest.sock.stale` from an earlier crash blocked its own socket rename, and
  the socket placeholder could not be deleted. Moving
  `%LOCALAPPDATA%\Docker\run` aside (to `run.stale-<timestamp>`) and relaunching fixed
  it. The moved folder is safe to delete once Docker is healthy.

- **The "unexplained flake" was two test suites sharing one database.** Nearly every
  database test calls `seed()`, which `TRUNCATE ... CASCADE`s the case tables, so a
  second concurrent suite deletes the first's rows mid-test. It surfaces somewhere
  unrelated — a version that should have been found, a foreign key valid a moment
  earlier — and in a different test each run, which reads exactly like flakiness. The
  recorded hypothesis (transient state after a container restart) was wrong in the
  direction that stops you looking: it blamed the environment for something reproducible
  on demand. `tests/conftest.py` now refuses the second run and says why.
- **A hardening step broke an unrelated reliability guarantee.** Sanitisation went in
  front of version creation, and version identity was the digest of the stored bytes —
  so it depended on PyMuPDF serialising identically every time. It very nearly does.
  Migration 0008 records `source_sha256`, what arrived, and identity keys on that
  (ADR 0017). The general rule: anything upstream of content-addressed storage must be a
  pure function of its input, and if it cannot be, identity must not depend on it.
- **Sanitisation is deterministic but not a fixed point.** `sanitise(sanitise(x))`
  differs from `sanitise(x)` about one specimen in twenty-five, because mupdf compacts
  object numbering differently on a second save. An earlier test asserted the fixed
  point, passed most of the time, and failed once per full run in a different file each
  time — a test asserting a property the library never offered is worse than no test.
- **Two columns named `confidence` were on different scales.** Tesseract reports 0–100
  and it was stored raw, beside `extracted_field.confidence` holding 0–1. Nothing
  failed; the screen printed "mean confidence 9252.6%", which is the only reason anyone
  looked. Normalised at the boundary, with a test.
- **The pytest suite was running 11 of 15 Sentinel scenarios.** Three places imported
  the scenario modules by name and the test's list fell behind, so slice 5b's four
  scenarios only ever ran by hand — the newest and least proven. Registration is
  discovery now, with a test asserting it reaches every file.
- **A Sentinel scenario passed while proving nothing.** VERIFY-01 committed a row that a
  test fixture had inserted by hand rather than one the pipeline produced, because it
  reused whatever document it found. It now always runs the pipeline.
- **Next 16 writes `CLAUDE.md` and `AGENTS.md` into `web/` on first run.** A nested
  CLAUDE.md there would shadow the project's own instructions. Disabled with
  `agentRules: false` and gitignored.
- **Server Actions failed the origin check** in an embedded browser (`Origin: null`) and
  would fail behind a proxy or when reached by IP. Writes are plain form posts now
  (ADR 0018), which also makes every page work with JavaScript off.
- **A redirect built from `request.url` silently lost the session**, rewriting
  `127.0.0.1` to `localhost` so the cookie was not sent back. Redirects are relative.
- **The container images were broken for four slices** at one point, because the
  Dockerfile never learned about new packages. `verify-compose` is the only thing that
  catches it; run it at both gates, not just the second.
- **`verify-compose` was verifying the wrong things, three ways.** It probed the api on
  port 8000 while compose publishes 8001 — so for several sessions it was checking
  whatever answered there, which on this machine is the *other checkout*. It never
  confirmed the containers were running, so when a port clash stopped api and web from
  starting it still reported "web page green" against the native dev server on the same
  port. Both are fixed and the container check now runs first. A harness that can pass
  against something else entirely is worse than no harness.
- **The database identity guard rejected a correct database.** Its parser required the
  annotated `revision: str = "..."` spelling, and migration 0008 used the plain form
  Alembic also emits — so the guard did not know the revision existed and refused every
  test run. A tripwire that fires on correct behaviour gets disabled; there is now a test
  asserting the parser finds a revision in every migration file.
- **Generating Python with a shell heredoc corrupts escapes.** Hit twice more this
  session: `\b` became a backspace inside a regex, and `\\(` became `\(`. Use the Edit
  tool for anything containing escapes.

## Slices completed

- [x] **1a Skeleton** — postgres + two roles, /health, structured logs, Alembic, tasks.py
- [x] **1b Skeleton** — worker, web health page, Dockerfiles, four-container compose
- [x] **2 Domain model** — 12 tables, audit chain + REVOKE (mutation-tested), seed
- [x] **6a Fixture pack** — 10 documents, EN+HI, ground-truth sidecars with bboxes
- [x] **3a Policy + query-level authz** — evaluator, registry, filter, agreement test
- [x] **3b Session, PolicyDecision persistence, HTTP routes, Sentinel registry**
- [x] **4a Integrity** — BlobStore, LocalAnchorStore, verify() with five states
- [x] **5a Golden thread, headless** — OCR, extraction, sign, anchor, idempotent
- [x] **7 Destructive redaction + role-switch** — remove/rasterise/rebuild, VIC-01 closed
- [x] **11a OCR accuracy table** — CER by language, latency, caveats on the page
- [x] **5b Verification UI** — draft fields, scan, the human commit
- [x] **5b+ Span highlighting** — char offsets to rectangles via `ocr_word`
- [x] **8 Sentinel dashboard** — 15 scenarios, run live on every load
- [x] **4b Upload hardening** — sniffing, size cap, sanitisation, worker-side thread
- [x] **6b Corpus scale-up** — 48 documents, 10 degraded, clean-vs-degraded CER

Cut, and still cut: 10 (completeness engine), 11's extraction metric, 12 (selective
disclosure).

## Next concrete action

**Rehearse the narration, not the software.** The build is complete and rehearsed twice
end to end. What is unrehearsed is a person talking over it: `python tasks.py demo`,
`python tasks.py up`, then walk the eight steps in the rehearsal record above without
notes.
