#!/bin/sh
# Creates the restricted runtime role. Runs once, on first initialisation of an
# empty postgres volume, as POSTGRES_USER against POSTGRES_DB.
#
# This is a shell script rather than a .sql file for one reason: the password
# comes from the environment. A committed .sql file would put a working
# credential in a public submission repository (threat EXT-03).
#
# See docs/adr/0001-two-postgres-roles.md. The short version:
#
#   A table owner is NOT subject to REVOKE on its own table. If the role that
#   runs migrations is also the role the application connects as, then slice 2's
#   "REVOKE UPDATE, DELETE ON audit_events FROM the app role" is a no-op and its
#   acceptance test passes while proving nothing. Security invariant 10 would be
#   void and green at the same time.
#
#   So: ordin_owner owns every object and runs Alembic. ordin_app connects, reads
#   and writes rows, and owns nothing.

set -eu

: "${ORDIN_APP_PASSWORD:?ORDIN_APP_PASSWORD must be set}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     --set app_password="$ORDIN_APP_PASSWORD" \
     --set db_name="$POSTGRES_DB" <<'EOSQL'

CREATE ROLE ordin_app WITH LOGIN PASSWORD :'app_password';

-- May reach the database and see the schema. Nothing more by default.
GRANT CONNECT ON DATABASE :"db_name" TO ordin_app;
GRANT USAGE   ON SCHEMA  public      TO ordin_app;

-- ordin_app must never create objects: an object it created, it would own, and
-- an owner cannot be restrained by REVOKE. Postgres 15+ already removes CREATE
-- from PUBLIC on the public schema; this is explicit so it survives a schema
-- being recreated by hand.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM ordin_app;

-- Tables that ordin_owner creates later grant row-level DML to ordin_app
-- automatically, and never DDL. Slice 2 narrows this further for audit tables by
-- revoking UPDATE and DELETE on them specifically.
-- No FOR ROLE clause: it defaults to the current user, which is ordin_owner,
-- which is exactly the role whose future tables we are talking about.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ordin_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ordin_app;

EOSQL

echo "01-roles.sh: created ordin_app (login, no CREATE, no ownership)"
