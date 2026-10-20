#!/bin/bash
# Creates one database role per access pattern. Runs once, when the Postgres data volume is empty
# (the official postgres image runs every file in /docker-entrypoint-initdb.d in name order).
#
#   spendcheck_app  read/write transactions  - gateway and Modules 1-3
#   chat_agent_ro   read-only, one user only - Module 4 (enforced by row-level security)
#   report_reader   owns the reports schema  - Module 5
#
# Passwords come from environment variables: .env for docker compose, a Secret on Kubernetes.
# No `set -e` here: the entrypoint may source this file, and it already stops on errors; psql's
# ON_ERROR_STOP makes any failed statement fail the init.

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_pw="$APP_DB_PASSWORD" \
  -v chat_pw="$CHAT_AGENT_DB_PASSWORD" \
  -v reports_pw="$REPORT_READER_DB_PASSWORD" <<'EOSQL'
CREATE ROLE spendcheck_app LOGIN PASSWORD :'app_pw';
CREATE ROLE chat_agent_ro  LOGIN PASSWORD :'chat_pw';
CREATE ROLE report_reader  LOGIN PASSWORD :'reports_pw';
EOSQL
