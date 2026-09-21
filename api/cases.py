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
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.deps import policy as get_policy
from api.deps import require_subject
from domain.case import InvalidTransition, transition
from domain.completeness import assess
from domain.enums import AuditAction, CaseState
from domain.policy import Policy
from domain.subject import Subject
from infra.audit_log import append_audit
from infra.authz import authorized_case_ids, authorized_cases, decide
from infra.decisions import record_decision
from infra.disclosure import Disclosure
from infra.logging_context import current_correlation_id
from infra.tables import case_record, party

log = logging.getLogger("ordin.api.cases")
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
                        "SELECT count(*) FROM extracted_field f "
                        "WHERE f.case_id = :c AND f.status = 'draft' "
                        # A draft a person has already answered with their own value
                        # is not awaiting anyone.
                        "  AND NOT EXISTS (SELECT 1 FROM extracted_field h "
                        "    WHERE h.version_id = f.version_id "
                        "      AND h.field_key = f.field_key AND h.source = 'human')"
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


# --- creating a case, and moving it -------------------------------------------
#
# Until this existed, `domain/case.py`'s state machine was tested and unreachable: ten
# tests over ALLOWED_TRANSITIONS, and no caller anywhere. The only INSERT INTO
# case_record in the repository was in seed.py, which meant an investigator could not
# register a case and a case could not move from registered to filed. A vault somebody
# else has to stock.


class CreateCaseRequest(BaseModel):
    reference: str = Field(min_length=3, max_length=64)
    sealed: bool = False


class TransitionRequest(BaseModel):
    state: CaseState


@router.post("/cases", status_code=201)
async def create_case(
    body: CreateCaseRequest,
    request: Request,
    subject: Subject = Depends(require_subject),
):
    """Register a case, in the organization and jurisdiction of the post you hold.

    **Neither is a parameter**, deliberately. Both come from the subject the server
    resolved, so a caller cannot file a case into somebody else's station: accepting
    them from the body would let anybody who may create a case create one anywhere,
    which is the organization dimension defeated at the point of creation.

    The creator is designated on it in the same transaction. A case nobody can open is
    not a safer case, it is a lost one - and the alternative, making creation grant
    access implicitly, would be a second route to a case that the policy never sees.
    An assignment row is the *existing* route, so `ordin.case_read` decides this access
    exactly as it decides every other.
    """
    engine = request.app.state.engine
    reference = body.reference.strip()

    async with engine.begin() as conn:
        clash = (
            await conn.execute(
                sa.text("SELECT 1 FROM case_record WHERE reference = :r"), {"r": reference}
            )
        ).scalar_one_or_none()
        if clash:
            # Not an existence oracle: the caller is authenticated, and a duplicate
            # reference within a station is something they must be told about.
            raise HTTPException(status_code=409, detail="reference_already_used")

        case_id = str(
            (
                await conn.execute(
                    sa.text(
                        "INSERT INTO case_record "
                        "  (id, reference, organization_id, jurisdiction_id, state, access_class) "
                        "VALUES (gen_random_uuid(), :r, :o, :j, :s, :a) RETURNING id"
                    ),
                    {
                        "r": reference,
                        "o": subject.organization_id,
                        "j": subject.jurisdiction_id,
                        "s": CaseState.REGISTERED.value,
                        "a": "sealed" if body.sealed else "normal",
                    },
                )
            ).scalar_one()
        )

        await conn.execute(
            sa.text(
                "INSERT INTO case_assignment (id, case_id, user_id, valid_from, assigned_by) "
                "VALUES (gen_random_uuid(), :c, :u, now(), :u)"
            ),
            {"c": case_id, "u": subject.user_id},
        )

        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.CASE_CREATED,
            object_type="case_record",
            object_id=case_id,
        )

    # Reference only in the log - it is a case number, not a party (invariant 12).
    log.info(
        "case created",
        extra={"case_id": case_id, "actor": subject.user_id, "sealed": body.sealed},
    )
    return {
        "case_id": case_id,
        "reference": reference,
        "state": CaseState.REGISTERED.value,
        "designated": True,
    }


