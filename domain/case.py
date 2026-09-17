"""Case state machine.

Transitions are **data**, not a chain of conditionals, for the same reason
authorization policy is data: they are the part most likely to be wrong, and data can
be reviewed, diffed and unit-tested without the application running.

The state names are generic procedural stages, not Indian statutory ones. CLAUDE.md
forbids guessing statutory behaviour and this table is deliberately easy to replace
once the real stages are confirmed against a source.
"""
from domain.enums import CaseState


class InvalidTransition(Exception):
    """Raised rather than returned, so a caller cannot ignore a refusal."""


# Every state must appear as a key, including terminal ones with an empty set.
# A missing key would deny every move out of that state, silently.
ALLOWED_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.REGISTERED: frozenset({CaseState.UNDER_INVESTIGATION, CaseState.CLOSED}),
    CaseState.UNDER_INVESTIGATION: frozenset({CaseState.FILED, CaseState.CLOSED}),
    CaseState.FILED: frozenset({CaseState.IN_TRIAL, CaseState.CLOSED}),
    CaseState.IN_TRIAL: frozenset({CaseState.CLOSED}),
    CaseState.CLOSED: frozenset(),
}


def can_transition(current: CaseState, target: CaseState) -> bool:
    """Is this move permitted?

    Fails closed (invariant 2): anything not recognisably a CaseState — a string from
    a request body, a None from a half-populated row — denies rather than raising or,
    worse, passing.
    """
    if not isinstance(current, CaseState) or not isinstance(target, CaseState):
        return False
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def transition(current: CaseState, target: CaseState) -> CaseState:
    """Apply a transition, or refuse loudly."""
    if not can_transition(current, target):
        raise InvalidTransition(
            f"a case in state {current!r} may not move to {target!r}; "
            f"permitted: {sorted(ALLOWED_TRANSITIONS.get(current, frozenset()))}"
        )
    return target
