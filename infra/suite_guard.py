"""One lock, honoured by everything that destroys the case tables — not just pytest.

`tests/conftest.py` has refused to run a second pytest session against a database
another suite is using since the day somebody worked out that the project's
long-standing "unexplained flake" was two suites truncating each other's rows. Its
docstring says the important part: the failure surfaces somewhere else entirely, in a
different test each run, and it looks exactly like flakiness.

**The lock only ever covered pytest**, and pytest is not the only thing that calls
`seed()`. `demo.py` does. `python seed.py` does. A one-off script written to poke the
running API does — which is how this gap was found: a review agent driving the app in
another process re-seeded mid-suite, and a test failed with a 404 on a version that had
existed a moment earlier. Exactly the symptom the docstring describes, from a direction
the lock did not watch.

So the check moves here, where both sides can reach it:

    conftest.py   takes the lock for the whole session, and marks this PROCESS as the
                  holder so the suite's own thousands of `seed()` calls pass through
    seed()        refuses when the lock is held by somebody else

A process marker rather than a re-entrant lock, because the two are not the same
question. "Am I allowed to truncate?" is answered by *who* is holding the lock, and the
holder is a whole pytest session that legitimately seeds hundreds of times inside it.

The lock is a file rather than a Postgres advisory lock for one reason: it must be
readable by a process that has not connected yet, so that a refusal costs nothing and
arrives before any damage. A stale one is cleaned up on age, because a crashed run must
not block the next one for ever.
"""
import hashlib
import os
import tempfile
import time
from pathlib import Path

# Long enough to cover a full suite several times over. A lock older than this belonged
# to a run that crashed.
STALE_LOCK_SECONDS = 30 * 60

# Set by conftest.py to this process's pid while it holds the lock. An environment
# variable rather than a module global, because `seed()` is sometimes invoked through
# `runpy` or a subprocess of the suite, and the marker has to survive that.
HOLDER_ENV = "ORDIN_SUITE_LOCK_HOLDER"


def lock_path(host: str, port: int, database: str) -> Path:
    """Keyed on the database, so two checkouts pointed at one database collide too.

    That is not hypothetical: the sibling tree at D:\\Legal Assistant once shared a
    container with this one, and a lock keyed on the checkout would have missed it.
    """
    fingerprint = hashlib.sha256(f"{host}:{port}/{database}".encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"ordin-suite-{fingerprint}.lock"


def clear_if_stale(path: Path) -> None:
    if path.exists() and time.time() - path.stat().st_mtime > STALE_LOCK_SECONDS:
        path.unlink(missing_ok=True)


def held_by_another_process(path: Path) -> str | None:
    """The holder's description, or None if this process may proceed.

    Returns None when the lock is absent, stale, or held by this very process — the
    last of which is how the suite seeds freely inside its own session.
    """
    clear_if_stale(path)
    if not path.exists():
        return None
    if os.environ.get(HOLDER_ENV) == str(os.getpid()):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or "an unnamed process"
    except OSError:
        return None


def refusal_message(path: Path, database: str, holder: str) -> str:
    return (
        f"refusing to seed: a test suite is using {database} (started by {holder}).\n"
        f"  seed() TRUNCATEs the case tables, so doing it now would delete rows that "
        f"suite is mid-way through asserting on - and the failure would surface in a "
        f"different test each run, looking like flakiness.\n"
        f"  Wait for it to finish, or delete {path} if nothing is running."
    )
