# The scheduled check and push webhooks

!!! abstract "TL;DR"
    - The `exactdocs-scheduled-checks` schedule ticks every minute by default
      (`EXACTDOCS_AUTO_SYNC_SCHEDULE`) and is paused while no library has a schedule.
    - `plan_auto_imports` imports matching tags among the newest `keep_last` and removes only `auto`
      versions; manual versions and the pinned default never count.
    - A permanent failure holds the tag back until it moves; repeated `unexpected` failures back off,
      at most a day.
    - A push webhook is checked by HMAC-SHA256 or GitLab's token, every refusal is a 401
      `invalid_signature`, and a delivery is recorded once across processes.
    - Each routed ref queues a `push` job, with one queued push per library, ref and kind, so a burst
      coalesces.

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
