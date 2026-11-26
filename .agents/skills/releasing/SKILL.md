---
name: releasing
description: Use when cutting an ExactDocs release or dev build, choosing the next version number, or debugging the release workflow.
---

# Releasing

Full policy: `docs/releasing/` (start at `docs/releasing/index.md`). Only do this when a human asked for a release.

## Pick the version

Look at what merged since the last tag (`git log $(git describe --tags --abbrev=0)..origin/main --oneline`):

- any new use case / feature → bump **minor**, reset patch (`0.3.4` → `0.4.0`)
- only fixes or small logic changes → bump **patch** (`0.3.4` → `0.3.5`)
- breaking change → **major**, but only with explicit maintainer approval; while pre-1.0 the
  default is to ship breaking changes as minor and call them out in the release notes

## Cut it

```bash
# stable, from main (after develop -> main is merged)
git switch main && git pull --ff-only
git tag v0.4.0 && git push origin v0.4.0

# dev build, from develop (rare): X.Y.Z.devN where X.Y.Z is the *next* stable version
git switch develop && git pull --ff-only
git tag v0.4.0.dev1 && git push origin v0.4.0.dev1
```

Watch it: `gh run watch $(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')`.

## Dry run first

`gh workflow run release.yml --ref develop` runs everything but the publishing (version
`0.0.0.dev<run number>`; no PyPI, no ghcr.io push, no GitHub Release). Do it before tagging when the
release workflow, the Dockerfile, the eval or a dependency changed: the eval and the arm64 size
budgets and scans do not run on pull requests. The release runs only the model-free eval gates;
before a release that touches retrieval or chunking, run the full eval with
`gh workflow run eval.yml --ref develop`. It leaves out the integration and end-to-end jobs
unless started with `-f integration=true`, which only a maintainer does, never an agent (#554).

## Runners

CI runs on our GCP self-hosted runners `[self-hosted, linux, ARM64, exactdocs, gcp]`
(docs/decisions/ci-runners.md, docs/releasing/runners.md *CI/CD and runners*). The repository
variable `RUNNER_MODE` is `self-hosted`: every job of a trusted run on those runners (amd64 images
cross-built, checked with `check_artifacts.py --no-python`; CI skips Pinecone Local). `hybrid`
(any other value, or unset) moves CI, the docs and the release's amd64 and publishing jobs to
`ubuntu-24.04`. A fork's pull request always runs on `ubuntu-24.04`. Every new self-hosted
`runs-on` uses exactly that label set (`tests/ci/test_runners.py`). Never change the variable or
the runners yourself: tell the maintainer.

## If it fails

- A tag runs the workflow file **of the tagged commit**, and *Re-run* reuses it: after a workflow
  fix, release from a new tag on a commit that has the fix, never by re-running the old run.
- **"neither vX.Y.Z nor vX.Y.Z.devN"** or **"must point at a commit on main/develop"**: wrong tag.
  Delete it (`git push origin :refs/tags/vX` and `git tag -d vX`) and tag the right commit.
  Never delete a tag whose packages already reached PyPI; PyPI versions are immutable. Bump instead.
- **PyPI 403 / invalid-publisher**: the trusted publisher on PyPI or the `pypi` / `pypi-exactdocs` environment is
  missing (see docs/releasing/release-workflow.md, one-time setup).
- Re-run only failed jobs: `gh run rerun <id> --failed`.
