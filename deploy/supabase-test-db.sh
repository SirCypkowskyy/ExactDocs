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
# supabase/postgres 17.11.0.008 (pushed 2026-10-27; amd64 and arm64): the 17.11 line new
# Supabase projects run. Bump it with the release, at least 14 days after it is pushed.
image=supabase/postgres:17.11.0.008@sha256:fef2654e52424e2748b1cd6763b73afcb2618c6ec696bd3af5ad572687be1dc7
password=$(openssl rand -hex 16)

# The image has no openssl (17.11 is built with Nix): the certificate is made here, mounted
# read-only, and copied inside where only the server's user can read the key (never in `-e`,
# which `docker inspect` would show).
certs=$(mktemp -d)
trap 'rm -rf "$certs"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=localhost \
  -keyout "$certs/server.key" -out "$certs/server.crt" 2>/dev/null
chmod 755 "$certs" # the key stays 0600: root in the container reads it, then hands it over

docker run -d --name "$name" -e POSTGRES_PASSWORD="$password" -p 127.0.0.1::5432 \
  -v "$certs:/certs:ro" --entrypoint bash "$image" -c '
    install -m 644 -o postgres /certs/server.crt /tmp/server.crt
    install -m 600 -o postgres /certs/server.key /tmp/server.key
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
docker logs --tail 50 "$name" >&2  # the server's log: it never contains the URL
echo "supabase/postgres did not get ready" >&2
exit 1
