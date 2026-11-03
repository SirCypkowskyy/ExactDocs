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

## What the release workflow does

`.github/workflows/release.yml`, on the self-hosted GB10 runners:

1. **meta**: validates tag shape and branch, derives version/channel.
2. **web**: `pnpm build`.
3. **python**: bundles the UI into the wheel, `uv build --all-packages`, `twine check`, runs the
   wheel the way `uvx` would.
4. **pypi-kernel**, then **pypi**: `uv publish` with **trusted publishing** (OIDC, no stored token).
5. **image**: multi-arch (`linux/amd64` emulated, `linux/arm64` native) build, push, SBOM +
   provenance attestations, keyless **cosign** signature.
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
