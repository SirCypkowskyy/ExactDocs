# CI on GitHub-hosted runners

!!! abstract "TL;DR"
    - Every CI job runs on a GitHub-hosted runner, a fresh VM per job. The self-hosted runners
      and the `RUNNER_MODE` switch are gone.
    - New workflows use `ubuntu-24.04`. `ubuntu-24.04-arm` is only for jobs that compare
      architectures or latencies: the arm64 image legs and the real-providers benchmark.
    - A hosted job stops after 6 hours, so a full local benchmark matrix runs in parts.

| | |
|---|---|
| **Status** | Accepted, 2026-11-26 |
| **Scope** | Every workflow in `.github/workflows/`; the layout is in [CI/CD and runners](../releasing/runners.md) |
| **Issue** | #533 (built in #537) |
| **Decided by** | The owner, in #533 |

## Context

CI could run on GitHub-hosted runners or on two self-hosted VMs, chosen by the repository
variable `RUNNER_MODE`. The self-hosted VMs existed only to save hosted minutes while the
repository was private. They were persistent, a job could get root on them, they sat on the
maintainer's home network, and they built the release artifacts. On a public repository a
`pull_request` run takes the workflow file from the pull request, so a fork could point a job
at the self-hosted label.

## Decision

Every job runs on a hosted runner, and nothing reads `RUNNER_MODE`.

- **Security.** A fresh VM per job keeps OIDC tokens, `packages: write` and the providers' keys
  off machines that outlive the job, and a fork's code runs only on a throwaway VM with a
  read-only token.
- **Cost.** Standard hosted runners, `ubuntu-24.04-arm` included, are free for public
  repositories.
- **Speed.** The self-hosted mode had two 4 vCPU / 8 GiB VMs and ran fewer test shards. Hosted
  runners for a public repository have 4 vCPUs and 16 GB, every shard runs in parallel, and each
  image architecture is built natively, so the QEMU and `--no-python` path in the release goes
  away.

The cost is the 6-hour job limit (self-hosted jobs could run for 5 days). The real-providers
benchmark and `harness-bench.yml` keep their 360-minute timeouts, and a full local benchmark
matrix is split across dispatches.

## Considered options

- **Keep the `RUNNER_MODE` switch** between hosted and self-hosted. Rejected: the self-hosted
  label stays reachable from fork pull requests, and the switch only saved minutes that are now
  free.
- **Self-hosted only.** Rejected for the same security reasons, and it is slower.
