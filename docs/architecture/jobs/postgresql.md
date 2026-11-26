# Several processes on PostgreSQL

!!! abstract "TL;DR"
    - Any number of processes share the DBOS queue on PostgreSQL; a job runs once and the limit of
      one per library holds across processes.
    - Each process holds an executor slot (`exactdocs-<n>`) through an advisory lock; the watchdog
      checks it every 2 s and gives up 15 s after it was last confirmed.
    - A process that lost its slot cancels its jobs, stops DBOS and stops itself within
      `halt_timeout` (5 s); free slots seen for `adopt_grace` (30 s) are adopted.
    - A release that changes `STEPS_VERSION` still needs every process stopped before the upgrade.
    - Tick workflows are kept for two intervals (at least 10 minutes), so a scheduled tick runs once
      across processes.

`serve` lets `WEB_CONCURRENCY` decide, and any number of servers may share the database. Each
process runs DBOS on the shared queue: DBOS claims a queued workflow in one transaction, so a job
runs once, and the partition limit of one per library holds across processes.

## Executor slots

Each process runs under an **executor slot** (`bootstrap/executors.py`):

- the lowest slot `n` whose two-key advisory lock (`EXECUTOR_LOCKS`, `n`) is free gives the executor
  ID `exactdocs-<n>`;
- the lock is held by a connection of its own (not the pool), with TCP keepalives
  (`SLOT_KEEPALIVES`), for the process's lifetime;
- a process that dies releases it. The next one to start takes the lowest free slot, often the
  same, waits `claim_grace` (15 s, logged) if that executor left pending workflows, and DBOS resumes
  them.

## Watchdog

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

## Adoption

Slots no new process takes (fewer processes than before) are adopted:

1. On each watchdog round the worker lists the pending job workflows of other executors.
2. It takes the locks of the free slots, so no process holds them and no other can adopt them
   meanwhile.
3. A slot must have been seen free for `adopt_grace` (30 s) first, by this run of the worker (a
   restarted worker starts counting again).
4. It then lists their workflows again and re-queues them (`resume_workflows`).

## Timing invariants

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

## Start

- Recovery (`sort_workflows`) deletes or recovers only the workflows of this process's executor and
  of free slots.
- A live process's workflows, of any `STEPS_VERSION`, are never touched, and `RecoverJobs` leaves
  their jobs alone.

!!! warning "Upgrades that change `STEPS_VERSION`"

    A release that changes `STEPS_VERSION` still needs every process stopped before the upgrade
    ([Deployment](../../deployment/upgrading.md)): an older process would keep running jobs the new
    build cannot resume.

## Scheduled ticks

- DBOS starts a tick only if its workflow ID (`sched-<name>-<time>`) is new, and each process's
  scheduler may come up to a tenth of an interval late.
- On PostgreSQL the tick's workflow is therefore kept for `tick_retention` (two intervals, at least
  10 minutes) before the worker deletes it, so a tick runs once across processes.

## Locks and work folders

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
  [Identity](../identity/index.md#the-sign-in-throttle)), so every process counts the same failures.
