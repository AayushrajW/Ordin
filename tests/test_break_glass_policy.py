"""The break-glass policies as data, with nothing running.

CLAUDE.md: "versioned YAML policy files, a small pure evaluator, `pytest` over policies
with no app running". No database, no FastAPI, no fixtures - if one of these fails, the
rule is wrong, not the wiring.

Two files are under test and the split between them is the design:

    ordin.break_glass   may this subject DECLARE an exception to a seal?
    ordin.case_read     does an existing declaration COUNT?

The second is the one that could be catastrophic. `break_glass_active` appears there
in a **deny** rule, so it can only subtract an obstacle from a path the subject already
had. Moved into an allow rule it would become a master key: a written excuse that opens
any sealed case in the system. `test_break_glass_is_never_a_ground_for_access` asserts
that placement structurally, over the file, so a future edit that promotes it is a test
failure rather than a discovery.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domain.policy import Effect, latest_policy_path, load_policy
from domain.subject import CLEARANCE_ORDINARY, CLEARANCE_SEALED, CaseFacts, Subject

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "policies"

NOW = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
ORG = "org-police"
JUR = "jur-north"


@pytest.fixture(scope="module")
def glass():
    return load_policy(latest_policy_path(POLICIES, "break_glass"))


@pytest.fixture(scope="module")
def case_read():
    return load_policy(latest_policy_path(POLICIES, "case_read"))


def officer(*, clearance: int = CLEARANCE_ORDINARY, active: bool = True) -> Subject:
    return Subject(
        user_id="u-officer",
        post_id="p-si",
        organization_id=ORG,
        jurisdiction_id=JUR,
        clearance_level=clearance,
        clearance_valid_to=NOW + timedelta(days=365),
        is_active=active,
    )


def sealed_case(**overrides) -> CaseFacts:
    defaults = dict(
        case_id="c-1",
        organization_id=ORG,
        jurisdiction_id=JUR,
        is_sealed=True,
    )
    defaults.update(overrides)
    return CaseFacts(**defaults)


# --- who may declare ------------------------------------------------------------


def test_a_designated_officer_without_clearance_may_declare(glass):
    decision = glass.evaluate(officer(), sealed_case(assignment_active=True), NOW)
    assert decision.allowed
    assert decision.rule_id == "designated-officer"


def test_a_grantee_may_not_declare(glass):
    """The rule this file exists for.

    An external party holding a lawful, purpose-limited grant must not be able to
    self-authorize past a seal, because there is nobody upstream of them to answer for
    it. In `ordin.case_read` that same grant is a ground for access; here it is
    nothing, which is why these are two policies and not one.
    """
    decision = glass.evaluate(
        officer(), sealed_case(grant_active=True, grant_is_self_issued=False), NOW
    )
    assert not decision.allowed
    assert decision.rule_id == "default-deny"


def test_an_already_cleared_officer_may_not_declare(glass):
    decision = glass.evaluate(
        officer(clearance=CLEARANCE_SEALED),
        sealed_case(assignment_active=True),
        NOW,
    )
    assert not decision.allowed
    assert decision.rule_id == "already-cleared"


def test_an_unsealed_case_has_no_glass_to_break(glass):
    decision = glass.evaluate(
        officer(), sealed_case(is_sealed=False, assignment_active=True), NOW
    )
    assert not decision.allowed
    assert decision.rule_id == "not-sealed"


def test_a_lapsed_clearance_is_not_a_reason_to_need_it(glass):
    """The three validity clocks intersect and never union (threat AZM-06).

    An officer whose clearance has lapsed is not someone who needs an exception; they
    are someone who is out until it is renewed. Break-glass must not become the route
    that keeps a lapsed subject working.
    """
    lapsed = Subject(
        user_id="u-officer",
        post_id="p-si",
        organization_id=ORG,
        jurisdiction_id=JUR,
        clearance_level=CLEARANCE_ORDINARY,
        clearance_valid_to=NOW - timedelta(days=1),
        is_active=True,
    )
    decision = glass.evaluate(lapsed, sealed_case(assignment_active=True), NOW)
    assert not decision.allowed
    assert decision.rule_id == "lapsed-clearance"


def test_a_designation_in_another_jurisdiction_does_not_qualify(glass):
    decision = glass.evaluate(
        officer(), sealed_case(jurisdiction_id="jur-south", assignment_active=True), NOW
    )
    assert not decision.allowed


def test_an_inactive_subject_may_not_declare(glass):
    decision = glass.evaluate(
        officer(active=False), sealed_case(assignment_active=True), NOW
    )
    assert not decision.allowed
    assert decision.rule_id == "inactive-subject"


# --- what a declaration does, and what it must never do -------------------------


def test_a_declaration_lifts_the_seal_for_a_designated_officer(case_read):
    designated = sealed_case(assignment_active=True)
    assert not case_read.evaluate(officer(), designated, NOW).allowed

    with_glass = sealed_case(assignment_active=True, break_glass_active=True)
    decision = case_read.evaluate(officer(), with_glass, NOW)
    assert decision.allowed
    assert decision.rule_id == "designated-officer", (
        "access was granted by a rule other than the one the subject already "
        "qualified for; break-glass is acting as a ground for access"
    )


def test_a_declaration_alone_admits_nobody(case_read):
    """No designation, no grant, a live declaration - and still nothing."""
    decision = case_read.evaluate(officer(), sealed_case(break_glass_active=True), NOW)
    assert not decision.allowed
    assert decision.rule_id == "default-deny"


def test_a_declaration_does_not_rescue_a_self_issued_grant(case_read):
    """Two separate controls, and neither cancels the other (threat INS-10)."""
    facts = sealed_case(
        grant_active=True, grant_is_self_issued=True, break_glass_active=True
    )
    assert not case_read.evaluate(officer(), facts, NOW).allowed


def test_break_glass_is_never_a_ground_for_access(case_read):
    """Structural, over the policy file rather than over one evaluation.

    `break_glass_active` may appear only in a deny rule. A future edit that moves it
    into an allow rule turns a written excuse into a master key, and every
    example-based test above would still pass while it did.
    """
    for rule in case_read.rules:
        if any(c.predicate == "break_glass_active" for c in rule.conditions):
            assert rule.effect is Effect.DENY, (
                f"rule {rule.id!r} reads break_glass_active in an ALLOW rule. "
                "Break-glass subtracts an obstacle from a path the subject already "
                "had; it is never itself a route in."
            )


def test_the_only_reader_of_break_glass_is_the_seal_rule(case_read):
    readers = [
        rule.id
        for rule in case_read.rules
        if any(c.predicate == "break_glass_active" for c in rule.conditions)
    ]
    assert readers == ["sealed-without-clearance"], readers


def test_the_declaration_policy_never_reads_its_own_output(glass):
    """`ordin.break_glass` must not consider existing declarations.

    If it did, a live declaration would qualify the subject to declare again, and the
    bounded window - the only control here, since there is no revocation - would
    renew itself for as long as somebody kept clicking.
    """
    named = {c.predicate for rule in glass.rules for c in rule.conditions}
    assert "break_glass_active" not in named
