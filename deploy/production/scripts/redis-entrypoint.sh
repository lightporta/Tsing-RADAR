#!/bin/sh
set -eu

password_file=/run/secrets/redis_password
if [ ! -r "$password_file" ]; then
  echo "redis secret file unavailable" >&2
  exit 78
fi

umask 077
password=$(cat "$password_file")
if [ -z "$password" ]; then
  echo "redis secret file empty" >&2
  exit 78
fi
case "$password" in
  *[!A-Za-z0-9_+=./-]*) echo "redis secret format invalid" >&2; exit 78 ;;
esac
acl_file=/tmp/users.acl
printf 'user default on >%s ~* +@all\n' "$password" > "$acl_file"
unset password
exec redis-server --appendonly yes --aclfile "$acl_file"
