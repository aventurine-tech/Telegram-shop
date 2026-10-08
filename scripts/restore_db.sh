#!/usr/bin/env bash
# Restore the shop database from a dump made by backup_db.sh. REPLACES everything currently in the database.
#
#   ./scripts/restore_db.sh backups/shop-20261008-033000.dump
#
# Stops the bot first so nothing writes during the restore, then starts it again (migrations run on start).
# Use DB_EXEC="" with PGHOST/PGPORT for a local PostgreSQL client (the bot is then not stopped/started for you).
# Practice this on a spare machine BEFORE you need it: a backup that was never restored is only a hope.
set -euo pipefail
cd "$(dirname "$0")/.."

dump=${1:-}
[ -f "$dump" ] || { echo "usage: $0 <backup.dump>" >&2; exit 1; }

env_value() {
    local name="$1" line
    if [ -n "${!name:-}" ]; then printf '%s' "${!name}"; return; fi
    line=$(grep -E "^${name}=" .env 2>/dev/null | tail -n1 || true)
    line=${line#*=}; line=${line%\"}; line=${line#\"}
    printf '%s' "$line"
}

DB_USER=$(env_value POSTGRES_USER)
DB_NAME=$(env_value POSTGRES_DB)
DB_PASSWORD=$(env_value POSTGRES_PASSWORD)
[ -n "$DB_USER" ] && [ -n "$DB_NAME" ] || { echo "POSTGRES_USER / POSTGRES_DB not found in .env" >&2; exit 1; }
DB_EXEC=${DB_EXEC-docker compose exec -T db}

if [ "${ASSUME_YES:-}" != "1" ]; then
    printf 'This REPLACES the database "%s" with %s. Type the database name to continue: ' "$DB_NAME" "$dump"
    read -r answer
    [ "$answer" = "$DB_NAME" ] || { echo "Aborted."; exit 1; }
fi

[ -z "$DB_EXEC" ] || docker compose stop bot

if [ -n "$DB_EXEC" ]; then
    $DB_EXEC env PGPASSWORD="$DB_PASSWORD" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner < "$dump"
else
    PGPASSWORD="$DB_PASSWORD" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner "$dump"
fi

[ -z "$DB_EXEC" ] || docker compose start bot
echo "Restored from $dump."
