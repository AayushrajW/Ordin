# 08 — Ordin Sentinel, on a page

> Status: complete. The registry has been accruing since slice 3; this renders it.

## What it does

Fifteen scenarios, each a security claim this system makes expressed as something that
can visibly go red: id, invariant, setup, expected, actual, severity, slice, outcome.
The same scenarios `python tasks.py sentinel` prints, rendered for someone standing in
front of the screen.

They are contributed by slices as those slices land — seven from authorization, four
from redaction, three from verification, one over the audit chain — rather than written
as a late slice that would not have got built.

## Why this design

**Every load runs them** (ADR 0015). Storing a run and displaying the most recent one is
the normal thing to build and it is the failure the registry's own docstring warns
about: a saved result can show green from an hour ago, after the code changed or the
database was replaced. A check that cannot currently fail manufactures confidence, and a
dashboard is where manufactured confidence gets believed.

**ERROR is its own state.** A scenario that raised proved nothing. Counting it as a pass
is how a dashboard lies; counting it as a failure makes a broken instrument look like a
broken system. This mattered in practice — when the context object lost an attribute,
two critical scenarios reported ERROR rather than quietly passing, which is how the gap
was found.

**Registration is discovery, not a list.** Three places imported the scenario modules by
name, and the test's copy fell behind: slice 5b added four scenarios and the pytest suite
kept running eleven, so the newest and least proven checks were the ones running only by
hand. `load_scenarios()` walks `sentinel/scenarios_*.py`, and a test asserts the
discovery reaches every file.

**Scenarios establish their own preconditions.** `fresh && seed && sentinel` is the demo
sequence, so a scenario that failed for want of a fixture would report the system broken
when it is not. They push their own document through the real pipeline — which is also
why one of them creating a second version would show up immediately.

## The two questions a judge will ask

**"Can any of these actually fail?"**

Yes, and that is the thing worth doing rather than saying. Comment out the
`_require_original` guard in `api/documents.py`, reload the page, and VERIFY-02 goes red
with the actual result printed beside the expected one. The scenarios were also caught
failing for real during the build: one reported a grantee being shown a document it
should not see, and the scenario was wrong rather than the system — the fix narrowed the
claim to the one that does not depend on what else ran.

**"What does green here actually mean?"**

That fifteen specific claims held against the running application, just now, on this
database. It does not mean the system is secure. The scenarios cover authorization at the
query layer, disclosure of derivatives, destructive redaction, the manifest's contents,
the human-commit invariant and the audit chain's linkage. They do not cover anything in
the accepted-risk list in the threat model — notably that the anchor sits in the same
database under the same administrator as the artefact it anchors (AR-4), and that
redaction covers only what OCR located (AR-6).
