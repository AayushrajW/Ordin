# Ordin — status

> Rewritten at the end of every session via `/wrap`. Written for a reader with
> no memory of any prior conversation.

## Current slice
**None — slice 4a is complete.** Next is **slice 5a, the golden thread (headless).**

## Acceptance criterion for current slice
Slice 5a (~5h, `docs/PLAN.md`): `upload → validate → version → OCR → text layer +
char-offset-to-bbox map → regex extract → sign → hash → anchor`, every stage a
`ProcessingJob` carrying the idempotency key from `docs/adr/0004`. Anchoring is a
separately retryable stage. Low OCR confidence or handwriting routes to
`requires_manual_entry`.

**Acceptance: running the pipeline twice on one upload yields exactly one version,
one extraction run, one field set, one anchor.** That is a test, not an intention.

Two things to settle first, both flagged and neither decided:
- **Invariant 7 vs manual entry.** Manual entry produces a field with no
  `source_span`, which is exactly what invariant 7 says must be rejected at the schema
  boundary. `ExtractedField` was deferred from slice 2 to here precisely so this is
  answered before the schema freezes.
- OCR needs Tesseract in the worker image, which is the first dependency that makes
  the worker container diverge from the api (docker/python.Dockerfile currently serves
  both).

## Test suite state
**16 passing, 0 skipped, 0 failing.** Plus `tests/test_ordin_guard.py` (4 tests) which
runs standalone.

```
python tasks.py test        # starts postgres, waits for health, runs pytest
python tasks.py doctor      # environment check before blaming the code
```

**There is no Makefile and `make` is not installed** — `tasks.py` is the runner, by
decision. See `docs/adr/0007`. `BOOTSTRAP.md` still says `make fresh && make up`;
that phrasing is superseded.

## Landed this session
- **Slice 4a** — `BlobStore` (content-addressed, immutable), `LocalAnchorStore`
  (hash-chained, honestly named), `disposition`, and `verify()` returning five states.
  30 new tests. CLAUDE.md invariant 5 amended per ADR 0010.
- **Slice 3b** — `policy_decision` persistence (invariant 3 end to end),
  `SimulatedSubjectProvider`, HTTP routes over `authorized_cases()`, and the Sentinel
  scenario registry with slice 3's seven scenarios. `python tasks.py sentinel` prints
  them; 7/7 passing.
- **Slice 3a** - policy as versioned YAML, a pure evaluator, one predicate registry
  with Python and SQL halves that are *proven* to agree, and the filter pushed inside
  the query on six surfaces. 47 new tests.
- **Stack isolation + foreign-database guard** after the two checkouts were found to
  be sharing one postgres container.
- **Slice 6a** — fixture generator producing 10 synthetic documents (8 English,
  2 Hindi) with ground-truth sidecars: exact pre-render text plus a bounding box for
  every identifying field. 12 new tests, including one asserting each bbox actually
  contains the value it claims. ADR 0009 records PyMuPDF's AGPL licence and the
  vendored OFL font.
- **Slice 2** — 12 tables (`0003_domain_model`), pure `domain/` layer with the case
  state machine and audit chain, seed of 3 cases across 2 organizations, 39 new tests.
  The audit REVOKE was **mutation-tested**: granting UPDATE/DELETE back fails three
  tests, revoking restores them.
- **ADR 0008** (domain model scope), `docs/modules/02-domain-model.md`.
- Folder renamed to `Ordin Build`; compose project pinned to `ordin` so it no longer
  tracks the directory name.

### Earlier this session
- **Slice 1b** (`72bca85`): worker with heartbeat loop, Next.js health page, two
  Dockerfiles, four-service compose with `mem_limit`s, `tasks.py verify-compose`.
  `/health` extended from one check to three.
- **Compose path verified for the first time** — passed on the first run.
- ADR 0006 amended with the measured memory figure, which falsified its own premise.
- `docs/modules/01-skeleton.md` completed; slice 1 closed.

## Half-done, and exactly where
**Nothing is half-done.** Working tree clean, 120 tests green.

