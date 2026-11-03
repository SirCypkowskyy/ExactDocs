#!/usr/bin/env bash
# End an agent's claim on an issue.
#   handoff.sh <issue> review  <pr-url> <summary>   PR is open      -> status: in review
#   handoff.sh <issue> release ""       <reason>    stopping, no PR -> status: ready (or keeps blocked)
set -euo pipefail
n=${1:?usage: handoff.sh <issue> review|release <pr-url> <summary>}
mode=${2:?review or release}
pr=${3:-}
summary=${4:?summary}

case "$mode" in
  review)
    [ -n "$pr" ] || { echo "review needs a PR url" >&2; exit 1; }
    gh issue edit "$n" --add-label "status: in review" \
      --remove-label "status: in progress" --remove-label agent
    gh issue comment "$n" --body "🤖 **PR ready for review:** $pr
$summary"
    ;;
  release)
    blocked=$(gh issue view "$n" --json labels --jq 'any(.labels[]; .name == "status: blocked")')
    args=(--remove-label "status: in progress" --remove-label agent --remove-assignee @me)
    [ "$blocked" = true ] || args+=(--add-label "status: ready")
    gh issue edit "$n" "${args[@]}"
    gh issue comment "$n" --body "🤖 **Released, no PR.**
$summary"
    ;;
  *) echo "mode must be review or release" >&2; exit 1 ;;
esac
