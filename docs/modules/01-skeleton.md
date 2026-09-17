# 01 — Skeleton

> Status: **complete.** 1a `6e8f63a`, 1b `72bca85`. Both acceptance paths verified on
> the build machine: `dev` (native processes) and `compose` (four containers).

## What it does

Brings up Postgres, a FastAPI api, a worker and a Next.js web tier, applies an Alembic
baseline, and exposes `GET /health`, which checks three dependencies — database,
migrations, worker — and reports each one's status and latency. The web page renders
them. Structured JSON logs carry a correlation id that a caller can supply and that is
echoed back, so one request can be traced across processes. `python tasks.py` drives all
of it: `doctor`, `up`, `down`, `fresh`, `test`, `migrate`, `worker`, `verify-compose`.

The worker has no jobs until slice 5a. It writes a `system_heartbeat` row on a loop so
that `/health`'s worker check is meaningful rather than decorative: green proves the
process is alive *and* that it can reach the database as `ordin_app`. `system_heartbeat`
is infrastructure, not a domain entity.

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

**Telemetry off, and asserted rather than configured.** Next.js posts anonymous
telemetry by default, which breaks invariant 11's "no external network calls on the demo
path" — and at an air-gapped venue it fails visibly. There is no config key for this:
writing `telemetry: false` in `next.config.mjs` is silently ignored, which is the worst
kind of fix. Only `NEXT_TELEMETRY_DISABLED=1` works, so it is set in every Dockerfile
stage and in compose, and `tasks.py verify-compose` asserts it *inside the running
container*. No `next/font/google` anywhere; a CSP permits no external origins.

**Hybrid dev loop** (ADR 0006) and **`tasks.py` instead of `make`** (ADR 0007) follow
from one 8 GB machine being both the build and demo machine — though see ADR 0006's
postscript: the four-container path measures 203 MiB at idle, so the capacity argument
for the hybrid loop did not survive measurement. The ergonomics argument did.

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
