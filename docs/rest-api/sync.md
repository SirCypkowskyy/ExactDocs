# Syncing, schedules and webhooks

!!! abstract "TL;DR"
    - `POST .../sync` re-imports every branch version that moved upstream, reusing the chunks of
      unchanged files. Read each version's `status` in the body, not the HTTP status.
    - A tag that moved is reported as `tag_moved` and never re-imported by a sync; confirm it with
      `POST .../versions/reimport`.
    - `PUT .../auto-sync` checks a library on a schedule, imports matching tags and keeps the
      newest `keep_last`.
    - `PUT .../webhook` sets up a push webhook; forges post to `POST /webhooks/{owner}/{repo}`
      with the secret.
    - `/sources/plan` and `/sources/apply` sync the instance with a sources file (operators only).

## Endpoints

| Method | Path | Purpose | Caller or role |
|---|---|---|---|
| `POST` | `/libraries/{owner}/{repo}/sync` | re-sync branch versions | `contributor` |
| `POST` | `/libraries/{owner}/{repo}/versions/reimport` | re-import a moved tag | `contributor` |
| `GET` | `/libraries/{owner}/{repo}/auto-sync` | read the schedule | `viewer` |
| `PUT` | `/libraries/{owner}/{repo}/auto-sync` | set the schedule | `admin` |
| `DELETE` | `/libraries/{owner}/{repo}/auto-sync` | turn it off | `admin` |
| `GET` | `/libraries/{owner}/{repo}/webhook` | webhook state | operator, session cookie |
| `PUT` | `/libraries/{owner}/{repo}/webhook` | create or rotate the secret | operator, session cookie |
| `DELETE` | `/libraries/{owner}/{repo}/webhook` | turn it off | operator, session cookie |
| `POST` | `/webhooks/{owner}/{repo}` | a forge's push delivery | none, only the secret |
| `POST` | `/sources/plan` | compare a sources file | operator |
| `POST` | `/sources/apply` | apply a sources file | operator |
| `GET` | `/sources/schema` | the file's JSON Schema | operator |

## Re-syncing

`POST /libraries/{owner}/{repo}/sync` (no body) asks the remote where each *branch* version of the
library is now, and queues an import pinned to the new commit for each one that moved.

### What the import reuses

- The chunks of every unchanged file (by git blob SHA). The job reports:
    - `chunked`: chunk sets cut, one per distinct new file content
    - `reused`: articles whose chunk set was stored before
- Files are still fetched and read, but only the changed ones are parsed. A file stored before at
  the same path with the same parser (by git blob SHA and parser version) takes its title, front
  matter and text from the catalog, and its tags are derived again from the library's rules. The
  job reports `parsed` and `taken` (articles taken from the catalog).

### Stale chunk IDs

The new manifest is activated in place of the old one: the version keeps its ID, and chunk IDs of
changed sections answer `409 stale_chunk`.

Its `detail` names the section's article and new chunk ID when they can be found, in this order:

1. same headings and text
2. same headings and occurrence (marked "text changed")
3. same text elsewhere in the article

A tie names only the article. A renamed article is followed through the rename map, which covers
one hop (the version before), so an ID that is several re-syncs old may get no location.

### The answer

The body lists every version with a `status`. Read it rather than the HTTP status.

| `status` | Meaning |
|---|---|
| `queued` | with the `job_id` |
| `up_to_date` | nothing moved |
| `importing` | an import of that branch is already queued or running:<br/>it is left alone and the others still sync |
| `pinned` | commits, and tags that still name the commit they were imported at |
| `failed` | with an `error_code` and an `error`, below |

