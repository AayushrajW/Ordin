"""Administration: placing accounts, designating officers, issuing grants.

Every route here depends on `require_admin`, which is a **policy decision** made by
`ordin.admin` and logged with the policy and rule id that made it. There is no role
conditional in this file, by construction: CLAUDE.md forbids hand-rolled role
conditionals anywhere, and an administration surface is precisely where one gets
written.

**Administration is not case access.** Nothing here returns a document, an extracted
field, a party name or any OCR text, and `ordin.admin` names no predicate that could
route to one. An administrator can give Kavya Raut a case and cannot read it.

**One bounded disclosure, stated rather than hidden.** `GET /admin/cases` returns case
*references and states* so that a person can be assigned to a case by picking it. That is
metadata about cases the administrator cannot open, and it is a real disclosure: a
reference like `VRN-N/2026/0001` says a case exists in that station in that year. It is
accepted here because assignment is unusable without it, it is the narrowest thing that
makes assignment possible, and the alternative — typing a reference blind — moves the
same knowledge into the administrator's head without removing it. Recorded as AR-19.

**Two-person rules are not implemented** (AR-15), with one exception that was free: a
grant may not name its issuer as its grantee, which the `grant_not_self_issued`
predicate already enforces at read time and this refuses at write time too.
"""
import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import require_admin
from domain.enums import AuditAction
from domain.subject import Subject
from infra.audit_log import append_audit

log = logging.getLogger("ordin.api.admin")
router = APIRouter(tags=["administration"], prefix="/admin")

MAX_GRANT_DAYS = 365


class AccountOut(BaseModel):
    user_id: str
    display_name: str
    email: str | None
    is_active: bool
    placed: bool
    post_title: str | None
    organization: str | None
    clearance_level: int
    is_administrative: bool
    last_login_at: datetime | None
    locked: bool


class PostOut(BaseModel):
    post_id: str
    title: str
    organization: str
    jurisdiction: str
    is_administrative: bool


class CaseBriefOut(BaseModel):
    """Reference and state only. Never content — see the module docstring."""

    case_id: str
    reference: str
    state: str
    is_sealed: bool


class PlaceRequest(BaseModel):
    post_id: str
    clearance_level: int = Field(ge=1, le=3)
    is_active: bool = True


class AssignmentRequest(BaseModel):
    user_id: str
    case_id: str


class GrantRequest(BaseModel):
    grantee_id: str
    case_id: str
    purpose: str = Field(min_length=3, max_length=200)
    days: int = Field(ge=1, le=MAX_GRANT_DAYS)


@router.get("/users")
async def list_accounts(
    request: Request, subject: Subject = Depends(require_admin)
) -> list[AccountOut]:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT u.id, u.display_name, u.email, u.is_active, u.clearance_level, "
                    "       u.last_login_at, u.locked_until, u.post_id, "
                    "       p.title AS post_title, p.is_administrative, o.name AS organization "
                    "  FROM app_user u "
                    "  LEFT JOIN post p ON p.id = u.post_id "
                    "  LEFT JOIN organization o ON o.id = p.organization_id "
                    " ORDER BY u.post_id IS NOT NULL, u.display_name"
                )
            )
        ).mappings().all()
    now = datetime.now(timezone.utc)
    return [
        AccountOut(
            user_id=str(r["id"]),
            display_name=r["display_name"],
            email=r["email"],
            is_active=r["is_active"],
            placed=r["post_id"] is not None,
            post_title=r["post_title"],
            organization=r["organization"],
            clearance_level=r["clearance_level"],
            is_administrative=bool(r["is_administrative"]),
            last_login_at=r["last_login_at"],
            locked=bool(r["locked_until"] and r["locked_until"] > now),
        )
        for r in rows
    ]


@router.get("/posts")
async def list_posts(
    request: Request, subject: Subject = Depends(require_admin)
) -> list[PostOut]:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT p.id, p.title, p.is_administrative, o.name AS organization, "
                    "       j.name AS jurisdiction "
                    "  FROM post p "
                    "  JOIN organization o ON o.id = p.organization_id "
                    "  JOIN jurisdiction j ON j.id = p.jurisdiction_id "
                    " ORDER BY o.name, p.title"
                )
            )
        ).mappings().all()
    return [
        PostOut(
            post_id=str(r["id"]),
            title=r["title"],
            organization=r["organization"],
            jurisdiction=r["jurisdiction"],
            is_administrative=bool(r["is_administrative"]),
        )
        for r in rows
    ]


