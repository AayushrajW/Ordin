# Ordin — status

> Rewritten at the end of every session via `/wrap`. Written for a reader with no
> memory of any prior conversation.

## Start here

```bash
python tasks.py setup     # venv, dependencies, .env, fixtures — safe to re-run
python tasks.py doctor    # says what is missing and what to type; works on a bare clone
python tasks.py test      # 275 tests
```

`README.md` is the entry point. This file is the state of the build.

## Current slice

**None. Tier A, Tier B and slice 11a are complete.** The build is ahead of the
rehearsal, which is the actual risk now.

## Acceptance criterion for the next thing

There are two remaining PLAN items, both Tier C, neither blocking anything:

- **4b — upload hardening** (~2.5h). Content sniffing, size cap, qpdf sanitisation.
  Acceptance: a PDF carrying JavaScript comes out sanitised. Upload is currently the
  one unhardened entry point, and it is a visible demo beat.
- **6b — corpus scale-up** (~1.5h). More documents plus a degradation pass, which is
  what would make the OCR accuracy figure comparable to a real intake.

**Recommended before either: rehearse twice more.** Two clean-clone rehearsals this
session each found real defects that no test caught. BOOTSTRAP is explicit that every
failure you will have shows up on the second clean run.

## Test suite state

**275 passing, 0 skipped, 0 failing** (`python tasks.py test`), plus
`tests/test_ordin_guard.py` (7 tests, standalone).

`pytest -q` **hides the pass count** — `pyproject.toml` already sets `-q` in addopts, so
a second one makes it `-qq` and suppresses the summary. A full run then looks like bare
dots with no total, which is how a failure gets scrolled past. Use `tasks.py test`.

## Landed this session

- **Slice 3** (3a `887f762`, 3b `5fdb06d`) — policy as versioned data, one predicate
  registry proven to agree across Python and SQL, the predicate inside six query
  surfaces, `SimulatedSubjectProvider`, `policy_decision` persistence, HTTP routes,
  and the Sentinel scenario registry.
- **Slice 4a** (`314406e`) — `BlobStore`, `LocalAnchorStore`, `disposition`, five-state
  `verify()`. CLAUDE.md invariant 5 amended per ADR 0010.
- **Slice 6a** (`29b8bf4`) — 10 fixture documents with ground-truth sidecars.
- **Slice 5a** (`553b40d`) — the golden thread, headless and idempotent.
- **Slice 7** (`aa3a9b1`) — destructive redaction, and the disclosure rule that closes
  threat VIC-01.
- **Slice 11a** (`929c30d`) — OCR accuracy table with its caveats printed.
- **Container images repaired** (`97eae52`) — broken since slice 3a.
- **Clean-clone setup** (`c919afc`) — `tasks.py setup`, README, `doctor` that works on
  a bare clone.
- ADRs 0008–0013. Module briefs 03, 04a, 05a, 07.

## Half-done, and exactly where

**Nothing is half-done.** Working tree clean, 275 tests green, no partially written
file and no partially implemented code path. 4b and 6b have not been started.

## Next concrete action

`python tasks.py fresh && python tasks.py seed && python tasks.py sentinel`, on this
machine, twice. Then `/slice 4b` if time remains.

## Measured, 2026-09-18

OCR character error rate, real Tesseract over rasterised pages, 10-document fixture
corpus:

| language | documents | chars | errors | CER |
|---|---|---|---|---|
| eng | 8 | 3231 | 11 | **0.34%** |
| hin | 2 | 685 | 69 | **10.07%** |

Latency p50 1.16s, p95 5.63s. Four containers: 230 MiB total.

**The Hindi figure is the honest finding and should be said out loud.** Devanagari is
roughly thirty times worse than Latin here, on clean synthetic renders. Two
consequences: any bilingual claim must carry that number, and slice 7's redaction
targeting — which relies on locating a name in OCR text — is correspondingly less
reliable on Hindi documents. That compounds accepted risk AR-6 rather than sitting
beside it.

## Environment — verified, do not re-derive

- Docker Desktop 29.8.0. Installs **per-user** to `%LOCALAPPDATA%\Programs\DockerDesktop`,
  not `C:\Program Files\Docker`.
