"""Case routes.

**Every query in this file starts from `infra.authz.authorized_cases()`.** That is not
a convention to remember, it is the only way to get a `case_record` row into a
response: the filter is a SQLAlchemy expression, so a route that forgot it would have
to build its own `select(case_record)` — which is visible in review in a way that a
forgotten string template is not.

Two response choices that look like ordinary REST and are actually invariants:

  A case the caller may not read returns **404, not 403**. A 403 confirms the case
  exists, which is an existence oracle over guessable ids (threat INS-04). Denied and
  nonexistent are deliberately indistinguishable, and there is a test asserting the
  two responses are byte-identical.

  Search and autocomplete **join** the authorized set rather than filtering results
  afterwards. Invariant 1 names autocomplete as the worst offender: three letters must
  never surface a name from an unauthorised case, and post-filtering leaks through the
  suggestion list and its length.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.deps import policy as get_policy
from api.deps import require_subject
from domain.policy import Policy
from domain.subject import Subject
from infra.authz import authorized_case_ids, authorized_cases, decide
from infra.decisions import record_decision
from infra.logging_context import current_correlation_id
from infra.tables import case_record, party

router = APIRouter(tags=["cases"])

MAX_PAGE = 50


class CaseOut(BaseModel):
    id: str
    reference: str
    state: str
    access_class: str


class PartySuggestion(BaseModel):
    display_name: str
    role: str


@router.get("/cases")
async def list_cases(
    request: Request,
    limit: int = Query(default=20, le=MAX_PAGE, ge=1),
    offset: int = Query(default=0, ge=0),
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> list[CaseOut]:
    now = datetime.now(timezone.utc)
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                authorized_cases(policy, subject, now)
                .order_by(case_record.c.reference)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    return [
        CaseOut(
            id=str(r.id), reference=r.reference, state=r.state, access_class=r.access_class
        )
        for r in rows
    ]


@router.get("/cases/count")
async def count_cases(
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """A separate endpoint precisely because a count is its own leak.

    The predicate is inside the aggregate, so this returns what the caller may see
    rather than a total they may not (threat INS-03).
    """
    engine = request.app.state.engine
    async with engine.connect() as conn:
        inner = authorized_case_ids(policy, subject, datetime.now(timezone.utc)).subquery()
        total = (
            await conn.execute(sa.select(sa.func.count()).select_from(inner))
        ).scalar_one()
    return {"count": total}


@router.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> CaseOut:
    now = datetime.now(timezone.utc)
    engine = request.app.state.engine

    async with engine.connect() as conn:
        # The point decision, so the reason is attributable and logged.
        decision = await decide(conn, policy, subject, case_id, now)
        await record_decision(
            conn,
            decision,
            subject=subject,
            resource_type="case",
            resource_id=case_id,
            correlation_id=current_correlation_id(),
        )
        await conn.commit()

        if not decision.allowed:
            # 404, not 403. See the module docstring.
            raise HTTPException(status_code=404, detail="not_found")

        row = (
            await conn.execute(
                authorized_cases(policy, subject, now).where(case_record.c.id == case_id)
            )
        ).one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    return CaseOut(
        id=str(row.id), reference=row.reference, state=row.state, access_class=row.access_class
    )


@router.get("/parties/suggest")
async def suggest_parties(
    request: Request,
    q: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=10, le=MAX_PAGE, ge=1),
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> list[PartySuggestion]:
    """Autocomplete, joined to the authorized case set.

    Invariant 1 calls this the worst offender. The join is what makes it safe;
    querying `party` and filtering the rows afterwards is the bug.
    """
    engine = request.app.state.engine
    async with engine.connect() as conn:
        allowed = authorized_case_ids(policy, subject, datetime.now(timezone.utc)).subquery()
        rows = (
            await conn.execute(
                sa.select(party.c.display_name, party.c.role)
                .join(allowed, allowed.c.id == party.c.case_id)
                .where(party.c.display_name.ilike(f"%{q}%"))
                .order_by(party.c.display_name)
                .limit(limit)
            )
        ).all()
    return [PartySuggestion(display_name=r.display_name, role=r.role) for r in rows]


@router.get("/search")
async def search_cases(
    request: Request,
    q: str = Query(min_length=1, max_length=128),
    limit: int = Query(default=20, le=MAX_PAGE, ge=1),
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> list[CaseOut]:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                authorized_cases(policy, subject, datetime.now(timezone.utc))
                .where(case_record.c.reference.ilike(f"%{q}%"))
                .order_by(case_record.c.reference)
                .limit(limit)
            )
        ).all()
    return [
        CaseOut(
            id=str(r.id), reference=r.reference, state=r.state, access_class=r.access_class
        )
        for r in rows
    ]


@router.get("/cases/{case_id}/summary")
async def case_summary(
    case_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """How *this subject* reaches the case, and what is waiting for them in it.

    The access route is the part worth showing on a screen. "You see this because you
    are designated on it" and "you see a redacted copy because you hold a grant for
    charge-sheet preparation that expires in 29 days" are the seven dimensions made
    legible, and a person who can read why they have access is a person who notices
    when they should not.

    Denied and nonexistent are the same 404 as everywhere else (threat INS-04).
    """
    from infra.authz import load_case_facts
    from infra.disclosure import Disclosure, disclosure_for

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        decision = await decide(conn, policy, subject, case_id, now)
        await record_decision(
            conn, decision, subject=subject, resource_type="case", resource_id=case_id,
            correlation_id=current_correlation_id(),
        )
        await conn.commit()
        if not decision.allowed:
            raise HTTPException(status_code=404, detail="not_found")

        facts = await load_case_facts(conn, subject, case_id, now)
        disclosure = disclosure_for(subject, facts).disclosure
        grant = (
            await conn.execute(
                sa.text(
                    "SELECT purpose, expires_at FROM access_grant "
                    "WHERE case_id = :c AND grantee_id = :u AND revoked_at IS NULL "
                    "  AND expires_at > :now AND granted_by <> grantee_id "
                    "ORDER BY expires_at DESC LIMIT 1"
                ),
                {"c": case_id, "u": subject.user_id, "now": now},
            )
        ).mappings().one_or_none()
        derivative_only = disclosure is not Disclosure.ORIGINAL
        documents = (
            await conn.execute(
                sa.text(
                    "SELECT count(DISTINCT d.id) FROM document d "
                    "JOIN document_version v ON v.document_id = d.id "
                    "WHERE d.case_id = :c "
                    "  AND (NOT :derivative_only OR v.derived_from_version_id IS NOT NULL)"
                ),
                {"c": case_id, "derivative_only": derivative_only},
            )
        ).scalar_one()
        drafts = None
        if not derivative_only:
            # Counted only for an original reader: how many fields await a human is
            # a fact about the original's contents.
            drafts = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM extracted_field "
                        "WHERE case_id = :c AND status = 'draft'"
                    ),
                    {"c": case_id},
                )
            ).scalar_one()

    return {
        "route": "designation" if facts.assignment_active else "grant",
        "disclosure": disclosure.value,
        "purpose": grant["purpose"] if grant else None,
        "grant_expires_at": grant["expires_at"] if grant else None,
        "clearance_valid_to": subject.clearance_valid_to,
        "sealed": facts.is_sealed,
        "documents": documents,
        "drafts_awaiting": drafts,
        "policy": f"{decision.policy_id} v{decision.policy_version}",
        "rule": decision.rule_id,
    }
