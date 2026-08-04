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
temporary=$(mktemp "/backups/${DATABASE_NAME}-${stamp}-XXXXXX.dump.partial")
target=${temporary%.partial}
checksum_temporary=""
cleanup() {
  [ -z "$temporary" ] || rm -f -- "$temporary"
  [ -z "$checksum_temporary" ] || rm -f -- "$checksum_temporary"
}
trap cleanup EXIT INT TERM
checksum_temporary=$(mktemp "/backups/.${DATABASE_NAME}-${stamp}-XXXXXX.sha256.partial")
[ ! -e "$target" ] || { echo "backup target collision" >&2; exit 73; }
[ ! -e "${target}.sha256" ] || { echo "backup checksum collision" >&2; exit 73; }
pg_dump --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" --format custom --file "$temporary"
ln "$temporary" "$target"
rm -f -- "$temporary"
(cd /backups && sha256sum "$(basename "$target")") > "$checksum_temporary"
ln "$checksum_temporary" "${target}.sha256"
rm -f -- "$checksum_temporary"
[ -f "$target" ] || { echo "backup file unavailable after creation" >&2; exit 66; }
[ -f "${target}.sha256" ] || { echo "backup checksum unavailable after creation" >&2; exit 66; }
(cd /backups && sha256sum -c "$(basename "${target}.sha256")") >/dev/null
unset PGPASSWORD
printf 'backup_created=%s\n' "$(basename "$target")"
