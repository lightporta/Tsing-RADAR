#!/bin/sh
set -eu

for name in DATABASE_HOST DATABASE_NAME DATABASE_USER DATABASE_PASSWORD_FILE; do
  eval "value=\${$name:-}"
  [ -n "$value" ] || { echo "missing $name" >&2; exit 78; }
done
case "$DATABASE_NAME:$DATABASE_USER" in
  *[!a-z0-9_:]*) echo "invalid database identity" >&2; exit 78 ;;
esac
[ -r "$DATABASE_PASSWORD_FILE" ] || { echo "database secret unavailable" >&2; exit 78; }
export PGPASSWORD="$(cat "$DATABASE_PASSWORD_FILE")"
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="/backups/${DATABASE_NAME}-${stamp}.dump"
temporary="${target}.partial"
trap 'rm -f "$temporary"' EXIT INT TERM
pg_dump --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" --format custom --file "$temporary"
mv "$temporary" "$target"
sha256sum "$target" > "${target}.sha256"
unset PGPASSWORD
printf 'backup_created=%s\n' "$(basename "$target")"