| `error_code` | Meaning |
|---|---|
| `ref_deleted` | the branch or tag no longer exists upstream |
| `tag_moved` | the tag names another commit now; reported, never re-imported by a sync.<br/>Confirm it with [`versions/reimport`](#re-importing-a-moved-tag) |
| `unexpected` | its import could not be queued |

- A failed version keeps serving what it had.
- 202 Accepted with `Location` (the import job, or the library's jobs when several were queued)
  when anything was queued, else 200.
- At most one import per library and ref is unfinished at any time (a unique index), so
  concurrent syncs cannot queue it twice.

### Errors

| Error | When |
|---|---|
| 404 `not_found` | unknown library |
| 409 `version_importing` | an import is running and nothing could be queued |
| 422 `repo_unreachable` | the remote cannot be read[^unreachable] |
| 422 `auth_failed` | the stored token or key was refused, e.g. expired or revoked,<br/>or cannot be read with the current secret key |
| `host_key_changed` | an SSH host key that changed stays this code |
| `git_not_installed` | a server without git |

[^unreachable]: The repository was deleted, made private, moved, or the server cannot be reached.
    A login prompt for a library stored without a credential counts too, because GitHub answers a
    missing repository that way.

- The versions keep what they served.
- A failed job with that code is recorded per branch and tag (once per distinct reason) and named
  in the message.
- A later sync that finds the version fine again records a succeeded no-op job, so the error no
  longer shows.

## Re-importing a moved tag

`POST /libraries/{owner}/{repo}/versions/reimport` with `{"ref"}` is the confirmation a
`tag_moved` asks for. The ref is in the body because a ref may hold slashes, so nothing could
follow it in the path.

The tag is checked against the remote again and a `refresh` import of the commit it names now is
queued. It answers 202 Accepted with `library_id`, `ref`, `ref_kind` (`tag`),
`previous_commit_sha`, `commit_sha` (the new one), `job_id` and `Location: /api/v1/jobs/{job_id}`.

- Like a re-synced branch, the version keeps its ID and serves the old commit until the import has
  finished.
- Unchanged files reuse their chunks, and chunk IDs of changed sections then answer
  `409 stale_chunk`.
- The import is the version's newest job, so its `tag_moved` error no longer shows.

| Error | When |
|---|---|
| 404 `not_found` | unknown library or version |
| 422 `not_a_tag` | a branch, which a sync follows, or a commit, which never changes |
| 409 `tag_not_moved` | the tag still names the commit the version serves |
| 422 `ref_deleted` | the tag is gone upstream |
| 409 `version_importing` | an import of it is queued or running |
| 422 `repository_unreachable`, `credentials_required`, ... | the codes of reading a repository |

!!! warning "Two sets of codes"
    These are the codes adding a version answers, not the sync's own `repo_unreachable` /
    `auth_failed`. A script that branches on codes handles both sets.

## Scheduled check

`PUT /libraries/{owner}/{repo}/auto-sync` (SYNC-02) checks the library on its own.

| Field | Default | Meaning |
|---|---|---|
| `tag_pattern` | no pattern | a case-sensitive glob, `v*` |
| `keep_last` | 5 | 1 to 100 `auto` versions kept |
| `interval_minutes` | 60 | 1 to 10080 |
| `sync_branches` | false | also re-sync every branch version |

What is left out takes its default.

### What a check does

- It runs every `interval_minutes`, starting at the next tick of the server's schedule
  (`EXACTDOCS_AUTO_SYNC_SCHEDULE`, every minute).
- It asks the repository for its refs once.
- Tags matching `tag_pattern` that have a version order (`v1.4.0`, `2.1`; pre-releases and other
  names do not) are imported as versions with `origin: "auto"`, oldest first.
- Only the newest `keep_last` `auto` versions are kept. Older ones are removed as by
  `DELETE .../versions/{ref}`, at the first check after their replacements are versions, so a
  failed import never leaves the library short. One being imported is left for the next check.
- Never removed and not counted:
    - versions added by hand (`origin: "manual"`, in `GET /libraries/{owner}/{repo}`)
    - the pinned default version (`PUT .../default-version`)
- With `sync_branches`, every branch version is then re-synced as `POST .../sync` does, from the
  same list of refs. Its failures are recorded on the versions' jobs the same way.
- The import jobs it queues carry `origin: "auto"`.
- While no library has a schedule, the server's tick is paused and writes nothing.

### Retrying failed tags

| Failure | Tried again |
|---|---|
| for good (`no_articles`, `import_too_large`) | only once the tag names another commit |
| `unexpected` (a bug) | backs off: after the n-th such failure in a row at the same commit,<br/>it waits 2^(n-1) - 1 more intervals, at most a day |
| any other (an unreachable repository, a refused credential, a full disk...) | at the next check |

!!! note
    An `auto` version removed by hand comes back at the next check while it is among the newest
    `keep_last` matching tags. Narrow the pattern or lower `keep_last` to keep it out.

### Reading and removing

- `GET .../auto-sync` reads it, with `enabled` false when the library is never checked on its own,
  plus `checked_at`, `next_check_at` and `last_error` (what the last check could not do).
- `DELETE .../auto-sync` turns it off and keeps every version.
- 404 for an unknown library, 422 for a value out of range.
- Saving it again makes the library due at the next tick.
- Removing the library removes its schedule.

## Push webhooks

`PUT /libraries/{owner}/{repo}/webhook` (TEAM-03) creates or rotates the library's webhook secret
and answers it once, with `url` (where the forge posts) and `created_at`. The old secret stops
working at once.

- `GET .../webhook` says `enabled`, `url` and `created_at`, never the secret.
- `DELETE .../webhook` turns it off.
- 404 for an unknown library. Removing the library removes its secret.

!!! warning "Operator session only"
    These three are for operators, as `/users` is: an `admin` signed in with a session. An API
    token is refused with 401, another account with 403 `forbidden`, since the answer reveals a
    secret.

### Deliveries

Forges post to `POST /webhooks/{owner}/{repo}`, which needs no caller, only the secret:

| Forge | Header |
|---|---|
| GitHub | `X-Hub-Signature-256` (`sha256=<hex>`) |
| Bitbucket | `X-Hub-Signature` (`sha256=<hex>`) |
| GitLab | `X-Gitlab-Token` |

The signatures are HMAC-SHA256 of the raw body.

| Answer | When |
|---|---|
| 401 `invalid_signature` | every refusal: no or a wrong signature, a SHA-1 one, an unknown forge,<br/>a library without a secret, no such library |
| 413 | a body above 5 MiB, before anything is looked up |
| 400 `missing_delivery_id` | a signed delivery without its ID[^delivery-id] |
| 202 | otherwise, with `status` and `job_ids` |

[^delivery-id]: `X-GitHub-Delivery`; `Idempotency-Key` or `X-Gitlab-Event-UUID`; `X-Request-UUID`
    or `X-Request-Id`.

| `status` | Meaning |
|---|---|
| `queued` | a `push` job per branch version pushed, or per tag the auto-sync `tag_pattern` matches;<br/>a push of a ref whose `push` job still waits joins it |
| `duplicate` | that delivery ID was accepted in the last 7 days |
| `ignored` | an untracked branch, a tag without auto-import, a ping |

The `push` job syncs the branch alone, as `POST .../sync` would (a deleted one gets
`ref_deleted`), or runs the tag part of the scheduled check without recording a check. Only ref
names are read from the payload.

## Sources file

See [Sources file](../sources.md) (TEAM-02) for the file itself.

=== "`POST /sources/plan`"

    Body `{"sources": <the file as JSON>, "prune": false}`. Compares the declared libraries with
    the instance and writes nothing. Answers:

    - `create`
    - `update`: per library the managed settings that change, `refs_to_add`, `auto_sync`,
      `job_kind`, `undeclared_versions`
    - `unchanged`, `undeclared`
    - `errors` (`source_mismatch`)
    - `changes` (false: apply would write nothing)

=== "`POST /sources/apply`"

    Same body. Plans again and applies it library by library: creations, updates, then removals
    only with `prune`.

    - One failing library does not stop the others.
    - `results` has each library's `action`, `jobs` and `error`.

=== "`GET /sources/schema`"

    Returns the file's JSON Schema, committed as `docs/schemas/exactdocs.sources.schema.json`.

- Settings the file leaves out are not managed.
- 422 for an invalid file (an unknown key, a short SHA, a duplicate ID) or a setting the server
  cannot store (`invalid_sources`, naming the entry).
- Operators only: the account's role must be `admin` (403 `forbidden` otherwise), signed in with
  a session or an API token. The CLI and CI only have tokens.
