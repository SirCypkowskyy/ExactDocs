<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../docs/assets/logo/exactdocs-lockup-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="../../docs/assets/logo/exactdocs-lockup-light.svg">
  <img src="../../docs/assets/logo/exactdocs-lockup-light.svg" alt="ExactDocs" width="220">
</picture>

# Self-hosted runners (GCP)

CI runs on one GCP VM (docs/decisions/ci-runners.md). Which job runs on them is set by the
repository variable `RUNNER_MODE` (docs/releasing/runners.md, *CI/CD and runners*); it is
`self-hosted`, so every job of a trusted run does, and a fork's pull request runs on
GitHub-hosted `ubuntu-24.04`.

| | |
|---|---|
| VMs | `exactdocs-gcp-runner-1` to `exactdocs-gcp-runner-8`, `t2a-standard-2` (2 vCPU, 8 GiB, ARM64), 50 GiB `pd-balanced` disk, Ubuntu 24.04 |
| Labels | `self-hosted`, `Linux`, `ARM64`, `exactdocs`, `gcp`; workflows use `runs-on: [self-hosted, linux, ARM64, exactdocs, gcp]` |
| Scope | this repository only |
| GCP identity | none: the VMs have no service account |
| Tooling | Docker + buildx + compose + QEMU (amd64 images are emulated), git, gh, jq; uv, Node and pnpm come from setup actions |
| Provisioning | Terraform in the maintainer's private infrastructure repository; a startup script installs the toolchain, the pinned runner binary and its systemd service, and registers the VM once |

The earlier LXD VMs on the maintainer's workstation and their `create-vms.sh` / `register.sh`
are gone. Any runner registered without the `gcp` label gets no job.

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

## Job-started hook

`job-started.sh` cleans Docker before every job. A job that ends without its own cleanup
(cancelled, its runner lost, the disk full) leaves its service containers,
`exactdocs-supabase-<run>` or a release's buildx builder behind, and the next job on that VM
inherits them: the hook removes every container, anonymous volume and buildx builder state, since
a runner takes one job at a time, and at 80% disk or more also build cache and images older than
72 hours. Named volumes such as `exactdocs-ci-data` and recent layers stay.

The runner VMs' startup script in the infrastructure repository installs it as
`/opt/runner-hooks/job-started.sh` (owned by root, mode 0755), outside the runner's own directory
as GitHub's docs advise, and sets `ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/runner-hooks/job-started.sh`
in `/opt/actions-runner/.env`, restarting the runner service only when that file changed. VMs that
existed before the hook get it from that repository's `scripts/install-hook.sh`, which skips busy
runners. Its output is in each job's *Set up runner* step.

## Security notes

- The repository is public. *Settings → Actions → Fork pull request workflows* requires approval
  for all external contributors, and the CI and Docs workflows send a fork's run to
  GitHub-hosted runners. Self-hosted runners must never run untrusted fork code.
- Runners are persistent (not ephemeral): `_work` and the Docker cache survive between jobs, and
  the runner user has passwordless sudo. That keeps builds fast; recreate a VM if it ever runs
  something untrusted.
