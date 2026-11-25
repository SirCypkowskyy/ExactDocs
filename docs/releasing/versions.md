# Versions and tags

!!! abstract "TL;DR"
    - `MAJOR.MINOR.PATCH`, the same number on PyPI, ghcr.io and the git tag (`v` prefix on the tag
      only). MAJOR stays `0` until the project is declared stable.
    - Versions come from the git tag: nothing in the repository is edited to release.
    - A tag `vX.Y.Z` on `main` publishes a stable release; `vX.Y.Z.devN` on `develop` a dev
      pre-release. Any other shape, or the wrong branch, fails before anything is published.
    - Each image tag is published for three variants: base, `-ai` and `-local`.

## Versions (SemVer + PEP 440)

`MAJOR.MINOR.PATCH`, the same number on PyPI, ghcr.io and the git tag (`v` prefix on the tag only).

| Part | When it changes |
|---|---|
| **MAJOR** | only for breaking changes (MCP tool contracts, config variables, REST API, data format)[^major] |
| **MINOR** | new use cases / features |
| **PATCH** | fixes to the current minor, or small logic changes with no new use case |

[^major]: MAJOR stays `0` until we decide the project is stable. Bumping it is a deliberate
    decision, not part of a regular release.

- Package versions come from the git tag (`uv-dynamic-versioning`); nothing in the repo is edited
  to release.
- `exactdocs` pins `exactdocs-kernel==<same version>`.

## Tags and what they publish

| Tag | Must be on | PyPI | ghcr.io/sircypkowskyy/exactdocs | GitHub Release |
|---|---|---|---|---|
| `v0.1.3` | `main` | `exactdocs 0.1.3`<br/>`exactdocs-kernel 0.1.3` | `0.1.3`, `0.1`, `latest` | release, marked latest |
| `v0.1.3.dev2` | `develop` | `0.1.3.dev2` (pre-release) | `0.1.3.dev2`<br/>`0.1.3.dev2-<sha7>`<br/>`dev` | pre-release |

### Image variants

Every image tag is published three times, once per variant of `deploy/Dockerfile` (#246):

| Variant | Tag suffix | Examples |
|---|---|---|
| the base image | none | the tags above |
| `exactdocs[ai]` | `-ai` | `0.1.3-ai`, `latest-ai`, `dev-ai` |
| `exactdocs[ai,local]` with the default local models | `-local` | `0.1-local`, `0.1.3.dev2-<sha7>-local` |

See [Size and model-free budgets](images.md#size-and-model-free-budgets).

### Dev tags

- Dev tags use the PEP 440 developmental-release form `X.Y.Z.devN`, meaning "work towards X.Y.Z",
  so `0.1.3.dev2 < 0.1.3`.
- pip and `uvx exactdocs` ignore them unless asked (`uvx --prerelease allow exactdocs@0.1.3.dev2`).
- PyPI forbids local versions (`+sha`), so the commit is visible on the image tag and in the
  release instead.

!!! failure "Wrong tag shape or branch"
    Any other tag shape, or a tag on the wrong branch, fails the workflow before anything is
    published.

## Cutting a release

Before a stable release, run `just screenshots` on `develop` and merge the retaken pictures in
`docs/assets/screenshots/` if they changed (with their alt texts in the README and the docs, if
what they show changed). Then the README and the docs show the UI being released.

```bash
# stable
git switch main && git pull && git tag v0.1.3 && git push origin v0.1.3
# dev (rare)
git switch develop && git pull && git tag v0.1.3.dev1 && git push origin v0.1.3.dev1
```

Creating a release in the GitHub UI with a new tag works too: it pushes the tag, the workflow
runs, and it attaches the distributions to that release.

What the workflow then does is on [The release workflow](release-workflow.md).
