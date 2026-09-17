# 0007 — `tasks.py` is the task runner, not `make`

## Context
`BOOTSTRAP.md` slice 1 specifies a Makefile with `up`, `down`, `test` and `fresh`, and
slice 1's acceptance test is phrased as `make fresh && make up`.

`make` is not installed on this machine and is not native to Windows. Since the build
machine is also the demo machine (ADR 0006), "install GNU make first" would become a
prerequisite of the demo itself — and `docs/PLAN.md` R3 flagged the runner as a
decision that must be made before slice 1's acceptance test can run at all.

Two smaller environment facts were settled at the same time and belong here rather
than in three separate records.

## Decision
**`python tasks.py <command>`** replaces the Makefile: `doctor`, `up`, `down`, `fresh`,
`test`, `migrate`. Plain Python, no install step, identical on every machine.

It does two things a Makefile would not:

- **`test` starts Postgres and waits for health before invoking pytest**, so tests
  marked `requires_db` actually run instead of silently skipping. A silently skipped
  test is the same failure mode as the silently dead guard hook.
- **`doctor`** reports interpreter version, Docker engine, database reachability and
  available memory, so an environment problem reads as a message rather than as a
  mysterious failure at 3am.

**Native Python is pinned to 3.11** (`requires-python = ">=3.11,<3.12"`) to match the
api image. This box also has 3.10 and 3.13; running a different interpreter natively
than the one that ships is the divergence ADR 0006's two-path test exists to catch.

**Postgres publishes on 5433, not 5432**, because a pre-existing `postgresql-x64-17`
Windows service already holds 5432 on this machine. It binds to `127.0.0.1` only —
there is no authentication slice yet (threats EXT-01, EXT-04).

## Consequences
- `BOOTSTRAP.md`'s `make fresh && make up` phrasing is superseded; PLAN.md and
  STATUS.md carry the current commands.
- Anyone reading BOOTSTRAP first will type `make` and get nothing. Accepted: the
  alternative is a demo prerequisite that has to be installed on the demo machine.
- 5433 is non-standard and must be stated wherever the database is described. The
  alternative — stopping the user's existing Postgres 17 service — is more invasive
  and reversible only by them.
