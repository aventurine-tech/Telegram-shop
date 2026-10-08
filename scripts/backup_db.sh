#!/usr/bin/env bash
# Back up the shop database (customers, orders, catalog, product pictures — all of it lives in PostgreSQL).
#
#   ./scripts/backup_db.sh                 # writes backups/shop-YYYYmmdd-HHMMSS.dump, keeps the newest 14
#   BACKUP_KEEP=30 ./scripts/backup_db.sh  # keep 30 instead
#   BACKUP_DIR=/mnt/usb/shop ./scripts/backup_db.sh
#
# Runs against the compose `db` service. To use a local PostgreSQL client instead, set DB_EXEC="" and the usual
# PGHOST/PGPORT variables. Reads POSTGRES_USER / POSTGRES_DB / POSTGRES_PASSWORD from .env (never prints them).
# Cron example (every night at 03:30):  30 3 * * *  cd /path/to/Telegram-shop && ./scripts/backup_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

env_value() {  # env_value NAME — the value from .env, or the process environment
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

BACKUP_DIR=${BACKUP_DIR:-backups}
BACKUP_KEEP=${BACKUP_KEEP:-14}
DB_EXEC=${DB_EXEC-docker compose exec -T db}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M%S)
target="$BACKUP_DIR/shop-$stamp.dump"
partial="$target.partial"
trap 'rm -f "$partial"' EXIT

# Custom format: compressed, and pg_restore can restore it whole or in part.
PGPASSWORD="$DB_PASSWORD" $DB_EXEC env PGPASSWORD="$DB_PASSWORD" pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$partial"

# A dump that pg_restore cannot even list is not a backup.
if [ -n "$DB_EXEC" ]; then
    $DB_EXEC pg_restore --list < "$partial" > /dev/null
else
    pg_restore --list "$partial" > /dev/null
fi

chmod 600 "$partial"
mv "$partial" "$target"
trap - EXIT

# Keep only the newest BACKUP_KEEP dumps.
ls -1t "$BACKUP_DIR"/shop-*.dump 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | xargs -r rm -f --

echo "Backup written: $target ($(du -h "$target" | cut -f1))"
echo "Copy it off this machine too — a backup on the same disk does not survive the disk."
