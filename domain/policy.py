"""The policy evaluator.

Security invariant 3: authorization is declarative data, not code. Policies are
versioned YAML, evaluated by this small pure function, and unit-testable with no
application and no database running. Every decision carries the policy ID and the
rule ID that produced it, so invariant 3's "every decision logs the policy ID that
decided it" has something to log.

Invariant 2 governs every failure mode here:

  - A policy that names an unknown predicate fails at LOAD, not at decision time.
  - A policy with no terminal deny is rejected at load.
  - An evaluator error denies.
  - An unmatched rule set denies.

The last one is why `evaluate` ends with a deny even though the loader already
requires an explicit `default-deny` rule: belt and braces on the one path where
getting it wrong means degrading open.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import yaml

from domain.predicates import UnknownPredicate, resolve
from domain.subject import CaseFacts, Subject


class Effect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class PolicyError(Exception):
    """Malformed policy. Raised at load time so a bad file cannot reach a request."""


@dataclass(frozen=True)
class Condition:
    predicate: str
    negated: bool = False

    def holds(self, s: Subject, c: CaseFacts, at: datetime) -> bool:
        result = resolve(self.predicate)(s, c, at)
        return (not result) if self.negated else result


@dataclass(frozen=True)
class Rule:
    id: str
    effect: Effect
    conditions: tuple[Condition, ...] = ()

    def matches(self, s: Subject, c: CaseFacts, at: datetime) -> bool:
        """All conditions must hold. An empty condition set always matches.

        An empty set matching is what makes a terminal `default-deny` rule work, and
        it is safe *only* because the loader forbids an allow rule with no conditions.
        """
        return all(cond.holds(s, c, at) for cond in self.conditions)


@dataclass(frozen=True)
class Decision:
    effect: Effect
    policy_id: str
    policy_version: int
    rule_id: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.effect is Effect.ALLOW


@dataclass(frozen=True)
class Policy:
    policy_id: str
    version: int
    maturity: str
    production_adapter: str
    rules: tuple[Rule, ...]

    def evaluate(self, subject: Subject, case: CaseFacts, at: datetime) -> Decision:
        """First matching rule wins. Rules are ordered; denies are written first."""
        for rule in self.rules:
            try:
                matched = rule.matches(subject, case, at)
            except Exception as exc:  # noqa: BLE001 - invariant 2: an error denies
                return Decision(
                    effect=Effect.DENY,
                    policy_id=self.policy_id,
                    policy_version=self.version,
                    rule_id=rule.id,
                    reason=f"evaluator_error:{type(exc).__name__}",
                )
            if matched:
                return Decision(
                    effect=rule.effect,
                    policy_id=self.policy_id,
                    policy_version=self.version,
                    rule_id=rule.id,
                    reason=rule.id,
                )
        # Unreachable while the loader requires a terminal deny. Kept because the
        # cost of being wrong here is degrading open.
        return Decision(
            effect=Effect.DENY,
            policy_id=self.policy_id,
            policy_version=self.version,
            rule_id="implicit-deny",
            reason="no_rule_matched",
        )


def _parse_condition(raw: str) -> Condition:
    text = raw.strip()
    if text.startswith("not "):
        return Condition(predicate=text[4:].strip(), negated=True)
    return Condition(predicate=text)


def load_policy(path: Path | str) -> Policy:
    """Read and validate a policy file. Every failure here is a load-time failure."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PolicyError(f"{path.name}: unreadable ({type(exc).__name__})") from exc

    if not isinstance(raw, dict):
        raise PolicyError(f"{path.name}: top level must be a mapping")

    for key in ("policy_id", "version", "maturity", "production_adapter", "rules"):
        if key not in raw:
            raise PolicyError(f"{path.name}: missing required key {key!r}")

    rules: list[Rule] = []
    for index, raw_rule in enumerate(raw["rules"]):
        if "id" not in raw_rule or "effect" not in raw_rule:
            raise PolicyError(f"{path.name}: rule {index} needs an id and an effect")
        try:
            effect = Effect(raw_rule["effect"])
        except ValueError as exc:
            raise PolicyError(
                f"{path.name}: rule {raw_rule['id']!r} has effect "
                f"{raw_rule['effect']!r}; expected allow or deny"
            ) from exc

        conditions = tuple(_parse_condition(c) for c in raw_rule.get("when", []))

        # An allow with no conditions matches everything and would make every rule
        # after it dead. That is a catastrophic typo, so it is a load error.
        if effect is Effect.ALLOW and not conditions:
            raise PolicyError(
                f"{path.name}: rule {raw_rule['id']!r} allows unconditionally"
            )

        # Resolve every predicate now, so an unknown name fails here rather than on
        # the first request that reaches this rule.
        for condition in conditions:
            try:
                resolve(condition.predicate)
            except UnknownPredicate as exc:
                raise PolicyError(f"{path.name}: {exc}") from exc

        rules.append(Rule(id=raw_rule["id"], effect=effect, conditions=conditions))

    if not rules:
        raise PolicyError(f"{path.name}: no rules")

    # Deny by default is a property of the file, not a hope about it.
    last = rules[-1]
    if last.effect is not Effect.DENY or last.conditions:
        raise PolicyError(
            f"{path.name}: the final rule must be an unconditional deny; "
            f"got {last.id!r} ({last.effect}, {len(last.conditions)} conditions)"
        )

    return Policy(
        policy_id=raw["policy_id"],
        version=int(raw["version"]),
        maturity=raw["maturity"],
        production_adapter=raw["production_adapter"],
        rules=tuple(rules),
    )
