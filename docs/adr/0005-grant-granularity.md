# 0005 — Access grants are always case-scoped

## Context
`CLAUDE.md` requires cross-organization access to be an explicit, purpose-limited,
expiring grant and never a role — but neither it nor `BOOTSTRAP.md` states what an
`AccessGrant` resolves to. The distinction is invisible in the entity list and decisive
in effect: a grant keyed to (grantee, organization) means one lawful grant issued for
one case silently opens **every** case in that organization, in perpetuity until expiry
(AZM-07 in `docs/THREAT-MODEL.md`).

Organization-wide grants are also the natural convenience implementation, which is
exactly why the choice has to be written down before slice 3 rather than discovered
during it.

## Decision
    AccessGrant = (grantee, case_id, purpose, expiry, granted_by)

Grants are **always case-scoped**. Organization-wide grants do not exist in this system
— not as a table, not as a nullable `case_id`, not as a wildcard value. There is no
representation for one.

A denial test asserting that organization-wide access is refused goes in slice 3,
alongside the existing denial tests for a non-designated officer, an expired grant, a
cross-organization read and an unclearanced sealed read.

## Consequences
- Granting access to twelve cases means twelve rows. Accepted: the audit and revocation
  story is per case, which is the unit a court and a supervisor both reason about.
- `granted_by` makes issuance attributable, which is what makes the self-issued-grant
  path (INS-10) detectable after the fact. Two-person approval is still cut, so it stays
  detective rather than preventive — the policy test asserting issuer and grantee differ
  is the cheap partial.
- A nullable `case_id` must never be added later as a convenience. If organization-wide
  grants are ever genuinely needed, they are a new entity with their own policy rules and
  their own denial tests, not a relaxation of this one.
