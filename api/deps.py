"""Request dependencies: the subject, and the policy.

The subject comes from the signed session cookie and from **nothing else**.

That is the whole security property, and it is worth being blunt about why the file
looks paranoid. Slice 7's demo is "one document, three roles, one URL". The cheapest
way to build a role switch is a dropdown that sends `?role=full` or an `X-Role`
header, and an API that reads it. Doing that would invalidate slices 3, 7 and 8
simultaneously: every authorization test would still pass, and every one of them would
be testing a forgeable identity (threat EXT-02). Sentinel's "unauthorized access"
scenario would go green against an attacker who simply typed a different value.

So there is no code path here that reads identity from a header, a query parameter or
a body. `tests/test_api_authorization.py` asserts that by sending those headers and
watching them be ignored.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from domain.policy import Policy
from domain.subject import CaseFacts, Subject
from infra.authz import load_subject
from infra.subject_provider import COOKIE_NAME, SimulatedSubjectProvider

log = logging.getLogger("ordin.api.deps")


def provider(request: Request) -> SimulatedSubjectProvider:
    return SimulatedSubjectProvider(request.app.state.settings.ordin_session_secret)


def policy(request: Request) -> Policy:
    return request.app.state.policy


def break_glass_policy(request: Request) -> Policy:
    """Who may declare an exception to a seal. A different question from reading."""
    return request.app.state.break_glass_policy


async def require_subject(request: Request) -> Subject:
    """Resolve the subject server-side, or refuse.

    Re-resolved from the database on every request rather than trusted from the
    token. The token says only *who*; organization, jurisdiction, clearance and
    active status are read fresh, so a lapsed clearance or a transfer takes effect
    immediately instead of at the end of an eight-hour session (threats INS-13,
    SESS-02, AZM-06).
    """
    user_id = provider(request).parse(request.cookies.get(COOKIE_NAME))
    if not user_id:
        raise HTTPException(status_code=401, detail="session_required")

    engine = request.app.state.engine
    async with engine.connect() as conn:
        subject = await load_subject(conn, user_id)

    if subject is None or not subject.is_active:
        # A deleted or suspended account presents a valid signature and no subject.
        raise HTTPException(status_code=401, detail="session_required")
    return subject


# A case the administrative policy never reads. The evaluator is case-scoped by
# construction; `ordin.admin` names no predicate that touches the resource, and a test
# asserts that. Passing a real case here would imply administration is decided per case,
# which it is not.
_NO_CASE = CaseFacts(
    case_id="00000000-0000-0000-0000-000000000000",
    organization_id="00000000-0000-0000-0000-000000000000",
    jurisdiction_id="00000000-0000-0000-0000-000000000000",
    is_sealed=False,
)


async def require_admin(request: Request) -> Subject:
    """Administrative capability, decided by `ordin.admin` and logged with its id.

    Deliberately not a conditional in this file. CLAUDE.md forbids hand-rolled role
    conditionals anywhere, and an administration surface is where one would otherwise be
    written — so the same evaluator that decides case access decides this, from a
    versioned file that is unit-tested with no app running.

    **It grants no case access.** `ordin.admin` allowing does not put a single case in
    reach: every case route still runs the `ordin.case_read` filter against the same
    subject, and an administrative post satisfies no rule in it.
    """
    subject = await require_subject(request)
    policy = request.app.state.admin_policy
    decision = policy.evaluate(subject, _NO_CASE, datetime.now(timezone.utc))
    if not decision.allowed:
        log.info(
            "administration refused",
            extra={
                "user_id": subject.user_id,
                "policy_id": decision.policy_id,
                "rule_id": decision.rule_id,
            },
        )
        # 404, not 403: whether this system has an administration surface, and whether
        # you are close to reaching it, are not facts an ordinary account needs.
        raise HTTPException(status_code=404, detail="not_found")
    return subject
