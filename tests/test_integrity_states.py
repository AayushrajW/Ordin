"""Every branch of invariant 5, with nothing running.

The single most important assertion in this file is that a lawfully disposed document
returns DISPOSED_ANCHOR_ONLY and **never** MISMATCH. CLAUDE.md is explicit that
getting this wrong is not a cosmetic bug: it is a claim that evidence was tampered
with, made about a document that was destroyed lawfully.

The second is that a document awaiting its anchor returns PENDING rather than
UNAVAILABLE (ADR 0010). It is the normal state of every document for a few seconds
after upload, and rendering it as an error would make the demo show red for a system
behaving correctly.
"""
import pytest

from domain.integrity import AnchorFacts, VerificationState, VersionFacts, verify_version

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def facts(**overrides) -> VersionFacts:
    base = dict(
        version_id="v1",
        lifecycle_state="active",
        recorded_sha256=DIGEST_A,
        anchor=AnchorFacts(content_sha256=DIGEST_A),
        live_sha256=DIGEST_A,
        disposition_recorded=False,
    )
    return VersionFacts(**{**base, **overrides})


# --- the happy path -----------------------------------------------------------

def test_matching_bytes_verify():
    result = verify_version(facts())
    assert result.state is VerificationState.VERIFIED
    assert result.version_id == "v1"


@pytest.mark.parametrize("state", ["active", "superseded"])
def test_a_superseded_version_still_verifies_against_its_own_anchor(state):
    """`superseded` verifies the historical version; it is not an error state."""
    assert verify_version(facts(lifecycle_state=state)).state is VerificationState.VERIFIED


# --- tampering ----------------------------------------------------------------

def test_altered_bytes_are_a_mismatch():
    result = verify_version(facts(live_sha256=DIGEST_B))
    assert result.state is VerificationState.MISMATCH
    assert "do not match" in result.detail


def test_the_mismatch_names_the_diverged_version():
    """The acceptance criterion says MISMATCH must name which version diverged."""
    assert verify_version(facts(version_id="v-42", live_sha256=DIGEST_B)).version_id == "v-42"


def test_a_version_row_disagreeing_with_its_anchor_is_a_mismatch():
    """Bytes matching the anchor is not enough if the row claims something else.

    This is the shape of an insider edit that updates the version record and leaves
    the anchor alone, hoping only the bytes get compared.
    """
    result = verify_version(facts(recorded_sha256=DIGEST_B))
    assert result.state is VerificationState.MISMATCH
    assert "version record" in result.detail


# --- lawful disposal, the one that must never read as tampering ---------------

def test_a_disposed_document_is_not_a_tampered_one():
    result = verify_version(
        facts(lifecycle_state="disposed", live_sha256=None, disposition_recorded=True)
    )
    assert result.state is VerificationState.DISPOSED_ANCHOR_ONLY, (
        "a lawfully disposed document reported as anything else - CLAUDE.md calls "
        "this both a correctness bug and a legal misrepresentation"
    )


def test_disposal_is_decided_before_the_bytes_are_considered():
    """Even with bytes present and diverging, disposal wins.

    Checking the digest first would report MISMATCH for a lawful disposal, which is
    exactly the error invariant 5 names.
    """
    result = verify_version(
        facts(lifecycle_state="disposed", live_sha256=DIGEST_B, disposition_recorded=True)
    )
    assert result.state is VerificationState.DISPOSED_ANCHOR_ONLY


def test_disposal_without_a_disposition_record_is_not_attested_as_lawful():
    """"The bytes are gone and we cannot say why" must not render as a clean disposal."""
    result = verify_version(
        facts(lifecycle_state="disposed", live_sha256=None, disposition_recorded=False)
    )
    assert result.state is VerificationState.UNAVAILABLE


def test_disposal_without_an_anchor_is_not_attested_either():
    result = verify_version(
        facts(lifecycle_state="disposed", anchor=None, live_sha256=None,
              disposition_recorded=True)
    )
    assert result.state is VerificationState.UNAVAILABLE


# --- pending, per ADR 0010 -----------------------------------------------------

def test_an_unanchored_version_is_pending_not_unavailable():
    result = verify_version(facts(anchor=None))
    assert result.state is VerificationState.PENDING, (
        "a document waiting for its anchor is valid per the reliability invariants; "
        "reporting UNAVAILABLE would render a normal state as an incident"
    )


def test_pending_is_reported_even_though_the_bytes_are_present():
    """The distinguishing fact is the absent anchor, not absent bytes."""
    assert verify_version(facts(anchor=None, live_sha256=DIGEST_A)).state is (
        VerificationState.PENDING
    )


def test_pending_and_unavailable_are_different_states():
    unanchored = verify_version(facts(anchor=None))
    missing_bytes = verify_version(facts(live_sha256=None))
    assert unanchored.state is VerificationState.PENDING
    assert missing_bytes.state is VerificationState.UNAVAILABLE
    assert unanchored.state is not missing_bytes.state


# --- unavailable ---------------------------------------------------------------

def test_anchored_but_unreadable_bytes_are_unavailable():
    result = verify_version(facts(live_sha256=None))
    assert result.state is VerificationState.UNAVAILABLE
    assert "could not be read" in result.detail


# --- the contract itself -------------------------------------------------------

def test_the_result_is_never_a_boolean():
    """Invariant 5's first clause. A boolean cannot express four of these five."""
    result = verify_version(facts())
    assert not isinstance(result.state, bool)
    assert isinstance(result.state, VerificationState)


def test_exactly_five_states_exist():
    assert {s.value for s in VerificationState} == {
        "VERIFIED", "MISMATCH", "DISPOSED_ANCHOR_ONLY", "PENDING", "UNAVAILABLE"
    }


def test_no_detail_string_could_carry_document_content():
    """Invariant 12. Details are ours, short, and about state - never about content."""
    for f in (facts(), facts(live_sha256=DIGEST_B), facts(anchor=None),
              facts(lifecycle_state="disposed", live_sha256=None, disposition_recorded=True),
              facts(live_sha256=None)):
        detail = verify_version(f).detail
        assert len(detail) < 120
        assert DIGEST_A not in detail and DIGEST_B not in detail
