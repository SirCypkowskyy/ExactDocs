# Upgrades, migrations and "requires reindex"

!!! abstract "TL;DR"
    - Updating must never mean importing everything again (RUN-04).
    - Schema changes are Alembic revisions that run on start and keep the data.
    - A change to how the search index is built bumps `FORMAT`. The old index keeps answering
      until `exactdocs reindex` rebuilds it from the stored chunks, with nothing fetched again.
    - The CI upgrade test starts the newest stable release from PyPI, then this build on the same
      data directory, and checks it serves the same libraries, articles and search results.

## Two mechanisms

### Schema migrations run on start

- Every schema change is an Alembic revision (`bootstrap/migrations/versions`).
- `exactdocs serve` brings the database to the head before it answers.
- A revision must keep the data: a new column gets a default or is filled from what is stored,
  never "re-import to get it".

### The search index records its format

The format is `retrieval_search_format`, `FORMAT` in `retrieval/adapters/driven/sqlite_fts.py`. A
change to how index entries are made from chunks (tokenizer, `identifier_tokens`, what goes in
which column) bumps `FORMAT`. Then:

- the old index keeps answering as it was built;
- the server logs a warning, and `/api/health` says `"reindex_required": true`;
- the release notes have a **Requires reindex** section ([Release notes template](release-notes.md)).

`exactdocs reindex` rebuilds the index:

- run it where the server runs, e.g. `docker exec exactdocs exactdocs reindex`;
- it rebuilds the index from the stored chunks into a second table while the old one keeps
  answering, then swaps them in one transaction;
- nothing is fetched or imported again.

!!! note "Column changes"
    A change of the index's *columns* is an Alembic revision that rebuilds the table on start
    instead, because the search queries name them.

## The CI upgrade test

The integration job *uvx* runs `deploy/upgrade_check.py`. It runs when the integration jobs are
started by hand (see [Fast and integration tests](tests.md#when-ci-runs-them)).

1. The newest stable release from PyPI starts on an empty data directory and imports the fixture
   docs repository at two tags.
2. This build starts on the same directory. It must migrate it to its head revision and serve the
   same libraries, articles and search results to the same API token.
3. Last, `exactdocs reindex` runs while that server keeps answering searches.

Run it locally with `python3 deploy/upgrade_check.py` (`--previous X.Y.Z` to pick the release).

!!! info "Yanked releases"
    A yanked release still counts and still installs (0.1.0 to 0.2.0 should be yanked, #533).
    The check pins both `exactdocs==X.Y.Z` and `exactdocs-kernel==X.Y.Z` itself, because uv takes
    a yanked version only for an exact pin the user gives, not for one in another package's
    metadata.

### The in-process half

The behave scenario *Upgrading keeps the libraries* (`features/upgrade.feature`) is its in-process
half: it takes the schema back to the previous release's head revision.

After tagging a stable release, move `PREVIOUS_RELEASE` and `PREVIOUS_REVISION` in
`features/steps/upgrade_steps.py` to it. The head is:

```bash
uv run python -c "from alembic.script import ScriptDirectory; from exactdocs.bootstrap.database import alembic_config; print(ScriptDirectory.from_config(alembic_config()).get_current_head())"
```