@router.get("/cases")
async def list_cases_for_assignment(
    request: Request, subject: Subject = Depends(require_admin)
) -> list[CaseBriefOut]:
    """References and states, so that a case can be picked. See AR-19."""
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT id, reference, state, access_class FROM case_record "
                    "ORDER BY reference"
                )
            )
        ).mappings().all()
    return [
        CaseBriefOut(
            case_id=str(r["id"]),
            reference=r["reference"],
            state=r["state"],
            is_sealed=r["access_class"] == "sealed",
        )
        for r in rows
    ]


@router.post("/users/{user_id}/place")
async def place_account(
    user_id: str,
    body: PlaceRequest,
    request: Request,
    subject: Subject = Depends(require_admin),
):
    """Give an account a post, a clearance and a live status.

    This is the moment a signed-up account stops being able to do nothing. It is not
    case access: a placed account still sees no case until it is designated on one or
    granted access to one.
    """
    engine = request.app.state.engine
    async with engine.begin() as conn:
        post = (
            await conn.execute(
                sa.text("SELECT id FROM post WHERE id = :p"), {"p": body.post_id}
            )
        ).scalar_one_or_none()
        if post is None:
            raise HTTPException(status_code=404, detail="no_such_post")

        updated = (
            await conn.execute(
                sa.text(
                    "UPDATE app_user SET post_id = :p, clearance_level = :c, "
                    "is_active = :a, failed_attempts = 0, locked_until = NULL "
                    "WHERE id = :u RETURNING id"
                ),
                {"p": body.post_id, "c": body.clearance_level, "a": body.is_active,
                 "u": user_id},
            )
        ).scalar_one_or_none()
        if updated is None:
            raise HTTPException(status_code=404, detail="no_such_account")

    # Not appended to the audit chain: invariant 4 fixes a row's shape as
    # (case_id, doc_id, version, sha256, actor_id, action, utc_ts), and placing an
    # account belongs to no case. Widening the chain to carry case-less rows would be a
    # change to the thing whose narrowness is the point. Recorded in the log instead,
    # and named as a gap in docs/PLAN-PRODUCT.md.
    log.info(
        "account placed",
        extra={"actor": subject.user_id, "user_id": user_id, "post_id": body.post_id,
               "clearance": body.clearance_level, "active": body.is_active},
    )
    return {"placed": True}


@router.post("/users/{user_id}/suspend")
async def suspend_account(
    user_id: str, request: Request, subject: Subject = Depends(require_admin)
):
    """Deactivate an account. Takes effect on the next request, not at session end.

    `require_subject` re-resolves `is_active` from the database every time, so there is
    no window in which a suspended account keeps working with a valid cookie.
    """
    if user_id == subject.user_id:
        # Not a moral position: an administrator who suspends themselves may leave a
        # system with no reachable administrator at all.
        raise HTTPException(status_code=400, detail="cannot_suspend_yourself")

    engine = request.app.state.engine
    async with engine.begin() as conn:
        updated = (
            await conn.execute(
                sa.text("UPDATE app_user SET is_active = false WHERE id = :u RETURNING id"),
                {"u": user_id},
            )
        ).scalar_one_or_none()
    if updated is None:
        raise HTTPException(status_code=404, detail="no_such_account")
    log.info("account suspended", extra={"actor": subject.user_id, "user_id": user_id})
    return {"suspended": True}


@router.post("/users/{user_id}/restore")
async def restore_account(
    user_id: str, request: Request, subject: Subject = Depends(require_admin)
):
    """Undo a suspension and clear a lockout. The control that did not exist.

    **Suspension was irreversible through the product.** The accounts table renders a
    Suspend button and, for a suspended account, static text. The only statement
    anywhere that set `is_active` back to true lived inside `/users/{id}/place`, which
    the web tier offers solely in the "awaiting placement" list - and a suspended
    officer still holds a post, so they never appear in it. Recovery meant hand-crafting
    a POST with the right post and clearance, or a psql UPDATE.

    **It also answers the lockout.** Eight wrong passwords lock an account for fifteen
    minutes, and the rate limiter allows thirty login attempts a minute from one
    address - so roughly one request every two minutes holds a named officer out
    indefinitely. `locked_until` is a column, so restarting the api does not clear it.
    The administration screen showed a `locked` badge and offered nothing that cleared
    it. This does, without touching the post or the clearance: restoring access is not
    the same act as changing what somebody may reach, and conflating them is how an
    unlock quietly becomes a promotion.
    """
    engine = request.app.state.engine
    async with engine.begin() as conn:
        updated = (
            await conn.execute(
                sa.text(
                    "UPDATE app_user "
                    "SET is_active = true, failed_attempts = 0, locked_until = NULL "
                    "WHERE id = :u RETURNING id"
                ),
                {"u": user_id},
            )
        ).scalar_one_or_none()
    if updated is None:
        raise HTTPException(status_code=404, detail="no_such_account")
    log.info("account restored", extra={"actor": subject.user_id, "user_id": user_id})
    return {"restored": True}


