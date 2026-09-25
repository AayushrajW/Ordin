"""What a fresh machine's `.env` ends up containing.

`tasks.py setup` is the command a new demo machine runs, and `render_env` is the part of
it that decides the configuration. The rest of setup creates a venv, runs pip and shells
out to npm — none of which a test should do — so this function was pulled out to be
testable, because it had no test at all and it is where a machine move goes wrong.

The two failures these are written against, both of which produce a system that *starts*
and is wrong:

  an empty ORDIN_MASTER_KEY   blobs written in plaintext, and Sentinel CRYPT-01/02/03
                              reporting red on a brand new machine for a feature that
                              is built and working
  no administrator            the login screen hardcodes a sign-in hint, so without the
                              matching account the first thing an operator sees is a
                              screen stating a password that does not work
"""
from pathlib import Path

import pytest

import tasks

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
KEY = "a-generated-master-key-value-goes-here"


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    body = tasks.render_env(EXAMPLE, KEY)
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in body.splitlines()
        if line and not line.startswith("#") and "=" in line
    }


def test_no_placeholder_survives(rendered):
    """A `change_me_*` reaching a running system is a password nobody chose."""
    leftovers = {k: v for k, v in rendered.items() if v.startswith("change_me")}
    assert not leftovers, f"unreplaced placeholders: {sorted(leftovers)}"


def test_the_master_key_is_set(rendered):
    """The one that costs three red Sentinel scenarios when it is missing."""
    assert rendered["ORDIN_MASTER_KEY"] == KEY


def test_the_master_key_is_generated_per_machine_not_shipped():
    """Two renders must differ. A key baked into `render_env` would be a committed
    secret shared by every machine that ever ran setup, which is worse than none:
    'encrypted at rest' would be true of the file format and false of the system."""
    from infra.crypto import generate_master_key

    first = tasks.render_env(EXAMPLE, generate_master_key())
    second = tasks.render_env(EXAMPLE, generate_master_key())
    assert first != second


def test_the_generated_key_actually_loads():
    """A key of the wrong length or alphabet would pass every check above and fail at
    the first upload, on the machine, in front of whoever is demonstrating."""
    from infra.crypto import EnvironmentMasterKey, generate_master_key

    body = tasks.render_env(EXAMPLE, generate_master_key())
    value = next(
        line.split("=", 1)[1]
        for line in body.splitlines()
        if line.startswith("ORDIN_MASTER_KEY=")
    )
    assert EnvironmentMasterKey.from_setting(value) is not None


def test_the_advertised_administrator_is_configured(rendered):
    """`web/app/login/page.tsx` prints these. If they are not set, the screen is lying."""
    assert rendered["ORDIN_ADMIN_EMAIL"] == "admin@gmail.com"
    assert rendered["ORDIN_ADMIN_PASSWORD"] == "admin"
    # Five characters. `admin.py` refuses it unless the environment is a development one
    # AND this flag is set, and that double condition is the control - so the flag being
    # present here is exactly as far as it should go.
    assert rendered["ORDIN_ADMIN_ALLOW_WEAK"] == "1"


def test_the_environment_stays_development(rendered):
    """ALLOW_WEAK only does anything in dev. If setup ever produced a production env
    with a weak administrator, `admin.py` would refuse and the machine would have an
    unreachable administration screen — a confusing way to find out."""
    assert rendered["ORDIN_ENV"] in ("dev", "development", "test")


def test_the_result_is_a_valid_settings_file(tmp_path, monkeypatch):
    """Parsed by the application's own loader rather than by this test's assumptions.

    A rendered file that pydantic-settings rejects would fail at import time on the new
    machine, before any command could explain itself.
    """
    from api.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(tasks.render_env(EXAMPLE, KEY), encoding="utf-8")
    settings = Settings(_env_file=str(env_file))

    assert settings.ordin_master_key.get_secret_value() == KEY
    assert settings.postgres_owner_password.get_secret_value().startswith("dev_")
    # And the DSNs build, which is the first thing anything does.
    assert settings.owner_dsn and settings.app_dsn


def test_rendering_is_idempotent():
    """Re-running setup must not corrupt an already-rendered file. Setup never
    overwrites an existing .env, but the function should not depend on that promise."""
    once = tasks.render_env(EXAMPLE, KEY)
    assert tasks.render_env(once, KEY) == once


def test_a_value_somebody_set_deliberately_is_left_alone():
    """Filling in blanks must never overwrite a decision.

    The danger case is `ORDIN_MASTER_KEY`: replacing a configured one orphans every
    blob already in the store, and ADR 0028 is blunt that there is no recovery. The
    same rule protects a real password on a machine that is not a demo.
    """
    chosen = EXAMPLE.replace("ORDIN_MASTER_KEY=", "ORDIN_MASTER_KEY=a-key-somebody-chose")
    chosen = chosen.replace("ORDIN_ADMIN_PASSWORD=", "ORDIN_ADMIN_PASSWORD=a-real-password")

    rendered = tasks.render_env(chosen, "a-DIFFERENT-generated-key")

    assert "ORDIN_MASTER_KEY=a-key-somebody-chose" in rendered
    assert "a-DIFFERENT-generated-key" not in rendered
    assert "ORDIN_ADMIN_PASSWORD=a-real-password" in rendered


def test_comments_and_blank_lines_survive():
    """The template is mostly explanation - why the ports are non-default, what the
    master key costs if lost. A renderer that stripped it would leave the next operator
    with a working file and no idea why any of it is the way it is."""
    rendered = tasks.render_env(EXAMPLE, KEY)
    assert rendered.count("#") == EXAMPLE.count("#")
    assert "Lose this and every stored document is unreadable" in rendered
