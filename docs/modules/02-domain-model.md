# 02 — Domain model

> Status: **complete.** Migration `0003_domain_model`, 61 tests green.

## What it does

Twelve tables covering the organizational structure (organization, jurisdiction, post,
app_user), the case record (case_record, party, case_assignment), documents
(document, document_version), the pipeline (processing_job), and the two things that
make the rest defensible: access_grant and audit_event.

Alongside them sits `domain/` — pure Python that imports no framework. It holds the
case state machine and the audit chain arithmetic, both unit-tested with no database
and no application running.

## Why this design

**Two axes, not one status column.** A `document_version` carries `lifecycle_state`
(active / superseded / disposed) and `access_class` (normal / sealed) independently,
because a document can be sealed *and* superseded simultaneously. Collapsing them into
one status is the classic modelling error here, and it makes `verify()` unable to
distinguish a lawfully disposed document from a tampered one — which is both a
correctness bug and a legal misrepresentation.

**Assignments are append-only with a validity window.** `case_assignment` carries
`valid_from` / `valid_to` rather than being deleted on un-assignment. Anyone who can
assign officers to cases can designate themselves, read, and un-designate — completely
lawfully at every instant (threat INS-09). A window makes that cycle permanently
visible, and makes revocation a data change rather than a schema change later.

**Grants are always case-scoped.** `access_grant` is (grantee, case, purpose, expiry,
granted_by), per ADR 0005. There is no representation for an organization-wide grant:
no nullable `case_id`, no wildcard. One lawful grant opening every case in an
organization is the failure that choice forecloses.

**The audit table is where slice 1's two database roles pay off.** `audit_event` is
hash-chained and the migration revokes UPDATE, DELETE and TRUNCATE from the
application's role. That REVOKE only means anything because `ordin_app` does not own
the table — a table owner is not subject to REVOKE on its own table — which is why
ADR 0001 put two roles in the compose file a slice earlier.

**The state machine is data.** Transitions live in a table in `domain/case.py`, not in
a chain of conditionals, so they can be reviewed and replaced. The state names are
generic placeholders and the code says so: confirming the real Indian statutory stages
is an open question, and CLAUDE.md forbids guessing them.

## The two questions a judge will ask

**"How do I know that audit log hasn't been edited?"**

You know it has not been edited *in place* by the application, and you can see exactly
where if it was: each row commits to its predecessor, so altering one breaks every hash
after it. Two limits we state rather than wait to be asked. The digest is unkeyed, so
someone who can write the table could alter a row and recompute the rest — the control
that actually bites is that the application's database role has no UPDATE or DELETE on
that table, and does not own it. And truncating the *tail* is undetectable: the
remaining prefix is a valid chain. Catching that needs an externally witnessed head,
which this build does not have, and it is written down as accepted risk AR-4 rather
than glossed.

There is a test asserting that tail truncation still goes undetected — so if the
property ever changes, the threat model gets updated instead of quietly drifting.

**"Isn't the REVOKE just a line in a migration? How do you know it works?"**

Because removing it fails the test. The suite does not merely check that an UPDATE
raises — an UPDATE can fail for many uninteresting reasons — it queries
`information_schema.role_table_grants` directly and asserts UPDATE and DELETE are
absent while INSERT and SELECT are present, and separately asserts the application role
is not the table's owner. It also asserts the role can still write *other* tables, so
the result cannot be explained by a blanket read-only role.

That was verified by mutation: granting UPDATE and DELETE back makes three tests fail;
revoking restores them.
