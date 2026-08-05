#!/bin/sh
set -eu

lock_file=${JOB_LOCK_FILE_IN_CONTAINER:-/run/tsing-radar/job.lock}
timeout=${JOB_LOCK_TIMEOUT_SECONDS:-5}

case "$timeout" in
  ''|*[!0-9]*) echo "invalid job lock timeout" >&2; exit 78 ;;
esac
if [ "$timeout" -lt 1 ] || [ "$timeout" -gt 300 ]; then
  echo "invalid job lock timeout" >&2
  exit 78
fi
if [ ! -f "$lock_file" ] || [ -L "$lock_file" ]; then
  echo "job lock file is missing or invalid" >&2
  exit 78
fi
if [ "$#" -eq 0 ]; then
  echo "job command is required" >&2
  exit 78
fi
if ! command -v flock >/dev/null 2>&1; then
  echo "flock is unavailable" >&2
  exit 78
fi

# Use the file-descriptor form supported by both util-linux and BusyBox flock.
# The descriptor is inherited by the exec'd child, so normal exit, failure,
# SIGTERM or container death releases the kernel lock.
exec 9<>"$lock_file"
attempts=$((timeout * 10))
while ! flock -n 9; do
  if [ "$attempts" -le 0 ]; then
    echo "job lock busy" >&2
    exit 75
  fi
  attempts=$((attempts - 1))
  sleep 0.1
done
exec "$@"
