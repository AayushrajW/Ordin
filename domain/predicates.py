"""The named predicates a policy file may reference.

**This registry is the single source of truth for what a predicate means.** A policy
rule names a predicate; the evaluator looks it up here. `infra/authz_sql.py` supplies
the SQL expression for the same name, and `test_policy_sql_agreement.py` asserts the
two produce identical answers over the seeded data.

That agreement test is the point of the whole arrangement. The obvious way to build
this — a YAML file describing the rules and a separate hand-written SQL fragment
implementing them — gives two encodings that drift silently, and the policy tests run
with no database, so they stay green while the SQL does something else. Here the names
are shared, the loader rejects a policy naming a predicate that does not exist, and a
test proves the two sides agree case by case.

Pure Python: no SQLAlchemy, no framework. Everything is testable with nothing running.
"""
from datetime import datetime
from typing import Callable

from domain.subject import CLEARANCE_SEALED, CaseFacts, Subject

Predicate = Callable[[Subject, CaseFacts, datetime], bool]


def _assignment_active(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Case designation is decisive. Seniority does not imply access."""
    return c.assignment_active


def _same_organization(s: Subject, c: CaseFacts, at: datetime) -> bool:
    return s.organization_id == c.organization_id


def _same_jurisdiction(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Separate from organization, and deliberately so.

    A prosecutor and an officer can share a jurisdiction and not an organization;
    a transferred case can leave a jurisdiction without changing organization.
    """
    return s.jurisdiction_id == c.jurisdiction_id


def _grant_active(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Case-scoped, unexpired, unrevoked. Organization-wide grants do not exist
    in this system at all — see docs/adr/0005 — so there is nothing to check for."""
    return c.grant_active


def _grant_not_self_issued(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Issuing yourself a grant is lawful at every instant and is the cheapest
    insider path in the design (threat INS-10). Two-person approval was cut, so
    this is the affordable partial: the issuer may not be the grantee."""
    return not c.grant_is_self_issued


def _case_is_sealed(s: Subject, c: CaseFacts, at: datetime) -> bool:
    return c.is_sealed


def _clearance_current(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Clearance has its own validity window, checked at request time.

    A cached clearance string captured at login would let a lapsed clearance keep
    working for the life of the session (threats INS-13, AZM-06).
    """
    return s.clearance_is_current(at)


def _clearance_permits_sealed(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Sealed records require authorization beyond ordinary clearance."""
    return s.clearance_is_current(at) and s.clearance_level >= CLEARANCE_SEALED


def _break_glass_active(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Has this subject declared an unexpired exception to this case's seal?

    Read by exactly one rule - the sealed-record deny - and by nothing else. That is
    the whole design: break-glass subtracts an obstacle from a path the subject already
    had, and is never itself a ground for access. A policy that used this predicate in
    an `allow` rule would turn a written excuse into a master key.
    """
    return c.break_glass_active


def _subject_is_active(s: Subject, c: CaseFacts, at: datetime) -> bool:
    return s.is_active


def _post_is_administrative(s: Subject, c: CaseFacts, at: datetime) -> bool:
    """Does the subject hold an administrative office?

    Reads the post, never the person. An administrative post confers the ability to
    place other people; it confers **no case access whatsoever**, which is why no rule
    in ordin.case_read mentions it. Seniority and administration are both ways of
    saying "important", and neither opens a case you are not designated on.
    """
    return s.post_is_administrative


REGISTRY: dict[str, Predicate] = {
    "assignment_active": _assignment_active,
    "same_organization": _same_organization,
    "same_jurisdiction": _same_jurisdiction,
    "grant_active": _grant_active,
    "grant_not_self_issued": _grant_not_self_issued,
    "case_is_sealed": _case_is_sealed,
    "clearance_current": _clearance_current,
    "clearance_permits_sealed": _clearance_permits_sealed,
    "break_glass_active": _break_glass_active,
    "subject_is_active": _subject_is_active,
    "post_is_administrative": _post_is_administrative,
}


class UnknownPredicate(KeyError):
    """Raised at policy LOAD time, not at decision time.

    A policy naming a predicate that does not exist must fail when the file is read,
    not silently deny (or worse, silently skip the condition) on the first request
    that happens to reach that rule.
    """


def resolve(name: str) -> Predicate:
    if name not in REGISTRY:
        raise UnknownPredicate(
            f"policy references unknown predicate {name!r}; known: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]
