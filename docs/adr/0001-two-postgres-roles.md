# 0001 — Two Postgres roles, provisioned in slice 1

## Context
Security invariant 10 requires audit rows to be append-only, with UPDATE and DELETE
revoked from the application role in the migration, and slice 2's acceptance test is
"prove the app role cannot UPDATE an audit row".

In a default compose there is one Postgres role. It owns the schema (Alembic runs as
it) and it is also the application's runtime connection. **A table owner is not subject
to REVOKE on its own table.** The REVOKE would therefore be a no-op and the acceptance
test would pass while proving nothing — the control is void and its test is green.

## Decision
Provision two roles in slice 1, not slice 2: an owner/migration role that Alembic uses,
and a restricted runtime role the api and worker connect as. Two DSNs, set in compose
and in the Alembic config. The REVOKE in the slice 2 migration targets the runtime role
and extends to `AnchorRecord`, which BOOTSTRAP lists as an ordinary table.

The slice 2 test must fail if the REVOKE is removed. A test that cannot fail is not a test.

## Consequences
- Slice 1 grows (~30 min) and slice 2's acceptance test becomes meaningful.
- Owner and superuser remain unaffected by design: a grant cannot restrain the principal
  that issues grants. Recorded as accepted risk AR-3 in `docs/THREAT-MODEL.md`.
- The audit chain is tamper-**evident**, not tamper-**proof**, and only for rows written
  through the application. A direct database write produces no audit row at all (PRV-09).
- No runtime check detects grant drift if someone re-grants later.
