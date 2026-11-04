# Branching, versioning and releases

## Branches

| Branch | Purpose | Protection |
|---|---|---|
| `main` | released code; every commit is releasable | no deletion, no force-push; changes only through a PR, merged with **merge commit** or **rebase** |
| `develop` | integration branch; feature branches merge here | no deletion, no force-push; changes only through a PR, merged with **squash** |
| `feature/<issue>-<slug>`, `bugfix/<issue>-<slug>`, `docs/<issue>-<slug>`, `chore/<issue>-<slug>` | one issue each, from `develop` | none |

Flow: `feature/12-version-filter` → PR into `develop` (squash: one commit per issue) → PR
`develop` → `main` (merge commit or rebase, keeping the squashed history) → tag on `main`.

The merge methods are enforced by repository rulesets on the target branch, so they apply to every
PR into it, whatever the source branch (a rare `main` → `develop` back-merge is squashed too).

## Versions (SemVer + PEP 440)

`MAJOR.MINOR.PATCH`, the same number on PyPI, ghcr.io and the git tag (`v` prefix on the tag only).

- **MAJOR**: only for breaking changes (MCP tool contracts, config variables, REST API, data
  format). Stays `0` until we decide the project is stable; bumping it is a deliberate decision,
  not part of a regular release.
- **MINOR**: new use cases / features.
- **PATCH**: fixes to the current minor, or small logic changes with no new use case.

Package versions come from the git tag (`uv-dynamic-versioning`); nothing in the repo is edited
to release. `exactdocs` pins `exactdocs-kernel==<same version>`.

## Tags and what they publish

| Tag | Must be on | PyPI | ghcr.io/sircypkowskyy/exactdocs | GitHub Release |
|---|---|---|---|---|
| `v0.1.3` | `main` | `exactdocs 0.1.3`, `exactdocs-kernel 0.1.3` | `0.1.3`, `0.1`, `latest` | release, marked latest |
| `v0.1.3.dev2` | `develop` | `0.1.3.dev2` (pre-release) | `0.1.3.dev2`, `0.1.3.dev2-<sha7>`, `dev` | pre-release |

Dev tags use the PEP 440 developmental-release form `X.Y.Z.devN`, meaning "work towards X.Y.Z",
so `0.1.3.dev2 < 0.1.3`. pip and `uvx exactdocs` ignore them unless asked
(`uvx --prerelease allow exactdocs@0.1.3.dev2`). PyPI forbids local versions (`+sha`), so the
commit is visible on the image tag and in the release instead.

Any other tag shape, or a tag on the wrong branch, fails the workflow before anything is published.

```bash
# stable
git switch main && git pull && git tag v0.1.3 && git push origin v0.1.3
# dev (rare)
git switch develop && git pull && git tag v0.1.3.dev1 && git push origin v0.1.3.dev1
```

Creating a release in the GitHub UI with a new tag works too: it pushes the tag, the workflow
runs, and it attaches the distributions to that release.

## Image retention

`.github/workflows/ghcr-retention.yml` keeps the registry small: the **5 newest dev images**
(`X.Y.Z.devN`) and the **10 newest stable images** (`X.Y.Z`); a multi-arch image is removed with
its platform images, cosign signature and attestations, and untagged leftovers are deleted. It
runs after every release, weekly, and on demand (`gh workflow run ghcr-retention.yml -f
dry-run=true` shows what would be deleted). Change `KEEP_DEV` / `KEEP_STABLE` in the workflow to
adjust. PyPI releases are never deleted.

## Size and model-free budgets

RUN-02: many installs only ever use BM25, so the artifacts hold no models and no ML libraries. CI
enforces it (`deploy/check_artifacts.py`, CI job *Docker image*; the sizes land in the job summary):

| Artifact | Budget | Now | Also checked |
|---|---|---|---|
| wheel (with the UI) | 5 MB | 0.4 MB | no `*.safetensors`, `*.bin`, `*.onnx`, `*.gguf`, `*.pt`; no ML package in `Requires-Dist` |
| image (uncompressed) | 375 MB | 354 MB | no such model file anywhere in the filesystem |

The unit tests add that `uv.lock` holds no torch, transformers, sentence-transformers,
huggingface-hub, onnx, pydantic-ai or chonkie, and that a started app imports none of them
(`packages/exactdocs/tests/bootstrap/test_model_free.py`). Optional AI extras must stay out of the
default dependencies; add them as extras and extend those lists.

