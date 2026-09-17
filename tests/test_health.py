"""The /health contract.

Two of these tests exist because of specific invariants, not because a health
endpoint is interesting:

  Invariant 2 (deny by default, fail closed). The tempting bug is returning 200
  with status "unknown" when a dependency check raises. That is degrading open.
  An unreachable dependency must produce 503.

  Invariant 12 (never log document content, identifiers, keys or raw OCR text;
  log IDs and decisions only). A health endpoint that returns the raw driver
  exception hands out the DSN, the host and the password. Slice 1 sets the
  pattern every later slice copies, so it gets asserted here.
"""
import httpx
import pytest

from api.config import Settings
from api.main import create_app

UNREACHABLE_PORT = 59999  # nothing listens here


def settings_with_dead_database() -> Settings:
    return Settings(
        postgres_host="127.0.0.1",
        postgres_port=UNREACHABLE_PORT,
        postgres_db="ordin",
        ordin_app_user="ordin_app",
        ordin_app_password="irrelevant",
        postgres_owner_user="ordin_owner",
        postgres_owner_password="irrelevant",
    )


async def call_health(settings: Settings) -> httpx.Response:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


# --- fail closed -------------------------------------------------------------

async def test_unreachable_database_returns_503_not_200():
    """Invariant 2. A dependency that cannot be reached is not 'unknown', it is down."""
    response = await call_health(settings_with_dead_database())
    assert response.status_code == 503, (
        f"expected 503 for an unreachable database, got {response.status_code}. "
        f"Returning 2xx when a check fails is degrading open."
    )
    body = response.json()
    assert body["status"] == "unhealthy"
    database = next(c for c in body["checks"] if c["name"] == "database")
    assert database["status"] == "down"


async def test_failure_reason_is_enumerated_never_an_exception_string():
    """Invariant 12. The reason is a code we chose, not whatever the driver said."""
    response = await call_health(settings_with_dead_database())
    database = next(c for c in response.json()["checks"] if c["name"] == "database")
    assert database["reason"] in {"unreachable", "auth_failed", "timeout", "error"}, (
        f"reason {database['reason']!r} is not one of the enumerated codes - this is "
        f"how a raw exception string reaches a caller"
    )


async def test_response_body_leaks_no_credentials_or_dsn():
    """Invariant 12, the part that actually bites: the password is in the DSN."""
    settings = settings_with_dead_database()
    settings.ordin_app_password = "hunter2-should-never-appear"
    response = await call_health(settings)
    raw = response.text
    for forbidden in ("hunter2-should-never-appear", "postgresql://", "asyncpg", "Traceback"):
        assert forbidden not in raw, (
            f"{forbidden!r} appears in the /health response body"
        )


# --- correlation ids ---------------------------------------------------------

async def test_response_carries_a_correlation_id():
    response = await call_health(settings_with_dead_database())
    assert response.headers.get("x-correlation-id"), "no X-Correlation-Id header"


async def test_supplied_correlation_id_is_echoed_back():
    """A caller's id must survive, or tracing across api and worker is impossible."""
    app = create_app(settings_with_dead_database())
    transport = httpx.ASGITransport(app=app)
    supplied = "test-correlation-0001"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Correlation-Id": supplied})
    assert response.headers.get("x-correlation-id") == supplied


# --- the happy path ----------------------------------------------------------

@pytest.mark.requires_db
async def test_healthy_when_database_is_up(live_settings):
    response = await call_health(live_settings)
    assert response.status_code == 200, f"expected 200, got {response.status_code}"
    body = response.json()
    assert body["status"] == "healthy"
    database = next(c for c in body["checks"] if c["name"] == "database")
    assert database["status"] == "up"
    assert isinstance(database["latency_ms"], (int, float))


@pytest.mark.requires_db
async def test_every_declared_dependency_is_checked(live_settings):
    """'/health checking each dependency' - not a hardcoded ok."""
    body = (await call_health(live_settings)).json()
    names = {c["name"] for c in body["checks"]}
    assert "database" in names
    assert body["checks"], "health reported no checks at all"
