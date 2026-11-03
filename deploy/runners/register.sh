#!/usr/bin/env bash
# Register (or remove) the exactdocs-runner-N VMs as repository runners (run on the GB10 host).
#
#   deploy/runners/register.sh <owner/repo> <registration-token>
#   deploy/runners/register.sh --remove <owner/repo> <removal-token>
#
# Tokens are short-lived; get one from a machine with the gh CLI:
#   gh api -X POST repos/<owner/repo>/actions/runners/registration-token --jq .token
#   gh api -X POST repos/<owner/repo>/actions/runners/remove-token --jq .token
# Labels: self-hosted, linux, ARM64 (automatic) + exactdocs. Which VMs: RUNNERS="1 2" (default: all).
set -euo pipefail

remove=0
[ "${1:-}" = --remove ] && { remove=1; shift; }
repo=${1:?usage: register.sh [--remove] <owner/repo> <token>}
token=${2:?pass a registration (or removal) token}
runners=${RUNNERS:-$(sudo lxc list '^exactdocs-runner-[0-9]+$' -c n --format csv | sed 's/^exactdocs-runner-//')}

for i in $runners; do
  vm=exactdocs-runner-$i
  sudo lxc start "$vm" 2>/dev/null || true
  if [ $remove = 1 ]; then
    sudo lxc exec "$vm" -- bash -ec "cd /opt/actions-runner
      ./svc.sh stop || true; ./svc.sh uninstall || true
      sudo -u runner ./config.sh remove --token '$token'"
  else
    sudo lxc exec "$vm" -- bash -ec "cd /opt/actions-runner
      sudo -u runner ./config.sh --unattended --replace --url 'https://github.com/$repo' \
        --token '$token' --name '$vm' --labels exactdocs --work _work
      ./svc.sh install runner && ./svc.sh start"
  fi
  echo "$vm done"
done