@router.post("/assignments")
async def assign_to_case(
    body: AssignmentRequest, request: Request, subject: Subject = Depends(require_admin)
):
    """Designate an account on a case. This is what actually opens a case to somebody."""
    engine = request.app.state.engine
    async with engine.begin() as conn:
        # Selected as a row, not a scalar: `post_id` is nullable since migration 0009,
        # so a scalar None cannot tell "no such account" from "account holds no post" —
        # two different answers with two different fixes.
        target = (
            await conn.execute(
                sa.text("SELECT id, post_id FROM app_user WHERE id = :u AND is_active"),
                {"u": body.user_id},
            )
        ).mappings().one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="no_such_active_account")
        if target["post_id"] is None:
            # A designation on a case would otherwise be held by an account with no
            # organization or jurisdiction, which no case_read rule can ever satisfy:
            # a row that looks like access and grants none.
            raise HTTPException(status_code=400, detail="account_holds_no_post")

        case = (
            await conn.execute(
                sa.text("SELECT id FROM case_record WHERE id = :c"), {"c": body.case_id}
            )
        ).scalar_one_or_none()
        if case is None:
            raise HTTPException(status_code=404, detail="no_such_case")

        live = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM case_assignment WHERE case_id = :c AND user_id = :u "
                    "AND (valid_to IS NULL OR valid_to > now())"
                ),
                {"c": body.case_id, "u": body.user_id},
            )
        ).scalar_one_or_none()
        if live is not None:
            return {"assigned": True, "already": True}

        await conn.execute(
            sa.text(
                "INSERT INTO case_assignment (id, case_id, user_id, valid_from, assigned_by) "
                "VALUES (gen_random_uuid(), :c, :u, now(), :by)"
            ),
            {"c": body.case_id, "u": body.user_id, "by": subject.user_id},
        )
        await append_audit(
            conn,
            case_id=body.case_id,
            actor_id=subject.user_id,
            action=AuditAction.ASSIGNMENT_CHANGED,
            object_type="app_user",
            object_id=body.user_id,
        )
    log.info(
        "assignment created",
        extra={"actor": subject.user_id, "user_id": body.user_id, "case_id": body.case_id},
    )
    return {"assigned": True}


@router.delete("/assignments")
async def end_assignment(
    body: AssignmentRequest, request: Request, subject: Subject = Depends(require_admin)
):
    """End a designation by closing its validity window.

    The row is **not deleted**. An assignment that once existed is part of the record of
    who could see what and when, and `valid_to` is what makes a past decision
    replayable. Deleting it would quietly rewrite that history.
    """
    engine = request.app.state.engine
    async with engine.begin() as conn:
        closed = (
            await conn.execute(
                sa.text(
                    "UPDATE case_assignment SET valid_to = now() "
                    "WHERE case_id = :c AND user_id = :u "
                    "AND (valid_to IS NULL OR valid_to > now()) RETURNING id"
                ),
                {"c": body.case_id, "u": body.user_id},
            )
        ).scalar_one_or_none()
        if closed is None:
            raise HTTPException(status_code=404, detail="no_live_assignment")
        await append_audit(
            conn,
            case_id=body.case_id,
            actor_id=subject.user_id,
            action=AuditAction.ASSIGNMENT_CHANGED,
            object_type="app_user",
            object_id=body.user_id,
        )
    log.info(
        "assignment ended",
        extra={"actor": subject.user_id, "user_id": body.user_id, "case_id": body.case_id},
    )
    return {"ended": True}


