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
