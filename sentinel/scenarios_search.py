"""Search, as claims that can go red.

Invariant 1 names search and autocomplete as the worst offenders, and the reason is
that both leak while looking like they work. A search that ranks first and filters
afterwards still returns the right *rows* — and discloses the wrong things through its
counts, its pagination and its snippets.

SEARCH-01 asks for the exact reference of a case the caller cannot open. The only
acceptable answer is nothing at all.

SEARCH-02 is the one worth watching. A grantee holds a lawful grant, so the case is
theirs to find — and the document text is not, because they receive a redacted
derivative and the original's OCR text is the same content in a different shape
(threat VIC-01). A snippet would hand them precisely what redaction destroyed, through
a box built for convenience.
"""
from sentinel.registry import Severity, scenario

SLICE = "search"


async def _sign_in(ctx, key: str) -> None:
    response = await ctx.client.post("/session", json={"user_id": ctx.ids[key]})
    assert response.status_code == 200, f"could not open a session: {response.text}"


async def _a_word_from_an_original(ctx) -> str:
    """A word that genuinely appears in some original's OCR text.

    Taken from the data, never hardcoded. A scenario that searched for a word which
    happens not to be in the corpus would pass by finding nothing — reporting the
    control as holding precisely when it had tested nothing.
    """
    import sqlalchemy as sa

    async with ctx.engine.connect() as conn:
        text = (
            await conn.execute(
                sa.text(
                    "SELECT o.text FROM ocr_text o "
                    "JOIN document_version v ON v.id = o.version_id "
                    "WHERE v.derived_from_version_id IS NULL AND length(o.text) > 40 "
                    "LIMIT 1"
                )
            )
        ).scalar_one_or_none()
    assert text, "no original has OCR text; run `python tasks.py demo` first"
    words = [w.strip(".,:;()[]") for w in text.split()]
    word = next((w for w in words if len(w) >= 6 and w.isalpha()), None)
    assert word, "no usable word in the OCR text"
    return word


@scenario(
    id="SEARCH-01",
    invariant="1 - the authorization predicate is inside the query, not applied after",
    setup=(
        "Sign in as the designated officer and search for the exact reference of a case "
        "they hold no designation or grant on."
    ),
    expected="No case and no document is returned - not a redacted row, and not a count.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def unreachable_cases_are_not_searchable(ctx) -> str:
    import sqlalchemy as sa

    await _sign_in(ctx, "officer")

    # **The reachable set is what the caller can LIST, paged in full.** This used to be
    # `/search/all?q=VRN` - a substring search on the demo corpus's own reference prefix
    # - so any case whose reference did not contain "VRN" was classified as unreachable
    # no matter who was designated on it. The moment another scenario registered a case
    # under a different prefix, this asserted that search must not return a case the
    # officer was legitimately designated on, and failed. A precondition derived from a
    # fixture's naming convention is not a precondition.
    reachable: set[str] = set()
    offset = 0
    while True:
        page = (await ctx.client.get(f"/cases?limit=50&offset={offset}")).json()
        reachable.update(c["reference"] for c in page)
        if len(page) < 50:
            break
        offset += 50

    async with ctx.engine.connect() as conn:
        every = (
            await conn.execute(sa.text("SELECT reference FROM case_record"))
        ).scalars().all()
    others = [r for r in every if r not in reachable]
    assert others, "this identity reaches every case; the scenario proves nothing"

    for reference in others:
        body = (await ctx.client.get(f"/search/all?q={reference}")).json()
        assert body["cases"] == [], (
            f"searching {reference!r} returned {len(body['cases'])} case(s) to somebody "
            "with no route to it"
        )
        assert body["documents"] == [], (
            f"searching {reference!r} returned document text from an unreachable case"
        )
    return (
        f"{len(others)} unreachable reference(s) searched by exact match; "
        "every one returned nothing"
    )


@scenario(
    id="SEARCH-02",
    invariant="VIC-01 - a snippet is derived text, and derived text follows disclosure",
    setup=(
        "Take a word from an original's OCR text. Search it as the designated officer, "
        "then as a grantee who holds a lawful, unexpired grant on that same case."
    ),
    expected=(
        "The officer receives document hits with snippets. The grantee receives the "
        "case and no document text whatsoever, and is told that content was not searched."
    ),
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def a_grantee_gets_no_snippets(ctx) -> str:
    word = await _a_word_from_an_original(ctx)

    await _sign_in(ctx, "officer")
    officer = (await ctx.client.get(f"/search/all?q={word}")).json()
    assert officer["documents"], (
        f"the designated officer found no document for {word!r}, which came from an "
        "original's own text - the scenario cannot discriminate"
    )

    await ctx.client.delete("/session")
    await _sign_in(ctx, "grantee")
    grantee = (await ctx.client.get(f"/search/all?q={word}")).json()

    assert grantee["documents"] == [], (
        f"a grantee received {len(grantee['documents'])} document snippet(s) drawn from "
        "an original. Redaction destroyed that content in the copy they are entitled to, "
        "and search handed it back"
    )
    assert grantee["content_withheld"] is True, (
        "the response did not report that content was withheld, so a grantee cannot "
        "tell 'nothing matched' from 'nothing was searched'"
    )

    # Withholding content is not withholding the case, and that distinction is the whole
    # point. Checked with a *reference* query: case matching is on the reference, so the
    # word query above returns no cases to anybody, including the officer.
    reachable = (await ctx.client.get("/search/all?q=VRN")).json()
    assert reachable["cases"], (
        "the grantee cannot find the case they hold a lawful grant on; withholding the "
        "content has been over-applied to the case itself"
    )
    return (
        f"officer: {len(officer['documents'])} document hit(s) with snippets; "
        f"grantee: 0 documents, told why, and still finds "
        f"{len(reachable['cases'])} case(s) by reference"
    )
