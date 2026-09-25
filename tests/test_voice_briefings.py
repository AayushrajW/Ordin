"""The voice assistant must not speak an identifying value.

`VoiceAssistant.tsx` states the rule as absolute: "It never speaks an identifying
value... Counts, field names, flags and states only. The same reasoning as invariant 12:
the screen may show it to the person entitled to see it; the air may not." The panel
repeats that promise to the user, README.md states it, and docs/STATUS.md states it.

Two briefings broke it, and both were strings the codebase elsewhere says can name a
person:

  search       `Search for ${term}` — api/search.py: "The query itself can be a
               victim's name, and invariant 12 keeps it out of the log"
  case page    `a purpose-limited grant for ${summary.purpose}` — api/admin.py: "The
               purpose is a free-text string a person typed... a purpose can name a
               person"

An officer searching for a victim by name at a shared desk and pressing Alt+V had the
name read into the room, while the panel on screen asserted it never does that.

This is a source check rather than a rendering test, because the property is about what
CAN be assembled into a briefing, not about one page's output with one fixture. It runs
with nothing started.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "app"

# Values that can carry a person. Named after where they come from, so a failure says
# which source reached the air.
FORBIDDEN_IN_A_BRIEFING = {
    "term": "the raw search query",
    "q": "the raw search query",
    "summary.purpose": "the grant purpose, free text somebody typed",
    "summary?.purpose": "the grant purpose, free text somebody typed",
    "f.value": "an extracted field value, which is document content",
    "field.value": "an extracted field value, which is document content",
    "selected.value": "an extracted field value, which is document content",
    "p.display_name": "a party name",
    "party.display_name": "a party name",
}

# **The document title is a judged exception, not an oversight.**
#
# It is a filename somebody chose, so it can carry a name - `Sunita-Kale-statement.pdf`
# is a realistic upload. By the letter of rule 1 it should not be spoken. It is spoken
# anyway on the document page, because it is the only thing that tells a listener which
# document they are on: the alternative briefing is "Document, version 2. Integrity:
# VERIFIED", which identifies nothing and makes the feature pointless for the person it
# exists for.
#
# The bound that makes this defensible: the title is already rendered as the page
# heading, the listener is the person who opened that document, and reaching it required
# passing both the case filter and the disclosure check. That is a weaker argument than
# the one for the search term - which is typed by the person and never gated - and it is
# recorded here so the difference is a decision rather than an inconsistency.
SPOKEN_DESPITE_BEING_FREE_TEXT = {"document.title"}


def _briefing_sources() -> list[tuple[Path, str]]:
    """Every `briefing:` or `const briefing =` expression in the web tier.

    Captured to the end of the statement rather than the line, because these are
    multi-line template concatenations.
    """
    found: list[tuple[Path, str]] = []
    for path in WEB.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:briefing:|const briefing\s*=)", text):
            # Take a generous window: the longest of these is about fifteen lines.
            window = text[match.start(): match.start() + 1200]
            # Stop at the next top-level key or statement so we do not swallow the page.
            cut = re.search(r"\n\s{0,8}(commands:|\}\s*\}|return |const )", window[20:])
            found.append((path, window[: cut.start() + 20] if cut else window))
    return found


def test_there_are_briefings_to_check():
    """A source check that finds nothing passes vacuously. This is the guard."""
    sources = _briefing_sources()
    assert len(sources) >= 3, f"only found {len(sources)} briefings; the pattern is stale"


@pytest.mark.parametrize("expression,why", sorted(FORBIDDEN_IN_A_BRIEFING.items()))
def test_no_briefing_interpolates_an_identifying_value(expression, why):
    offenders = []
    for path, source in _briefing_sources():
        if f"${{{expression}" in source:
            offenders.append(f"{path.relative_to(ROOT)} interpolates {expression}")
    assert not offenders, (
        f"a spoken briefing carries {why}:\n  " + "\n  ".join(offenders)
    )


def test_the_case_briefing_still_says_the_route_without_the_purpose():
    """The briefing must stay useful. Dropping the purpose should not have dropped the
    fact that access is by grant — which is a flag, and flags are allowed."""
    source = (WEB / "cases" / "[caseId]" / "page.tsx").read_text(encoding="utf-8")
    assert "purpose-limited grant" in source
    assert "${summary.purpose}" not in source
    assert "${summary?.purpose}" not in source


def test_the_search_briefing_still_reports_counts():
    source = (WEB / "search" / "page.tsx").read_text(encoding="utf-8")
    assert "within your reach" in source, "the briefing lost its counts"
    assert "Search for ${term}" not in source


def test_the_document_briefing_names_the_document_it_is_describing():
    """The exception above, asserted so it stays a decision.

    If somebody later removes the title to satisfy rule 1 literally, this fails and
    they have to read why it is there rather than discovering the briefing has become
    useless.
    """
    source = (WEB / "documents" / "[documentId]" / "page.tsx").read_text(encoding="utf-8")
    assert "${document.title}" in source


def test_the_exception_list_stays_short():
    """One exception is a judgement. Five is a policy nobody decided on."""
    assert len(SPOKEN_DESPITE_BEING_FREE_TEXT) == 1
