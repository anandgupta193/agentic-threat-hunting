#!/bin/sh
# Runs once, on first start of an empty volume: creates the separate database used by the test suite.
set -eu
if [ -n "${POSTGRES_TEST_DB:-}" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
SELECT 'CREATE DATABASE "${POSTGRES_TEST_DB}" OWNER "${POSTGRES_USER}"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_TEST_DB}')\gexec
SQL
fi
