# 01 — Skeleton

> Status: **1a landed** (commit `6e8f63a`). 1b — worker, Next.js health page, three
> Dockerfiles, four-container compose run — not yet built.

## What it does

Brings up a Postgres 16 container and a FastAPI application, applies an Alembic
baseline, and exposes `GET /health`, which checks every declared dependency and
reports each one's status and latency. Structured JSON logs carry a correlation id
that a caller can supply and that is echoed back, so one request can be traced across
processes. `python tasks.py` drives all of it: `doctor`, `up`, `down`, `fresh`, `test`,
`migrate`.

No business logic, no domain model, no authorization. Those start at slice 2.

## Why this design

**Two database roles, from the first commit.** `ordin_owner` owns the schema and runs
migrations; `ordin_app` connects, reads and writes rows, and owns nothing. This is not
tidiness — it is the precondition for security invariant 10. Audit rows are meant to be
append-only, enforced by revoking UPDATE and DELETE from the application's role, and
**a table owner is not subject to REVOKE on its own table**. With a single role, slice
2's audit-immutability test would pass while the control did nothing. Asserting the
separation in slice 1, before any audit table exists, means a later collapse back to
one role fails immediately instead of silently. (ADR 0001.)

**`/health` fails closed.** An unreachable dependency returns 503, never 200 with an
"unknown" status — invariant 2. Failure reasons come from a fixed enumeration
(`unreachable`, `auth_failed`, `timeout`, `error`) rather than the driver's exception
text, because an asyncpg connection error carries the host, user and sometimes the DSN
itself. Passwords are `SecretStr`, so only a `***`-masked DSN is ever logged
(invariant 12).

**Uvicorn's access logger is disabled.** It records the full request line including the
query string, so the first `GET /search?q=…` would write a protected identifier to a
log file — threat LOG-01. Our middleware logs method, path, status and duration, and
deliberately not the query string. Slice 1 sets the pattern every later slice copies,
which is why this is fixed here rather than discovered at slice 5.

**Hybrid dev loop** (ADR 0006) and **`tasks.py` instead of `make`** (ADR 0007) follow
from one 8 GB machine being both the build and demo machine.

## The two questions a judge will ask

**"Your audit log is hash-chained — doesn't that just mean you can detect tampering
after the fact, not prevent it?"**

Correct, and we are precise about it. The chain makes the audit log tamper-**evident**,
not tamper-proof, and only for rows written through the application: a direct database
write produces no audit row at all. What slice 1 adds is the part most projects skip —
the application cannot own its own audit tables, so the REVOKE that makes rows
append-only actually binds. Against a database administrator it still does not, and
that is written down as accepted risk AR-3 rather than claimed away. The honest fix is
an externally witnessed chain head, which needs infrastructure outside a hackathon
scope (AR-4).

**"Why is a health endpoint worth a slice?"**

It is not — the dependency it proves is. `/health` is the first place the fail-closed
rule gets tested (503, not a shrug), the first place the no-credentials-in-output rule
gets tested, and the first place the two database roles are asserted. Those three
behaviours are copied by every slice after it. The endpoint is a side effect; the
acceptance test for it is the point, and it was written and watched fail before the
implementation existed.
