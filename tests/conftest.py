import hashlib
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

# The application is a layout, not an installed package - put the project root on
# the path so `import api` works without a build step.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings  # noqa: E402
from infra import suite_guard  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Configuration as the app would load it. Does not require a running database."""
    return Settings()


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def only_one_suite_at_a_time(settings: Settings):
    """Refuse to run while another pytest process is using this database.

    **This is the explanation for the "unexplained flake" STATUS carried for weeks.**
    Nearly every test that touches the database calls `seed()`, which
    `TRUNCATE ... CASCADE`s the case tables. Two suites against one database therefore
    delete each other's rows mid-test, and the failure surfaces somewhere else
    entirely: a second version that should have been found, a foreign key that was
    valid a moment ago, a different test each run. It looks exactly like flakiness and
    it is not.

    The recorded hypothesis — transient database state after a container restart — was
    wrong, and was wrong in the direction that stops you looking: it blamed the
    environment for something reproducible on demand by running two suites at once.

    A session-held advisory lock makes the second run say so and stop. It is not
    serialisation: a suite that waits would still interleave its `seed()` with nothing
    useful. Refusing is the correct behaviour, because the second run cannot produce a
    trustworthy result.
    """
    if not _port_is_open(settings.postgres_host, settings.postgres_port):
        yield
        return

    # Keyed on the database this suite will actually use, so two checkouts pointed at
    # one database collide too — which is how the sibling tree at D:\Legal Assistant
    # once shared a container with this one.
    #
    # The path and the staleness rule now live in `infra/suite_guard.py`, because this
    # lock stopped being a pytest-only concern: `seed()` consults the same file, so a
    # stray `python seed.py`, a `demo.py` run, or a script somebody wrote to poke the
    # running API is refused too. Pytest was never the only thing that truncates.
    lock = suite_guard.lock_path(
        settings.postgres_host, settings.postgres_port, settings.postgres_db
    )
    suite_guard.clear_if_stale(lock)

    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = lock.read_text(encoding="utf-8", errors="replace").strip()
        pytest.exit(
            f"another test suite is already using {settings.postgres_db} at "
            f"{settings.postgres_host}:{settings.postgres_port} (started by {holder}).\n"
            f"  Nearly every database test calls seed(), which TRUNCATEs the case "
            f"tables, so two suites delete each other's rows mid-test and fail "
            f"somewhere unrelated.\n"
            f"  Wait for it to finish, or delete {lock} if nothing is running.",
            returncode=2,
        )

    os.write(handle, f"pid {os.getpid()}".encode())
    os.close(handle)
    # Mark THIS process as the holder, so the suite's own several-hundred `seed()`
    # calls pass straight through the guard that refuses everybody else. The question
    # the guard answers is "who holds the lock", not "is it held" - the holder is a
    # whole pytest session that legitimately re-seeds inside itself.
    os.environ[suite_guard.HOLDER_ENV] = str(os.getpid())
    try:
        yield
    finally:
        os.environ.pop(suite_guard.HOLDER_ENV, None)
        lock.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def live_settings(settings: Settings) -> Settings:
    """Settings, but only for tests that genuinely need postgres listening.

    Skips rather than fails when the database is down, because a developer running
    the unit tests without docker should not see red for an unrelated reason.

    The guarantee that these actually RUN comes from `python tasks.py test`, which
    starts postgres and waits for it to be healthy before invoking pytest, and
    reports how many requires_db tests were skipped. A silently skipped test is
    the same failure mode as a silently dead hook.
    """
    if not _port_is_open(settings.postgres_host, settings.postgres_port):
        pytest.skip(
            f"postgres not reachable at {settings.postgres_host}:{settings.postgres_port} "
            f"- run `python tasks.py up` first"
        )
    return settings
