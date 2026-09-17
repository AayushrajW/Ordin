"""The guard that turns a silent database collision into a loud one.

This exists because of a real incident, not a hypothetical. Two checkouts of this
project shared a postgres container (identical `container_name`, and container names
are globally unique in Docker). The other one migrated; this tree's schema vanished;
Alembic reported "at head" and was correct, about a revision history this tree has
never contained. A green 73-test suite had been running against a schema that no
longer existed.

`check_revision` is the cheap question that would have caught it immediately.
"""
from pathlib import Path

from infra.db_identity import check_revision, known_revisions

ROOT = Path(__file__).resolve().parents[1]


def test_reads_the_revisions_this_checkout_defines():
    revisions = known_revisions(ROOT / "alembic" / "versions")
    assert "0001_baseline" in revisions
    assert "0003_domain_model" in revisions


def test_our_own_revision_is_accepted():
    known = known_revisions(ROOT / "alembic" / "versions")
    assert check_revision("0003_domain_model", known).ok


def test_the_other_checkouts_revision_is_rejected():
    """`0003_domain` is the real revision id that replaced our schema."""
    known = known_revisions(ROOT / "alembic" / "versions")
    result = check_revision("0003_domain", known)
    assert not result.ok, (
        "a revision this checkout cannot produce was accepted as ours - this is the "
        "exact condition that made the incident silent"
    )
    assert "another project's database" in result.message


def test_an_unmigrated_database_is_not_treated_as_foreign():
    """No revision row yet is a normal starting state, not a collision."""
    known = known_revisions(ROOT / "alembic" / "versions")
    assert check_revision(None, known).ok


def test_missing_migration_files_fail_closed(tmp_path):
    """Invariant 2. If we cannot tell whose database it is, we do not assume ours."""
    result = check_revision("0001_baseline", known_revisions(tmp_path))
    assert not result.ok


def test_the_message_names_what_to_check(tmp_path):
    """A guard that fires without saying what to do costs more than it saves."""
    known = known_revisions(ROOT / "alembic" / "versions")
    message = check_revision("someone_elses_head", known).message
    assert "POSTGRES_PORT" in message and "container_name" in message
