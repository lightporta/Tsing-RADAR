#!/bin/sh
set -eu

for name in DATABASE_HOST DATABASE_NAME DATABASE_USER DATABASE_PASSWORD_FILE; do
  eval "value=\${$name:-}"
  [ -n "$value" ] || { echo "missing $name" >&2; exit 78; }
done
case "$DATABASE_NAME:$DATABASE_USER" in
  *[!a-z0-9_:]*) echo "invalid database identity" >&2; exit 78 ;;
esac

load_secret() {
  secret_path=$1
  [ -f "$secret_path" ] && [ ! -L "$secret_path" ] || return 1
  secret_size=$(wc -c < "$secret_path") || return 1
  set -- $secret_size
  [ "$#" -eq 1 ] || return 1
  secret_size=$1
  case "$secret_size" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$secret_size" -ge 1 ] && [ "$secret_size" -le 4096 ] || return 1
  secret_hex=$(od -An -v -t x1 "$secret_path") || return 1
  for octet in $secret_hex; do
    [ "$octet" != "00" ] || return 1
  done
  unset secret_hex
  if ! secret_value=$(cat "$secret_path"); then
    return 1
  fi
  [ -n "$secret_value" ] || return 1
  SECRET_VALUE=$secret_value
  unset secret_value
}

if ! load_secret "$DATABASE_PASSWORD_FILE"; then
  echo "database secret unavailable or invalid" >&2
  exit 78
fi
export PGPASSWORD="$SECRET_VALUE"
unset SECRET_VALUE
export PGCONNECT_TIMEOUT=10
export PGOPTIONS="-c statement_timeout=600000 -c lock_timeout=10000"
umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
temporary_prefix="/backups/.${DATABASE_NAME}-${stamp}-dump-"
temporary=$(mktemp "${temporary_prefix}XXXXXX")
token=${temporary#"$temporary_prefix"}
case "$token" in
  [A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]) ;;
  *) echo "invalid backup temporary name" >&2; exit 66 ;;
esac
target="/backups/${DATABASE_NAME}-${stamp}-${token}.dump"
checksum_temporary=""
cleanup() {
  [ -z "$temporary" ] || rm -f -- "$temporary"
  [ -z "$checksum_temporary" ] || rm -f -- "$checksum_temporary"
}
trap cleanup EXIT INT TERM
checksum_prefix="/backups/.${DATABASE_NAME}-${stamp}-sha256-"
checksum_temporary=$(mktemp "${checksum_prefix}XXXXXX")
checksum_token=${checksum_temporary#"$checksum_prefix"}
case "$checksum_token" in
  [A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]) ;;
  *) echo "invalid checksum temporary name" >&2; exit 66 ;;
esac
[ ! -e "$target" ] || { echo "backup target collision" >&2; exit 73; }
[ ! -e "${target}.sha256" ] || { echo "backup checksum collision" >&2; exit 73; }
timeout -s TERM -k 10 840 pg_dump --no-password --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" --format custom --file "$temporary"
ln "$temporary" "$target" || { echo "backup target collision" >&2; exit 73; }
rm -f -- "$temporary"
(cd /backups && sha256sum "$(basename "$target")") > "$checksum_temporary"
ln "$checksum_temporary" "${target}.sha256" || { echo "backup checksum collision" >&2; exit 73; }
rm -f -- "$checksum_temporary"
[ -f "$target" ] || { echo "backup file unavailable after creation" >&2; exit 66; }
[ -f "${target}.sha256" ] || { echo "backup checksum unavailable after creation" >&2; exit 66; }
(cd /backups && sha256sum -c "$(basename "${target}.sha256")") >/dev/null
unset PGPASSWORD PGCONNECT_TIMEOUT PGOPTIONS
printf 'backup_created=%s\n' "$(basename "$target")"
