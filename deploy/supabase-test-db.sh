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

# The image has no openssl (17.11 is built with Nix): the certificate is made here and handed
# over in the environment, then written where only the server's user can read it.
certs=$(mktemp -d)
trap 'rm -rf "$certs"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=localhost \
  -keyout "$certs/server.key" -out "$certs/server.crt" 2>/dev/null

docker run -d --name "$name" -e POSTGRES_PASSWORD="$password" -p 127.0.0.1::5432 \
  -e SSL_CERT="$(cat "$certs/server.crt")" -e SSL_KEY="$(cat "$certs/server.key")" \
  --entrypoint bash "$image" -c '
    printf "%s\n" "$SSL_CERT" > /tmp/server.crt
    (umask 077 && printf "%s\n" "$SSL_KEY" > /tmp/server.key)
    chown postgres /tmp/server.key /tmp/server.crt
    unset SSL_CERT SSL_KEY
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
