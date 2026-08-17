#!/bin/sh
set -eu

access_file=/run/secrets/milvus_minio_access_key
secret_file=/run/secrets/milvus_minio_secret_key
if [ ! -r "$access_file" ] || [ ! -r "$secret_file" ]; then
  echo "Milvus storage secret file unavailable" >&2
  exit 78
fi

export MINIO_ACCESS_KEY_ID="$(cat "$access_file")"
export MINIO_SECRET_ACCESS_KEY="$(cat "$secret_file")"
if [ -z "$MINIO_ACCESS_KEY_ID" ] || [ -z "$MINIO_SECRET_ACCESS_KEY" ]; then
  echo "Milvus storage secret file empty" >&2
  exit 78
fi
exec milvus run standalone
