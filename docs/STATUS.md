# Ordin — status

> Rewritten at the end of every session via `/wrap`. Written for a reader with
> no memory of any prior conversation.

## Current slice
**None — slice 1 is complete.** Next is **slice 2, the domain model.**

Slice 1 was split into 1a (`6e8f63a`) and 1b (`72bca85`); see `docs/PLAN.md`.
Both acceptance paths are verified on this machine:

- **dev** — `python tasks.py up`: postgres in docker, api/worker/web native;
  `/health` reports three checks green; killing the worker turns it 503 with
  reason `stale` while database and migrations stay up.
- **compose** — `python tasks.py verify-compose`: all four containers built and
  ran, api healthy, web page green, `NEXT_TELEMETRY_DISABLED=1` asserted inside
  the container, **203 MiB total**, then torn down. Passed first run.

## Acceptance criterion for current slice
Slice 2 (~3.5h, `docs/PLAN.md`): migrations run clean both ways; seed loads 3 cases
across 2 organizations; **a test proves the app role cannot UPDATE an audit row, and
that test fails if the REVOKE is removed**; `CaseAssignment` carries `valid_to`;
`ProcessingJob` carries an idempotency key whose derivation is `docs/adr/0004`
(`SHA256(case_id || content_sha256 || operation || params_hash)`), written up in an
ADR before the first job runs. Entity set trimmed from BOOTSTRAP's 16 to the ~10 the
golden thread and slice 3 actually need.

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
- **Slice 1b** (`72bca85`): worker with heartbeat loop, Next.js health page, two
  Dockerfiles, four-service compose with `mem_limit`s, `tasks.py verify-compose`.
  `/health` extended from one check to three.
- **Compose path verified for the first time** — passed on the first run.
- ADR 0006 amended with the measured memory figure, which falsified its own premise.
- `docs/modules/01-skeleton.md` completed; slice 1 closed.

## Half-done, and exactly where
**Nothing is half-done.** Working tree clean, all tests green, both slice 1 paths
verified. Slice 2 has not been started: `domain/` does not exist.

## Next concrete action
Run `/slice 1b`. First step inside it: add the `api`, `worker` and `web` services to
`docker-compose.yml` with `mem_limit`s, since the memory ceiling is the thing most
likely to make 1b fail and it should be discovered first, not last.

**Before starting, close applications.** `python tasks.py doctor` reported 457 MB
available at the end of this session, under its 800 MB warning threshold. Slice 1a
needs ~400 MB and fits; 1b adds a Next.js dev server at ~800 MB and will not.

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

1. **Time authority.** Application clock or database clock. Pick one — the database
   boundary is cheapest and survives container clock skew — and write the ADR. A hash
   chain proves order, never time (threat EVD-05).
2. **Is a redacted derivative itself processed** by the pipeline? It is a first-class
   version, so it may be OCR'd, extracted, indexed and anchored, producing a second
   field set derived from redacted content (seam 11).
3. **Invariant 7 vs manual entry.** Manual entry produces a field with no `source_span`
   by construction, which is exactly what invariant 7 says must be rejected at the
   schema boundary. Resolve before slice 5a.
4. **The 1,631-case finding** cited in BOOTSTRAP slice 7 — citation pending. Until
   supplied it appears in no document, deck or fixture.
5. **Statutory citations.** Slice 10 is cut, so nothing here cites a section number.
   If one enters the UI, fixtures or deck it needs a source.
6. Team ID for the SIH submission still unknown.

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
- [ ] 2 Domain model
- [ ] 6a Fixture pack
- [ ] 3 Policy + query-level authz
- [ ] 4a Integrity
- [ ] 5a Golden thread, headless
- [ ] 5b Verification UI (minimum)
- [ ] 7 Destructive redaction + role-switch
- [ ] ——— hard stop on coding at hour 30 ———
- [ ] 8 Sentinel dashboard (Tier C)
- [ ] 11a OCR accuracy table (Tier C)
- [ ] 4b Upload hardening (Tier C)
- [ ] 6b Corpus scale-up (Tier C)

Cut: 10 (completeness engine), 11's extraction metric, 12 (selective disclosure).
