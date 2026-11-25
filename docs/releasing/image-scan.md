# Image scan

!!! abstract "TL;DR"
    - Every integration run and every release scans each built image variant with
      [Trivy](https://trivy.dev). Every PR lints `deploy/Dockerfile` with hadolint.
    - The scan fails on a CRITICAL or HIGH vulnerability that has a fix. No image of a release is
      pushed while the scan of any variant fails.
    - When it fails, rebuild with fresh base layers first, then update the dependency. Accept a
      finding in `.trivyignore` only if it does not apply and cannot be fixed yet.
    - Trivy and hadolint are pinned by digest where Dependabot cannot see them: bump them by hand
      at every release.

## Where it runs

| Check | Where |
|---|---|
| Trivy scan | integration jobs *Docker image* and *Docker image variants* of `integration.yml` (started by hand: [Fast and integration tests](tests.md#when-ci-runs-them)); every release's *Scan image* jobs |
| hadolint | every PR, CI's *Lint* job; its one accepted rule, with the reason, is in `.hadolint.yaml` |

- The scan **fails on a CRITICAL or HIGH vulnerability that has a fix** (`--ignore-unfixed`).
- The table is in the job log and in the artifact: `trivy-report` (`trivy-report-ai`,
  `trivy-report-local`), and in a release `trivy-report-<variant>-<arch>`.
- No image of a release is pushed while the scan of any variant fails.

## When it fails

1. **Rebuild with fresh base layers.** Bump the base images: Dependabot's `docker` PRs for
   `/deploy` move tag and digest together, and merging one is usually the fix.
    - Debian packages are not pinned. The Dockerfile's `DEBIAN_REFRESH` build argument (the date
      in a release, the ISO week in CI) makes a new build fetch fresh package indexes, so it also
      picks up a fixed `git` or `openssh-client`.
    - It does not upgrade the packages that come with the base image (`apt`, `libc6`, `dpkg`,
      ...): `apt-get install` leaves installed packages alone. A finding in one of those is fixed
      by a newer base digest or, until one ships the fix, by an explicit
      `apt-get install --only-upgrade <package>` in the `runtime-tools` stage (as for `zlib1g`,
      #275; remove it once the base digest catches up).
2. **If the fix is a Python dependency**, update it in `uv.lock`; for a web dependency,
   `pnpm-lock.yaml`.
3. **Only if the finding does not apply to ExactDocs and cannot be fixed yet, accept it.** Add the
   ID to `.trivyignore` with a comment above it saying why, the date and who accepted it, in the
   PR that needs it. The reviewer decides; remove the entry once a fixed version ships.

!!! info "A scan that passed yesterday can fail today"
    Every job downloads a fresh Trivy DB. So a scan can fail on an advisory published since, and the amd64 and arm64 legs of one release can
    briefly disagree. The failing run is the real result.

!!! note "Slower Mondays"
    Because the week is part of the cache key, the first Docker build of each ISO week (Monday)
    re-runs the apt steps and is about a minute slower. That is expected, not a cache bug.

## Unfixed findings

Unfixed findings are not listed by the gate. Check them occasionally:

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock ghcr.io/aquasecurity/trivy image <image>
```

## Pinned tools

The scanner and the linter are pinned by digest in `run:`/`env:` text, which Dependabot does not
read. Bump them by hand at every release, or a stale scanner stops finding new vulnerabilities:

| Tool | Where |
|---|---|
| `hadolint/hadolint` | `.github/workflows/ci.yml`, job *image* |
| `ghcr.io/aquasecurity/trivy` | `.github/actions/trivy-gate/action.yml` |

## Build caches

- The CI Docker jobs use the runner's own BuildKit (`driver: docker`): on a fresh GitHub-hosted VM
  nothing is cached between runs.
- The release uses the GitHub Actions cache (one scope per variant and architecture,
  `scope=exactdocs-<variant>-<arch>`), which hands the scanned layers to the build that pushes
  them.
