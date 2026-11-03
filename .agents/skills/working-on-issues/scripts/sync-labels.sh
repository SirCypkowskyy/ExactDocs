#!/usr/bin/env bash
# Create or update the repository labels from .github/labels.yml (idempotent).
set -euo pipefail
root=$(git rev-parse --show-toplevel)
grep -E '^- \{' "$root/.github/labels.yml" | while IFS= read -r line; do
  name=$(sed -E 's/.*name: "([^"]+)".*/\1/' <<<"$line")
  color=$(sed -E 's/.*color: "([^"]+)".*/\1/' <<<"$line")
  desc=$(sed -E 's/.*description: "([^"]+)".*/\1/' <<<"$line")
  gh label create "$name" --color "$color" --description "$desc" --force
done
