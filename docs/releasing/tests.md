# Fast and integration tests

!!! abstract "TL;DR"
    - Pull requests and pushes to `develop` and `main` run the fast checks only (#507): parallel
      jobs with no service container and no image build.
    - Integration tests need a container, a service, the network or a download. pytest marks them
      `integration`, behave tags them `@integration`, and both leave them out by default.
    - `--integration` or `EXACTDOCS_INTEGRATION=1` turns them on. Each then runs when its
      service's `EXACTDOCS_TEST_<NAME>_URL` is set.
    - In CI they run only when someone starts them by hand (#554), never from a pull request, push
      or tag. Agents never start them.

## The fast checks

The fast checks are the parallel jobs of `ci.yml`:

| Job | What it runs |
|---|---|
| *Lint (ruff, ty, hadolint)* | `ruff format --check`, `ruff check`, `ty check`, hadolint on `deploy/Dockerfile` |
| *pytest (1/6)* … *(6/6)* | `uv run pytest` in six groups of about the same time[^pytest]; each writes its coverage data |
| *behave (1/3)* … *(3/3)* | `uv run behave`, every scenario but the `@integration` ones, the feature files in three groups of about the same time[^behave] |
| *Python (ruff, ty, pytest, behave)* | waits for the jobs above and fails unless all passed; combines the shards' coverage into one report |
| *Web (biome, fallow, react-doctor, vitest, build)* | the web client |

[^pytest]: Split by [pytest-split](https://github.com/jerry-git/pytest-split) from the durations
    in `.test_durations`; two groups in `self-hosted` mode.

[^behave]: `deploy/behave_shards.py`, from the times in `.behave_durations`; one group in
    `self-hosted` mode.

*Python (ruff, ty, pytest, behave)* is the check branch protection requires. The coverage total is
in the job summary, and the data in the `python-reports` artifact.

### Durations

- **`.test_durations`** holds the time of every fast test, from a default run with
  `--store-durations`.
- **`.behave_durations`** holds the time of every feature file.
- The shards are balanced by them, and a test or feature they do not know counts as the average.
- Refresh them with `just test-durations` and `just bdd-durations` (and commit them) when many
  tests were added or a shard runs much longer than the others.

## Integration tests

Integration tests are the ones that need a container, a service, the network or a download:

- PostgreSQL (with pg_search, pgvector, PgBouncer, Supabase);
- libSQL servers;
- every search or vector server (Elasticsearch, OpenSearch, Qdrant, Chroma, Redis, MongoDB,
  Milvus, Pinecone, Azure AI Search);
- the default local models.

pytest marks them `integration` and behave tags them `@integration`. Both leave them out by
default, and the run ends saying how many it left out and how to run them.

### How they are marked

Most are marked from what they take, so none is missed by hand
(`packages/exactdocs/tests/fixtures/integration.py`):

- a test on `on_postgres`, or a PostgreSQL case of `SQL_BACKENDS` / `SEARCH_BACKENDS`;
- every server case of `index_backends.BackendCase`.

A behave scenario with a service tag (`@postgres`, `@qdrant` …) must also carry `@integration`, or
the run stops.

Two checks prove the default:

- A test (`tests/ci/test_integration_tests.py`): with every service variable set, a default run
  collects no test that is marked, takes a service fixture or runs on a server case.
- The fast CI jobs set every `EXACTDOCS_TEST_<NAME>_URL` to a port where nothing listens, so a test
  that reached a service without the marker would fail there, not skip.

### Turning them on

| Switch | Where |
|---|---|
| `--integration` | pytest |
| `EXACTDOCS_INTEGRATION=1` | pytest and behave |
| `just test-integration`, `just bdd-integration` | set it |
| `-m integration`, `--tags=@integration` | narrow a run to them |

Then each runs when its service's variable is set, and is skipped, naming the variable, when it is
not. `EXACTDOCS_REQUIRE_<NAME>=1` turns that into an error, as CI does.

```bash
export EXACTDOCS_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1/postgres  # may create databases
export EXACTDOCS_TEST_MILVUS_URL=$(deploy/milvus-test-server.sh exactdocs-milvus)
just test-integration -m integration           # pytest: only the integration tests
just bdd-integration --tags=@integration       # behave: only the @integration scenarios
```

### Service variables

CI's pinned images are in `.github/workflows/integration.yml`.

| Variable | Service |
|---|---|
| `EXACTDOCS_TEST_POSTGRES_URL`<br/>`EXACTDOCS_TEST_PG_SEARCH=1` | a PostgreSQL role that may create databases and roles; `pg_search` when the server has it (ParadeDB) |
| `EXACTDOCS_TEST_PGBOUNCER_URL` | PgBouncer in transaction mode in front of that server |
| `EXACTDOCS_TEST_SUPABASE_URL` | `deploy/supabase-test-db.sh` |
| `EXACTDOCS_TEST_LIBSQL_URL`, `_AUTH_TOKEN` | `deploy/libsql-test-server.sh` (the index backend) |
| `EXACTDOCS_TEST_LIBSQL_DATABASE_URL`, `_AUTH_TOKEN` | another, empty libSQL server (ExactDocs' own database; the SQLite cases move there) |
| `EXACTDOCS_TEST_MILVUS_URL` | `deploy/milvus-test-server.sh` |
| `EXACTDOCS_TEST_QDRANT_URL` (`_API_KEY`)<br/>`_ELASTICSEARCH_URL`, `_OPENSEARCH_URL`<br/>`_CHROMA_URL`, `_REDIS_URL`<br/>`_MONGODB_URL`, `_PINECONE_URL` | the server of that name ([Configuration](../configuration.md)) |
| `EXACTDOCS_TEST_AZURE_SEARCH_URL` | a real Azure AI Search service (the manual `azure-search.yml`) |
| `EXACTDOCS_TEST_MODELS_DIR` | the default local models, pulled by `exactdocs models pull` (the release's eval job) |

## When CI runs them

The jobs are in `integration.yml`:

- the integration pytest and behave suites, with every service above as a container (and the
  ranking suite on Supabase, the persistence suite on libSQL);
- the Docker image build, scan and smoke tests, and the `-ai` and `-local` variants;
- uvx, with the upgrade check and the browser end-to-end test.

One run takes 45 to 60 minutes of runner time, so they run only when someone starts them by hand
(#554), on the branch they pick:

| Start | How |
|---|---|
| a manual run of CI with the input `integration` | *Actions → CI → Run workflow*, or `gh workflow run ci.yml --ref <branch> -f integration=true` |
| a manual run of Integration itself, on the same runners as from CI | *Actions → Integration → Run workflow*, or `gh workflow run integration.yml --ref <branch>` |
| a release dry run with the input `integration`, with the Python job on the self-hosted runner, where the eval runs ([Dry run](release-workflow.md#dry-run)) | *Actions → Release → Run workflow*, or `gh workflow run release.yml --ref <branch> -f integration=true` |

!!! warning "Who starts them"
    - No pull request, push or tag starts them, whatever its labels, and a release does not wait
      for them.
    - A maintainer starts them when a change touches PostgreSQL, an index backend on a server, the
      Dockerfile, the wheel or the end-to-end flow, or before tagging a release that has such
      changes.
    - Agents never start them.

Locally, `just test --integration` (pytest) and `EXACTDOCS_INTEGRATION=1` (pytest and behave) run
the same tests against the services you start, as above.
