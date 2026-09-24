"""The subject of an authorization decision, and the facts a case presents to it.

Pure value objects. No framework, no database, no ORM — which is what lets the policy
evaluator be unit-tested with neither the application nor postgres running, as
CLAUDE.md requires.

`Subject` deliberately carries the *seven dimensions* as separate fields rather than a
role. Roles grant capabilities; they are not the model. There is no `role` attribute
here and there should never be one.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Subject:
    """Who is asking, resolved server-side from a signed session — never from a header.

    `identity` and `post` are two dimensions, not one (threat DIM-03). A post is an
    office and outlives its holder; assignments and grants key on the *user*, and
    organization and jurisdiction come from the post held at request time.
    """

    user_id: str
    post_id: str
    organization_id: str
    jurisdiction_id: str
    clearance_level: int
    clearance_valid_to: datetime | None
    is_active: bool = True

    # Administration is a property of the **post**, not of the person (migration 0009).
    # An office outlives its holder, which is the same reason identity and post are two
    # dimensions here and not one. Carried on the subject so the policy evaluator can
    # read it through a predicate: `if user.is_admin` in a route is the hand-rolled
    # check CLAUDE.md forbids by name, and a column called `is_admin` would only have
    # moved it into the database.
    post_is_administrative: bool = False

    def clearance_is_current(self, at: datetime) -> bool:
        """Clearance carries its own clock, independent of assignment and grant.

        A lapsed clearance is one of three validity windows that can expire
        separately (threat AZM-06), and the effective permission is their
        intersection, not their union.
        """
        if not self.is_active:
            return False
        if self.clearance_valid_to is None:
            return True
        return self.clearance_valid_to > at


@dataclass(frozen=True)
class CaseFacts:
    """What the resource presents. Deliberately not the ORM row.

    The evaluator sees only these fields, so a policy can never accidentally depend
    on something that is not part of the authorization surface.
    """

    case_id: str
    organization_id: str
    jurisdiction_id: str
    is_sealed: bool

    # Assignment: is there an in-force designation for this subject on this case?
    assignment_active: bool = False

    # Grant: case-scoped, unexpired, unrevoked, and not self-issued.
    grant_active: bool = False
    grant_is_self_issued: bool = False
    grant_purpose: str | None = None

    # Break-glass: an unexpired declaration by this subject on this case (ADR 0029).
    # It is a fact about the *subject's relationship to the case*, like the other two,
    # and it is deliberately not a ground for access - the only rule that reads it is
    # the sealed-record deny, so it removes an obstacle and never opens a door.
    break_glass_active: bool = False


# Clearance levels. Ordinal rather than a flag, so "beyond ordinary clearance" for
# sealed records is a comparison and not a second boolean to keep in sync.
CLEARANCE_ORDINARY = 1
CLEARANCE_SEALED = 3
