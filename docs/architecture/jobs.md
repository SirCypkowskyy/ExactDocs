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

## Kinds

| Kind | What it does |
|---|---|
| `import` | a version's first import |
| `refresh` | a re-sync of a branch version that moved, or the confirmed re-import of a moved tag;<br/>reuses unchanged chunks, fails with `not_found` if the version was removed meanwhile |
| `reprocess` | every version of a library re-imported at its commit after its paths were edited<br/>(`version` is null) |
| `rechunk` | every version cut again from its stored text after its chunking was edited<br/>(see [Per-library chunking](import.md#per-library-chunking-e4-05)) |
| `retag` | every version re-tagged from its stored articles after only its tag rules were edited[^retag] |
| `collect` | frees content nothing uses after a removal |
| `embed` | one version embedded with the instance's embedding model, a durable step per batch[^embed] |
| `push` | the refs a push webhook routed (see [Push webhooks](#push-webhooks-team-03)) |

[^retag]: The catalog switches each version in one transaction and the search index's tag copies
    follow right after, as for manual tags.

[^embed]: Given an `embedder`, `IngestionModule.build` registers it and makes `import`, `refresh`,
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

## Several processes on PostgreSQL

`serve` lets `WEB_CONCURRENCY` decide, and any number of servers may share the database. Each
process runs DBOS on the shared queue: DBOS claims a queued workflow in one transaction, so a job
runs once, and the partition limit of one per library holds across processes.

### Executor slots

Each process runs under an **executor slot** (`bootstrap/executors.py`):

- the lowest slot `n` whose two-key advisory lock (`EXECUTOR_LOCKS`, `n`) is free gives the executor
  ID `exactdocs-<n>`;
- the lock is held by a connection of its own (not the pool), with TCP keepalives
  (`SLOT_KEEPALIVES`), for the process's lifetime;
- a process that dies releases it. The next one to start takes the lowest free slot, often the
  same, waits `claim_grace` (15 s, logged) if that executor left pending workflows, and DBOS resumes
  them.

### Watchdog

A connection can die while its process lives (a failover, a NAT timeout, `idle_session_timeout`),
which frees the slot.

- **The check.** Every 2 s (`slot_check_interval`) the worker checks in `pg_locks` that its own
  backend still holds the slot.
    - The whole check is bounded by 1.5 s (`slot_check_timeout`; the slot connection also has
      `tcp_user_timeout`), so a host that stopped answering cannot hold the check.
    - If the slot is free, the worker takes it again, and goes on only if every job it runs is still
      its own pending workflow. That job check shares the check's one `slot_check_timeout` deadline
      (a check that runs out of it counts the slot lost), so a check never takes longer than
      `slot_check_timeout` in all.
- **Unreachable database.** A database that cannot be reached is `unknown`: the worker adopts
  nothing and waits. It gives up 15 s (`slot_give_up`) after the slot was **last confirmed held**, so
  outages up to about 15 s are waited out and longer ones restart the process.
- **Confirmations at start.**
    - The claim counts as the first confirmation (the clock is read just before it).
    - One more check (`keep`, bounded by `slot_check_timeout`) just before DBOS launches moves it
      there if the slot is still held, so a `claim_grace` wait does not use up the give-up time.
    - If another process holds the slot by then, the start fails before DBOS launches (it would
      resume and dequeue that process's jobs).
- **During startup.** The watchdog starts right after `DBOS.launch()` (DBOS resumes the slot's
  workflows from then on) and checks at once, while the queue is registered, the jobs recovered and
  the schedule applied. A slot lost during a slow startup is given up counting from its last
  confirmation: the startup is cancelled and fails, and the process stops.
- **When the slot is lost** (another process holds it, or after that wait), the worker:
    1. stops taking jobs (a job DBOS still hands over is refused);
    2. cancels the running ones and gives them half of `halt_timeout` to end;
    3. stops DBOS whether they did or not (and gives the event loop a new thread pool, as its normal
       teardown does);
    4. queues the refused jobs again through a `DBOSClient`;
    5. stops the process with `SIGTERM`, at most `halt_timeout` after the check that found the slot
       lost, also when a part of that stop failed or ran out of time. The watchdog does not check
       again once the slot is lost.
- **`halt_timeout`** (5 s) is a hard bound on all of it. When it runs out, whatever is left is
  abandoned: a job that ignores or delays its cancellation is not waited for, and its next step
  finds DBOS stopped.
- **Shutdown.** `serve` bounds the shutdown (`timeout_graceful_shutdown`, 30 s) and a restart policy
  brings the process back. The normal teardown that follows waits for a job still unwinding
  (`stop_grace`, then until it ends). A job that ignores its cancellation holds the shutdown up to
  `timeout_graceful_shutdown`, or until the restart policy kills the process (its next step fails
  meanwhile: DBOS is stopped).

### Adoption

Slots no new process takes (fewer processes than before) are adopted:

1. On each watchdog round the worker lists the pending job workflows of other executors.
2. It takes the locks of the free slots, so no process holds them and no other can adopt them
   meanwhile.
3. A slot must have been seen free for `adopt_grace` (30 s) first, by this run of the worker (a
   restarted worker starts counting again).
4. It then lists their workflows again and re-queues them (`resume_workflows`).

### Timing invariants

These are checked when the worker is built (a `ValueError` otherwise). They rely on `halt_timeout`
bounding the halt whatever the jobs do (the halt never waits on a job past its deadline: cancelling
tasks does not swallow the caller's own cancellation), and on one `slot_check_timeout` bounding a
whole check, a retaken slot's job check included.

1. `slot_give_up + slot_check_interval + slot_check_timeout + halt_timeout < adopt_grace`
   (15 + 2 + 1.5 + 5 = 23.5 < 30). A process whose slot went unconfirmed has cancelled its jobs,
   stopped DBOS and asked to be stopped before anyone adopts them, also while it is still starting,
   since the watchdog runs from DBOS's launch on.
2. `claim_grace > slot_check_interval + slot_check_timeout + halt_timeout` (15 > 8.5). A process
   that lost its slot to a newly started one stops before the newcomer's DBOS resumes the slot's
   jobs.

### Start

- Recovery (`sort_workflows`) deletes or recovers only the workflows of this process's executor and
  of free slots.
- A live process's workflows, of any `STEPS_VERSION`, are never touched, and `RecoverJobs` leaves
  their jobs alone.

!!! warning "Upgrades that change `STEPS_VERSION`"

    A release that changes `STEPS_VERSION` still needs every process stopped before the upgrade
    ([Deployment](../deployment.md#upgrading)): an older process would keep running jobs the new
    build cannot resume.

### Scheduled ticks

- DBOS starts a tick only if its workflow ID (`sched-<name>-<time>`) is new, and each process's
  scheduler may come up to a tenth of an interval late.
- On PostgreSQL the tick's workflow is therefore kept for `tick_retention` (two intervals, at least
  10 minutes) before the worker deletes it, so a tick runs once across processes.

### Locks and work folders

- Re-tags, an import's activation and settings edits take turns through `PostgresLibraryLocks`
  (`ingestion.adapters.driven.postgres`):
    - a session-level advisory lock per purpose and library;
    - held on a connection of its own while the work runs (released by PostgreSQL if the process
      dies);
    - behind an in-process `asyncio.Lock`, so waiters do not each hold a connection.
- Each process fetches in a `work/process-*` folder of its own, which it creates and `flock`s in one
  step when it starts running (then checks the locked file is still the folder's). A starting
  process removes only the folders whose lock it can take, while it holds it.
- The sign-in throttle's counts are in the database (`SqliteFailedSignInLog`, see
  [Identity](identity.md#the-sign-in-throttle)), so every process counts the same failures.

## The scheduled check (SYNC-02)

The worker also keeps a DBOS schedule, `exactdocs-scheduled-checks`:

- `EXACTDOCS_AUTO_SYNC_SCHEDULE`, a cron expression with seconds, every minute by default;
- its workflow runs `RunScheduledChecks` outside its own workflow context (the jobs it queues are
  workflows of their own) and is deleted when it ends.

The tick only wakes it up. The kernel `Clock` decides which libraries are due, from each one's
`AutoSync` (`ingestion_auto_syncs`): tag pattern, `keep_last`, `interval_minutes`, `sync_branches`,
when it was last checked and what failed, and a `revision` each save changes.

### What gets imported and removed

`plan_auto_imports` is the pure rule:

- it imports the matching ordered tags among the newest `keep_last` of (those tags plus the `auto`
  versions);
- it removes only the `auto` versions outside the newest `keep_last` *versions*, so an old one goes
  after its replacement is imported;
- manual versions and the pinned default never count.

Failures:

| Failure | Retried |
|---|---|
| permanent (`PERMANENT_IMPORT_FAILURES`: `no_articles`, `import_too_large`) | the tag is held back until it moves |
| repeated `unexpected` failures at one commit | backs off 2^(n-1) - 1 more intervals after the n-th, at most a day |
| anything else | at the next check |

### Pausing, origin and concurrency

- The schedule is paused while no library has one (`ScheduleSwitch`; `DbosScheduleSwitch` pauses or
  resumes it by name, and the worker sets it from the stored schedules at start), so an idle server
  writes no tick workflow.
- A version's `origin` (`manual`/`auto`) travels from the job through the import's `StoreManifest`
  to `catalog_manifests.origin`. The activation that creates the version gives it that origin
  (`catalog_library_versions.origin`); later imports never change it.
- A tick that meets one still running does nothing.
- A check is recorded by a compare-and-set on the `revision` and `checked_at` it read
  (`AutoSyncStore.record_check`), so a save made meanwhile is kept.
- With both a pattern and `sync_branches`, the refs are listed once.

## Push webhooks (TEAM-03)

`ReceiveWebhook` is the only use case a request without a caller reaches besides sign-in.

1. **Read.** The driving adapter reads the raw body (capped at `MAX_WEBHOOK_BYTES`, 413 before any
   lookup) and the headers.
2. **Check.** The use case does the rest with pure functions of `models.py` on the standard
   library:
    - `webhook_provider` (by the event header);
    - `verify_webhook` (HMAC-SHA256 or GitLab's token, every comparison `hmac.compare_digest`);
    - `parse_push` (delivery ID and ref names only);
    - `route_push`.
3. **Secret.** The secret is read by library (`WebhookSecrets`). A library without one, or unknown,
   is checked against a random key all the same, so every refusal costs one indexed read and one
   HMAC, writes nothing, and reads alike (401 `invalid_signature`).
4. **Record.** An accepted delivery is recorded in `ingestion_webhook_deliveries`
   (`INSERT ... ON CONFLICT DO NOTHING` on its primary key: one winner across processes; rows older
   than `WEBHOOK_DELIVERY_TTL` pruned in the same write). It is forgotten again if queueing fails,
   so the forge's retry works.
5. **Queue.** Each routed ref queues a `push` job (`version` the ref, `ref_kind` branch or tag).
   The partial unique index `ingestion_jobs_queued_push` keeps one *queued* push per (library, ref,
   kind), so a burst coalesces (`PushQueuedError`), while a push that arrives after the job started
   queues the next.

`PushJobUseCase` runs `SyncLibrary` with `refs` (that branch only) or, for a tag, the tag part of the
scheduled check (`AutoImports`, shared with `RunScheduledChecks`) without recording a check. Being a
job, it waits behind the library's running job.

## Running jobs one at a time in tests

`RunNextJob` (claim the oldest queued job whose library has none running, in one atomic statement,
and run it inline) remains for tests that drive jobs one at a time.