- WSL2 capped at 1.86 GB by `~/.wslconfig`.
- **This stack is namespaced end to end**: compose project `ordin-build`, containers
  `ordin-build-*`, volume `ordin_build_pgdata`, postgres `127.0.0.1:5434`, api 8001,
  web 3001. Every port differs from 5432 (a native PostgreSQL 17 service), and from
  5433/8000/3000 which belong to a second checkout at `D:\Legal Assistant`.
- Python **3.11.9** in `.venv`, pinned to match the api image. The machine also has
  3.10 and 3.13; always use `.venv/Scripts/python.exe`.
- Tesseract 5.5.0 with `eng` and `hin`.

## WARNING — a divergent duplicate of this project exists

`D:\Legal Assistant` is the old path of this checkout. It was **copied, not moved**,
and a second Claude Code session then built in it independently — slices 3–7 work,
uncommitted, forked from `91a46b5`.

**This tree is the project**, by the builder's decision. The other has been left
untouched; deleting it is the builder's call.

The two trees shared a postgres container until they were namespaced, because both
compose files declared identical `container_name` values and those are **globally
unique in Docker**. The other tree migrated over this one's schema. `tasks.py test` now
refuses to run against a database this checkout did not migrate.

## Open questions

1. **Time authority.** Application clock or database clock. Pick one — the database
   boundary is cheapest and survives container clock skew — and write the ADR. A hash
   chain proves order, never time (threat EVD-05).
2. **Is a redacted derivative itself processed** by the pipeline? It is a first-class
   version, so it could be OCR'd, extracted, indexed and anchored, producing a second
   field set derived from redacted content. Currently it is not, by omission rather
   than by decision.
3. **Case state names are placeholders.** `registered / under_investigation / filed /
   in_trial / closed` are generic procedural stages, not confirmed Indian statutory
   ones (ADR 0008). Check against a source before they appear in UI copy or the deck.
   Transitions are data, so the fix is one table.
4. **The 1,631-case finding** cited in BOOTSTRAP slice 7 — citation still pending. It
   appears in no document, deck or fixture until supplied.
5. **Statutory citations.** Nothing in this build cites a section number, and no
   extractor pattern matches one. If one enters anywhere it needs a source.
6. Team ID for the SIH submission still unknown.

## Surprising, and worth not rediscovering

- **The container images were broken for four slices.** `docker/python.Dockerfile` was
  written at slice 1b and never learned about `domain/`, `infra/`, `sentinel/` or
  `policies/`; the api died at import from slice 3a onward. The dev loop runs from the
  source tree, so nothing noticed. ADR 0006 schedules `verify-compose` at two gates
  precisely for this; only the second gate was run.
- **Three controls looked applied and did nothing.** `telemetry: false` is not a valid
  Next config key (Next rejects it and keeps posting; only the env var works). The
  first database-identity guard read the revision via `docker compose exec`, so it
  always reported our own container whatever the port said. A token-forgery test
  "tampered" by string-replacing a base64 payload, so it matched nothing and tested an
  unmodified token. Each was caught only by testing the control against the condition
  it exists to catch.
- **The guard hook fired on `.env.example`**, a file that must be committed. It blocked
  a correct commit twice. Narrowed, with tests asserting real secrets are still
  blocked. A tripwire that fires on correct behaviour teaches evasion.
- **One observed flake, unexplained.** A pipeline idempotency test failed once and has
  passed on every run since. It happened immediately after `verify-compose` tore the
  containers down, so the leading hypothesis is transient database state during
  restart — a hypothesis, not a diagnosis. If it recurs, capture the assertion output
  first: the row counts distinguish a duplicate from a missing row, and those have
  different causes.
- **Generating Python with a shell heredoc corrupts escapes.** `\\t` became a literal
  tab and `\\n` a real newline, producing a silently non-applied edit and a syntax
  error. Use the Edit tool for anything containing escapes.

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
- [ ] 4b Upload hardening (Tier C)
- [ ] 6b Corpus scale-up (Tier C)
- [ ] 5b Verification UI (Tier C — span highlighting; the API path exists)
- [ ] 8 Sentinel dashboard page (Tier C — the 11 scenarios exist and run in the CLI)

Cut: 10 (completeness engine), 11's extraction metric, 12 (selective disclosure).
