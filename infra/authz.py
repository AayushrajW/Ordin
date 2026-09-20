"""Loading a subject, loading case facts, and the authorized query.

The two paths that must agree:

  `load_case_facts` + `Policy.evaluate`  — a point decision about one case, used
      when something must be explained: which rule fired, under which policy id.

  `authorized_cases`                     — the same policy compiled into a WHERE
      clause, used for every *set* operation: list, COUNT, export, autocomplete,
      search, and single-object fetch.

Invariant 1 requires the second for anything that returns or counts rows, because
post-filtering leaks through counts, page behaviour and suggestion lists. Invariant 3
requires the first to log a policy id. Having both means they can disagree, which is
why `tests/test_policy_sql_agreement.py` asserts they never do over the seeded data.
"""
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.sql import Select

from domain.policy import Decision, Policy
from domain.subject import CaseFacts, Subject
from infra.authz_sql import case_read_filter
from infra.tables import AUTHZ_TABLES, access_grant, app_user, case_assignment, case_record, post


async def load_subject(conn, user_id: str) -> Subject | None:
    """Resolve the seven dimensions from the database, server-side.

    Organization and jurisdiction come from the post held *now*, not from anything
    the caller supplied. A request header that looks like identity is never an input
    to this (threat EXT-02).
    """
    row = (
        await conn.execute(
            sa.select(
                app_user.c.id,
                app_user.c.post_id,
                app_user.c.clearance_level,
                app_user.c.clearance_valid_to,
                app_user.c.is_active,
                post.c.organization_id,
                post.c.jurisdiction_id,
                post.c.is_administrative,
            )
            .select_from(app_user.join(post, post.c.id == app_user.c.post_id))
            .where(app_user.c.id == user_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return Subject(
        user_id=str(row.id),
        post_id=str(row.post_id),
        organization_id=str(row.organization_id),
        jurisdiction_id=str(row.jurisdiction_id),
        clearance_level=row.clearance_level,
        clearance_valid_to=row.clearance_valid_to,
        is_active=row.is_active,
        post_is_administrative=bool(row.is_administrative),
    )


async def load_case_facts(conn, subject: Subject, case_id: str, at: datetime) -> CaseFacts | None:
    """Everything the policy may see about one case, for this subject.

    Computed with the same definitions the SQL predicates use - `valid_to IS NULL`
    counts as in force, an expired or revoked grant does not, and a self-issued grant
    is identified by issuer equal to grantee.
    """
    case_row = (
        await conn.execute(
            sa.select(
                case_record.c.id,
                case_record.c.organization_id,
                case_record.c.jurisdiction_id,
                case_record.c.access_class,
            ).where(case_record.c.id == case_id)
        )
    ).one_or_none()
    if case_row is None:
        return None

    assignment_active = bool(
        (
            await conn.execute(
                sa.select(sa.literal(1)).where(
                    case_assignment.c.case_id == case_id,
                    case_assignment.c.user_id == subject.user_id,
                    case_assignment.c.valid_from <= at,
                    sa.or_(
                        case_assignment.c.valid_to.is_(None),
                        case_assignment.c.valid_to > at,
                    ),
                )
            )
        ).first()
    )

    grants = (
        await conn.execute(
            sa.select(access_grant.c.granted_by, access_grant.c.grantee_id, access_grant.c.purpose)
            .where(
                access_grant.c.case_id == case_id,
                access_grant.c.grantee_id == subject.user_id,
                access_grant.c.expires_at > at,
                access_grant.c.revoked_at.is_(None),
            )
        )
    ).all()

    # "Active" means at least one live grant exists. "Not self-issued" means at least
    # one live grant was issued by somebody else - holding a lawful grant and a
    # self-issued one must not deny the lawful one.
    usable = [g for g in grants if str(g.granted_by) != str(g.grantee_id)]

    return CaseFacts(
        case_id=str(case_row.id),
        organization_id=str(case_row.organization_id),
        jurisdiction_id=str(case_row.jurisdiction_id),
        is_sealed=case_row.access_class == "sealed",
        assignment_active=assignment_active,
        grant_active=bool(grants),
        grant_is_self_issued=bool(grants) and not usable,
        grant_purpose=usable[0].purpose if usable else None,
    )


async def decide(
    conn, policy: Policy, subject: Subject, case_id: str, at: datetime
) -> Decision:
    """A point decision, carrying the policy and rule id that produced it."""
    facts = await load_case_facts(conn, subject, case_id, at)
    if facts is None:
        # A case that does not exist and a case you cannot see are indistinguishable
        # on purpose: the alternative is an existence oracle (threat INS-04).
        return Decision(
            effect=policy.rules[-1].effect,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            rule_id="no-such-case",
            reason="not_found_or_not_permitted",
        )
    return policy.evaluate(subject, facts, at)


def authorized_cases(policy: Policy, subject: Subject, at: datetime) -> Select:
    """A SELECT over case_record with the policy already in its WHERE clause.

    Every set operation starts here. Building a query that touches case_record
    without going through this function is the bug invariant 1 exists to prevent -
    and because this returns a Select rather than a string to interpolate, the
    mistake looks like a mistake instead of like a working query.
    """
    return sa.select(case_record).where(
        case_read_filter(policy, subject, case_record, AUTHZ_TABLES, at)
    )


def authorized_case_ids(policy: Policy, subject: Subject, at: datetime) -> Select:
    return sa.select(case_record.c.id).where(
        case_read_filter(policy, subject, case_record, AUTHZ_TABLES, at)
    )
