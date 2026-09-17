"""The case state machine, as pure logic.

No database, no application, no framework — the point of keeping the domain layer
framework-free is that rules like these are testable in milliseconds and stay
testable when the persistence layer changes underneath them.

Invariant 2 applies: an unrecognised or unmatched transition denies. A state machine
that shrugs and allows is a state machine that lets a closed case reopen itself.
"""
import pytest

from domain.case import ALLOWED_TRANSITIONS, InvalidTransition, can_transition, transition
from domain.enums import CaseState


def test_every_state_appears_in_the_transition_table():
    """A state missing from the table would deny every move out of it, silently."""
    for state in CaseState:
        assert state in ALLOWED_TRANSITIONS, f"{state} has no entry in ALLOWED_TRANSITIONS"


def test_the_ordinary_progression_is_permitted():
    assert can_transition(CaseState.REGISTERED, CaseState.UNDER_INVESTIGATION)
    assert can_transition(CaseState.UNDER_INVESTIGATION, CaseState.FILED)
    assert can_transition(CaseState.FILED, CaseState.IN_TRIAL)
    assert can_transition(CaseState.IN_TRIAL, CaseState.CLOSED)


def test_a_case_can_be_closed_from_any_open_state():
    """Cases end early for many lawful reasons; the machine must not trap them open."""
    for state in CaseState:
        if state is CaseState.CLOSED:
            continue
        assert can_transition(state, CaseState.CLOSED), f"{state} cannot be closed"


def test_closed_is_terminal():
    for target in CaseState:
        assert not can_transition(CaseState.CLOSED, target), (
            f"a closed case was allowed to move to {target}"
        )


def test_stages_cannot_be_skipped():
    assert not can_transition(CaseState.REGISTERED, CaseState.IN_TRIAL)
    assert not can_transition(CaseState.REGISTERED, CaseState.FILED)
    assert not can_transition(CaseState.UNDER_INVESTIGATION, CaseState.IN_TRIAL)


def test_a_case_cannot_move_backwards():
    assert not can_transition(CaseState.FILED, CaseState.UNDER_INVESTIGATION)
    assert not can_transition(CaseState.IN_TRIAL, CaseState.FILED)


def test_a_state_is_not_a_transition_to_itself():
    for state in CaseState:
        assert not can_transition(state, state), f"{state} allowed a no-op transition"


def test_transition_raises_rather_than_returning_a_sentinel():
    """The caller must not be able to ignore a refusal by forgetting to check."""
    with pytest.raises(InvalidTransition) as exc:
        transition(CaseState.CLOSED, CaseState.IN_TRIAL)
    assert "closed" in str(exc.value).lower()


def test_transition_returns_the_new_state_on_success():
    assert transition(CaseState.REGISTERED, CaseState.UNDER_INVESTIGATION) is (
        CaseState.UNDER_INVESTIGATION
    )


def test_an_unknown_state_denies_rather_than_erroring_open():
    """Invariant 2. A value from outside the enum must not be treated as permissive."""
    assert not can_transition("not_a_state", CaseState.CLOSED)  # type: ignore[arg-type]
    assert not can_transition(CaseState.REGISTERED, "not_a_state")  # type: ignore[arg-type]
    assert not can_transition(None, None)  # type: ignore[arg-type]
