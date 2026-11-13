#!/bin/sh
# Generates /etc/pgbouncer/userlist.txt from environment variables at container start.
# Credentials are never committed to source control.
set -e

USERLIST_PATH="/etc/pgbouncer/userlist.txt"

if [ -z "${POSTGRES_USER}" ] || [ -z "${POSTGRES_PASSWORD}" ]; then
  echo "[ERROR] POSTGRES_USER and POSTGRES_PASSWORD must be set" >&2
  exit 1
fi

# Write scram-sha-256 compatible userlist (plain password — PgBouncer hashes on connect)
printf '"%s" "%s"\n' "${POSTGRES_USER}" "${POSTGRES_PASSWORD}" > "${USERLIST_PATH}"
chmod 600 "${USERLIST_PATH}"

echo "[pgbouncer] userlist.txt generated for user: ${POSTGRES_USER}"
exec pgbouncer /etc/pgbouncer/pgbouncer.ini
