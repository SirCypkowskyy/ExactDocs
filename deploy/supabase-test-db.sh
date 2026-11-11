#!/usr/bin/env bash
# Start Supabase's PostgreSQL image with SSL on, for the Supabase tests (#244), and print the URL
# of its `postgres` role with sslmode=require, ready for EXACTDOCS_TEST_SUPABASE_URL:
#
#   export EXACTDOCS_TEST_SUPABASE_URL=$(deploy/supabase-test-db.sh exactdocs-supabase)
#   uv run behave packages/exactdocs/features/supabase.feature
#   docker rm -f exactdocs-supabase
#
# The container gets a throwaway self-signed certificate and password, and a free port on
# 127.0.0.1. Supabase's hosted `postgres` role is no superuser either; this image's is the same.
set -euo pipefail

name=${1:?usage: supabase-test-db.sh <container name>}
# supabase/postgres 17.6.1.044 (amd64 and arm64), the PostgreSQL that Supabase projects run.
image=supabase/postgres:17.6.1.044@sha256:74d0c29b7cac2edb075f8995415144700010e36a5a87d3caa3173e7905094fbd
password=$(openssl rand -hex 16)

docker run -d --name "$name" -e POSTGRES_PASSWORD="$password" -p 127.0.0.1::5432 \
  --entrypoint bash "$image" -c '
    openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=localhost \
      -keyout /tmp/server.key -out /tmp/server.crt 2>/dev/null
    chown postgres /tmp/server.key /tmp/server.crt && chmod 600 /tmp/server.key
    exec docker-entrypoint.sh postgres -D /etc/postgresql \
      -c ssl=on -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key' >/dev/null

port=$(docker port "$name" 5432/tcp | head -n1 | cut -d: -f2)
url="postgresql://postgres:${password}@127.0.0.1:${port}/postgres?sslmode=require"

# The image runs its own migrations on a temporary server first: wait for the real one, which
# is the one that has SSL on (the temporary one listens on the socket only).
for _ in $(seq 120); do
  if docker exec "$name" pg_isready -q -h 127.0.0.1 -U postgres 2>/dev/null \
    && docker logs "$name" 2>&1 | grep -q "PostgreSQL init process complete"; then
    echo "$url"
    exit 0
  fi
  sleep 1
done
docker logs "$name" >&2
echo "supabase/postgres did not get ready" >&2
exit 1
