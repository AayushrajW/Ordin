"""The policy evaluator, with nothing running.

CLAUDE.md: "versioned policy files, unit-tested without the app running". No database,
no FastAPI, no fixtures — these run in milliseconds and would still run if the rest of
the project were deleted.

Most of this file is about **load-time** failure. A malformed policy that reaches a
request is far worse than one that refuses to start: the failure modes are a condition
that never fires, a rule that shadows everything after it, or a predicate name that
silently matches nothing. Each is a quiet widening of access, which is invariant 2
inverted.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domain.policy import Effect, PolicyError, latest_policy_path, load_policy
from domain.subject import CLEARANCE_ORDINARY, CLEARANCE_SEALED, CaseFacts, Subject

ROOT = Path(__file__).resolve().parents[1]
# Resolved, never spelled out. Five test files used to hardcode `case_read.v1.yaml`,
# so the version bump in ADR 0029 would have left the whole suite green while
# asserting against a policy the running system no longer loads.
POLICY = latest_policy_path(ROOT / "policies", "case_read")
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def subject(**overrides) -> Subject:
    base = dict(
        user_id="u1", post_id="p1", organization_id="org1", jurisdiction_id="jur1",
        clearance_level=CLEARANCE_ORDINARY, clearance_valid_to=None, is_active=True,
    )
    return Subject(**{**base, **overrides})


def case(**overrides) -> CaseFacts:
    base = dict(
        case_id="c1", organization_id="org1", jurisdiction_id="jur1", is_sealed=False,
        assignment_active=False, grant_active=False, grant_is_self_issued=False,
    )
    return CaseFacts(**{**base, **overrides})


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "p.yaml"
    path.write_text(body, encoding="utf-8")
    return path


HEAD = """
policy_id: test
version: 1
maturity: mvp
production_adapter: OPA
rules:
"""


# --- the real policy ---------------------------------------------------------

def test_the_shipped_policy_loads():
    policy = load_policy(POLICY)
    assert policy.policy_id == "ordin.case_read"
    assert policy.maturity == "mvp"
    assert policy.production_adapter == "OPA"


def test_the_shipped_policy_ends_in_an_unconditional_deny():
    assert load_policy(POLICY).rules[-1].effect is Effect.DENY


def test_no_rule_mentions_rank_or_role():
    """Roles grant capabilities; they are not the model. There is no rank predicate."""
    named = {c.predicate for r in load_policy(POLICY).rules for c in r.conditions}
    assert not any("role" in n or "rank" in n or "senior" in n for n in named), named


# --- load-time refusals ------------------------------------------------------

def test_missing_required_key_is_refused(tmp_path):
    with pytest.raises(PolicyError, match="missing required key"):
        load_policy(write(tmp_path, "policy_id: x\nversion: 1\nrules: []\n"))


def test_unknown_predicate_is_refused_at_load_not_at_decision(tmp_path):
    """A typo must fail on startup, not on the first request that reaches the rule."""
    body = HEAD + "  - id: r\n    effect: allow\n    when: [no_such_predicate]\n" \
                  "  - id: d\n    effect: deny\n"
    with pytest.raises(PolicyError, match="unknown predicate"):
        load_policy(write(tmp_path, body))


def test_unconditional_allow_is_refused(tmp_path):
    """It would match everything and make every later rule dead code."""
    body = HEAD + "  - id: oops\n    effect: allow\n  - id: d\n    effect: deny\n"
    with pytest.raises(PolicyError, match="allows unconditionally"):
        load_policy(write(tmp_path, body))


def test_a_policy_without_a_terminal_deny_is_refused(tmp_path):
    """Deny by default is a property of the file, not a hope about it."""
    body = HEAD + "  - id: r\n    effect: allow\n    when: [assignment_active]\n"
    with pytest.raises(PolicyError, match="final rule must be an unconditional deny"):
        load_policy(write(tmp_path, body))


def test_a_trailing_conditional_deny_is_refused(tmp_path):
    """A deny with conditions can fall through, which is not a default."""
    body = HEAD + "  - id: d\n    effect: deny\n    when: [case_is_sealed]\n"
    with pytest.raises(PolicyError, match="final rule must be an unconditional deny"):
        load_policy(write(tmp_path, body))


def test_an_unrecognised_effect_is_refused(tmp_path):
    body = HEAD + "  - id: r\n    effect: maybe\n    when: [assignment_active]\n" \
                  "  - id: d\n    effect: deny\n"
    with pytest.raises(PolicyError, match="expected allow or deny"):
        load_policy(write(tmp_path, body))


def test_unreadable_yaml_is_refused(tmp_path):
    with pytest.raises(PolicyError):
        load_policy(write(tmp_path, "rules: [unclosed\n"))


# --- decisions ---------------------------------------------------------------

def test_designated_officer_is_allowed():
    decision = load_policy(POLICY).evaluate(
        subject(), case(assignment_active=True), NOW
    )
    assert decision.allowed and decision.rule_id == "designated-officer"


def test_designation_alone_is_not_enough_across_an_organization():
    decision = load_policy(POLICY).evaluate(
        subject(), case(assignment_active=True, organization_id="other"), NOW
    )
    assert not decision.allowed and decision.rule_id == "default-deny"


def test_designation_alone_is_not_enough_across_a_jurisdiction():
    """A case that moves jurisdiction stops being yours even with the row intact."""
    decision = load_policy(POLICY).evaluate(
        subject(), case(assignment_active=True, jurisdiction_id="elsewhere"), NOW
    )
    assert not decision.allowed


def test_nothing_at_all_is_denied_by_the_default_rule():
    decision = load_policy(POLICY).evaluate(subject(), case(), NOW)
    assert not decision.allowed and decision.rule_id == "default-deny"


def test_a_live_grant_allows_across_organizations():
    decision = load_policy(POLICY).evaluate(
        subject(organization_id="prosecution"),
        case(grant_active=True),
        NOW,
    )
    assert decision.allowed and decision.rule_id == "purpose-limited-grant"


def test_a_self_issued_grant_does_not(ctx=None):
    """Lawful at every instant, and the cheapest insider path (threat INS-10)."""
    decision = load_policy(POLICY).evaluate(
        subject(organization_id="prosecution"),
        case(grant_active=True, grant_is_self_issued=True),
        NOW,
    )
    assert not decision.allowed


def test_sealed_denies_an_ordinary_clearance_even_when_designated():
    decision = load_policy(POLICY).evaluate(
        subject(clearance_level=CLEARANCE_ORDINARY),
        case(assignment_active=True, is_sealed=True),
        NOW,
    )
    assert not decision.allowed and decision.rule_id == "sealed-without-clearance"


def test_sealed_allows_a_cleared_and_designated_officer():
    decision = load_policy(POLICY).evaluate(
        subject(clearance_level=CLEARANCE_SEALED),
        case(assignment_active=True, is_sealed=True),
        NOW,
    )
    assert decision.allowed


def test_a_lapsed_clearance_denies_before_anything_else_is_considered():
    """Denies are ordered first so a later allow cannot out-vote them."""
    decision = load_policy(POLICY).evaluate(
        subject(clearance_valid_to=NOW - timedelta(days=1)),
        case(assignment_active=True, grant_active=True),
        NOW,
    )
    assert not decision.allowed and decision.rule_id == "lapsed-clearance"


def test_a_clearance_expiring_later_is_still_current():
    decision = load_policy(POLICY).evaluate(
        subject(clearance_valid_to=NOW + timedelta(days=1)),
        case(assignment_active=True),
        NOW,
    )
    assert decision.allowed


def test_an_inactive_subject_is_denied_first():
    """No slice builds account suspension; the predicate exists so it can (INS-13)."""
    decision = load_policy(POLICY).evaluate(
        subject(is_active=False), case(assignment_active=True), NOW
    )
    assert not decision.allowed and decision.rule_id == "inactive-subject"


# --- every decision is attributable ------------------------------------------

def test_every_decision_carries_the_policy_id_and_version():
    """Invariant 3: every decision logs the policy ID that decided it."""
    for facts in (case(), case(assignment_active=True), case(is_sealed=True)):
        decision = load_policy(POLICY).evaluate(subject(), facts, NOW)
        assert decision.policy_id == "ordin.case_read"
        assert decision.policy_version == load_policy(POLICY).version
        assert decision.rule_id and decision.reason


# --- policy versioning ------------------------------------------------------------


def test_latest_policy_path_picks_the_highest_version():
    """Numeric, not lexical. `v10` must beat `v9`, which string sorting gets wrong."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for version in (1, 2, 9, 10):
            (folder / f"demo.v{version}.yaml").write_text("{}", encoding="utf-8")
        (folder / "demo.vdraft.yaml").write_text("{}", encoding="utf-8")
        assert latest_policy_path(folder, "demo").name == "demo.v10.yaml"


def test_no_test_hardcodes_a_versioned_policy_filename():
    """The guard that makes a version bump safe.

    Before `latest_policy_path` existed, four test files named `case_read.v1.yaml`
    directly. Bumping the policy to v2 left every one of them green - asserting
    correctly, about a file the running application no longer loads. That is the worst
    shape a test suite can take, because the failure is invisible from inside it.

    Old versions stay on disk so a decision recorded under them is still explainable;
    nothing should *load* one except a test about versioning itself.
    """
    import re

    # A versioned filename inside a string literal. Prose in a docstring that happens
    # to name a policy file is not a load, and flagging it would train people to
    # stop writing the explanation.
    literal = re.compile(r"""["'][^"']*(?:case_read|admin|break_glass)\.v\d+\.yaml["']""")
    offenders = []
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if literal.search(line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, (
        "these tests load a policy by version number, so a version bump would leave "
        "them asserting against a file nothing runs:\n  " + "\n  ".join(offenders)
    )
