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

from fastapi import HTTPException, Request

from domain.policy import Policy
from domain.subject import Subject
from infra.authz import load_subject
from infra.subject_provider import COOKIE_NAME, SimulatedSubjectProvider

log = logging.getLogger("ordin.api.deps")


def provider(request: Request) -> SimulatedSubjectProvider:
    return SimulatedSubjectProvider(request.app.state.settings.ordin_session_secret)


def policy(request: Request) -> Policy:
    return request.app.state.policy


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
