# ExactDocs task runner. `just` lists recipes; `just check` runs everything CI runs.
# Requires: uv, Node 26 + pnpm 12, Docker (for docker-*). Recipes are bash; on Windows they run
# in Git Bash at its default install path (plain `bash` there is usually WSL's).

set shell := ["bash", "-euo", "pipefail", "-c"]
set windows-shell := ["C:/Program Files/Git/bin/bash.exe", "-euo", "pipefail", "-c"]
set dotenv-load := true

image := "exactdocs:build"
web := "web"

# List recipes
default:
    @just --list --unsorted

# ---------------------------------------------------------------- setup

# Install Python (all groups) and web dependencies
setup:
    uv sync --all-groups
    cd {{ web }} && pnpm install

# ---------------------------------------------------------------- run

# Backend with auto-reload on :3000 (API, /mcp, and the UI if it was built)
serve *args:
    uv run exactdocs serve --reload {{ args }}

# MCP over stdio, as an agent would launch it
serve-stdio:
    uv run exactdocs serve --stdio

# Vite dev server on :5173, proxying /api and /mcp to :3000
web-dev:
    cd {{ web }} && pnpm dev

# Backend and web dev server together (Ctrl+C stops both)
dev:
    trap 'kill 0' EXIT; uv run exactdocs serve --reload & (cd {{ web }} && pnpm dev) & wait

# New Alembic revision in the one history owned by bootstrap: `just migration "add jobs table"`
migration message:
    uv run alembic -c packages/exactdocs/alembic.ini revision -m "{{ message }}"

# ---------------------------------------------------------------- quality

# Format Python and web code
fmt:
    uv run ruff format .
    uv run ruff check --fix .
    cd {{ web }} && pnpm format

# Lint without changing files (ruff, ty, biome, fallow, react-doctor)
lint:
    uv run ruff format --check .
    uv run ruff check .
    uv run ty check
    cd {{ web }} && pnpm lint

# Python tests: unit, in-process integration, architecture (pass extra pytest args; `just test -m eval`: the slow eval tests)
test *args:
    uv run pytest {{ args }}

# Python tests with the integration tests too: they need PostgreSQL, a search or vector server, Docker or the network, each named by an EXACTDOCS_TEST_<NAME>_URL (docs/releasing.md); `just test-integration -m integration`: only them
test-integration *args:
    uv run pytest --integration {{ args }}

# Refresh .test_durations, which CI's pytest shards are balanced by (the default suite, timed)
test-durations:
    uv run pytest --store-durations --clean-durations -q

# Architecture rules only (ArchUnitPython)
arch:
    uv run pytest packages/exactdocs/tests/architecture -q

# Acceptance scenarios (behave); e.g. `just bdd packages/exactdocs/features/search.feature`
bdd *args:
    uv run behave {{ args }}

# Acceptance scenarios with the @integration ones too (their services: docs/releasing.md); `just bdd-integration --tags=@integration`: only them
bdd-integration *args:
    EXACTDOCS_INTEGRATION=1 uv run behave {{ args }}

# Retrieval eval suite (runs on releases, not in CI): modes compared on the fixture docs repository (docs/evals.md); `just eval --help`
eval *args:
    uv run python packages/exactdocs/evals/run_retrieval_eval.py {{ args }}

# Golden set: fetch the pinned corpus and check every case's sections exist (docs/evals.md)
golden-validate *args:
    uv run python packages/exactdocs/evals/run_golden.py validate {{ args }}

# Golden set: fetch and import every pinned version with the real importer; records the commits
golden-import *args:
    uv run python packages/exactdocs/evals/run_golden.py import {{ args }}

# Ingestion benchmark: chunking configurations measured on the golden corpus, with BM25 recall (docs/evals.md)
ingestion-bench *args:
    uv run python packages/exactdocs/evals/run_ingestion_bench.py {{ args }}

# Retrieval benchmark: modes, models, rerankers and chunking measured on the golden set (docs/evals.md)
retrieval-bench *args:
    uv run python packages/exactdocs/evals/run_retrieval_bench.py {{ args }}

# Agent benchmark (never in CI): an agent with only the ExactDocs MCP tools answers the golden set (docs/evals.md); `just agent-bench run --offline`
agent-bench *args:
    uv run python packages/exactdocs/evals/run_agent_bench.py {{ args }}

# Benchmark pages (docs/benchmark/): refill their tables from evals/results/*.json and the golden set; `--check` fails when one is out of date
bench-pages *args:
    uv run python packages/exactdocs/evals/run_bench_pages.py {{ args }}

