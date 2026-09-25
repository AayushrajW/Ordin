"""What a case is expected to hold before it reaches a given state.

The deck's third capability, cut in the original build and still carrying a tick on the
comparison table. This is the minimum honest version of it.

**It reports; it does not decide.** CLAUDE.md forbids the system making a completeness
decision, and the distinction is not pedantic: "this case has no forensic report" is an
observation anybody can check, while "this case is ready to file" is a judgement with
consequences. The engine produces the first. A person makes the second.

**It carries no statutory deadlines**, because nobody on this build has a citation for
one. `policies/completeness.v1.yaml` has an empty `deadlines` list and a loader that
refuses an entry with no `source:` field, so a deadline cannot arrive by accident — the
way a plausible-looking "90 days" arrives in software that nobody asked where it came
from.

The requirements it does carry are **procedural configuration**: what this deployment
expects a case file to contain, the way a station's own checklist would. An agency edits
the file. Nothing here is asserted to be law.

No framework below this line: this module imports yaml and the standard library, and is
unit-tested with no database and no application running.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml


class CompletenessPolicyError(Exception):
    """The policy file is unusable. Raised at load, never at decision time."""


@dataclass(frozen=True)
class Requirement:
    doc_class: str
    label: str
    minimum: int
    blocking: bool


@dataclass(frozen=True)
class Deadline:
    label: str
    from_field: str
    days: int
    source: str


@dataclass(frozen=True)
class CompletenessPolicy:
    policy_id: str
    version: int
    maturity: str
    requirements: dict[str, tuple[Requirement, ...]]
    deadlines: tuple[Deadline, ...]

    def for_state(self, state: str) -> tuple[Requirement, ...]:
        return self.requirements.get(state, ())

    def knows(self, state: str) -> bool:
        """Is there a requirement block for this state at all?

        Distinct from "has no unmet requirements", and conflating the two is what let an
        unknown state report 100% complete and clear to proceed. `configured_states`
        below is what a caller should offer; this is what it should check.
        """
        return state in self.requirements

    @property
    def configured_states(self) -> tuple[str, ...]:
        return tuple(self.requirements)


@dataclass(frozen=True)
class Shortfall:
    doc_class: str
    label: str
    required: int
    present: int
    blocking: bool

    @property
    def short_by(self) -> int:
        return max(0, self.required - self.present)


@dataclass(frozen=True)
class CompletenessReport:
    """What is present, what is missing, and whether anything missing is blocking."""

    target_state: str
    policy_id: str
    satisfied: tuple[Requirement, ...]
    shortfalls: tuple[Shortfall, ...]

    @property
    def blocking(self) -> tuple[Shortfall, ...]:
        return tuple(s for s in self.shortfalls if s.blocking)

    @property
    def may_proceed(self) -> bool | None:
        """No **blocking** requirement is unmet, or None when nothing was checked.

        A non-blocking shortfall is reported and does not stop anybody. The distinction
        exists because a case can legitimately have no forensic report, and a checklist
        that treated every absence as an error would be ignored within a week — which is
        the failure mode of every checklist nobody can satisfy.

        None when there are no requirements for the target state at all: "nothing is
        blocking you" and "nobody has written down what this state requires" are
        different answers, and only one of them should ever look like a green light.
        """
        if not self.satisfied and not self.shortfalls:
            return None
        return not self.blocking

    @property
    def percent(self) -> int | None:
        """How much of the checklist is met, or None when there is no checklist.

        **None, not 100.** `total == 0` means one of two very different things: every
        requirement is satisfied, or this state has no requirements configured. Returning
        100 for both meant `?target=under_investigation` - a real, valid case state the
        policy simply says nothing about - reported a completely empty case as 100%
        complete and clear to proceed, and so did a typo like `?target=fied`.

        That is the exact failure `load_completeness_policy` fails hard to avoid: "A
        malformed policy must stop the process rather than quietly report every case
        complete, which is what an empty requirement list would do." The same empty list
        was reachable through a query parameter. Invariant 2 wants an unmatched rule to
        deny, not to congratulate.
        """
        total = len(self.satisfied) + len(self.shortfalls)
        return None if total == 0 else round(len(self.satisfied) * 100 / total)


def load_completeness_policy(path: Path | str) -> CompletenessPolicy:
    """Read and validate the policy. Fails at load, like the authorization loader.

    A malformed policy must stop the process rather than quietly report every case
    complete, which is what an empty requirement list would do.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CompletenessPolicyError("policy file is not a mapping")

    for key in ("policy_id", "version", "maturity", "requirements"):
        if key not in raw:
            raise CompletenessPolicyError(f"policy is missing {key!r}")

    requirements: dict[str, tuple[Requirement, ...]] = {}
    for entry in raw["requirements"] or []:
        state = entry.get("state")
        if not state:
            raise CompletenessPolicyError("a requirement block has no 'state'")
        items = []
        for c in entry.get("classes") or []:
            for field in ("class", "label", "minimum"):
                if field not in c:
                    raise CompletenessPolicyError(
                        f"state {state!r}: a class entry is missing {field!r}"
                    )
            items.append(
                Requirement(
                    doc_class=c["class"],
                    label=c["label"],
                    minimum=int(c["minimum"]),
                    # Absent means non-blocking. A requirement that stops a case moving
                    # must say so explicitly; the dangerous default is the other way.
                    blocking=bool(c.get("blocking", False)),
                )
            )
        requirements[state] = tuple(items)

    deadlines = []
    for d in raw.get("deadlines") or []:
        # The whole point. A deadline with no citation is a guessed statutory period,
        # which CLAUDE.md forbids by name, so it is refused at load rather than
        # displayed to somebody who will believe it.
        if not d.get("source"):
            raise CompletenessPolicyError(
                f"deadline {d.get('label')!r} has no 'source'. A deadline without a "
                "citation is a guessed statutory period; add the provision and where "
                "it was read, or remove the entry."
            )
        for field in ("label", "from_field", "days"):
            if field not in d:
                raise CompletenessPolicyError(f"a deadline is missing {field!r}")
        deadlines.append(
            Deadline(
                label=d["label"],
                from_field=d["from_field"],
                days=int(d["days"]),
                source=d["source"],
            )
        )

    return CompletenessPolicy(
        policy_id=raw["policy_id"],
        version=int(raw["version"]),
        maturity=raw["maturity"],
        requirements=requirements,
        deadlines=tuple(deadlines),
    )


def assess(
    policy: CompletenessPolicy, *, target_state: str, counts: dict[str, int]
) -> CompletenessReport:
    """Compare what a case holds against what the policy expects for a state.

    `counts` is document classes to how many of each the case holds. A class absent
    from the mapping counts as zero, so a caller cannot make a case look complete by
    omitting a key.
    """
    satisfied: list[Requirement] = []
    shortfalls: list[Shortfall] = []

    for requirement in policy.for_state(target_state):
        present = int(counts.get(requirement.doc_class, 0))
        if present >= requirement.minimum:
            satisfied.append(requirement)
        else:
            shortfalls.append(
                Shortfall(
                    doc_class=requirement.doc_class,
                    label=requirement.label,
                    required=requirement.minimum,
                    present=present,
                    blocking=requirement.blocking,
                )
            )

    return CompletenessReport(
        target_state=target_state,
        policy_id=policy.policy_id,
        satisfied=tuple(satisfied),
        shortfalls=tuple(shortfalls),
    )
