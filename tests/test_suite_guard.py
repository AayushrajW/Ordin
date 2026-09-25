"""The lock that stops two things truncating the case tables at once.

`tests/conftest.py` has refused a second pytest session since somebody worked out that
this project's long-standing "unexplained flake" was two suites deleting each other's
rows mid-assertion. The failure surfaces in a different test each run and reads as
flakiness, which is why it survived weeks of looking.

**The lock only ever watched pytest**, and pytest is not the only caller of `seed()`.
`demo.py` calls it, `python seed.py` calls it, and so does any one-off script written to
poke the running API. That last one is how the gap was found: a review agent driving the
app in a second process re-seeded mid-suite, and a test failed with a 404 on a version
that had existed a moment earlier - the documented symptom, from a direction nothing was
watching.

These tests run with no database and no application. They are about the guard.
"""
import os
import time
from pathlib import Path

import pytest

from infra import suite_guard


@pytest.fixture
def lock(tmp_path, monkeypatch):
    """A lock file in a temp directory, so a real suite's lock is never touched."""
    monkeypatch.setattr(suite_guard.tempfile, "gettempdir", lambda: str(tmp_path))
    path = suite_guard.lock_path("127.0.0.1", 5434, "ordin")
    monkeypatch.delenv(suite_guard.HOLDER_ENV, raising=False)
    return path


# --- what it refuses ------------------------------------------------------------


def test_an_absent_lock_lets_anybody_seed(lock):
    assert suite_guard.held_by_another_process(lock) is None


def test_a_lock_held_by_someone_else_refuses(lock):
    lock.write_text("pid 4242", encoding="utf-8")
    assert suite_guard.held_by_another_process(lock) == "pid 4242"


def test_the_holding_process_passes_through(lock, monkeypatch):
    """The suite seeds hundreds of times inside its own session, and must not be
    refused by its own lock. The question is *who* holds it, not whether it is held."""
    lock.write_text(f"pid {os.getpid()}", encoding="utf-8")
    monkeypatch.setenv(suite_guard.HOLDER_ENV, str(os.getpid()))
    assert suite_guard.held_by_another_process(lock) is None


def test_a_different_pid_in_the_marker_does_not_exempt(lock, monkeypatch):
    """The marker is this process's own pid, so a stale environment variable inherited
    by a child does not silently grant it the parent's exemption."""
    lock.write_text("pid 4242", encoding="utf-8")
    monkeypatch.setenv(suite_guard.HOLDER_ENV, "999999")
    assert suite_guard.held_by_another_process(lock) is not None


# --- what it must not do --------------------------------------------------------


def test_a_stale_lock_does_not_block_forever(lock):
    """A crashed run must not wedge every future run. The alternative - a lock that
    needs a human to clear it - is one that gets deleted reflexively, including while a
    real suite is holding it."""
    lock.write_text("pid 4242", encoding="utf-8")
    old = time.time() - suite_guard.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))

    assert suite_guard.held_by_another_process(lock) is None
    assert not lock.exists(), "a stale lock was reported clear but left on disk"


def test_an_unreadable_lock_does_not_wedge_the_seed(lock, monkeypatch):
    """Fails OPEN, deliberately, and this is the one place in the codebase that does.

    Everywhere else an error denies (invariant 2). This is not an authorization
    control - it is a developer convenience that prevents two processes corrupting each
    other's fixtures - and a convenience that can permanently block seeding because of
    an unreadable file is worse than the collision it prevents.
    """
    lock.write_text("pid 4242", encoding="utf-8")

    def explode(*args, **kwargs):
        raise OSError("unreadable")

    monkeypatch.setattr(Path, "read_text", explode)
    assert suite_guard.held_by_another_process(lock) is None


# --- the key is the database, not the checkout ----------------------------------


def test_the_lock_is_keyed_on_the_database(lock):
    """Two checkouts pointed at one database must collide; one checkout pointed at two
    databases must not. The sibling tree at D:\\Legal Assistant once shared a container
    with this one, and a lock keyed on the working directory would have missed it."""
    same = suite_guard.lock_path("127.0.0.1", 5434, "ordin")
    other_db = suite_guard.lock_path("127.0.0.1", 5434, "ordin_scratch")
    other_port = suite_guard.lock_path("127.0.0.1", 5432, "ordin")

    assert same == lock
    assert other_db != lock
    assert other_port != lock


def test_the_refusal_says_what_to_do(lock):
    message = suite_guard.refusal_message(lock, "ordin", "pid 4242")
    assert "ordin" in message
    assert "pid 4242" in message
    assert str(lock) in message, "the message does not say which file to delete"
    assert "TRUNCATE" in message, "the message does not say why it matters"
