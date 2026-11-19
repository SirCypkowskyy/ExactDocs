# Self-hosted runners (GB10)

CI and releases run on our own hardware: two LXD **virtual machines** on the Dell Pro Max GB10
(`dellpromaxgb10`, Ubuntu 24.04, ARM64). VMs, not containers or host services, because the host
runs other production containers and a job with Docker access on the host could reach them.

| | |
|---|---|
| VMs | `exactdocs-runner-1`, `exactdocs-runner-2` (LXD profile `exactdocs-runner`: 4 vCPU, 8 GiB, 50 GiB sparse disk) |
| Labels | `self-hosted`, `linux`, `ARM64`, `exactdocs`; workflows use `runs-on: [self-hosted, linux, ARM64, exactdocs]` |
| Scope | this repository only |
| Tooling | Docker + buildx + compose + QEMU (amd64 images are emulated), git, gh, jq; uv, Node and pnpm come from setup actions |

## Existing VMs

`create-vms.sh` only provisions new VMs. When it gains a package, install it once on the running
ones, e.g. for the compose plugin the PostgreSQL smoke step needs (#103). Until then that step
warns and uses a pinned standalone compose binary in the job's temp directory (it never changes
the host):

```bash
for vm in exactdocs-runner-1 exactdocs-runner-2; do
  sudo lxc exec "$vm" -- sh -c 'apt-get update -q && apt-get install -y -q docker-compose-v2'
done
```

## Browser dependencies

The built-wheel CI job caches Chromium and probes a real headless launch, page rendering and
screenshot before its browser E2E test. Working persistent runners skip APT entirely. If the
probe fails, the job attempts Playwright system dependency installation with passwordless sudo,
15-second APT network timeouts, one retry and a 180-second overall deadline (then a 10-second
kill grace). These APT settings live in a temporary command-specific config; host configuration
is unchanged. A second failed probe fails the job. This readiness probe does not replace the
application E2E gate or verify visual fidelity/font coverage. The fallback runs the pinned
Playwright CLI through an absolute Node executable as root inside the deadline, keeping its
APT children in the privileged timeout process group; it does not run pnpm as root or carry
the user PATH into sudo. Browser download also has a 180-second deadline; each readiness
probe has a 30-second deadline.

## Setup

From a workstation with `gh` logged in (NVIDIA Sync's SSH config provides the `dellpromaxgb10.local` host):

```bash
scp -r deploy/runners dellpromaxgb10.local:~/exactdocs-runners
ssh dellpromaxgb10.local '~/exactdocs-runners/create-vms.sh 1 2'

token=$(gh api -X POST repos/SirCypkowskyy/ExactDocs/actions/runners/registration-token --jq .token)
ssh dellpromaxgb10.local "~/exactdocs-runners/register.sh SirCypkowskyy/ExactDocs $token"
gh api repos/SirCypkowskyy/ExactDocs/actions/runners --jq '.runners[] | [.name, .status] | @tsv'
```

Add a third runner: `create-vms.sh 3`, then `RUNNERS=3 register.sh ...`.

Remove: `register.sh --remove SirCypkowskyy/ExactDocs <remove-token>`, then `sudo lxc delete --force exactdocs-runner-N`.

## Security notes

- The repository is private. If it ever goes public, set *Settings → Actions → Fork pull request
  workflows* to require approval for all outside collaborators; self-hosted runners must never
  run untrusted fork code unattended.
- Runners are persistent (not ephemeral): `_work` and the Docker cache survive between jobs. That
  keeps builds fast; recreate a VM if it ever runs something untrusted.
