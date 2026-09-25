"""A 422 must not hand the submitted value back.

FastAPI's default validation response carries an `input` key holding the offending value
verbatim. For most applications that is a convenience. For this one the request bodies
are a plaintext password on signup, a written justification on break-glass, and the text
of an extracted field on a manual entry — so the default shape returns a credential or
document content to the caller, writes it into any proxy log in between, and leaves it
in the browser's network tab. Invariant 12 forbids exactly that.

The fix is one handler registered for the whole application rather than a change per
model, so anything added later inherits it instead of having to remember. These tests
drive the routes that need no session, because authentication runs *before* body
validation — an authenticated route answers 401 to an unauthenticated caller and never
reaches the validator. That ordering is why the signup path is the one that proves the
property: it is the route where an unauthenticated stranger's own secret is the input.
"""
import json

import httpx
import pytest

from api.main import create_app


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def flat(body) -> str:
    """Everything the response says, as one string, so nothing hides in a nested key."""
    return json.dumps(body)


async def test_a_short_password_is_not_echoed_back(client):
    secret = "hunter2"
    response = await client.post(
        "/auth/signup",
        json={"email": "a@b.example", "password": secret, "display_name": "A"},
    )
    assert response.status_code == 422, response.text
    assert secret not in flat(response.json()), (
        "the submitted password came back in the validation error"
    )


async def test_a_long_password_is_not_echoed_back_either(client):
    """The other side of the length constraint, because `max_length` and `min_length`
    are different validators and only one of them was ever going to be exercised."""
    secret = "x" * 5000
    response = await client.post(
        "/auth/login", json={"email": "a@b.example", "password": secret}
    )
    assert response.status_code == 422, response.text
    assert secret[:64] not in flat(response.json())


async def test_a_wrong_typed_field_is_not_echoed_back(client):
    """A type error is a different validator again, and its default message sometimes
    quotes the value where a length error does not."""
    response = await client.post(
        "/auth/signup",
        json={"email": {"nested": "secret-value-here"}, "password": "x", "display_name": "A"},
    )
    assert response.status_code == 422, response.text
    assert "secret-value-here" not in flat(response.json())


async def test_the_error_still_says_which_field_and_why(client):
    """Scrubbing must not make the response useless. A 422 that names no field is a
    worse answer than one that echoes a value, and the fix would have traded one defect
    for another."""
    response = await client.post(
        "/auth/signup",
        json={"email": "a@b.example", "password": "short", "display_name": "A"},
    )
    detail = response.json()["detail"]
    assert detail, "no errors reported at all"
    first = detail[0]
    assert first["loc"] == ["body", "password"]
    assert first["msg"], "no message"
    assert "input" not in first, "the raw input survived the scrub"


async def test_every_error_in_a_multi_field_failure_is_scrubbed(client):
    """One bad field must not be scrubbed while the next one leaks. The handler walks
    the whole list, and a test that submitted a single bad field would not have noticed
    if it had not."""
    response = await client.post(
        "/auth/signup",
        json={"email": "x", "password": "short", "display_name": ""},
    )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert len(errors) >= 2, f"expected several errors, got {errors}"
    assert all("input" not in e for e in errors)
