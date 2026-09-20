#!/bin/sh
# Restore a backup produced by backup.sh.
#
#   ./scripts/restore.sh /var/backups/ordin/2026-09-20T14-00-00
#
# **This overwrites the running system.** It refuses unless ORDIN_RESTORE_CONFIRM=yes
# is set, because the one command in this repository that destroys data without asking
# is `tasks.py fresh`, and that is a development command with a name that says so.
#
# Restores blobs first, then the database — the reverse of the backup order, and for the
# same reason. A restore interrupted after the blobs is a system whose store holds bytes
# nothing references. Interrupted after the database, it is a system that believes it
# holds evidence it cannot produce.

set -eu

SRC="${1:?usage: restore.sh <backup directory>}"
PROJECT="${COMPOSE_PROJECT_NAME:-ordin-build}"
DB_CONTAINER="${ORDIN_DB_CONTAINER:-${PROJECT}-postgres}"
DB_USER="${POSTGRES_OWNER_USER:-ordin_owner}"
DB_NAME="${POSTGRES_DB:-ordin}"
BLOB_VOLUME="${ORDIN_BLOB_VOLUME:-ordin_blobs}"

[ -f "${SRC}/database.sql" ] || { echo "  no database.sql in ${SRC}"; exit 1; }

echo "  restoring from ${SRC}"
[ -f "${SRC}/MANIFEST" ] && cat "${SRC}/MANIFEST"

if [ "${ORDIN_RESTORE_CONFIRM:-no}" != "yes" ]; then
    echo ""
    echo "  This replaces the contents of database '${DB_NAME}' and volume"
    echo "  '${BLOB_VOLUME}'. Nothing currently in them is recoverable afterwards."
    echo ""
    echo "  Re-run with:  ORDIN_RESTORE_CONFIRM=yes $0 ${SRC}"
    exit 2
fi

# 1. Blobs first. See the header.
if [ -f "${SRC}/blobs.tar.gz" ]; then
    echo "  blobs: restoring into ${BLOB_VOLUME}"
    docker volume create "$BLOB_VOLUME" >/dev/null
    docker run --rm \
        -v "${BLOB_VOLUME}:/blobs" \
        -v "${SRC}:/in:ro" \
        alpine:3 \
        sh -c 'rm -rf /blobs/* && tar xzf /in/blobs.tar.gz -C /blobs'
else
    echo "  blobs: no blobs.tar.gz in this backup — documents will verify UNAVAILABLE"
fi

# 2. The database. The dump carries --clean --if-exists, so it drops what it replaces.
echo "  postgres: replaying database.sql"
docker exec -i "$DB_CONTAINER" psql \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    -v ON_ERROR_STOP=1 \
    < "${SRC}/database.sql"

echo ""
echo "  restored. Now verify rather than assume:"
echo "    curl -sf http://127.0.0.1:\${ORDIN_API_PORT:-8001}/health"
echo "    python tasks.py sentinel"
echo ""
echo "  Open a document and check its integrity panel reports VERIFIED. A blob store"
echo "  and a database restored out of step report MISMATCH or UNAVAILABLE, and that"
echo "  is the check that tells you which."
