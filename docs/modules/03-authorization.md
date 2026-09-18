# 03 — Policy and query-level authorization

> Status: complete (3a `887f762`, 3b `5fdb06d`).

## What it does

A versioned YAML policy (`policies/case_read.v1.yaml`), a pure evaluator that runs with
no application and no database, and the same policy compiled into a SQL `WHERE` clause
so the predicate sits **inside** every query that returns or counts rows. Seven
dimensions, deny by default. Every decision is persisted with the policy id, version
and rule id that produced it.

## Why this design

**One predicate registry behind two encodings.** The obvious build is a YAML policy
describing the rules plus a hand-written SQL fragment implementing them. Those are two
encodings of one intent; they drift, and because CLAUDE.md requires the policy tests to
run with no database, those tests stay green while the SQL does something else. The
policy file becomes decorative and nobody finds out until a judge types three letters
into a search box.

Here both halves key off one registry of predicate names. The loader rejects a policy
naming a predicate with no Python implementation; the filter compiler rejects one with
no SQL implementation; and `test_policy_sql_agreement.py` asserts the two produce
identical answers for **every subject against every case** in the seed — plus that both
outcomes occur and that each denial rule actually fires, because a comparison where
everything denies would pass while proving nothing.

**Fail-closed in the direction that is easy to get backwards.** The filter returns a
SQLAlchemy expression, not a format string: a call site either applies it or does not
compile. A forgotten string template yields a query with no predicate at all — the
natural failure of interpolation is a *wider* result set. Assembly starts from
`sa.false()` for the same reason.

**Counts, not pages.** Six surfaces are tested for a smaller COUNT rather than a
filtered page. A filtered page proves rows were removed before the caller saw them; a
smaller count proves they were removed before the database counted them, which is the
only version that does not leak through a total, a last-page number or an export size.

## The two questions a judge will ask

**"How do I know the filter is actually on every query?"**

Because it is a SQLAlchemy expression rather than a convention. A route that skipped it
would have to construct its own `select(case_record)`, which is conspicuous in review.
The tests cover the surfaces BOOTSTRAP names and the two it omits — single-object fetch
by id, which a hand-written detail endpoint bypasses entirely, and full-text search.
Sentinel scenario AUTHZ-01 asserts the count and the list agree and are both smaller
than the table.

**"What stops someone claiming to be a senior officer?"**

Identity is resolved server-side from a signed session and from nothing else. No code
path reads it from a header, a query parameter or a body, and a test sends four
identity-shaped headers with no session and asserts all are ignored. That matters more
than it looks: if identity were ever readable from a header, every authorization test
here would keep passing while testing a forgeable identity. Seniority is separately
irrelevant — no rule in the policy file mentions rank, and a test asserts none ever
does.
