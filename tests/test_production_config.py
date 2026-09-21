"""The production configuration guard (docs/PLAN-PRODUCT.md P5).

Every value checked here produces a system that **starts, serves traffic and looks
entirely correct** when it is wrong. That is the whole reason the guard raises instead
of warning: a warning in a log nobody reads is exactly how a placeholder session secret
reaches a pilot.

`ORDIN_SESSION_SECRET` is the sharpest of them. It signs the token from which every
access decision is resolved, so a known value is not a weak password — it is the ability
to mint a session as any account, including an administrative one, without touching the
database (threat SESS-01).
"""
import pytest

from api.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "ordin_env": "production",
        "ordin_session_secret": "l" * 48,
        "ordin_app_password": "a real password",
        "postgres_owner_password": "another real password",
        # Encryption at rest is part of a sound production configuration now: without
        # it, document bytes reach the disk in plaintext (ADR 0028).
        "ordin_master_key": "b3JkaW4tdGVzdC1tYXN0ZXIta2V5LTMyLWJ5dGVzISE",
    }
    base.update(overrides)
    return Settings(**base)


def test_a_sound_production_configuration_is_accepted():
    _settings().refuse_unsafe_production()


def test_dev_is_never_refused():
    """The guard must not make the development loop harder than it already is."""
    Settings(
        ordin_env="dev",
        ordin_session_secret="change_me_session_secret",
        ordin_app_password="change_me_app",
    ).refuse_unsafe_production()


@pytest.mark.parametrize("secret", ["", "change_me_session_secret", "changeme", "secret", "dev"])
def test_a_placeholder_session_secret_refuses_to_start(secret):
    with pytest.raises(RuntimeError, match="ORDIN_SESSION_SECRET"):
        _settings(ordin_session_secret=secret).refuse_unsafe_production()


def test_a_short_session_secret_refuses_to_start():
    """Not a style rule. A guessable signing key mints sessions as anybody."""
    with pytest.raises(RuntimeError, match="32 characters"):
        _settings(ordin_session_secret="short-but-not-a-placeholder").refuse_unsafe_production()


@pytest.mark.parametrize(
    "field,name",
    [
        ("ordin_app_password", "ORDIN_APP_PASSWORD"),
        ("postgres_owner_password", "POSTGRES_OWNER_PASSWORD"),
    ],
)
@pytest.mark.parametrize("value", ["", "change_me_app", "change_me_owner"])
def test_a_template_database_password_refuses_to_start(field, name, value):
    with pytest.raises(RuntimeError, match=name):
        _settings(**{field: value}).refuse_unsafe_production()


def test_an_unset_master_key_refuses_to_start():
    """Without it, every document reaches the disk readable to anyone with a shell."""
    with pytest.raises(RuntimeError, match="ORDIN_MASTER_KEY"):
        _settings(ordin_master_key="").refuse_unsafe_production()


def test_the_refusal_names_every_problem_at_once():
    """One restart per mistake is how a deployment takes an afternoon."""
    with pytest.raises(RuntimeError) as raised:
        _settings(
            ordin_session_secret="",
            ordin_app_password="",
            postgres_owner_password="change_me_owner",
            ordin_master_key="",
        ).refuse_unsafe_production()
    message = str(raised.value)
    for name in (
        "ORDIN_SESSION_SECRET", "ORDIN_APP_PASSWORD",
        "POSTGRES_OWNER_PASSWORD", "ORDIN_MASTER_KEY",
    ):
        assert name in message, f"{name} was not reported: {message}"


def test_the_refusal_does_not_print_the_values():
    """A guard that echoes the secret it is complaining about has leaked it to the log."""
    with pytest.raises(RuntimeError) as raised:
        _settings(
            ordin_session_secret="short", ordin_app_password="hunter2-the-real-one"
        ).refuse_unsafe_production()
    assert "hunter2" not in str(raised.value)


@pytest.mark.parametrize("env,production", [
    ("dev", False), ("development", False), ("test", False),
    ("production", True), ("prod", True), ("staging", True), ("pilot", True),
])
def test_anything_that_is_not_development_is_treated_as_production(env, production):
    """Fail closed on the environment name too.

    An unrecognised value like `staging` must take the strict path. Treating only the
    literal string "production" as production would leave every other deployment name
    running on development defaults.
    """
    assert Settings(ordin_env=env).is_production is production
