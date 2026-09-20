"""The case completeness engine (audit P0-1).

The deck's third capability, which carried a tick on the comparison table and had
nothing behind it. This is the minimum honest version, and two of its properties are
more interesting than the feature:

**It reports; it does not decide.** "This case has no forensic report" is an observation
anybody can check. "This case is ready to file" is a judgement with consequences, and
CLAUDE.md forbids the system making it.

**It carries no statutory deadlines, and cannot acquire one by accident.** The loader
refuses a deadline entry with no `source:` field, because a deadline with no citation is
a guessed statutory period — the thing CLAUDE.md forbids by name, arriving as a helpful
default that nobody remembers adding.
"""
from pathlib import Path

import pytest

from domain.completeness import (
    CompletenessPolicyError,
    assess,
    load_completeness_policy,
)

POLICY = Path("policies") / "completeness.v1.yaml"


@pytest.fixture(scope="module")
def policy():
    return load_completeness_policy(POLICY)


# --- the shipped policy ----------------------------------------------------------


def test_the_shipped_policy_loads(policy):
    assert policy.policy_id == "ordin.completeness"
    assert policy.maturity == "mvp"


def test_the_shipped_policy_carries_no_statutory_deadlines(policy):
    """Not an oversight, and the test exists so that adding one is a deliberate act.

    Nobody on this build has a citation for an Indian procedural deadline. A checklist
    that said "charge sheet due within 90 days" would be a statutory claim with nothing
    behind it, on a screen an investigator would believe.
    """
    assert policy.deadlines == (), (
        "a deadline appeared in the policy. Every one must cite the provision it comes "
        "from; if this is intentional, update this test and say where the number is from"
    )


def test_a_deadline_without_a_source_is_refused_at_load(tmp_path):
    """The guard that keeps the above true."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "policy_id: x\nversion: 1\nmaturity: mvp\nrequirements: []\n"
        "deadlines:\n  - label: Charge sheet\n    from_field: date_of_incident\n"
        "    days: 90\n",
        encoding="utf-8",
    )
    with pytest.raises(CompletenessPolicyError, match="source"):
        load_completeness_policy(bad)


def test_a_deadline_with_a_source_is_accepted(tmp_path):
    """The mechanism works; this build simply has nothing to put in it."""
    good = tmp_path / "good.yaml"
    good.write_text(
        "policy_id: x\nversion: 1\nmaturity: mvp\nrequirements: []\n"
        "deadlines:\n  - label: Example\n    from_field: date_of_incident\n"
        "    days: 30\n    source: 'a provision, and where it was read'\n",
        encoding="utf-8",
    )
    loaded = load_completeness_policy(good)
    assert loaded.deadlines[0].source


def test_a_malformed_policy_stops_the_process_rather_than_passing_everything(tmp_path):
    """An empty requirement list would report every case complete."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("policy_id: x\nversion: 1\n", encoding="utf-8")
    with pytest.raises(CompletenessPolicyError):
        load_completeness_policy(bad)


# --- assessment ------------------------------------------------------------------


def test_an_empty_case_is_short_of_everything(policy):
    report = assess(policy, target_state="filed", counts={})
    assert report.percent == 0
    assert not report.may_proceed
    assert {s.doc_class for s in report.shortfalls} >= {"fir", "statement", "charge_sheet"}


def test_a_complete_case_may_proceed(policy):
    report = assess(
        policy,
        target_state="filed",
        counts={"fir": 1, "statement": 3, "forensic_report": 1, "charge_sheet": 1},
    )
    assert report.percent == 100
    assert report.may_proceed
    assert report.shortfalls == ()


def test_a_non_blocking_shortfall_is_reported_and_does_not_stop_anybody(policy):
    """A case can legitimately have no forensic report.

    A checklist that treated every absence as an error would be ignored within a week,
    and an ignored checklist is worse than none: it still looks like a control.
    """
    report = assess(
        policy,
        target_state="filed",
        counts={"fir": 1, "statement": 1, "charge_sheet": 1},
    )
    assert [s.doc_class for s in report.shortfalls] == ["forensic_report"]
    assert report.shortfalls[0].blocking is False
    assert report.may_proceed, "a non-blocking shortfall stopped the case"


def test_a_blocking_shortfall_stops_it(policy):
    report = assess(policy, target_state="filed", counts={"fir": 1, "statement": 1})
    assert not report.may_proceed
    assert [s.doc_class for s in report.blocking] == ["charge_sheet"]


def test_an_absent_class_counts_as_zero_rather_than_being_skipped(policy):
    """A caller must not be able to make a case look complete by omitting a key."""
    omitted = assess(policy, target_state="filed", counts={"fir": 1})
    explicit = assess(
        policy,
        target_state="filed",
        counts={"fir": 1, "statement": 0, "forensic_report": 0, "charge_sheet": 0},
    )
    assert [s.doc_class for s in omitted.shortfalls] == [
        s.doc_class for s in explicit.shortfalls
    ]


def test_a_state_with_no_requirements_is_complete_and_says_so(policy):
    """`registered` has no checklist. Nothing is missing, and percent is not a lie."""
    report = assess(policy, target_state="registered", counts={})
    assert report.may_proceed
    assert report.percent == 100
    assert report.shortfalls == ()


def test_more_than_the_minimum_is_still_satisfied(policy):
    report = assess(
        policy,
        target_state="filed",
        counts={"fir": 2, "statement": 9, "forensic_report": 3, "charge_sheet": 1},
    )
    assert report.may_proceed and report.shortfalls == ()
