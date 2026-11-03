#!/usr/bin/env bash
# Claim an issue for an agent: assign, label, and leave a claim comment.
#   claim.sh <issue> <agent-name> <branch> <one-line plan>
set -euo pipefail
n=${1:?usage: claim.sh <issue> <agent-name> <branch> <plan>}
agent=${2:?agent name}
branch=${3:?branch}
plan=${4:?one-line plan}
here=$(dirname "$0")

"$here/status.sh" "$n" >/dev/null || { "$here/status.sh" "$n"; echo "refusing to claim" >&2; exit 1; }

gh issue edit "$n" --add-assignee @me \
  --add-label "status: in progress" --add-label agent --remove-label "status: ready"
gh issue comment "$n" --body "🤖 **Claimed by \`$agent\`**, branch \`$branch\`.
Plan: $plan
I'll post here when a PR is open or if I stop."
echo "claimed #$n; re-run status.sh to make sure your claim is the earliest"
