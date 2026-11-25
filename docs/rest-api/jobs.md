# Jobs

!!! abstract "TL;DR"
    - Imports, re-processing, embedding, collection and pushes run as jobs; `GET /jobs/{id}`
      polls one.
    - Every job names the person who queued it in `created_by`, and `origin` tells the
      instance's own work (`auto`) from requests (`manual`).
    - A failed job has `error` for people and `error_code` for scripts.
    - `POST /jobs/{id}/cancel` stops a job at its next step boundary and keeps what it finished.
    - An import lists its per-file problems as `{path, code, reason, is_skip}`: branch on `code`.

## Endpoints

| Method | Path | Purpose | Caller or role |
|---|---|---|---|
| `GET` | `/jobs` | list jobs | readable libraries |
| `GET` | `/jobs/latest` | the newest job of every library version | readable libraries |
| `GET` | `/jobs/{id}` | one job | `viewer` |
| `POST` | `/jobs/{id}/cancel` | cancel a job | `contributor` |
| `GET` | `/libraries/{owner}/{repo}/jobs` | one library's jobs, newest first | `viewer` |
| `GET` | `/stats/jobs` | jobs per day by state and kind | operator |

## A job

`GET /jobs/{id}` is one job:

| Field | Values |
|---|---|
| kind | `import`, `refresh`, `reprocess`, `rechunk`, `retag`, `collect`, `embed` or `push` |
| state | `queued`, `running`, `succeeded`, `failed` or `cancelled` |
| `done` / `total` | files, or chunks for `embed` |
| `chunked` / `reused` | chunk sets cut, articles whose chunk set was stored before |
| `parsed` / `taken` | articles parsed, articles taken from the catalog |
| problems | per file, see [Job problems](#job-problems) |
| `cancelled_by` / `cancelled_at` | who cancelled it, and when |
| `cancellable` | whether the caller may cancel it now |

### Who queued a job

Every job (also on `GET /jobs`, a library's jobs and `/jobs/latest`) has `created_by`, the person
whose request queued it, as `{"id": <account ID>, "username": ...}`.

- It is the account of the session or API token (REST) or OAuth/API token (MCP), never the token
  or its ID.
- The user name is the one the account had then, so a job keeps naming its person after the
  account is removed.
- It is `null` when no person queued the job:
    - the instance's own work
    - the command line on the server (`exactdocs ...` without the API)
    - every job queued before ExactDocs recorded it. Upgrading leaves those `null`; nothing can
      tell who queued them.

### Origin

`origin` is stored with the job. It is `manual` unless the instance queued the job on its own,
which makes it `auto`:

- the scheduled check's tag imports and branch syncs, with the failures and recoveries they record
- a repository webhook's `push` job and the sync or imports it queues
- the `embed` jobs the instance queues after an import, at start and nightly

An `auto` job never names a person. Jobs queued before this release keep the origin they were
stored with (a scheduled branch sync was `manual` then). Filter with `origin=auto` or
`origin=manual` on `GET /jobs` and `GET /libraries/{owner}/{repo}/jobs`.

<figure class="xd-shot" markdown>

![The Jobs page listing import and embed jobs, each with its library, version, state, progress and how long it took](../assets/screenshots/jobs-light.webp#only-light){ loading=lazy }
![The Jobs page listing import and embed jobs, each with its library, version, state, progress and how long it took](../assets/screenshots/jobs-dark.webp#only-dark){ loading=lazy }

<figcaption>The <strong>Jobs</strong> page: state, progress, origin and duration of each job.</figcaption>

</figure>

## Failures

A failed job has its `error` (for people), its `error_code` (stable, for scripts) and its
`finished_at`.

- The code of an upstream problem is one of `repo_unreachable`, `auth_failed`, `ref_deleted` and
  `tag_moved`, the same for a sync and for an import that meets it.
- Any other failure keeps the error's own code (`no_articles`, `commit_unavailable`, ...) or is
  `unexpected`.
- Jobs that failed before codes were recorded have `error_code: null`.

## `embed` jobs

An `embed` job embeds one version with the instance's embedding model.

- Its `total` counts the version's chunks without a vector, each once. Identical files share their
  chunks, so they are embedded once.
- Chunks another job embedded while it ran (files shared with another library) count in `done` and
  in `reused`, so a succeeded `embed` job ends with `done` = `total`.

| `error_code` | Meaning | Queued again |
|---|---|---|
| `embedding_failed` | its error names the model and the HTTP status, never a key | at the next start |
| `ai_budget_reached` | a budget its embedding counts to (embedding, instance or library)<br/>was used up before its next batch | just after the UTC midnight that resets the window |

## The newest jobs

`GET /jobs/latest` is the newest job of every library version in one call (`{"jobs": [...]}`),
with `skipped` instead of the problem list.

- A `push` job never counts; its outcome shows through the sync it queued.
- The library list uses it to show freshness and sync errors without a request per library.

`GET /libraries/{owner}/{repo}/jobs` pages one library's jobs, newest first.

## Job statistics

`GET /stats/jobs?bucket=day&from=2026-11-01&to=2026-11-30` counts the jobs queued on each UTC day
from `from` to `to` by the state they are in now (`by_state`) and by kind (`by_kind`), with each
day's `total`.

| Parameter | Meaning |
|---|---|
| `bucket` | `day`, the default and only bucket |
| `from` | `YYYY-MM-DD`, included; default 29 days before `to` |
| `to` | `YYYY-MM-DD`, included; default today (UTC) |

- Every day of the range is listed, oldest first, and every state and kind with it, 0 included,
  so a chart needs no filling in.
- A range that ends before it starts, or covers more than 366 days, is a 422 `invalid_range`.
- Operators only: a session or an API token of an `admin`, 403 `forbidden` otherwise. The counts
  cover every library.
- One grouped query on an index of the jobs' creation time.

## Cancelling a job

`POST /jobs/{id}/cancel` needs the `contributor` role on the job's library. Operators always may;
anyone else gets 403 `forbidden`. CLI: `exactdocs jobs cancel <id>`.

| State | Effect |
|---|---|
| `queued` | becomes `cancelled` at once and never starts: its version stays as it was,<br/>or is never created for a first import |
| `running` | answers `running` with `cancelled_at` set, stops at its next step boundary,<br/>then ends `cancelled` with what it finished kept |
| ended | 409 `job_finished` with its `job_state` |

What a running job keeps:

- an import publishes nothing: its version is replaced in one step or not at all
- a `reprocess`, `rechunk` or `retag` keeps the versions it had finished
- an `embed` job sends no batch after the one in flight and keeps the vectors stored (their spend
  is counted as usual)

Asking again while it stops answers the same job.

### After a restart

- The cancellation is stored, so it survives a restart: a job interrupted while it was stopping
  ends `cancelled` on the next start.
- The scheduled check does not queue a cancelled auto import or branch sync again at the same
  commit. A new commit, or a sync or import by hand, does.
- The start and the nightly upkeep leave a version whose embedding was cancelled alone. An import
  of the version, or a change of the embedding model, queues it again, and it resumes from the
  chunks still missing vectors.

## Job problems

`GET /api/v1/jobs/{id}` lists the problems an import found per file as
`{path, code, reason, is_skip}`.

- `reason` is a sentence for people and may change; branch on `code`.
- `is_skip` is true when the file was left out of the version, false when it was imported anyway.
- `skipped` on `GET /api/v1/jobs/latest` is the number of skipped files, exact even when the list
  is capped.

| `code` | `is_skip` | Meaning |
|---|---|---|
| `binary` | true | the file contains NUL bytes |
| `too_large` | true | the file is over the per-file size cap (2 MiB by default) |
| `undecodable` | true | the file is not text in UTF-8, UTF-16/32 with a BOM or Windows-1252 |
| `not_a_file` | true | not a regular file (for example a symlink) |
| `unreadable` | true | the file could not be read |
| `bad_file_name` | true | the file name is not valid UTF-8 |
| `unparsable` | true | the file was read but could not be parsed or cut into chunks;<br/>the rest of the version is imported |
| `front_matter` | false | the article was imported, its front matter is malformed or partly ignored |
| `truncated` | false | marker with an empty `path`: more files were skipped than are listed |

- Text is decoded as UTF-8, then UTF-16/32 announced by a byte order mark, then Windows-1252
  (which covers Latin-1 files).
- At most 1000 skips and 200 `front_matter` notes are listed.

!!! warning "New codes may be added"
    Clients must treat an unknown `code` as a generic problem, using `is_skip` to tell skips from
    notes.
