"""Is this database ours?

On 2026-09-18 this checkout and a second one at `D:\\Legal Assistant` shared a
postgres container, because both compose files declared the same `container_name` and
container names are globally unique in Docker. The other checkout applied its own
`0003_domain` migration, replacing this tree's schema.

The damage was not the collision. It was that the collision was **silent**: Alembic
reported the database at head and was telling the truth — at head of a revision
history this tree has never contained. A seed then failed on a missing table, which
looks like a code bug and is not.

So this module answers one question cheaply and loudly: does the revision the database
reports exist in *our* `alembic/versions/`? If not, we are pointed at someone else's
database and every subsequent result is meaningless.

Pure and dependency-free so it can run in `doctor` before anything connects, and be
unit-tested with no database.
"""
import re
from dataclasses import dataclass
from pathlib import Path

REVISION_PATTERN = re.compile(r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']', re.M)


def known_revisions(versions_dir: Path | str) -> set[str]:
    """Every revision id this checkout defines, read from the migration files."""
    directory = Path(versions_dir)
    found: set[str] = set()
    for path in directory.glob("*.py"):
        match = REVISION_PATTERN.search(path.read_text(encoding="utf-8"))
        if match:
            found.add(match.group(1))
    return found


@dataclass(frozen=True)
class IdentityCheck:
    ok: bool
    message: str


def check_revision(current: str | None, known: set[str]) -> IdentityCheck:
    """Compare what the database reports against what this checkout can produce.

    `current` is None for a database with no `alembic_version` row yet, which is a
    normal pre-migration state rather than a foreign database.
    """
    if not known:
        return IdentityCheck(
            False,
            "no migration files found - cannot tell whose database this is",
        )
    if current is None:
        return IdentityCheck(True, "database has no revision yet (not yet migrated)")
    if current in known:
        return IdentityCheck(True, f"revision {current} belongs to this checkout")
    return IdentityCheck(
        False,
        f"database reports revision {current!r}, which does not exist in this "
        f"checkout's alembic/versions ({', '.join(sorted(known))}). This is another "
        f"project's database. Check POSTGRES_PORT and the compose container_name "
        f"before trusting any test result.",
    )
