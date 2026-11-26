#!/usr/bin/env bash
# Runs on a self-hosted runner VM before every job (ACTIONS_RUNNER_HOOK_JOB_STARTED; see
# deploy/runners/README.md). A runner takes one job at a time, so whatever Docker holds now is left by a
# job that ended without its own cleanup (cancelled, its runner lost, the disk full): its service
# containers, `exactdocs-supabase-<run>`, a release's buildx builders and their state. Remove it;
# when the disk is FULL_PERCENT full or more, also build cache and images older than KEEP.
# Named volumes (exactdocs-ci-data) and recent layers stay. Never fails the job.
set -u
FULL_PERCENT=${FULL_PERCENT:-80}
KEEP=${KEEP:-72h}

containers=$(docker ps -aq)
if [ -n "$containers" ]; then
  echo "removing $(wc -w <<<"$containers") container(s) left by earlier jobs:"
  docker ps -a --format '  {{.Names}} ({{.Image}}, {{.Status}})'
  docker rm -f $containers >/dev/null
fi
docker volume ls -q --filter name=buildx_buildkit_ | xargs -r docker volume rm >/dev/null
docker volume prune -f >/dev/null # anonymous volumes only

used=$(df --output=pcent / | tail -1 | tr -dc 0-9)
if [ "$used" -ge "$FULL_PERCENT" ]; then
  echo "disk ${used}% full: pruning build cache and images older than $KEEP"
  docker builder prune -af --filter "until=$KEEP" >/dev/null
  docker image prune -af --filter "until=$KEEP" >/dev/null
fi
df -h / | tail -1
exit 0
