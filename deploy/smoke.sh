#!/bin/sh
# The "docker run to a searchable library" flow of README Quick start, over HTTP, with sh and curl
# only. usage: smoke.sh BASE_URL REPOSITORY_URL LIBRARY_ID REF
#   e.g. smoke.sh http://127.0.0.1:3000 file:///fixture/docs-repo /fixture/docs-repo v1.3.0
# Needs a fresh instance (no admin yet). Exits non-zero at the first step that fails.
set -eu
base=$1 repo=$2 lib=$3 ref=$4
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
json='content-type: application/json'
field() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; } # first string field of a one-line JSON body
step() { echo "--- $*"; }

step "wait for the server"
for _ in $(seq 1 60); do curl -fsS "$base/api/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$base/api/health"; echo

step "setup, sign in"
# a fresh instance offers only the setup; setup does not sign in
test "$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/libraries")" = 403
creds='{"username":"ci","password":"ci smoke test password"}'
curl -fsS -H "$json" -d "$creds" "$base/api/v1/setup"; echo
test "$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/libraries")" = 401
curl -fsS -c "$jar" -H "$json" -d "$creds" "$base/api/v1/session"; echo

step "create a token"
token=$(curl -fsS -b "$jar" -H "$json" -d '{"name":"ci"}' "$base/api/v1/tokens" | field token)
test -n "$token"
auth="authorization: Bearer $token"

step "add the library"
job=$(curl -fsS -b "$jar" -H "$json" -d "{\"url\":\"$repo\",\"ref\":\"$ref\",\"include_paths\":[\"docs/\"]}" \
  "$base/api/v1/libraries" | field job_id)
test -n "$job"

step "poll the job $job"
for _ in $(seq 1 120); do
  state=$(curl -fsS -b "$jar" "$base/api/v1/jobs/$job" | field state)
  case $state in queued | running) sleep 1 ;; *) break ;; esac
done
if test "$state" != succeeded; then
  echo "import job ended as '$state':"; curl -sS -b "$jar" "$base/api/v1/jobs/$job"; echo; exit 1
fi

step "list and read an article"
articles=$(curl -fsS -H "$auth" -G "$base/api/v1/libraries$lib/articles" -d "ref=$ref")
path=$(echo "$articles" | field path)
test -n "$path"
echo "first article: $path"
curl -fsS -H "$auth" -G "$base/api/v1/libraries$lib/article" -d "ref=$ref" --data-urlencode "path=$path" | grep -q '"content'

step "search over REST"
# "token" is in v1.3.0; retry_policy exists only from v1.4.0 and never in v1.3.0
hits=$(curl -fsS -H "$auth" -G "$base/api/v1/libraries$lib/search" -d "ref=$ref" -d q=token)
echo "$hits" | grep -q '"results":\[{'
curl -fsS -H "$auth" -G "$base/api/v1/libraries$lib/search" -d "ref=$ref" -d q=retry_policy | grep -q '"results":\[\]'

step "MCP query-docs over HTTP"
mcp() { curl -fsS -H "$auth" -H "$json" -H 'accept: application/json, text/event-stream' -H 'mcp-protocol-version: 2025-06-18' "$@" "$base/mcp"; }
mcp -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"ci","version":"1"}}}' >/dev/null
mcp -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null
answer=$(mcp -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"query-docs\",\"arguments\":{\"libraryId\":\"$lib/$ref\",\"query\":\"token\"}}}")
echo "$answer" | head -c 300; echo
echo "$answer" | grep -q '"result"'
! echo "$answer" | grep -q '"isError":true'
echo "$answer" | grep -q "Source: docs/"

step "web UI, token required and revocable, Host header checked"
curl -fsS "$base/" | grep -qi '<div id="root"'
code() { curl -s -o /dev/null -w '%{http_code}' "$@" "$base/mcp"; }
init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"ci","version":"1"}}}'
accept='accept: application/json, text/event-stream'
test "$(code -H "$json" -H "$accept" -d "$init")" = 401
test "$(code -H "$auth" -H "$json" -H "$accept" -d "$init")" = 200
test "$(curl -s -o /dev/null -w "%{http_code}" -H "$auth" -H "$json" -H "$accept" -d "$init" "$base/mcp/")" = 200
id=$(curl -fsS -b "$jar" "$base/api/v1/tokens" | field id)
curl -fsS -b "$jar" -X DELETE "$base/api/v1/tokens/$id"
test "$(code -H "$auth" -H "$json" -H "$accept" -d "$init")" = 401
test "$(code -H 'Host: evil.example' -H "$json" -H "$accept" -d "$init")" = 400
echo "smoke flow OK"
