# 0025 — Administration is an office, and it reads no case

## Context
P3 needed screens to place accounts, designate officers and issue grants. An
administration surface is the single most likely place in this codebase for the rule the
whole authorization model exists to refuse — seniority as a route to evidence — to be
written, because there it arrives looking like a convenience.

CLAUDE.md forbids hand-rolled role conditionals in application code anywhere. The
obvious implementation, `app_user.is_admin` plus a check in each route, would have moved
that forbidden conditional into the database and kept it in the code.

## Decision

**`post.is_administrative`, not `app_user.is_admin`.** Administration is an office. It
outlives its holder, which is the same distinction the model already draws between
identity and post (threat DIM-03), and a transfer moves the capability with the job
rather than following the person.

**Decided by policy.** `policies/admin.v1.yaml` is a versioned file with the same shape
as `case_read`: denials first, one ground for access, a terminal unconditional deny the
loader insists on. `require_admin` evaluates it and logs the policy and rule id that
decided, exactly as case access does. The predicate exists in both registries, so
`test_policy_sql_agreement` keeps them honest.

**It grants no case access, and that is checked structurally.** `ordin.admin` names no
predicate that reads the case, and a test asserts the intersection with the case-reading
predicates is empty — so adding `same_organization` to that policy fails the suite rather
than silently turning administration into organization-scoped case access. The evaluator
is handed a placeholder `CaseFacts`, so a rule that read the case would be deciding on
nothing real.

**404, not 403.** Whether this system has an administration surface, and whether you are
close to reaching it, are not facts an ordinary account needs.

**Placing is not designating.** Giving an account a post makes it usable and opens no
case. Two steps, because collapsing them is how "I gave them an account" becomes "I gave
them the evidence".

## Consequences
- An administrator signs in and sees **zero cases**. This looks like a bug and is the
  control working; the screens say so, and `tasks.py admin` prints it at creation time.
- **One bounded disclosure, recorded rather than hidden.** `GET /admin/cases` returns
  case references and states so a case can be picked for assignment. That is metadata
  about cases the administrator cannot open. Accepted as **AR-19**: assignment is
  unusable without it, and the alternative — typing a reference blind — moves the same
  knowledge into the administrator's head without removing it.
- **AR-14 is answered.** "No way to answer *who currently has access to this case, and
  why*" now has `GET /admin/access`, covering both routes that exist.
- Placing an account is **not** appended to the audit chain. Invariant 4 fixes a row's
  shape around a case, and placement belongs to no case; widening the chain to carry
  case-less rows would change the thing whose narrowness is the point. It is logged
  instead, and named as a gap in `docs/PLAN-PRODUCT.md`.
- Ending a designation closes its validity window rather than deleting the row. An
  assignment that once existed is part of the record of who could see what, and when.
