# Branches

!!! abstract "TL;DR"
    - `main` holds released code, `develop` is the integration branch, and every issue gets its
      own branch from `develop`.
    - Issue branches are squashed into `develop`: one commit per issue.
    - `develop` goes into `main` by merge commit or rebase, keeping the squashed history.
    - Repository rulesets enforce the merge methods on every PR into a branch.

| Branch | Purpose | Protection |
|---|---|---|
| `main` | released code; every commit is releasable | no deletion, no force-push<br/>changes only through a PR, merged with **merge commit** or **rebase** |
| `develop` | integration branch; feature branches merge here | no deletion, no force-push<br/>changes only through a PR, merged with **squash** |
| `feature/<issue>-<slug>`<br/>`bugfix/<issue>-<slug>`<br/>`docs/<issue>-<slug>`<br/>`chore/<issue>-<slug>` | one issue each, from `develop` | none |

## The flow

1. `feature/12-version-filter` → PR into `develop` (squash: one commit per issue).
2. PR `develop` → `main` (merge commit or rebase, keeping the squashed history).
3. Tag on `main`.

```mermaid
gitGraph
    commit id: "v0.1.1" tag: "v0.1.1"
    branch develop
    checkout develop
    branch "feature/12-version-filter"
    commit id: "work"
    commit id: "tests"
    checkout develop
    merge "feature/12-version-filter" id: "squash: one commit per issue"
    branch "docs/123-mvp1-docs"
    commit id: "docs"
    checkout develop
    merge "docs/123-mvp1-docs" id: "squash"
    commit id: "v0.2.0.dev1" tag: "v0.2.0.dev1"
    checkout main
    merge develop id: "release PR (merge or rebase)" tag: "v0.2.0"
```

The branch names in the graph are examples.

- `feature/*`, `bugfix/*`, `docs/*` and `chore/*` branches are squashed into `develop`.
- `develop` is merged (or rebased) into `main`.
- A tag on `develop` publishes a dev pre-release, a tag on `main` a stable release
  ([Versions and tags](versions.md)).
- The registry then keeps only the newest images ([Image retention](images.md#image-retention)).

## Merge methods

The merge methods are enforced by repository rulesets on the target branch, so they apply to every
PR into it, whatever the source branch. A rare `main` → `develop` back-merge is squashed too.
