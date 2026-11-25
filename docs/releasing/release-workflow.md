# The release workflow

!!! abstract "TL;DR"
    - `.github/workflows/release.yml` validates the tag, runs the retrieval eval, builds the UI and
      the Python distributions, and publishes them to PyPI with trusted publishing.
    - Each image variant is built, budget-checked and scanned on both architectures. Images are
      pushed only when all six scans and the eval pass, then joined into signed multi-arch indexes.
    - A tag runs the workflow file of the tagged commit: release a fix from a new tag.
    - A manual run is a dry run that publishes nothing. Run one before tagging when the workflow,
      the Dockerfile, the eval or a size budget changed.

## What the release workflow does

`.github/workflows/release.yml` (runners: [CI/CD and runners](runners.md)):

1. **meta**: validates tag shape and branch, derives version/channel.
2. **eval**: the retrieval eval ([Retrieval evals](../evals/suite.md#when-it-runs)), which pull
   requests do not run:
    - the model-free gates on SQLite and on ParadeDB's pg_search, against the `baseline.json` of
      the tagged tree;
    - the suite's end-to-end tests (`pytest -m eval`);
    - the ingestion and retrieval benchmarks against their recorded runs;
    - then hybrid and rerank on the default local models, report-only.

    `pypi-kernel` and `image` need it, so a failing gate publishes nothing.

    **integration** (`integration.yml`, [Fast and integration tests](tests.md)) runs only in a dry
    run started with the input `integration` ([Dry run](#dry-run)). A tag push skips it, and no job
    needs it. It covers:

    - the integration pytest and behave suites on PostgreSQL, PgBouncer, Supabase, libSQL and
      every search and vector server (on the self-hosted runner, so Pinecone Local's cases skip
      there);
    - the Docker images' build, scan and smoke tests;
    - uvx, the upgrade from the previous release and the browser end-to-end test.
3. **web**: `pnpm build`.
4. **python**: bundles the UI into the wheel, `uv build --all-packages`, `twine check`, runs the
   wheel the way `uvx` would.
5. **pypi-kernel**, then **pypi**: `uv publish` with **trusted publishing** (OIDC, no stored token).
6. **image-scan** (six jobs: `base`, `ai`, `local` × `amd64`, `arm64`):
    - each variant is built natively on a runner of its architecture (`ubuntu-24.04`, the
      self-hosted ARM64 runner; in `self-hosted` mode amd64 is cross-built there and checked with
      `--no-python`);
    - checked against its size budget (`deploy/check_artifacts.py`);
    - and scanned (see [Image scan](image-scan.md)).

    So both architectures are checked and scanned, not only the build host's.
7. **image** (the same six), only when all six scans and the eval pass:
    - each is built again from the scan's cache. The build arguments are the same
      (`DEBIAN_REFRESH`, the date, and `CREATED` are set once in **meta**), so these are the
      layers that were scanned;
    - with SBOM + provenance attestations;
    - pushed **by digest only**, without a tag.
8. **image-publish**, once per variant: `docker buildx imagetools create`
    - joins the amd64 and arm64 images (with their attestations) into one multi-arch index;
    - tags it (suffix `-ai` / `-local`);
    - puts the title, description and licenses on it as annotations;
    - checks it holds exactly `linux/amd64` and `linux/arm64`;
    - signs it with a keyless **cosign** signature.

    In `hybrid` mode nothing runs under QEMU; in `self-hosted` mode the amd64 legs use it for the
    runtime stage's `apt-get` only.
9. **github-release**: creates or updates the release with the distributions.

!!! warning "The workflow file of the tagged commit"
    Pushing a tag runs the workflow file **of the tagged commit**, and so does *Re-run jobs* on an
    old run. A tag made before a workflow fix keeps failing the old way. Release from a new tag on
    a commit that has the fix.

## Dry run

A manual run is a dry run, from any branch, and publishes nothing:

```bash
gh workflow run release.yml --ref develop     # or a feature branch with workflow changes
```

| In a dry run | Jobs |
|---|---|
| runs | **meta** (without the tag checks), **eval**, **web**, **python** and all twelve image jobs (the six **image** builds with `push=false`, no registry login) |
| skipped (`if: github.event_name == 'push'`) | **pypi-kernel**, **pypi**, **image-publish**, **github-release** |
| with the input `integration` | **integration** too: the integration and end-to-end jobs, with the Python job on the self-hosted runner |

It builds version `0.0.0.dev<run number>`.

- With `integration`: `gh workflow run release.yml --ref develop -f integration=true`. No other job
  waits for the integration jobs; when one fails, the run fails.
- GHCR retention still starts after it (a `workflow_run` trigger fires on every completed Release
  run, from the file on the default branch) but skips its jobs when the run was not a tag push.

!!! tip "When to run one"
    Run one before tagging when the release workflow, the Dockerfile, the eval or a size budget
    changed. The gates that pull requests do not run (the eval, arm64 budgets and scans) fail here
    instead of on the tag.

What it cannot check:

- the publishing itself (PyPI trusted publishing, the index, the signature);
- the other runner mode: it runs on the runners of the current `RUNNER_MODE`, so a dry run in
  `hybrid` mode does not exercise the cross-built amd64 legs of `self-hosted` mode.

## One-time setup

1. **PyPI trusted publishers** (done 2026-11-03): owner `SirCypkowskyy`, repository `ExactDocs`,
   workflow `release.yml`.

    | Project | Environment |
    |---|---|
    | `exactdocs-kernel` | `pypi` |
    | `exactdocs` | `pypi-exactdocs` |

    PyPI allows only one pending publisher per repository + workflow + environment, hence two
    environments and two publish jobs.
2. **GitHub environments** `pypi` and `pypi-exactdocs` exist and accept deployments from tags `v*`
   only. Optionally add yourself as a required reviewer on both.
3. **ghcr.io package**: after the first image push, set the package visibility (private by
   default) and link it to the repository.
