#!/usr/bin/env bash
# Start the Milvus standalone server for the Milvus tests (#360) and print its URI, ready for
# EXACTDOCS_TEST_MILVUS_URL:
#
#   export EXACTDOCS_TEST_MILVUS_URL=$(deploy/milvus-test-server.sh exactdocs-milvus)
#   uv run pytest packages/exactdocs/tests/retrieval -k milvus
#   uv run behave packages/exactdocs/features/milvus_index.feature
#   docker rm -f exactdocs-milvus
#
# Standalone with its embedded etcd and local storage (no etcd or MinIO containers), on a free
# port of 127.0.0.1, without authentication. A step rather than a CI service: a service
# container cannot be given the `milvus run standalone` command.
set -euo pipefail

name=${1:?usage: milvus-test-server.sh <container name>}
# milvusdb/milvus v3.0.5 (pushed 2026-10-30; amd64 and arm64), the server line pymilvus 3.0
# (the `milvus` extra) talks to. Bump it with the extra, at least 14 days after it is pushed.
image=milvusdb/milvus:v3.0.5@sha256:b9b79b4a284b41cd12d60abc418310f84621fa4c977d409b38f501519a7ccf8a

docker run -d --name "$name" -p 127.0.0.1::19530 -p 127.0.0.1::9091 \
  -e ETCD_USE_EMBED=true -e ETCD_DATA_DIR=/var/lib/milvus/etcd \
  -e COMMON_STORAGETYPE=local -e DEPLOY_MODE=STANDALONE \
  "$image" milvus run standalone >/dev/null

port=$(docker port "$name" 19530/tcp | head -n1 | cut -d: -f2)
health=$(docker port "$name" 9091/tcp | head -n1 | cut -d: -f2)

for _ in $(seq 180); do
  if curl -sf "http://127.0.0.1:${health}/healthz" >/dev/null 2>&1; then
    echo "http://127.0.0.1:${port}"
    exit 0
  fi
  sleep 1
done
docker logs --tail 50 "$name" >&2
echo "milvus did not get ready" >&2
exit 1