# Web unit tests (vitest)
web-test:
    cd {{ web }} && pnpm test

# Regenerate web/openapi.json from the app, then the web's TypeScript types from it (commit both)
api:
    uv run python -c "import tempfile; from pathlib import Path; from exactdocs.bootstrap.container import Container; from exactdocs.bootstrap.http import create_app; from exactdocs.bootstrap.rest import v1_openapi_json; from exactdocs.bootstrap.settings import Settings; print(v1_openapi_json(create_app(Container.build(Settings(data_dir=Path(tempfile.mkdtemp()))))), end='')" > {{ web }}/openapi.json
    cd {{ web }} && pnpm gen:api

# Regenerate docs/schemas/exactdocs.sources.schema.json from the sources file's model (commit it)
sources-schema:
    uv run python -c "import json; from exactdocs.ingestion.dtos import sources_json_schema; print(json.dumps(sources_json_schema(), indent=2))" > docs/schemas/exactdocs.sources.schema.json

# Everything CI runs, in CI order
check: lint test bdd web-test web-build docs-build

# ---------------------------------------------------------------- build

# Production build of the web UI into web/dist
web-build:
    cd {{ web }} && pnpm build

# Wheels + sdists for both packages, UI bundled; version from git unless given: `just build 0.2.0`
build version="": web-build
    rm -rf packages/exactdocs/src/exactdocs/_web dist
    cp -r {{ web }}/dist packages/exactdocs/src/exactdocs/_web
    if [ -n "{{ version }}" ]; then export UV_DYNAMIC_VERSIONING_BYPASS="{{ version }}"; fi;       uv build --all-packages --out-dir dist

# Build the Docker image for the local platform: variant base, ai or local (tag exactdocs:build, -ai, -local)
docker-build version="0.0.0.dev0" variant="base":
    docker build -f deploy/Dockerfile --target {{ variant }} --build-arg VERSION={{ version }} \
      -t {{ image }}{{ if variant == "base" { "" } else { "-" + variant } }} .

# Check a built variant's size budget, packages and models, as CI does (docs/releasing.md)
docker-check variant="base":
    python3 deploy/check_artifacts.py image {{ image }}{{ if variant == "base" { "" } else { "-" + variant } }} {{ variant }}

# Run the local image on :3000 with a named data volume, hardened like CI and the Team compose example
docker-run: docker-build
    docker run --rm -it -p 3000:3000 -v exactdocs-data:/data --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges {{ image }}

# ---------------------------------------------------------------- docs

# Live preview of the documentation site on :8000
docs:
    uv run --only-group docs zensical serve

# Build the documentation site into site/ (strict, like CI)
docs-build:
    pnpm --dir deploy/mermaid-check install --frozen-lockfile
    pnpm --dir deploy/mermaid-check check
    uv run --only-group docs zensical build --clean --strict

# ---------------------------------------------------------------- repo

# Sync GitHub labels from .github/labels.yml
labels:
    .agents/skills/working-on-issues/scripts/sync-labels.sh

# Show whether an issue can be claimed (see .agents/skills/claiming-issues)
issue-status number:
    .agents/skills/claiming-issues/scripts/status.sh {{ number }}

# Tag a release on the current branch after checks: `just release 0.2.0` (main) or `0.2.0.dev1` (develop)
release version: check
    case "{{ version }}" in *.dev*) want=develop ;; *) want=main ;; esac;       branch=$(git rev-parse --abbrev-ref HEAD);       [ "$branch" = "$want" ] || { echo "v{{ version }} must be tagged on $want, not $branch" >&2; exit 1; };       git fetch origin "$want" --quiet;       [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$want")" ] || { echo "local $want differs from origin/$want" >&2; exit 1; }
    git tag -a "v{{ version }}" -m "v{{ version }}"
    git push origin "v{{ version }}"
    @echo "Release workflow: gh run list --workflow release.yml --limit 1"

# Remove build outputs and caches
clean:
    rm -rf dist site reports {{ web }}/dist packages/exactdocs/src/exactdocs/_web .pytest_cache .ruff_cache

# Browser end-to-end test against `uv run exactdocs serve` (builds the UI into the package first)
e2e: web-build
    rm -rf packages/exactdocs/src/exactdocs/_web
    cp -r {{ web }}/dist packages/exactdocs/src/exactdocs/_web
    cd e2e && pnpm install --frozen-lockfile && pnpm exec playwright install chromium && python3 run.py
