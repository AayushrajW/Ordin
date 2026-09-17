"""Persisting authorization decisions.

Security invariant 3's final clause: every decision logs the policy ID that decided
it. `Decision` carries that from `domain/policy.py`; this writes it down.

What is deliberately absent is as important as what is here. There is no `detail`
or `reason_text` parameter, because the schema has nowhere to put one. Invariant 12
forbids logging content, and a free-text column on a decision log is where a case
reference or a party name eventually lands - written by someone being helpful.

The decision's own `reason` field is not persisted for the same reason: it is
currently always the rule id, but it is a string, and a string field invites prose.
The rule id and the policy version are enough to replay the decision against the
versioned policy file that produced it, which is the question worth answering.
"""
import sqlalchemy as sa

from domain.policy import Decision
from domain.subject import Subject


async def record_decision(
    conn,
    decision: Decision,
    *,
    subject: Subject,
    resource_type: str,
    resource_id: str,
    action: str = "read",
    correlation_id: str | None = None,
) -> None:
    """Append one decision. Never updates, because the grant does not permit it."""
    await conn.execute(
        sa.text(
            "INSERT INTO policy_decision "
            "(subject_user_id, subject_post_id, resource_type, resource_id, action, "
            " effect, policy_id, policy_version, rule_id, correlation_id) "
            "VALUES (:user_id, :post_id, :rtype, :rid, :action, :effect, :policy_id, "
            "        :policy_version, :rule_id, :correlation_id)"
        ),
        {
            "user_id": subject.user_id,
            "post_id": subject.post_id,
            "rtype": resource_type,
            "rid": resource_id,
            "action": action,
            "effect": decision.effect.value,
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
            "rule_id": decision.rule_id,
            "correlation_id": correlation_id,
        },
    )
