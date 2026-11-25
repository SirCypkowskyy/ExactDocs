# Branching, versioning and releases

!!! abstract "TL;DR"
    - Work goes from a `feature/*`, `bugfix/*`, `docs/*` or `chore/*` branch into `develop`
      (squash), then from `develop` into `main` (merge commit or rebase).
    - Versions are SemVer in PEP 440 form, taken from the git tag. A tag on `main` publishes a
      stable release, a tag on `develop` a dev pre-release, to PyPI and ghcr.io.
    - Updating never means importing everything again: the database migrates on start, and a
      search-index format change is rebuilt with `exactdocs reindex`.
    - Pull requests run the fast checks only. The integration tests run when started by hand, and
      the release runs the model-free eval gates, the size budgets and the image scans before it
      publishes. The full eval runs by hand (`eval.yml`).

## Pages

| Page | What it covers |
|---|---|
| [Branches](branching.md) | `main`, `develop` and issue branches, merge methods |
| [Versions and tags](versions.md) | SemVer + PEP 440, what each tag publishes, how to tag |
| [Upgrades and reindex](upgrades.md) | schema migrations, the search index format, the CI upgrade test |
| [Release notes template](release-notes.md) | how to edit the generated release notes |
| [Image budgets and retention](images.md) | size and model-free budgets per image variant, registry retention |
| [Licences](licences.md) | what carries which licence in the wheels, the UI and the images |
| [Image scan](image-scan.md) | the Trivy gate, and what to do when it fails |
| [Fast and integration tests](tests.md) | the CI jobs, integration tests and their services |
| [CI/CD and runners](runners.md) | GitHub-hosted runners, which job runs where, limits |
| [The release workflow](release-workflow.md) | every job of `release.yml`, dry runs, one-time setup |
