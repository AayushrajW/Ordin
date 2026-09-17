# Ordin — status

> Rewritten at the end of every session via `/wrap`. Written for a reader with
> no memory of any prior conversation.

## Current slice
**Slice 1b** — the remaining half of the skeleton. Slice 1a is done and committed.

Slice 1 was split; see `docs/PLAN.md`. 1a was the useful unit (it unblocks slice 2
entirely); 1b is the demo path and can slip a session without blocking anything.

## Acceptance criterion for current slice
Slice 1b (~1.5h): a `worker` process and a Next.js `web` health page run natively;
three Dockerfiles exist (api, worker, web); `docker-compose.yml` defines all four
services with explicit `mem_limit`s; and **`docker compose up` brings all four up
inside 8 GB with the web health page green**. Both acceptance paths — `dev` and
`compose` — recorded here when they pass.

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
- **Slice 1a** (`6e8f63a`): Postgres 16 container with two roles, FastAPI skeleton,
  `/health`, structured JSON logging with correlation ids, Alembic baseline, `tasks.py`,
  16 tests. Test written first and watched fail before implementation.
- **Guard hook activated** (`8fa1be5`): it had been silently doing nothing.
- **ADRs 0004-0007**: idempotency key, grant granularity, hybrid dev loop, task runner.
- **`docs/modules/01-skeleton.md`**: module brief covering 1a.
- `BOOTSTRAP.md` "Finale shape" corrected (no 36h event).

## Half-done, and exactly where
**Nothing is half-done.** No file is partially written, no code path partially
implemented, working tree clean, all tests green.

Slice 1b has not been started — it is not half-done, it is not begun. The files it
will create (`worker/`, `web/`, `docker/*.Dockerfile`) do not exist yet.

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

## Slices completed
- [x] **1a Skeleton** — postgres + two roles, /health, structured logs, Alembic, tasks.py
- [ ] 1b Skeleton — worker, web health page, Dockerfiles, four-container compose
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
