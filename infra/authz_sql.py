"""The SQL half of the predicate registry.

Security invariant 1: the authorization predicate goes **inside the data query** —
before scoring, ranking, pagination, aggregation, COUNT, export and autocomplete. Not
after. Post-filtering leaks through result counts, page behaviour and suggestion
lists, and three letters in an autocomplete box must never surface a name from a case
the caller cannot open.

Two design choices here are load-bearing.

**Composable expressions, not a format string.** `case_read_filter()` returns a
SQLAlchemy `ColumnElement`, so a call site either applies it to a `select()` or it
does not compile. A `"... WHERE {alias}.id = ..."` template, by contrast, can be
forgotten — and a query with the predicate forgotten returns *everything*. The
natural failure of string interpolation is a wider result set, which is invariant 2
inverted at the worst possible place.

**Fail closed on construction.** If a policy names a predicate with no SQL
implementation, `case_read_filter` raises rather than skipping the condition. An
unknown predicate that silently evaluated to "no restriction" would widen the query;
one that raises cannot reach a request at all. And the AND/OR assembly below never
starts from an empty list: `sa.false()` is the identity it builds up from, so a rule
set that somehow produced no conditions denies rather than admitting everything
(threat AZM-08).
"""
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement

from domain.policy import Effect, Policy
from domain.subject import CLEARANCE_SEALED, Subject


class UnsupportedPredicate(Exception):
    """A policy predicate with no SQL implementation.

    Raised when the filter is built, which is before any row is read.
    """


def _assignment_active(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    a = tables["case_assignment"]
    return sa.exists(
        sa.select(sa.literal(1)).where(
            a.c.case_id == case.c.id,
            a.c.user_id == sa.literal(s.user_id),
            a.c.valid_from <= sa.func.now(),
            # valid_to IS NULL means "no end date", which is in force. Writing
            # `valid_to > now()` instead would deny every permanent assignment.
            sa.or_(a.c.valid_to.is_(None), a.c.valid_to > sa.func.now()),
        )
    )


def _same_organization(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    return case.c.organization_id == sa.literal(s.organization_id)


def _same_jurisdiction(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    return case.c.jurisdiction_id == sa.literal(s.jurisdiction_id)


def _grant_active(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    g = tables["access_grant"]
    return sa.exists(
        sa.select(sa.literal(1)).where(
            g.c.case_id == case.c.id,
            g.c.grantee_id == sa.literal(s.user_id),
            g.c.expires_at > sa.func.now(),
            g.c.revoked_at.is_(None),
        )
    )


def _grant_not_self_issued(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    """True when no self-issued grant is the thing carrying this access.

    Expressed as "there exists a grant that is not self-issued" rather than
    "not exists a self-issued grant", so holding one lawful grant and one
    self-issued grant does not deny the lawful one.
    """
    g = tables["access_grant"]
    return sa.exists(
        sa.select(sa.literal(1)).where(
            g.c.case_id == case.c.id,
            g.c.grantee_id == sa.literal(s.user_id),
            g.c.expires_at > sa.func.now(),
            g.c.revoked_at.is_(None),
            g.c.granted_by != g.c.grantee_id,
        )
    )


def _case_is_sealed(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    return case.c.access_class == sa.literal("sealed")


def _clearance_current(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    """A property of the subject, not of the row, so it lifts to a constant.

    `at` is passed in rather than read from the clock here, so the SQL side and the
    Python evaluator are answering the question at the same instant — otherwise the
    agreement test could fail on a clearance that lapses between the two calls.

    The subject is re-resolved server-side on every request. A clearance captured at
    login and cached for the session would let a lapsed one keep working (threats
    INS-13, AZM-06).
    """
    return sa.true() if s.clearance_is_current(at) else sa.false()


def _clearance_permits_sealed(
    s: Subject, case: sa.Table, tables: dict, at: datetime
) -> ColumnElement:
    return (
        sa.true()
        if s.clearance_is_current(at) and s.clearance_level >= CLEARANCE_SEALED
        else sa.false()
    )


def _subject_is_active(s: Subject, case: sa.Table, tables: dict, at: datetime) -> ColumnElement:
    return sa.true() if s.is_active else sa.false()


# Keyed by exactly the names in domain/predicates.REGISTRY. A test asserts the two
# key sets are identical, so a predicate added to one side and not the other is a
# test failure rather than a policy that behaves differently in SQL.
SQL_REGISTRY = {
    "assignment_active": _assignment_active,
    "same_organization": _same_organization,
    "same_jurisdiction": _same_jurisdiction,
    "grant_active": _grant_active,
    "grant_not_self_issued": _grant_not_self_issued,
    "case_is_sealed": _case_is_sealed,
    "clearance_current": _clearance_current,
    "clearance_permits_sealed": _clearance_permits_sealed,
    "subject_is_active": _subject_is_active,
}


def case_read_filter(
    policy: Policy, subject: Subject, case: sa.Table, tables: dict, at: datetime
) -> ColumnElement:
    """Compile a policy into a WHERE clause over `case`.

    First-match-wins rule order becomes, in SQL, an expression evaluated over each
    candidate row:

        allowed(row) = OR over allow rules of (rule holds AND no earlier deny holds)

    Built from `sa.false()` so an empty rule set denies rather than admitting
    everything.
    """
    for rule in policy.rules:
        for condition in rule.conditions:
            if condition.predicate not in SQL_REGISTRY:
                raise UnsupportedPredicate(
                    f"policy {policy.policy_id!r} rule {rule.id!r} names predicate "
                    f"{condition.predicate!r}, which has no SQL implementation"
                )

    def expr(condition) -> ColumnElement:
        built = SQL_REGISTRY[condition.predicate](subject, case, tables, at)
        return sa.not_(built) if condition.negated else built

    allowed: ColumnElement = sa.false()
    denials_so_far: list[ColumnElement] = []

    for rule in policy.rules:
        if not rule.conditions:
            # Terminal unconditional deny: nothing after it can allow.
            if rule.effect is Effect.DENY:
                break
            continue

        conjunction = sa.and_(*[expr(c) for c in rule.conditions])

        if rule.effect is Effect.DENY:
            denials_so_far.append(conjunction)
            continue

        # An allow only fires when no earlier deny matched this row.
        guard = sa.and_(*[sa.not_(d) for d in denials_so_far]) if denials_so_far else sa.true()
        allowed = sa.or_(allowed, sa.and_(guard, conjunction))

    return allowed
