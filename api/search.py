"""Search, with the authorization predicate inside every query.

This is the most dangerous surface in the product, and it is worth saying why before
the code. Invariant 1 names search and autocomplete as the worst offenders: a search
that ranks first and filters afterwards leaks through **result counts**, through
**pagination behaviour**, and through **snippets** — three channels that all look like
features. Three letters must never surface a name from a case the caller cannot open.

So every query below begins from `authorized_cases`/`authorized_case_ids`, which return
a `Select` with the policy compiled into the WHERE clause. Nothing here filters a list
in Python.

**Snippets are gated by disclosure class, not by case access.** Passing the case filter
is not enough to receive text from a document. A grantee receives redacted derivatives
(ADR 0013), and the original's OCR text is original content in a different shape
(threat VIC-01) — so a snippet drawn from `ocr_text` would hand a grantee exactly what
redaction destroyed, through a search box. The rule here is therefore stricter than the
case filter:

    designation  -> document content is searched, and snippets are returned
    grant        -> the case is found; **no document content is searched at all**

A grantee's derivatives carry no text layer, so there is genuinely nothing of theirs to
search. The response says so rather than silently returning fewer results, because
"your search found nothing" and "your search did not look" are different facts.

**Snippets are built by Postgres `ts_headline` over text the subject may already read in
full.** No snippet is ever constructed for a document the caller could not open directly.
"""
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from api.deps import policy as get_policy, require_subject
from domain.policy import Policy
from domain.subject import Subject
from infra.authz import authorized_case_ids, authorized_cases
from infra.tables import case_assignment

log = logging.getLogger("ordin.api.search")
router = APIRouter(tags=["search"])

MAX_RESULTS = 25


class CaseHit(BaseModel):
    case_id: str
    reference: str
    state: str
    is_sealed: bool


class DocumentHit(BaseModel):
    document_id: str
    version_id: str
    title: str
    case_id: str
    case_reference: str
    snippet: str


class SearchResults(BaseModel):
    query: str
    cases: list[CaseHit]
    documents: list[DocumentHit]
    # True when at least one reachable case was excluded from the content search
    # because the caller receives redacted derivatives only.
    content_withheld: bool
    note: str | None = None


@router.get("/search/all")
async def search_everything(
    request: Request,
    q: str = Query(min_length=2, max_length=128),
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> SearchResults:
    engine = request.app.state.engine
    at = datetime.now(timezone.utc)
    term = q.strip()

    async with engine.connect() as conn:
        # --- cases -------------------------------------------------------------
        # Starts from the authorized select; the reference match is an additional
        # condition on it, never a filter applied to its results.
        allowed = authorized_cases(policy, subject, at).subquery()
        case_rows = (
            await conn.execute(
                sa.select(
                    allowed.c.id, allowed.c.reference, allowed.c.state, allowed.c.access_class
                )
                .where(allowed.c.reference.ilike(f"%{term}%"))
                .order_by(allowed.c.reference)
                .limit(MAX_RESULTS)
            )
        ).mappings().all()

        # --- which of my cases give me originals? ------------------------------
        # Disclosure is per case: a designation yields ORIGINAL, a grant yields
        # REDACTED (ADR 0013). Only the first may have its content searched.
        ids = authorized_case_ids(policy, subject, at).subquery()
        # Composed, not interpolated. An earlier draft wrote this EXISTS as a text
        # fragment naming `anon_1`, the alias SQLAlchemy happens to generate — which
        # would break silently the day the surrounding query changed shape, and a
        # broken EXISTS here widens the set whose content gets searched.
        designated = (
            await conn.execute(
                sa.select(ids.c.id).where(
                    sa.exists(
                        sa.select(sa.literal(1)).where(
                            case_assignment.c.case_id == ids.c.id,
                            case_assignment.c.user_id == subject.user_id,
                            case_assignment.c.valid_from <= sa.func.now(),
                            sa.or_(
                                case_assignment.c.valid_to.is_(None),
                                case_assignment.c.valid_to > sa.func.now(),
                            ),
                        )
                    )
                )
            )
        ).scalars().all()
        reachable = (await conn.execute(sa.select(ids.c.id))).scalars().all()
        designated_ids = [str(x) for x in designated]
        withheld = len(reachable) > len(designated_ids)

        document_rows = []
        if designated_ids:
            # `plainto_tsquery` treats the input as words, never as query syntax, so a
            # caller cannot inject operators. `simple`, matching migration 0010.
            document_rows = (
                await conn.execute(
                    sa.text(
                        "SELECT d.id AS document_id, v.id AS version_id, d.title, "
                        "       c.id AS case_id, c.reference, "
                        "       ts_headline('simple', o.text, plainto_tsquery('simple', :q), "
                        "         'MaxWords=18, MinWords=6, ShortWord=2, MaxFragments=1, "
                        "          StartSel=<<, StopSel=>>') AS snippet "
                        "  FROM ocr_text o "
                        "  JOIN document_version v ON v.id = o.version_id "
                        "  JOIN document d ON d.id = v.document_id "
                        "  JOIN case_record c ON c.id = d.case_id "
                        " WHERE c.id = ANY(:ids) "
                        # A derivative has no text layer, so this is belt and braces:
                        # nothing should ever have indexed one.
                        "   AND v.derived_from_version_id IS NULL "
                        "   AND to_tsvector('simple', o.text) @@ plainto_tsquery('simple', :q) "
                        " ORDER BY ts_rank(to_tsvector('simple', o.text), "
                        "                  plainto_tsquery('simple', :q)) DESC "
                        " LIMIT :lim"
                    ),
                    {"q": term, "ids": designated_ids, "lim": MAX_RESULTS},
                )
            ).mappings().all()

    # Counts and the query length only. The query itself can be a victim's name, and
    # invariant 12 keeps it out of the log — `api/logging.py` says the query string is
    # exactly where a name ends up recorded by accident.
    log.info(
        "search",
        extra={
            "user_id": subject.user_id,
            "cases": len(case_rows),
            "documents": len(document_rows),
            "content_withheld": withheld,
        },
    )

    note = None
    if withheld:
        note = (
            "Some cases you can reach are not included in the document search. You "
            "receive redacted derivatives of those, which carry no text layer — so "
            "there is nothing of yours to search, rather than results being hidden."
        )

    return SearchResults(
        query=term,
        cases=[
            CaseHit(
                case_id=str(r["id"]),
                reference=r["reference"],
                state=r["state"],
                is_sealed=r["access_class"] == "sealed",
            )
            for r in case_rows
        ],
        documents=[
            DocumentHit(
                document_id=str(r["document_id"]),
                version_id=str(r["version_id"]),
                title=r["title"],
                case_id=str(r["case_id"]),
                case_reference=r["reference"],
                snippet=r["snippet"] or "",
            )
            for r in document_rows
        ],
        content_withheld=withheld,
        note=note,
    )