Slice 4a is complete. Slice 5a has not been started: there is no pipeline, no OCR,
no `ExtractedField` table and no `ProcessingJob` execution.

## Next concrete action
Run `/slice 1b`. First step inside it: add the `api`, `worker` and `web` services to
`docker-compose.yml` with `mem_limit`s, since the memory ceiling is the thing most
likely to make 1b fail and it should be discovered first, not last.

**Before starting, close applications.** `python tasks.py doctor` reported 457 MB
available at the end of this session, under its 800 MB warning threshold. Slice 1a
needs ~400 MB and fits; 1b adds a Next.js dev server at ~800 MB and will not.

## WARNING — a divergent duplicate of this project exists

`D:\Legal Assistant` is the old path of this checkout. The folder was **copied, not
moved** (a directory cannot be renamed while a session holds it open), and a second
Claude Code session — almost certainly running inside Cursor — then continued building
in it independently.

That copy forked from commit `91a46b5` (end of slice 1) and went straight at slices
3-7: `api/cases.py`, `api/session.py`, `api/uploads.py`, `api/search.py`,
`infra/blobstore.py`, `infra/esign.py`, `policies/`, `services/`, a subject-switcher
UI, and `alembic/versions/0003_domain.py`. None of it is committed there.

**This tree (`D:\Ordin Build`) is the project**, by the builder's decision on
2026-09-18. The other session is still running and has been left alone.

**The two trees shared a database until 2026-09-18.** Both compose files carried
identical `container_name` values, and container names are globally unique in Docker -
so `docker compose up` in either tree attached to the *same* container and the same
`ordin_pgdata` volume. The other session applied its `0003_domain` migration, which
replaced this tree's `0003_domain_model` schema underneath a green test suite.

This stack is now namespaced end to end and cannot collide again:

| | this tree | the other |
|---|---|---|
| compose project | `ordin-build` | `legalassistant` |
| containers | `ordin-build-*` | `ordin-*` |
| volume | `ordin_build_pgdata` | `ordin_pgdata` |
| postgres | `127.0.0.1:5434` | `127.0.0.1:5433` |
| api / web | `8001` / `3001` | `8000` / `3000` |

Do not un-namespace these without first checking the other checkout is gone.

Two things to know:

- The two `0003` migrations occupy the **same Alembic revision slot** with different
  contents. They can never both apply. Do not copy files between the trees without
  resolving that first.
- `D:\Legal Assistant` has been left completely untouched — it holds real, unreviewed
  work. Deleting it is the builder's call, not an automatic cleanup. Check whether a
  Cursor session is still attached to it before doing anything.

## Environment — verified, do not re-derive
- Docker Desktop 29.8.0, Linux engine, Compose v5.5.1. Installs **per-user** to
  `%LOCALAPPDATA%\Programs\DockerDesktop`, not `C:\Program Files\Docker`.
- WSL2 installed, capped at **1.86 GB** by `~/.wslconfig`.
- **Postgres publishes on 127.0.0.1:5433, not 5432** — a pre-existing
  `postgresql-x64-17` Windows service holds 5432. That service also listens on
  `0.0.0.0`, which is the pattern threat EXT-04 warns about; not ours, not changed.
- Python **3.11.9** in `.venv`, pinned to match the api image. The machine also has
  3.10 and 3.13; use `.venv/Scripts/python.exe`.
- Claude Code CLI 2.1.274 installed, so Cursor can drive this repo.
- `.env` is gitignored and must exist — copy `.env.example`.

## Open questions
Decided already, do not re-litigate: idempotency key (`adr/0004`), grant granularity
(`adr/0005`), hybrid dev loop (`adr/0006`), task runner and Python pin (`adr/0007`).

Still open:

1. **Case state names are placeholders.** `registered / under_investigation / filed /
   in_trial / closed` are generic procedural stages, not confirmed Indian statutory
   ones (ADR 0008). They must be checked against a source before appearing in UI copy,
   a fixture or the deck. Transitions are data, so the fix is one table.
