#!/bin/sh
set -eu

password_file=/run/secrets/redis_password
[ -r "$password_file" ] || exit 1
password=$(cat "$password_file")
[ -n "$password" ] || exit 1
REDISCLI_AUTH="$password" redis-cli --no-auth-warning ping 2>/dev/null | grep -qx PONG
unset password REDISCLI_AUTH
