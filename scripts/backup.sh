#!/bin/sh
# Back up the database and the blob store together, in that order.
#
#   ./scripts/backup.sh /var/backups/ordin
#
# **Order matters and is not arbitrary.** The database is dumped first, then the blobs
# are archived. A blob store newer than its database holds bytes nothing references,
# which is harmless. A database newer than its blobs references bytes that do not
# exist — every one of those documents reports UNAVAILABLE on verify, and the case
# record says evidence is held that is not.
#
# AR-18 recorded "no backups and no restore verification" as an accepted risk. This
# stops the first half being true. The second half is only untrue once you have run
# `restore.sh` at least once — see docs/DEPLOYMENT.md.

set -eu

DEST="${1:?usage: backup.sh <directory>}"
PROJECT="${COMPOSE_PROJECT_NAME:-ordin-build}"
DB_CONTAINER="${ORDIN_DB_CONTAINER:-${PROJECT}-postgres}"
DB_USER="${POSTGRES_OWNER_USER:-ordin_owner}"
DB_NAME="${POSTGRES_DB:-ordin}"
BLOB_VOLUME="${ORDIN_BLOB_VOLUME:-ordin_blobs}"

STAMP="$(date -u +%Y-%m-%dT%H-%M-%S)"
OUT="${DEST}/${STAMP}"
mkdir -p "$OUT"

echo "  backing up to ${OUT}"

# 1. The database. --clean --if-exists so the dump can be replayed onto a live
#    database without hand-editing it first.
echo "  postgres: pg_dump ${DB_NAME}"
docker exec "$DB_CONTAINER" pg_dump \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --clean --if-exists --no-owner \
    > "${OUT}/database.sql"

# 2. The blobs. A throwaway container mounts the named volume, because the volume is
#    the thing being backed up and the worker may be mid-write on its own filesystem.
echo "  blobs: archiving volume ${BLOB_VOLUME}"
if docker volume inspect "$BLOB_VOLUME" >/dev/null 2>&1; then
    docker run --rm \
        -v "${BLOB_VOLUME}:/blobs:ro" \
        -v "${OUT}:/out" \
        alpine:3 \
        tar czf /out/blobs.tar.gz -C /blobs .
else
    echo "  blobs: volume ${BLOB_VOLUME} does not exist (dev loop keeps them on the host)"
    echo "         copy var/blobs/ yourself, or this backup restores a database whose"
    echo "         documents have no bytes behind them."
fi

# 3. What this backup is of. Without it, a restore is guesswork about which schema
#    revision the dump expects.
{
    echo "created_utc=${STAMP}"
    echo "database=${DB_NAME}"
    echo "blob_volume=${BLOB_VOLUME}"
    printf 'alembic_revision='
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tA \
        -c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo unknown
} > "${OUT}/MANIFEST"

echo "  done:"
ls -la "$OUT"
echo ""
echo "  A backup nobody has restored is a belief, not a backup."
echo "  Run ./scripts/restore.sh ${OUT} against a scratch host at least once."
