# Background jobs

!!! abstract "TL;DR"

    - Long tasks (imports, syncs, GC) are **jobs** of the `ingestion` domain, never work done inside
      a request.
    - Every job is one **DBOS** durable workflow. A killed job resumes at its first unfinished step
      on the next start.
    - On SQLite one process runs jobs. On PostgreSQL any number of servers share the queue, each
      under an executor slot held by an advisory lock, with a watchdog and adoption of abandoned
      slots.
    - Scheduled checks (SYNC-02) and push webhooks (TEAM-03) only queue jobs.

Long tasks (imports, syncs, GC) are **jobs** of the `ingestion` domain, never work done inside a
request. A `Job` has:

- a kind, a library (and optionally a version);
- a state: `queued`, `running`, `succeeded`, `failed`;
- `done`/`total` files, per-file problems (path, reason), an error and timestamps.

`GET /api/v1/jobs/{id}` and `GET /api/v1/libraries/{owner}/{repo}/jobs` read them.

## Pages

| Page | What it covers |
|---|---|
| [Several processes on PostgreSQL](postgresql.md) | several processes on one queue, executor slots, the watchdog, upgrades |
| [The scheduled check and push webhooks](triggers.md) | the scheduled check and automatic tag imports, push webhooks |

## Kinds

| Kind | What it does |
|---|---|
| `import` | a version's first import |
| `refresh` | a re-sync of a branch version that moved, or the confirmed re-import of a moved tag;<br/>reuses unchanged chunks, fails with `not_found` if the version was removed meanwhile |
| `reprocess` | every version of a library re-imported at its commit after its paths were edited<br/>(`version` is null) |
| `rechunk` | every version cut again from its stored text after its chunking was edited<br/>(see [Per-library chunking](../import/chunking.md#per-library-chunking-e4-05)) |
| `retag` | every version re-tagged from its stored articles after only its tag rules were edited[^retag] |
| `collect` | frees content nothing uses after a removal |
| `embed` | one version embedded with the instance's embedding model, a durable step per batch[^embed] |
| `push` | the refs a push webhook routed (see [Push webhooks](triggers.md#push-webhooks-team-03)) |

[^retag]: ../The catalog switches each version in one transaction and the search index's tag copies
    follow right after, as for manual tags.

[^embed]: ../Given an `embedder`, `IngestionModule.build` registers it and makes `import`, `refresh`,
    `reprocess` and `rechunk` queue the `embed` jobs of their library when they succeed. The
    composition root queues the missing ones on start.

- A job queued from inside a running job is queued outside its workflow's context, so it is a
  workflow of its own.
- **Kinds are registered, not hard-coded.** `IngestionModule.build(handlers=..., recovery_hooks=...)`
  maps a kind to the `JobHandler` that runs it and, optionally, a `RecoveryHook`.
- Handlers report through a `JobProgress` port; every report is stored at once.
- Raising fails the job. A domain error's message is shown to users; anything else only as
  `unexpected <ErrorType>` (details go to the log).

## The worker is DBOS

DBOS runs durable workflows (`ingestion/adapters/driving/dbos_worker.py`), started in the app
lifespan (`Container.running()`).

- Every job is one DBOS workflow whose ID is the job's ID and whose body is the `RunJob` driving
  port.
- `EnqueueJob` stores the job, then hands it to the `JobRunner` driven port
  (`adapters/driven/dbos.py` queues the workflow by name).
- The queue runs two jobs at once and one per library: the library is its partition key.
- Where DBOS keeps its workflows and their steps:
    - on SQLite, its own file, `<data dir>/jobs.sqlite`;
    - on PostgreSQL, the schema `EXACTDOCS_DBOS_SYSTEM_SCHEMA` (`dbos`) of the app's own database.
      `system_database_url` is the app's URL, so DBOS never runs `CREATE DATABASE`. It still first
      connects to `postgres` to check that the database exists, and only logs a warning when the
      role may not.
- The `ingestion_jobs` table stays what the API reads.
- DBOS is imported only by ingestion's adapters and `bootstrap` (architecture test).

### Durable steps

- A handler marks its steps with the `Checkpoints` driven port (`step(name, run)`, DBOS steps in
  production, `InMemoryCheckpoints` in tests).
- A completed step's result is stored, and a resumed job gets it back without running the step
  again.
- `STEPS_VERSION` (the DBOS application version) changes when a job's steps do. A workflow of
  another version is not resumed; its job starts over.

!!! warning "Rules for a handler"

    A handler must take the same steps in the same order on every run, and keep each step safe to
    run twice.

### Restart

- Stopping the app lets running jobs finish for a second, then cancels them: the job stays
  `running` and its workflow pending.
- A process killed outright (`kill -9`, OOM, a deploy) leaves the same state.
- On the next start DBOS resumes the pending workflows. `RunJob`:
    1. finds the job `running`;
    2. runs its kind's recovery hook (the import's discards a pending manifest the interrupted step
       may have left);
    3. resets its progress and runs the handler, whose completed steps are replayed from the stored
       results.
- Every other unfinished job (`RecoverJobs`) gets its hook, is queued again from the beginning and
  submitted. Examples: a job `running` without a workflow (one the in-process worker of an earlier
  release left behind), or one queued while no worker ran.
- Workflows that ended, or of another `STEPS_VERSION`, are deleted at start.
- A job's workflow is deleted when it ends (its steps hold the whole text of an import).
- A hook that raises fails its job instead of blocking the start.

### Polling

- DBOS looks for a queued job to start every `EXACTDOCS_JOB_POLL_SECONDS` (1 s), so an idle server
  costs next to nothing; a job starts within about that long.
- Every 30 s the worker hands the queued jobs to DBOS again (`SubmitQueuedJobs`; queuing an ID it
  already has is a no-op), so a job DBOS did not take when it was queued still runs without a
  restart.
- The test suites lower the interval.

### DBOS's own environment

DBOS reads `DBOS__CLOUD`, `DBOS__VMID` and `DBOS__APPVERSION` from the environment.

!!! danger "Leave `DBOS__*` unset"

    `DBOS__CLOUD=true` turns its local recovery off (jobs would no longer resume), and the other two
    change the executor and the version that recovery matches.

ExactDocs sets the version itself (`STEPS_VERSION`), opens no DBOS Conductor connection (no key is
configured) and keeps DBOS's logs at warnings.

## One process runs jobs on SQLite

- Only the HTTP server starts the worker (`serve --stdio`, `reindex` and the account commands do
  not), and DBOS allows one worker per process.
- On SQLite `serve` pins uvicorn to one worker (`workers=1`, whatever `WEB_CONCURRENCY` says).
- DBOS runs as its one `local` executor, and `TagLocks` orders re-tags within the process.

## Running jobs one at a time in tests

`RunNextJob` (claim the oldest queued job whose library has none running, in one atomic statement,
and run it inline) remains for tests that drive jobs one at a time.
