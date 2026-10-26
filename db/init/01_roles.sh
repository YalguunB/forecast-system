#!/bin/bash
# Postgres контейнер анх асахад superuser-ээр нэг удаа ажиллана.
# fc_owner — миграцийн (схемийн эзэн) хэрэглэгч; fc_app — API, worker-ийн хэрэглэгч.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE ROLE fc_owner LOGIN PASSWORD '${FC_OWNER_PASSWORD}';
  CREATE ROLE fc_app   LOGIN PASSWORD '${FC_APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  CREATE DATABASE forecast OWNER fc_owner;
  REVOKE ALL ON DATABASE forecast FROM PUBLIC;
  GRANT CONNECT ON DATABASE forecast TO fc_app;
EOSQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname forecast <<-EOSQL
  REVOKE CREATE ON SCHEMA public FROM PUBLIC;
EOSQL