**Why 375 MB and not the 300 MB first planned.** The floor is the `python:3.14-slim` base (~120 MB),
git and ssh (~25 MB git-core plus libraries; Perl is already purged) and the virtualenv (167 MB). 57 MB
of that is precompiled `.pyc`: dropping it would reach ~297 MB but make every start of a read-only
container recompile the whole dependency tree. Keeping it is the better trade, so the budget is the
measured 354 MB plus about 6 % headroom for dependency and Debian security updates. Raising it needs a
reason in the PR; lowering it is the goal if a dependency is dropped.

## Image scan

Every PR (CI job *Docker image*) and every release scans the built image with
[Trivy](https://trivy.dev) and lints `deploy/Dockerfile` with hadolint (CI only; its one accepted
rule, with the reason, is in `.hadolint.yaml`). The scan **fails on a CRITICAL or HIGH
vulnerability that has a fix** (`--ignore-unfixed`); the table is in the job log and in the
`trivy-report` artifact. A release is not pushed while the scan fails.

When it fails:

1. Rebuild with fresh base layers: bump the base images (Dependabot's `docker` PRs for `/deploy`
   move tag and digest together; merging one is usually the fix). Debian packages are not
   pinned: the Dockerfile's `DEBIAN_REFRESH` build argument (the date in a release, the ISO week
   in CI) makes a new build fetch fresh package indexes, so it also picks up a fixed `git` or
   `openssh-client`.
   Because the week is part of the cache key, the first Docker build of each ISO week (Monday)
   re-runs the apt steps and is about a minute slower; that is expected, not a cache bug.
2. If the fix is a Python dependency, update it in `uv.lock`; for a web dependency, `pnpm-lock.yaml`.
3. Only if the finding does not apply to ExactDocs and cannot be fixed yet, accept it: add the ID
   to `.trivyignore` with a comment above it saying why, the date and who accepted it, in the PR
   that needs it. The reviewer decides; remove the entry once a fixed version ships.

Unfixed findings are not listed by the gate; check them occasionally with
`docker run --rm -v /var/run/docker.sock:/var/run/docker.sock ghcr.io/aquasecurity/trivy image <image>`.

The scanner and the linter are pinned by digest in `run:`/`env:` text, which Dependabot does not
read: bump `hadolint/hadolint` (`.github/workflows/ci.yml`, job *image*) and
`ghcr.io/aquasecurity/trivy` (`.github/actions/trivy-gate/action.yml`) by hand at every release, or
a stale scanner stops finding new vulnerabilities.

The CI Docker job uses the runner VM's own BuildKit (`driver: docker`), so layers and cache mounts
persist between jobs on the same VM (see `deploy/runners/README.md`); the release uses the GitHub
Actions cache instead (`scope=exactdocs`), because it builds multi-arch with a throwaway builder.

## What the release workflow does

`.github/workflows/release.yml`, on the self-hosted GB10 runners:

1. **meta**: validates tag shape and branch, derives version/channel.
2. **web**: `pnpm build`.
3. **python**: bundles the UI into the wheel, `uv build --all-packages`, `twine check`, runs the
   wheel the way `uvx` would.
4. **pypi-kernel**, then **pypi**: `uv publish` with **trusted publishing** (OIDC, no stored token).
5. **image**: builds the image natively and scans it (see *Image scan*), then multi-arch
   (`linux/amd64`, `linux/arm64`) build, push, SBOM + provenance attestations, keyless **cosign**
   signature. Only the runtime stage's `apt-get` runs under QEMU for amd64; the Python stages
   cross-build natively.
6. **github-release**: creates or updates the release with the distributions.

## One-time setup

1. PyPI trusted publishers (done 2026-11-03), owner `SirCypkowskyy`, repository `ExactDocs`,
   workflow `release.yml`: `exactdocs-kernel` with environment `pypi`, `exactdocs` with
   environment `pypi-exactdocs`. PyPI allows only one pending publisher per
   repository + workflow + environment, hence two environments and two publish jobs.
2. GitHub environments `pypi` and `pypi-exactdocs` exist and accept deployments from tags `v*`
   only. Optionally add yourself as a required reviewer on both.
3. After the first image push, set the ghcr.io package visibility (private by default) and link it
   to the repository.