2. **Time authority.** Application clock or database clock. Pick one — the database
   boundary is cheapest and survives container clock skew — and write the ADR. A hash
   chain proves order, never time (threat EVD-05).
3. **Is a redacted derivative itself processed** by the pipeline? It is a first-class
   version, so it may be OCR'd, extracted, indexed and anchored, producing a second
   field set derived from redacted content (seam 11).
4. **Invariant 7 vs manual entry.** Manual entry produces a field with no `source_span`
   by construction, which is exactly what invariant 7 says must be rejected at the
   schema boundary. Resolve before slice 5a.
5. **The 1,631-case finding** cited in BOOTSTRAP slice 7 — citation pending. Until
   supplied it appears in no document, deck or fixture.
6. **Statutory citations.** Slice 10 is cut, so nothing here cites a section number.
   If one enters the UI, fixtures or deck it needs a source.
7. Team ID for the SIH submission still unknown.

## Surprising, and worth not rediscovering
- **`ordin_owner` is a superuser**, because that is how the Postgres image creates
  `POSTGRES_USER`. ADR 0001's actual requirement (owner != app) holds and `ordin_app`
  has no attributes at all, but "the owner is a superuser" is a real residual to
  narrow before this is anything but a demo.
- **`.gitignore` had a bug**: the `.env.*` rule was swallowing `.env.example`, the one
  file in that family that must be committed. Fixed with a negation.
- **The guard hook was silently dead** for an entire session — `settings.json` invoked
  `python3`, which on this machine is the Store alias stub and exits 49, not 2. Fixed,
  and `tests/test_ordin_guard.py` reads the command out of settings.json and runs
  *that*, so a dead interpreter fails loudly.
- **The guard hook channels the 3am shortcut.** It blocks a hand-rolled role comparison
  in Python, so the fastest remaining fix is the same condition written directly into a
  SQL WHERE clause, which its regexes cannot see. Slice 3's tests are the real control.
- **Slices 1-12 as written price at 59-70 hours** against ~34 available (three
  independent estimates). The plan commits to eight trimmed slices.
- **The four-container path uses 203 MiB at idle**, not the ~1.15 GB feared. The
  earlier figure summed `mem_limit` ceilings, not usage. This removes the capacity
  argument for the hybrid dev loop (ADR 0006 amended); the faster-reload argument
  stands. Re-measure at slice 5a, when Tesseract gives the worker real work.
- **Next.js telemetry cannot be disabled from `next.config.mjs`.** A `telemetry` key
  there is silently ignored while Next keeps posting - a fix that looks applied and is
  not. Only `NEXT_TELEMETRY_DISABLED=1` works; `verify-compose` asserts it inside the
  running container because it is exactly the kind of setting that regresses quietly.
- **`pkill -f` does not kill Windows native processes.** Two stale uvicorn processes
  from an earlier session kept serving an old one-check `/health` response. Use
  PowerShell `Stop-Process`.

## Slices completed
- [x] **1a Skeleton** — postgres + two roles, /health, structured logs, Alembic, tasks.py
- [x] **1b Skeleton** — worker, web health page, Dockerfiles, four-container compose
- [x] **2 Domain model** — 12 tables, audit chain + REVOKE (mutation-tested), seed
- [x] **6a Fixture pack** — 10 documents, EN+HI, ground-truth sidecars with bboxes
- [x] **3a Policy + query-level authz** - evaluator, registry, filter, agreement test
- [x] **3b Session, PolicyDecision persistence, HTTP routes, Sentinel registry**
- [x] **4a Integrity** — BlobStore, LocalAnchorStore, verify() with five states
- [ ] 5a Golden thread, headless
- [ ] 5b Verification UI (minimum)
- [ ] 7 Destructive redaction + role-switch
- [ ] ——— hard stop on coding at hour 30 ———
- [ ] 8 Sentinel dashboard (Tier C)
- [ ] 11a OCR accuracy table (Tier C)
- [ ] 4b Upload hardening (Tier C)
- [ ] 6b Corpus scale-up (Tier C)

Cut: 10 (completeness engine), 11's extraction metric, 12 (selective disclosure).
