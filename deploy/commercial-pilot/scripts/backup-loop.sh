#!/bin/sh
set -eu

: "${KJDS_DEPLOYMENT_NAME:?KJDS_DEPLOYMENT_NAME must be set}"
: "${KJDS_DATABASE_NAME:?KJDS_DATABASE_NAME must be set}"
: "${KJDS_POSTGRES_USER:?KJDS_POSTGRES_USER must be set}"
: "${KJDS_CUSTOMER_SCOPE_JSON:?KJDS_CUSTOMER_SCOPE_JSON must be set}"

case "$KJDS_DEPLOYMENT_NAME" in
  *[!A-Za-z0-9_.-]*) echo "invalid deployment name" >&2; exit 2 ;;
esac
case "$KJDS_DATABASE_NAME:$KJDS_POSTGRES_USER" in
  *[!A-Za-z0-9_:]*) echo "invalid database name or user" >&2; exit 2 ;;
esac

interval="${KJDS_BACKUP_INTERVAL_SECONDS:-86400}"
retention_days="${KJDS_BACKUP_RETENTION_DAYS:-14}"
run_once="${KJDS_BACKUP_RUN_ONCE:-false}"
case "$interval:$retention_days" in
  *[!0-9:]*) echo "backup interval and retention must be numeric" >&2; exit 2 ;;
esac
if [ "$interval" -lt 300 ] || [ "$retention_days" -lt 1 ]; then
  echo "backup interval must be at least 300 seconds and retention at least one day" >&2
  exit 2
fi
if [ ! -s /run/secrets/kjds_postgres_password ]; then
  echo "postgres password secret is missing or empty" >&2
  exit 2
fi

umask 077
mkdir -p /backups
pgpass_file="$(mktemp)"
trap 'rm -f "$pgpass_file"' EXIT INT TERM
printf 'postgres:5432:%s:%s:%s\n' \
  "$KJDS_DATABASE_NAME" \
  "$KJDS_POSTGRES_USER" \
  "$(cat /run/secrets/kjds_postgres_password)" > "$pgpass_file"
export PGPASSFILE="$pgpass_file"

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  base="kjds-$KJDS_DEPLOYMENT_NAME-$KJDS_DATABASE_NAME-$stamp"
  archive="/backups/$base.dump"
  temporary="$archive.incomplete"
  manifest="$archive.manifest.json"
  manifest_temporary="$manifest.incomplete"

  rm -f "$temporary"
  rm -f "$manifest_temporary"
  pg_dump \
    --host=postgres \
    --username="$KJDS_POSTGRES_USER" \
    --dbname="$KJDS_DATABASE_NAME" \
    --format=custom \
    --no-owner \
    --no-acl \
    --file="$temporary"

  alembic_head="$(psql \
    --host=postgres \
    --username="$KJDS_POSTGRES_USER" \
    --dbname="$KJDS_DATABASE_NAME" \
    --tuples-only \
    --no-align \
    --command='SELECT version_num FROM alembic_version LIMIT 1;')"
  case "$alembic_head" in
    ''|*[!A-Za-z0-9_.-]*) rm -f "$temporary"; echo "invalid Alembic head" >&2; return 1 ;;
  esac

  mv "$temporary" "$archive"
  archive_hash="$(sha256sum "$archive" | awk '{print $1}')"
  scope_hash="$(printf '%s' "$KJDS_CUSTOMER_SCOPE_JSON" | sha256sum | awk '{print $1}')"
  archive_bytes="$(wc -c < "$archive" | tr -d ' ')"
  created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"manifest_version":1,"created_at":"%s","deployment_name":"%s","customer_scope_sha256":"%s","database":"%s","archive":"%s","sha256":"%s","bytes":%s,"alembic_head":"%s","format":"pg_dump-custom"}\n' \
    "$created_at" \
    "$KJDS_DEPLOYMENT_NAME" \
    "$scope_hash" \
    "$KJDS_DATABASE_NAME" \
    "$(basename "$archive")" \
    "$archive_hash" \
    "$archive_bytes" \
    "$alembic_head" > "$manifest_temporary"
  mv "$manifest_temporary" "$manifest"

  find /backups -type f -name 'kjds-*.dump' -mtime "+$retention_days" -delete
  find /backups -type f -name 'kjds-*.dump.manifest.json' -mtime "+$retention_days" -delete
  printf 'backup=%s sha256=%s\n' "$archive" "$archive_hash"
}

while true; do
  run_backup
  if [ "$run_once" = "true" ]; then
    exit 0
  fi
  sleep "$interval"
done