@router.post("/cases/{case_id}/state")
async def change_case_state(
    case_id: str,
    body: TransitionRequest,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """Move a case along its lifecycle, or refuse.

    The move is decided by `domain.case.transition`, which is pure and already tested;
    this route supplies the rows and the audit. Two separate refusals, and they are not
    the same refusal:

      404 - you cannot reach this case. Indistinguishable from it not existing, because
            the read filter is what answers first and a 403 would confirm the case is
            real (threat INS-04).
      409 - you can reach it, and the move is not permitted from where it stands.
    """
    from api.documents import _case_disclosure

    engine = request.app.state.engine
    at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        # **Designation, not merely reach.** A grant is purpose-limited *read* access;
        # it is not custody of the case. Gating on `authorized_cases` alone let a
        # prosecutor holding a charge-sheet-preparation grant close the investigating
        # officer's case — reaching a case and directing it are different powers, and
        # only designation carries the second. Disclosure class is where that
        # distinction already lives (ADR 0013), so it is reused rather than reinvented.
        disclosure = await _case_disclosure(conn, policy, subject, case_id, at)
        if disclosure is not Disclosure.ORIGINAL:
            raise HTTPException(status_code=404, detail="not_found")

        current = (
            await conn.execute(
                sa.text("SELECT state FROM case_record WHERE id = :c"), {"c": case_id}
            )
        ).scalar_one_or_none()
        if current is None:
            raise HTTPException(status_code=404, detail="not_found")

        try:
            target = transition(CaseState(current), body.state)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

        # Completeness gate. Reports everything, refuses only what the policy marks
        # blocking — a checklist that cannot be satisfied is ignored within a week, and
        # an ignored checklist is worse than none because it still looks like a control.
        report = assess(
            request.app.state.completeness,
            target_state=target.value,
            counts=await _class_counts(conn, case_id),
        )
        if not report.may_proceed:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "incomplete",
                    "policy": report.policy_id,
                    "missing": [
                        {"class": s.doc_class, "label": s.label,
                         "required": s.required, "present": s.present}
                        for s in report.blocking
                    ],
                },
            )

        await conn.execute(
            sa.text("UPDATE case_record SET state = :s WHERE id = :c"),
            {"s": target.value, "c": case_id},
        )
        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.CASE_STATE_CHANGED,
            object_type="case_record",
            object_id=case_id,
        )

    log.info(
        "case state changed",
        extra={"case_id": case_id, "actor": subject.user_id,
               "from": current, "to": target.value},
    )
    return {"case_id": case_id, "from": current, "to": target.value}


async def _class_counts(conn, case_id: str) -> dict[str, int]:
    """How many documents of each class this case holds.

    Counts `document`, not `document_version`: a redacted derivative is another version
    of the same document, and counting versions would let redacting an FIR twice satisfy
    a requirement for three FIRs.
    """
    rows = (
        await conn.execute(
            sa.text(
                "SELECT doc_class, count(*) AS n FROM document "
                "WHERE case_id = :c GROUP BY doc_class"
            ),
            {"c": case_id},
        )
    ).mappings().all()
    return {r["doc_class"]: int(r["n"]) for r in rows}


class ShortfallOut(BaseModel):
    doc_class: str
    label: str
    required: int
    present: int
    blocking: bool


class CompletenessOut(BaseModel):
    target_state: str
    policy: str
    percent: int
    may_proceed: bool
    satisfied: list[str]
    shortfalls: list[ShortfallOut]
    # Always empty in this build, and the field exists so the absence is visible rather
    # than looking like a feature nobody built.
    deadlines: list[dict]
    note: str


@router.get("/cases/{case_id}/completeness")
async def case_completeness(
    case_id: str,
    request: Request,
    target: str | None = Query(default=None),
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> CompletenessOut:
    """What this case holds, against what the policy expects for a target state.

    Reports. Does not decide. "This case has no forensic report" is an observation
    anybody can check; "this case is ready to file" is a judgement with consequences,
    and CLAUDE.md is explicit that the system does not make it.
    """
    from api.documents import _case_disclosure

    engine = request.app.state.engine
    at = datetime.now(timezone.utc)

    async with engine.connect() as conn:
        # **Disclosure class, not just case access.** Passing the case filter is what a
        # grant is for, and it is not enough here: these counts describe originals. A
        # case holding three FIRs and one redacted derivative would otherwise tell a
        # grantee "fir: 3" while showing them one document, confirming two originals
        # whose existence the document routes deliberately refuse to confirm
        # (threats VIC-01, INS-08). Raises the shared 404.
        disclosure = await _case_disclosure(conn, policy, subject, case_id, at)
        if disclosure is not Disclosure.ORIGINAL:
            raise HTTPException(status_code=404, detail="not_found")

        state = (
            await conn.execute(
                sa.text("SELECT state FROM case_record WHERE id = :c"), {"c": case_id}
            )
        ).scalar_one_or_none()
        if state is None:
            raise HTTPException(status_code=404, detail="not_found")
        counts = await _class_counts(conn, case_id)

    # Default to the next state a case would plausibly be checked against.
    target_state = target or CaseState.FILED.value
    report = assess(request.app.state.completeness, target_state=target_state, counts=counts)

    return CompletenessOut(
        target_state=target_state,
        policy=report.policy_id,
        percent=report.percent,
        may_proceed=report.may_proceed,
        satisfied=[r.label for r in report.satisfied],
        shortfalls=[
            ShortfallOut(
                doc_class=s.doc_class, label=s.label, required=s.required,
                present=s.present, blocking=s.blocking,
            )
            for s in report.shortfalls
        ],
        deadlines=[],
        note=(
            "Procedural configuration, not statute. This build carries no statutory "
            "deadlines because none of them has a citation behind it, and the policy "
            "loader refuses a deadline with no source."
        ),
    )
