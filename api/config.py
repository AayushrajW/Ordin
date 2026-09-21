"""Configuration.

Passwords are `SecretStr`, not `str`, and that is load-bearing rather than
decorative: a plain string finds its way into a log line, a traceback, a Pydantic
validation error or a `repr()` of the settings object eventually, and security
invariant 12 forbids exactly that. `SecretStr` renders as `**********` everywhere
except an explicit `.get_secret_value()`, so leaking one becomes a deliberate act.
"""
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # So that assigning a plain string to a SecretStr field in a test coerces
        # rather than silently replacing the type.
        validate_assignment=True,
    )

    # --- postgres ---
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "ordin"

    # Owns the schema, runs Alembic. Never used by the running application.
    postgres_owner_user: str = "ordin_owner"
    postgres_owner_password: SecretStr = SecretStr("")

    # The restricted role the api and worker actually connect as (docs/adr/0001).
    ordin_app_user: str = "ordin_app"
    ordin_app_password: SecretStr = SecretStr("")

    # --- api ---
    ordin_env: str = "dev"
    ordin_log_level: str = "INFO"
    ordin_api_host: str = "127.0.0.1"
    ordin_api_port: int = 8000

    # Signs the session token (ADR 0002). SecretStr so it cannot reach a log or a
    # repr; a compose or settings default here would be invisible to the guard hook
    # and would ship in a public repository (threat SESS-01).
    ordin_session_secret: SecretStr = SecretStr("")

    # Where `LocalBlobStore` keeps content-addressed bytes. A relative path is
    # resolved against the project root by whoever constructs the store, so the api
    # and the worker agree on one location without either of them owning it.
    ordin_blob_root: str = "var/blobs"

    # Wraps the per-blob data keys (infra/crypto.py). Base64, 32 bytes decoded.
    # Empty means blobs are written in plaintext, which is what a development
    # checkout does; `refuse_unsafe_production` makes a deployment configure one.
    #
    # SecretStr for the same reason as the session secret: a plain string reaches a
    # log, a traceback or a repr eventually, and this one decrypts every document.
    ordin_master_key: SecretStr = SecretStr("")

    # --- derived ---
    def _dsn(self, user: str, password: SecretStr) -> str:
        return (
            f"postgresql+asyncpg://{quote(user)}:{quote(password.get_secret_value())}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote(self.postgres_db)}"
        )

    @property
    def app_dsn(self) -> str:
        """What the application connects with. Owns nothing."""
        return self._dsn(self.ordin_app_user, self.ordin_app_password)

    @property
    def owner_dsn(self) -> str:
        """What Alembic connects with. Owns everything."""
        return self._dsn(self.postgres_owner_user, self.postgres_owner_password)

    @property
    def redacted_dsn(self) -> str:
        """Safe to log. The only DSN form that should ever reach an output stream."""
        return (
            f"postgresql+asyncpg://{self.ordin_app_user}:***"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    version: str = Field(default="0.1.0", exclude=True)

    @property
    def is_production(self) -> bool:
        return self.ordin_env.lower() not in ("dev", "development", "test")

    def refuse_unsafe_production(self) -> None:
        """Stop the process rather than run a deployment on development values.

        Every one of these is a configuration mistake that produces a system which
        **starts, serves traffic and looks correct**. That is what makes them worth a
        hard failure: a warning in a log nobody reads is how a placeholder session
        secret reaches a pilot.

        `ORDIN_SESSION_SECRET` is the sharpest. It signs the session token from which
        every access decision is resolved, so a known value is not a weak password — it
        is the ability to mint a session as any account, including an administrative
        one, without touching the database (threat SESS-01).

        Called from `create_app`, so there is no code path that constructs a production
        application without passing this.
        """
        if not self.is_production:
            return

        placeholders = {"", "change_me_session_secret", "changeme", "secret", "dev"}
        problems: list[str] = []

        def reveal(value) -> str:
            """The secret's text, whether it is a SecretStr or already a plain string.

            `model_copy(update=...)` bypasses validation, so a Settings built that way
            can hold a bare str where a SecretStr is declared. A security guard that
            raises AttributeError on the wrong type reports a traceback instead of the
            real problem, which is the least useful moment for that to happen.
            """
            return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)

        secret = reveal(self.ordin_session_secret)
        if secret.strip().lower() in placeholders:
            problems.append(
                "ORDIN_SESSION_SECRET is unset or still the template value. It signs "
                "every session token, so a known value mints a session as any account."
            )
        elif len(secret) < 32:
            problems.append(
                "ORDIN_SESSION_SECRET is shorter than 32 characters. Generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
            )

        if not reveal(self.ordin_master_key).strip():
            problems.append(
                "ORDIN_MASTER_KEY is unset, so document bytes are written to disk in "
                "plaintext. Generate one with `python tasks.py newkey`."
            )

        for name, value in (
            ("ORDIN_APP_PASSWORD", self.ordin_app_password),
            ("POSTGRES_OWNER_PASSWORD", self.postgres_owner_password),
        ):
            text = reveal(value)
            if not text or text.startswith("change_me"):
                problems.append(f"{name} is unset or still the template value.")

        if problems:
            raise RuntimeError(
                "refusing to start with ORDIN_ENV="
                f"{self.ordin_env!r} and development configuration:\n  - "
                + "\n  - ".join(problems)
                + "\n\nSet these in the environment. See docs/DEPLOYMENT.md."
            )
