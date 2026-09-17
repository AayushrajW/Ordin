import socket
import sys
from pathlib import Path

import pytest

# The application is a layout, not an installed package - put the project root on
# the path so `import api` works without a build step.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings  # noqa: E402


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
