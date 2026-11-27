# CI runs on our GCP self-hosted runners

!!! abstract "TL;DR"
    - CI runs on eight GCP VMs registered as self-hosted runners, and every self-hosted job asks
      for `[self-hosted, linux, ARM64, exactdocs, gcp]`. The runner on the maintainer's
      workstation gets no job.
    - `RUNNER_MODE` stays, set to `self-hosted`. `hybrid` is the way back to GitHub-hosted
      runners.
    - A pull request from a fork never reaches these VMs: it runs on GitHub-hosted
      `ubuntu-24.04`, and only after the maintainer approves the run.
    - The VMs are persistent, so a job can see what an earlier one left. Ephemeral runners are
      the next step.

| | |
|---|---|
| **Status** | Accepted, 2026-11-26 |
| **Scope** | Every workflow in `.github/workflows/`; the layout is in [CI/CD and runners](../releasing/runners.md) |
| **Issue** | Refs #533; replaces the hosted-only plan of #537 |
| **Decided by** | The owner, 2026-11-26 |

## Context

- The repository is public.
- The account's GitHub-hosted Actions minutes for this month are used up. #537 would have moved
  every job to GitHub-hosted runners, and it was not merged.
- Five ARM64 VMs on GCP are already provisioned with Terraform and registered to this
  repository: `exactdocs-gcp-runner-1` to `-5`, `t2a-standard-2` (2 vCPU, 8 GiB). Their labels
  are `self-hosted, Linux, ARM64, exactdocs, gcp`. They have no GCP service account.
- One older runner, an LXD VM on the maintainer's workstation, is still registered with
  `self-hosted, Linux, ARM64, exactdocs`. It sits on a home network, and jobs that asked for the
  old label set could land on it.
- A `pull_request` run takes its workflow file from the pull request, so a fork can point a job
  at any label.
- GitHub's billing docs say standard GitHub-hosted runners in a public repository are free and do
  not reduce the included usage. The fork fallback below relies on that.

## Decision

- **Every self-hosted `runs-on` asks for `[self-hosted, linux, ARM64, exactdocs, gcp]`.** That
  covers the 14 hard-coded jobs and the 19 that `RUNNER_MODE` switches. The label set is written
  out in each job, because a workflow cannot share a value across files: `runs-on` may read only
  `github`, `needs`, `strategy`, `matrix`, `vars` and `inputs`, and YAML anchors work within one
  file. `packages/exactdocs/tests/ci/test_runners.py` holds the one definition and fails on any
  `runs-on` that differs.
- **`RUNNER_MODE` stays, and is `self-hosted`.** Every job of a trusted run goes to the GCP
  runners. Setting it to `hybrid` (or deleting it) moves CI, the docs and the release's amd64 and
  publishing jobs back to `ubuntu-24.04` without a code change, for example when the VMs are
  down.
- **The amd64 work stays on ARM64** as `self-hosted` mode already did it. The release
  cross-builds the amd64 image legs, with QEMU only for the runtime stage's `apt-get`, and checks
  them with `check_artifacts.py --no-python`. CI and the integration jobs skip the amd64-only
  Pinecone Local and libSQL local-file cases. Using hosted amd64 runners for those legs was not
  chosen, since it depends on the hosted quota again.
- **Shards for 2-vCPU runners.** In `self-hosted` mode CI runs pytest in three shards and
  behave in two, about 20 and 18 minutes each on these VMs (one behave shard took 35 minutes,
  against a 45-minute timeout). The real-providers benchmark gets a 720-minute timeout, since its
  recorded local subset took 3 h 22 min on 4 CPUs.
- **The required Python check runs GitHub-hosted.** It only reads its `needs` results and the
  shards' coverage, and on a self-hosted runner it sat in the queue after every shard had passed
  (#652). Standard hosted runners are free for a public repository.

## Security measures

- **Fork pull requests stay off the VMs.** The CI and Docs jobs, the only ones a pull request
  starts, pick `ubuntu-24.04` when `github.event.pull_request.head.repo.fork` is true. One CI job,
  *Coding tasks*, lacked that check and has it now. The test checks every job of a workflow with
  a `pull_request` trigger.
- **Approval for all external contributors** (*Settings → Actions → General*). A fork can still
  edit `runs-on` in its copy, so the maintainer reads the workflow diff before approving a run.
- **No `pull_request_target`.** The one `workflow_run` trigger (GHCR retention) listens to the
  release, which runs from a tag or a manual run, and it checks out no code.
- **Read-only `GITHUB_TOKEN` by default.** Jobs that need more ask for it.
- **No GCP identity on the VMs.** A job that takes over a VM gets no credentials for the GCP
  project.

## Considered options

- **GitHub-hosted runners only (#537).** Rejected by the owner while the hosted minutes are used
  up. It stays available through `RUNNER_MODE=hybrid`.
- **Keep the LXD runners on the workstation.** Rejected: they sit on a home network next to other
  services, and the GCP VMs replace them. The `gcp` label keeps jobs off the one still
  registered, and `create-vms.sh` and `register.sh` are removed from `deploy/runners/`.
- **Ephemeral, autoscaled runners** (a fresh VM or container per job). Not now: the persistent
  VMs exist and work. This is the follow-up below.

## Consequences

- **State survives between jobs.** `_work`, the Docker cache and the BuildKit cache stay on a VM,
  and the runner user has passwordless sudo. A job can see or change what the next job on the
  same VM runs with, and in `self-hosted` mode that includes the release's publishing jobs and
  their OIDC tokens. The job-started hook in `deploy/runners/` removes leftover containers and is
  installed on every GCP VM.
- **Capacity is 8 × 2 vCPU** (five VMs at first, three more since 27 November 2026). One pull
  request's CI is nine jobs plus two for the docs, so two pull requests at once queue. A self-hosted job can run up to 5 days.
- **The arm64 numbers stay comparable.** The recorded benchmark runs were Linux aarch64, as are
  these VMs, though with 2 CPUs instead of 4.
- **Follow-up:** ephemeral runners, one fresh VM per job and deregistered after it, which removes
  the shared state and lets the publishing jobs run on a clean machine.
