"""Bootstrap an administrator.

Every administration system has the same hole at the beginning: the screen that creates
administrators requires an administrator. This closes it, from the command line, by the
person who already has shell access to the machine and the database — which is to say,
by somebody for whom this grants no privilege they did not already have.

    python tasks.py admin --email you@example.org --password '...' --name 'Your Name'

Idempotent. Run it again to reset a password or restore the account after
`python tasks.py demo`, which truncates `app_user` and would otherwise take the
administrator with it.

**Administration is an office, not a personal attribute.** The account is placed on a
post whose `is_administrative` is true (migration 0009). That keeps invariant 3 intact:
the policy evaluator decides administrative access from versioned policy data reading
that column, rather than from a hand-rolled `if user.is_admin` — which CLAUDE.md forbids
by name.

**An administrator is not a super-user.** The post carries no case designation and no
grant, so this account sees **no case content at all** — the case list is empty and
stays empty. It can place people; it cannot read their evidence. Seniority conferring
access to a case you are not assigned to is precisely the rule the authorization model
exists to refuse.
"""
import argparse
import asyncio
import os
import pathlib
import sys
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.config import Settings
from infra.accounts import normalise_email
from infra.passwords import MIN_LENGTH, hash_password

ADMIN_POST_TITLE = "System Administrator"


async def ensure_admin(
    *, email: str, password: str, display_name: str, settings: Settings | None = None
) -> str:
    """Create or update the administrator. Returns the account id."""
    config = settings or Settings()
    address = normalise_email(email)
    if "@" not in address:
        raise SystemExit("  an email address is required")

    weak = len(password) < MIN_LENGTH
    hashed = hash_password(password, enforce_quality=not weak)

    engine = create_async_engine(config.app_dsn)
    try:
        async with engine.begin() as conn:
            org = (
                await conn.execute(sa.text("SELECT id FROM organization ORDER BY name LIMIT 1"))
            ).scalar_one_or_none()
            jur = (
                await conn.execute(sa.text("SELECT id FROM jurisdiction ORDER BY name LIMIT 1"))
            ).scalar_one_or_none()
            if org is None or jur is None:
                raise SystemExit(
                    "  no organization or jurisdiction exists yet.\n"
                    "  run `python tasks.py seed` (or `demo`) first, then this."
                )

            post_id = (
                await conn.execute(
                    sa.text("SELECT id FROM post WHERE is_administrative LIMIT 1")
                )
            ).scalar_one_or_none()
            if post_id is None:
                post_id = uuid.uuid4()
                await conn.execute(
                    sa.text(
                        "INSERT INTO post (id, organization_id, jurisdiction_id, title, "
                        "is_administrative) VALUES (:i, :o, :j, :t, true)"
                    ),
                    {"i": post_id, "o": org, "j": jur, "t": ADMIN_POST_TITLE},
                )

            existing = (
                await conn.execute(
                    sa.text("SELECT id FROM app_user WHERE lower(email) = :e"), {"e": address}
                )
            ).scalar_one_or_none()

            if existing:
                await conn.execute(
                    sa.text(
                        "UPDATE app_user SET password_hash = :h, display_name = :n, "
                        "post_id = :p, is_active = true, failed_attempts = 0, "
                        "locked_until = NULL, clearance_level = 3 WHERE id = :i"
                    ),
                    {"h": hashed, "n": display_name, "p": post_id, "i": existing},
                )
                user_id = str(existing)
                action = "updated"
            else:
                user_id = str(
                    (
                        await conn.execute(
                            sa.text(
                                "INSERT INTO app_user (id, post_id, display_name, "
                                "clearance_level, is_active, email, password_hash) "
                                "VALUES (gen_random_uuid(), :p, :n, 3, true, :e, :h) "
                                "RETURNING id"
                            ),
                            {"p": post_id, "n": display_name, "e": address, "h": hashed},
                        )
                    ).scalar_one()
                )
                action = "created"
    finally:
        await engine.dispose()

    print(f"\n  administrator {action}: {address}")
    print(f"  post          : {ADMIN_POST_TITLE} (is_administrative)")
    print("  sees          : no case content. An administrator places people;")
    print("                  it is not a designation, so there is nothing to read.")
    if weak:
        print("")
        print(f"  WARNING  that password is {len(password)} characters. The signup form")
        print(f"           refuses anything under {MIN_LENGTH}, and this is the account that")
        print("           can place every other account. Fine on a specimen laptop;")
        print("           change it before anything is deployed:")
        print("             python tasks.py admin --email <same> --password <longer>")
    return user_id


def configured(name: str, default: str | None = None) -> str | None:
    """A value from the environment, falling back to `.env`.

    `.env` is read by pydantic-settings, which does not export into `os.environ` — so a
    value sitting in that file is invisible to `os.environ.get`. That is exactly how the
    first version of this silently failed to restore the administrator after
    `tasks.py demo`, reporting nothing at all.
    """
    if os.environ.get(name):
        return os.environ[name]
    env_file = pathlib.Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and value.strip():
                return value.strip()
    return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or update an administrator.")
    parser.add_argument("--email", default=configured("ORDIN_ADMIN_EMAIL"))
    parser.add_argument("--password", default=configured("ORDIN_ADMIN_PASSWORD"))
    parser.add_argument("--name", default=configured("ORDIN_ADMIN_NAME", "Administrator"))
    parser.add_argument(
        "--if-configured",
        action="store_true",
        help="Exit quietly when no administrator is configured. Used by `tasks.py demo`.",
    )
    args = parser.parse_args(argv)

    if not args.email or not args.password:
        if args.if_configured:
            return 0
        print("  usage: python tasks.py admin --email <address> --password <password>")
        print("  or set ORDIN_ADMIN_EMAIL and ORDIN_ADMIN_PASSWORD in .env, which also")
        print("  lets `python tasks.py demo` restore the account after it reseeds.")
        return 2

    asyncio.run(
        ensure_admin(email=args.email, password=args.password, display_name=args.name)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
