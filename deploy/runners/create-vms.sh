#!/usr/bin/env bash
# Create isolated LXD VMs for ExactDocs' self-hosted GitHub Actions runners (run on the GB10 host).
#
#   deploy/runners/create-vms.sh [N...]      default: 1 2  ->  exactdocs-runner-1, exactdocs-runner-2
#
# Each VM gets Docker + buildx + QEMU binfmt (multi-arch images), git, gh, jq, unzip and the
# actions/runner binary under /opt/actions-runner, owned by an unprivileged `runner` user.
# Jobs therefore never touch the host's Docker daemon or its production containers.
# Register them afterwards with deploy/runners/register.sh.
set -euo pipefail

image=${IMAGE:-ubuntu:24.04}
profile=exactdocs-runner
runner_version=2.338.2
runner_sha256=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945 # linux-arm64
[ $# -gt 0 ] || set -- 1 2

if ! sudo lxc profile show "$profile" >/dev/null 2>&1; then
  # Without a TTY, `profile create` reads the profile YAML from stdin.
  sudo lxc profile create "$profile" <<'YAML'
description: ExactDocs GitHub Actions runners (isolated VMs)
config:
  boot.autostart: "true"
  limits.cpu: "4"
  limits.memory: 8GiB
  security.secureboot: "false"
devices:
  eth0:
    name: eth0
    network: lxdbr0
    type: nic
  root:
    path: /
    pool: default
    size: 50GiB
    type: disk
YAML
fi

for i in "$@"; do
  vm=exactdocs-runner-$i
  if sudo lxc info "$vm" >/dev/null 2>&1; then
    echo "$vm exists, skipping creation"
    continue
  fi
  sudo lxc launch "$image" "$vm" --vm -p "$profile"
  for _ in $(seq 1 60); do sudo lxc exec "$vm" -- true 2>/dev/null && break; sleep 5; done
  sudo lxc exec "$vm" -- cloud-init status --wait >/dev/null || true
  sudo lxc exec "$vm" -- bash -euo pipefail -c "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q --no-install-recommends \
      ca-certificates curl git jq unzip zstd build-essential libatomic1 docker.io docker-buildx qemu-user-static binfmt-support
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/githubcli.gpg] https://cli.github.com/packages stable main' \
      > /etc/apt/sources.list.d/github-cli.list
    apt-get update -q && apt-get install -y -q gh
    id runner >/dev/null 2>&1 || useradd -m -s /bin/bash -G docker runner
    echo 'runner ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-runner && chmod 440 /etc/sudoers.d/90-runner
    mkdir -p /opt/actions-runner && cd /opt/actions-runner
    curl -fsSL -o runner.tgz https://github.com/actions/runner/releases/download/v$runner_version/actions-runner-linux-arm64-$runner_version.tar.gz
    echo '$runner_sha256  runner.tgz' | sha256sum -c -
    tar xzf runner.tgz && rm runner.tgz
    ./bin/installdependencies.sh >/dev/null
    chown -R runner:runner /opt/actions-runner
  "
  echo "$vm ready"
done
