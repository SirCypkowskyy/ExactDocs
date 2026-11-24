#!/usr/bin/env bash
# Start a libSQL server (sqld) with JWT auth, for the libSQL backend's tests (#358), and print
# two lines: its URL and an auth token, ready for EXACTDOCS_TEST_LIBSQL_URL and
# EXACTDOCS_TEST_LIBSQL_AUTH_TOKEN:
#
#   { read -r url; read -r token; } < <(deploy/libsql-test-server.sh exactdocs-libsql)
#   export EXACTDOCS_TEST_LIBSQL_URL=$url EXACTDOCS_TEST_LIBSQL_AUTH_TOKEN=$token
#   uv run pytest --integration packages/exactdocs/tests/retrieval -k libsql   # integration tests (#507)
#   docker rm -f exactdocs-libsql
#
# The server gets a throwaway Ed25519 key (only its public half is given to it) and a free port
# on 127.0.0.1; the token is signed here with the private half, as Turso signs its tokens, and
# the key is deleted. A request without the token is refused (401).
set -euo pipefail

name=${1:?usage: libsql-test-server.sh <container name>}
# libsql-server v0.24.33 (pushed 2025-12-19; amd64 and arm64): the latest sqld release. Bump it
# with the release, at least 14 days after it is pushed.
image=ghcr.io/tursodatabase/libsql-server:v0.24.33@sha256:f8ca0134cdded747793888e48591aece07647d9d598d3ac229aabfa93159ca88

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

keys=$(mktemp -d)
trap 'rm -rf "$keys"' EXIT
openssl genpkey -algorithm ed25519 -out "$keys/key.pem" 2>/dev/null
public=$(openssl pkey -in "$keys/key.pem" -pubout -outform DER | tail -c 32 | b64url)
now=$(date +%s)
header=$(printf '{"alg":"EdDSA","typ":"JWT"}' | b64url)
claims=$(printf '{"iat":%d,"exp":%d}' "$now" "$((now + 86400))" | b64url)
printf '%s.%s' "$header" "$claims" > "$keys/signed"
signature=$(openssl pkeyutl -sign -rawin -inkey "$keys/key.pem" -in "$keys/signed" | b64url)
token="$header.$claims.$signature"

docker run -d --name "$name" -e SQLD_AUTH_JWT_KEY="$public" -p 127.0.0.1::8080 "$image" >/dev/null
port=$(docker port "$name" 8080/tcp | head -n1 | cut -d: -f2)
url="http://127.0.0.1:${port}"

for _ in $(seq 60); do
  if curl -fsS -o /dev/null -X POST "$url/v2/pipeline" -H "Authorization: Bearer $token" \
    -H 'content-type: application/json' \
    -d '{"requests":[{"type":"execute","stmt":{"sql":"SELECT 1"}},{"type":"close"}]}' 2>/dev/null; then
    echo "$url"
    echo "$token"
    exit 0
  fi
  sleep 1
done
docker logs --tail 50 "$name" >&2 # the server's log: it never contains the token
echo "libsql-server did not get ready" >&2
exit 1
