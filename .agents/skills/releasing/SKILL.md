---
name: releasing
description: Use when cutting an ExactDocs release or dev build, choosing the next version number, or debugging the release workflow.
---

# Releasing

Full policy: `docs/releasing.md`. Only do this when a human asked for a release.

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

## If it fails

- **"neither vX.Y.Z nor vX.Y.Z.devN"** or **"must point at a commit on main/develop"**: wrong tag.
  Delete it (`git push origin :refs/tags/vX` and `git tag -d vX`) and tag the right commit.
  Never delete a tag whose packages already reached PyPI; PyPI versions are immutable. Bump instead.
- **PyPI 403 / invalid-publisher**: the trusted publisher on PyPI or the `pypi` environment is
  missing (see docs/releasing.md, one-time setup).
- Re-run only failed jobs: `gh run rerun <id> --failed`.
