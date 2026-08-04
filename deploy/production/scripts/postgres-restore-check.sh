#!/bin/sh
set -eu

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

if ! load_secret "$RESTORE_CHECK_PASSWORD_FILE"; then
  echo "restore secret unavailable or invalid" >&2
  exit 78
fi
case "$BACKUP_FILE" in
  [A-Za-z0-9_-]*.dump) ;;
  *) echo "invalid backup filename" >&2; exit 78 ;;
esac
source="/backups/$BACKUP_FILE"
[ -f "$source" ] || { echo "backup file unavailable" >&2; exit 66; }
[ -f "${source}.sha256" ] || { echo "backup checksum unavailable" >&2; exit 66; }
(cd /backups && sha256sum -c "${BACKUP_FILE}.sha256") >/dev/null
export PGPASSWORD="$SECRET_VALUE"
unset SECRET_VALUE
export PGCONNECT_TIMEOUT=10
export PGOPTIONS="-c statement_timeout=600000 -c lock_timeout=10000"
timeout -s TERM -k 10 840 pg_restore --no-password --host "$RESTORE_CHECK_HOST" --username restore_check --dbname restore_check --exit-on-error --no-owner "$source"
timeout -s TERM -k 5 60 psql --no-password --host "$RESTORE_CHECK_HOST" --username restore_check --dbname restore_check --command "SELECT 1" >/dev/null
unset PGPASSWORD PGCONNECT_TIMEOUT PGOPTIONS
echo "isolated_restore_check_passed"
