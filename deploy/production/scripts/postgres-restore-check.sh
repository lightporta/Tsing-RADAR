#!/bin/sh
set -eu

[ -r "$RESTORE_CHECK_PASSWORD_FILE" ] || { echo "restore secret unavailable" >&2; exit 78; }
case "$BACKUP_FILE" in
  [A-Za-z0-9_-]*.dump) ;;
  *) echo "invalid backup filename" >&2; exit 78 ;;
esac
source="/backups/$BACKUP_FILE"
[ -f "$source" ] || { echo "backup file unavailable" >&2; exit 66; }
[ -f "${source}.sha256" ] || { echo "backup checksum unavailable" >&2; exit 66; }
(cd /backups && sha256sum -c "${BACKUP_FILE}.sha256") >/dev/null
export PGPASSWORD="$(cat "$RESTORE_CHECK_PASSWORD_FILE")"
pg_restore --host "$RESTORE_CHECK_HOST" --username restore_check --dbname restore_check --exit-on-error --no-owner "$source"
psql --host "$RESTORE_CHECK_HOST" --username restore_check --dbname restore_check --command "SELECT 1" >/dev/null
unset PGPASSWORD
echo "isolated_restore_check_passed"