@router.post("/grants")
async def issue_grant(
    body: GrantRequest, request: Request, subject: Subject = Depends(require_admin)
):
    """Issue a purpose-limited, expiring, case-scoped grant.

    Purpose and expiry are not decoration: both are re-checked server-side on every
    request, and the grant dies by itself. A grant with no expiry is not expressible
    here, which is deliberate — AR-14 notes that expiry is doing most of the work that
    revocation administration would otherwise have to.
    """
    if body.grantee_id == subject.user_id:
        # Enforced at read time too, by `grant_not_self_issued`. Refusing it at write
        # time as well means the row never exists to be reasoned about.
        raise HTTPException(status_code=400, detail="cannot_grant_to_yourself")

    engine = request.app.state.engine
    expires = datetime.now(timezone.utc) + timedelta(days=body.days)
    async with engine.begin() as conn:
        grantee = (
            await conn.execute(
                sa.text("SELECT id FROM app_user WHERE id = :u AND is_active"),
                {"u": body.grantee_id},
            )
        ).scalar_one_or_none()
        if grantee is None:
            raise HTTPException(status_code=404, detail="no_such_active_account")
        case = (
            await conn.execute(
                sa.text("SELECT id FROM case_record WHERE id = :c"), {"c": body.case_id}
            )
        ).scalar_one_or_none()
        if case is None:
            raise HTTPException(status_code=404, detail="no_such_case")

        grant_id = (
            await conn.execute(
                sa.text(
                    "INSERT INTO access_grant "
                    "(id, grantee_id, case_id, purpose, expires_at, granted_by) "
                    "VALUES (gen_random_uuid(), :g, :c, :p, :e, :by) RETURNING id"
                ),
                {"g": body.grantee_id, "c": body.case_id, "p": body.purpose,
                 "e": expires, "by": subject.user_id},
            )
        ).scalar_one()
        await append_audit(
            conn,
            case_id=body.case_id,
            actor_id=subject.user_id,
            action=AuditAction.GRANT_ISSUED,
            object_type="access_grant",
            object_id=str(grant_id),
        )
    # The purpose is a free-text string a person typed. It is not logged: invariant 12
    # restricts logs to ids and decisions, and a purpose can name a person.
    log.info(
        "grant issued",
        extra={"actor": subject.user_id, "grant_id": str(grant_id),
               "case_id": body.case_id, "days": body.days},
    )
    return {"issued": True, "grant_id": str(grant_id), "expires_at": expires.isoformat()}


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: str, request: Request, subject: Subject = Depends(require_admin)
):
    """Revoke a grant. Effective on the next request; delivered bytes are unreachable.

    AR-7 is exact about the limit: revocation reaches the system's answers immediately
    and reaches nothing already downloaded, ever.
    """
    engine = request.app.state.engine
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "UPDATE access_grant SET revoked_at = now() "
                    "WHERE id = :g AND revoked_at IS NULL RETURNING case_id"
                ),
                {"g": grant_id},
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="no_live_grant")
        await append_audit(
            conn,
            case_id=str(row),
            actor_id=subject.user_id,
            action=AuditAction.GRANT_REVOKED,
            object_type="access_grant",
            object_id=grant_id,
        )
    log.info("grant revoked", extra={"actor": subject.user_id, "grant_id": grant_id})
    return {"revoked": True}


@router.get("/access")
async def current_access(
    request: Request, subject: Subject = Depends(require_admin)
):
    """Who currently holds access to what, and by which route.

    AR-14 named the absence of this as an accepted risk: "no way to answer *who
    currently has access to this case, and why*". This answers it for designations and
    grants, which are the only two routes that exist.
    """
    engine = request.app.state.engine
    async with engine.connect() as conn:
        assignments = (
            await conn.execute(
                sa.text(
                    "SELECT c.reference, u.id AS user_id, u.display_name, a.valid_from, a.valid_to "
                    "  FROM case_assignment a "
                    "  JOIN case_record c ON c.id = a.case_id "
                    "  JOIN app_user u ON u.id = a.user_id "
                    " WHERE a.valid_to IS NULL OR a.valid_to > now() "
                    " ORDER BY c.reference, u.display_name"
                )
            )
        ).mappings().all()
        grants = (
            await conn.execute(
                sa.text(
                    "SELECT g.id, c.reference, u.id AS user_id, u.display_name, g.purpose, g.expires_at "
                    "  FROM access_grant g "
                    "  JOIN case_record c ON c.id = g.case_id "
                    "  JOIN app_user u ON u.id = g.grantee_id "
                    " WHERE g.revoked_at IS NULL AND g.expires_at > now() "
                    " ORDER BY g.expires_at"
                )
            )
        ).mappings().all()
    return {
        "designations": [
            # `user_id` as well as the name: the administration screen counts rows
            # per account, and joining them on a DISPLAY NAME merges two officers who
            # share one - which reports each of them holding the other's access, on the
            # one screen whose job is to answer "who currently has access, and why".
            {"reference": r["reference"], "user_id": str(r["user_id"]),
             "display_name": r["display_name"],
             "since": r["valid_from"].isoformat() if r["valid_from"] else None}
            for r in assignments
        ],
        "grants": [
            {"grant_id": str(r["id"]), "reference": r["reference"],
             "user_id": str(r["user_id"]), "display_name": r["display_name"],
             "purpose": r["purpose"],
             "expires_at": r["expires_at"].isoformat()}
            for r in grants
        ],
    }
