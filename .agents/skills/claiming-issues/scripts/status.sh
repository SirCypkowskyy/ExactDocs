#!/usr/bin/env bash
# Print who owns an issue and whether it may be claimed. Exit 0 = free, 1 = taken / not ready.
#   status.sh <issue>
set -euo pipefail
n=${1:?usage: status.sh <issue>}

json=$(gh issue view "$n" --json number,title,state,labels,assignees,comments)
state=$(jq -r .state <<<"$json")
labels=$(jq -r '[.labels[].name] | join(", ")' <<<"$json")
assignees=$(jq -r '[.assignees[].login] | join(", ")' <<<"$json")

echo "#$n $(jq -r .title <<<"$json")"
echo "state:     $state"
echo "labels:    ${labels:-none}"
echo "assignees: ${assignees:-none}"
echo "claims (oldest first):"
jq -r '.comments[] | select(.body | startswith("🤖 **Claimed by"))
       | "  \(.createdAt)  \(.body | split("\n")[0])"' <<<"$json"

if [ "$state" != OPEN ]; then echo "=> closed"; exit 1; fi
for busy in "status: in progress" "status: in review" "status: triage" "status: blocked"; do
  if jq -e --arg l "$busy" 'any(.labels[]; .name == $l)' <<<"$json" >/dev/null; then
    echo "=> not claimable ($busy)"; exit 1
  fi
done
if [ -n "$assignees" ]; then echo "=> assigned to $assignees"; exit 1; fi
echo "=> free"
