# REST API

The REST API under `/api/v1` is the only API of the web UI and the CLI. Its OpenAPI description
is served at `/api/v1/openapi.json` and committed as `web/openapi.json`; the web client's types
(`web/src/shared/lib/api-schema.d.ts`) are generated from it. After changing a route or a DTO run
`just api` and commit both files (a test and a CI step fail otherwise).

There is deliberately no interactive Swagger UI or ReDoc: they load their assets from a CDN, and
ExactDocs makes no third-party requests by default. Open the JSON in any OpenAPI viewer.

## Conventions

- **Operation IDs** are `<tag>-<function name>` (for example `catalog-list_all`), one tag per
  domain. They never change once published, because generated clients are named after them:
  renaming a handler function renames its operation ID, which is a breaking change.
- **Errors** have one shape for every error under `/api`: `{"error": "<code>", "detail": "<message>", "fields": [], "close_matches": []}`.
  Unknown routes and wrong methods are `not_found` / `method_not_allowed`; an unexpected failure
  is 500 `internal_error` (no internals in `detail`).
  `error` is the stable `DomainError.code` (`not_found` is 404, `conflict` 409, `validation_error`
  and every `ValidationError` 422, `rate_limited` 429 with a `Retry-After` header in seconds,
  anything else 400). Request validation failures are 422 with
  `error: "validation_error"` and one `fields` entry (`loc`, `msg`, `type`) per invalid field.
- **First run**: until the first admin account exists, every `/api/v1` request except
  `POST /api/v1/setup`, `GET /api/v1/session` and the OpenAPI document is refused with 403
  `setup_required`, whatever the method (HEAD and OPTIONS included). `POST /api/v1/setup` creates the
  admin once (409 `already_set_up` afterwards). Only `/api/v1` is guarded: `/mcp` is
  guarded by its own API-token check instead (see Authentication).
- **Authentication**: every `/api/v1` operation needs a caller (401 `unauthenticated` otherwise):
  the session cookie, or `Authorization: Bearer exd_...` with an API token (a wrong bearer is
  refused even if a valid cookie is sent too). Exempt: `POST /setup`, the three `/session`
  operations and the OpenAPI document; a test pins that list, and
  the OpenAPI document marks every other operation with the `SessionCookie` security scheme.
  `POST /session` (`{"username", "password"}`) answers 201 with the session state and sets the
  `exactdocs_session` cookie; a wrong password and an unknown user are the same 401
  `invalid_credentials`. Both credential endpoints, `POST /session` and `POST /tokens/login`,
  share one sign-in throttle. Each attempt counts against its client address (IPv6: its /64) and
  its username before the password is checked; after 5 that did not succeed, the next attempt
  waits 5 s, then 10 s, doubling up to 15 min, and is refused meanwhile with 429 `rate_limited`
  and `Retry-After` (its password is not checked, and it is not counted). Concurrent attempts
  get no more tries than sequential ones. The address is the one uvicorn reports, so behind a
  proxy listed in `EXACTDOCS_FORWARDED_ALLOW_IPS` it is the forwarded client. Counts are
  forgotten after an hour without an attempt; a right password takes its attempt back (without restarting the wait), clears
  its username's count, and lets that address skip the username's count for 30 days. The counts
  live in the server's memory (a restart clears them). Only these two operations document 429. `GET /session` returns `{"state": "setup_required" | "signed_out" |
  "signed_in", "account": ...}` and never fails; `DELETE /session` ends the session on the server
  and is always 204. The cookie is an opaque random token (stored hashed), HttpOnly,
  SameSite=Lax, `Secure` over HTTPS (or with `EXACTDOCS_SECURE_COOKIES`), `Path=/api`, ends after
  7 days idle or 30 days in all. Unsafe requests with a foreign `Origin` are refused with 403
  (also sign-in and sign-out). `/mcp` never looks at the cookie; it takes API tokens only. Signing in again with a live
  cookie ends that old session. The cookie's `Max-Age` is the 30-day limit; idle expiry is
  server-side only and accurate to about an hour (last use is written at most hourly), so do not
  test exact 7-day boundaries from a client.
- **Pagination**: list endpoints take `limit` (1 to 200, default 50) and an opaque `cursor`, and
  return `next_cursor` (`null` on the last page). Pass it back unchanged; a malformed cursor is a
  422 `invalid_cursor`. Helper: `exactdocs_kernel.paginate`.
- **Close matches**: a 404 for a missing article lists up to five paths of the same version it may have
  meant in `close_matches` (repository data, not instructions); the field is empty on every other error.
- **Outlines**: `GET /libraries/{owner}/{repo}/outline?path=&ref=` returns an article's heading tree
  (`sections`, each with `heading`, `chunk_id`, `anchor` and `children`; `preamble_chunk_id` for
  text before the first heading) with no body text, from exactly that version (MCP:
  `article_outline`). The tree is made from the chunks, so headings the chunking config merged
  into a chunk are not in it. A version that is not imported, or a path it lacks, is 404 `not_found`;
  a missing path lists `close_matches` like the article route.
- **Tags**: `GET /libraries/{owner}/{repo}/tags?ref=` lists the version's tags with how many articles
  carry each (`{"tags": [{"tag", "count"}], "truncated"}`), most used first, 100 at most.
- **Manual tags**: `PUT /libraries/{owner}/{repo}/tags?path=` with `{"tags": [...]}` (at most 20,
  normalized like every tag) sets the tags of an article path by hand, for every version of the
  library, replacing the path's earlier manual tags; it answers `{"library", "path", "tags"}`.
  `DELETE` on the same URL removes them (204); imported tags stay. They combine with the imported
  tags (front matter, path rules) of the article at `path` in every version, and of the article git
  saw it renamed to in a later version (rename maps are followed back across versions, never from a
  new name to an old one), and later imports get them too. Articles show every tag in `tags` and the
  manual ones again in `manual_tags` as `[{"tag", "path"}]`, where `path` is the path the tag was
  set on: the article's own, or an older one it was renamed from. `PUT` and `DELETE` act on the path
  that was tagged, never on its successors: to remove a tag that came with a rename, remove it on
  the `path` it names (which removes it from every version). Listings, tag counts and search see them at once (the tag
  copies on chunks are refreshed, nothing is chunked again). A path no version has is accepted and
  waits for one. An unknown library is 404; a value that cannot be a tag is 422 `invalid_tags`.
- **Renames**: `GET /libraries/{owner}/{repo}/renamed-path?ref=&path=&direction=` follows `path` one
  hop across the renames git saw when `ref` was imported (default version without `ref`).
  `direction=forward` (default): `path` is from the version imported before `ref`; `back`: `path`
  is an article of `ref`. It answers 200 `{"renamed": {"library", "ref", "from_ref", "old_path",
  "new_path", "similarity"} | null}`; `null` means the path was not moved (or no renames are
  known; nothing is guessed). An unknown library or version, or one without an active manifest,
  is 404 `not_found`. Across several versions, ask once per version and chain the answers; a
  branch's map builds up over its syncs. Adding an older tag after a newer one (`v1.3.0` after
  `v1.4.0`) also detects the newer tag's map again, against the older one, so the order versions
  are added in does not matter.
- **Refs containing `/`**: library IDs are `/{owner}/{repo}` in the path. A ref may only be the
  last path segment, declared `{ref:path}`; a route that needs a ref and an article path takes
  `?ref=` and `?path=`, because servers decode `%2F` before routing.

- **API tokens**: `POST /api/v1/tokens` (`{"name", "expires_at"?}`, timezone-aware, in the future)
  answers 201 with the token's fields and `token`, the secret `exd_...`, which no other call ever
  returns (`Cache-Control: no-store`). `GET /tokens` lists the caller's tokens (`id`, `name`,
  `prefix`, `created_at`, `expires_at`, `last_used_at`; newest first) and `DELETE /tokens/{id}`
  revokes one at once (204; 404 `unknown_token` for another account's or a missing id). The
  secret is 256 random bits and only its SHA-256 is stored. An unknown, expired or revoked token is
  the same 401. `last_used_at` is written at most hourly, best effort (a failed write is logged
  and the request goes on). Expired tokens are purged when a new one is created. An account holds
  at most 50 tokens (409 `too_many_tokens`). A password reset revokes all of the account's
  tokens. The three token routes need the **session cookie**, not a token, so a stolen token
  cannot create a successor.
- **Editing a library**: `PATCH /libraries/{owner}/{repo}` (`{"title"?, "description"?}`). An edited
  field is kept across re-imports instead of following the default version's `context7.json` or
  root README (LIB-07).
- **Editing paths, tag rules and chunking** (LIB-09, TAG-02, IMP-03):
  `PUT /libraries/{owner}/{repo}/settings` with `{"include_paths", "exclude_paths", "tag_rules",
  "chunking"}` replaces the paths and tag rules as a whole set (what is left out is cleared;
  `GET /libraries/{owner}/{repo}` has the current `settings`) and the chunking when it is sent:
  `chunking` left out or `null` keeps the stored one, so a client that edits only paths and tag
  rules (the web UI) never resets it, validated like
  `POST /libraries` (422 `invalid_path_pattern` / `invalid_tag` / `invalid_chunking_config` or a
  field error, nothing stored), 404 for an unknown library. `chunking` is
  `{"split_level": 1-6, "min_chars": 0, "max_chars": null, "chunker": "markdown"}` (the
  defaults): `split_level` is the deepest heading that starts a chunk (`2` cuts at `#` and `##`
  only); a chunk longer than `max_chars` is cut again at its deeper headings (never inside a code
  block or table, so a section without deeper headings stays whole); chunks shorter than
  `min_chars` are merged with the next one (the last with the one before) as long as the result
  stays within `max_chars`, and the text before the first heading is never merged (a merged
  chunk keeps the heading path and anchor of its first section, so a hit in a later section of
  it links to that first heading); `max_chars`
  must not be smaller than `min_chars` (both at most 1,000,000). `markdown` (markdown-it-py) is
  the only chunker. Every version is then re-processed by **one** job, at the commit it serves (a
  branch is not synced): changed paths queue a `reprocess` job that fetches each version again
  and re-imports it (unchanged blobs reuse their chunks); a changed chunking (paths unchanged)
  queues a `rechunk` job that copies what each version serves into a new manifest, re-derives
  its tags and cuts the **stored** text again, fetching nothing (a blob already cut with that
  chunking reuses its chunks; a version stored by an older parser, or holding a rare article
  whose stored text cannot be cut exactly as its import cut it, is re-imported at its commit
  instead, so such a version needs the repository to be reachable whenever its chunking
  changes); only tag rules changed queue a `retag` job that derives each stored article's tags
  again from its stored front matter and the new rules, fetching and chunking nothing (manual
  tags stay). Each version keeps serving its old state (its old chunks too) until its new one is
  complete and then switches at once: a new manifest activated, or, for a `retag`, the version's
  catalog entries re-tagged in one transaction, with search's tag copies following a moment
  later under the same lock (as for manual tags; a rerun of the job always brings them in
  line). A version that cannot be re-processed keeps what it had, the others go on, and the job
  fails naming it (`error_code` the failures' shared code, else `reprocess_failed`); sending the
  same settings again then queues that job again. A job redoes what the smaller ones do
  (`reprocess` > `rechunk` > `retag`): while a wider one failed and has not been redone, a retry
  or a smaller edit queues the wider one, so a smaller job never hides that failure. The jobs
  count `done` / `total` in versions. The answer is **202** with the job in `Location` and the
  body's `job_id`, `reprocess` (`paths`, `chunking` or `tags`), the stored `chunking` and
  `versions` (the library's refs, which the job re-processes), or **200** with `job_id: null`
  when nothing changed and the last re-processing did not fail, or the library has no version
  yet (imports to come use the new settings). Edits of one library take turns. A queued job
  that does at least what is needed is reused. Removal waits for these jobs like for an import.
- **`context7.json`** (LIB-06): a repository's root `context7.json` is read when a library is
  added or previewed (only that one file of the pinned commit: its tree entry, then its blob) and
  again by every import. Reading it for an add or a preview uses a preview slot, never an
  import's, and waits for one only as long as a preview does. When every slot stays busy, an add
  sent **without** paths answers 429 `preview_busy` (with `Retry-After`) before anything is
  stored, because the file would decide the library's paths for good; a preview, or an add with
  paths, goes on with a warning instead. Used keys: `projectTitle`, `description`, `folders`, `excludeFolders`,
  `excludeFiles`, `rules`, `previousVersions`; others (`$schema`, `url`, ...) are ignored. Sent
  **without** `include_paths` and `exclude_paths`, `POST /libraries` and
  `POST /repositories/preview` apply its folders and exclusions: a folder is that path and all
  below it (`.` is the whole repository; a leading `./` or `/` means the root); an excluded
  folder or file given by its bare name (`archive`, `CHANGELOG.md`) is excluded wherever it is,
  one with a `/` (`./docs/internal`) only at that path, and globs are taken as patterns. Paths a
  user sends win: to import every article and ignore the file's paths, send
  `"include_paths": ["**"]`. The library keeps the paths it was created with for every later
  version, until they are edited with `PUT /libraries/{owner}/{repo}/settings`. The default version's `projectTitle` and `description` win over its README; a
  user's edit wins over both. Its `rules` (at most 20 distinct ones of at most 500 characters)
  are stored on the library (`rules` in `GET /libraries/{owner}/{repo}`) and come first in every
  `query-docs` answer, under a heading that marks them as untrusted repository text. They take
  at most a quarter of the size budget: whole rules, from the first one on, until one does not
  fit. They are the **default version's** rules: `query-docs` for `/owner/repo/<ref>` shows them
  too, not that version's. Both responses
  carry `include_paths` and `exclude_paths` (what is applied), `context7` (the parsed file, with
  its paths translated, its `rules`, `previous_versions` (`tag`, `title`) to offer for import
  with `POST /libraries/{owner}/{repo}/versions`, and `notes`) and `context7_warning`. A
  `previousVersions` entry whose tag git would not accept as a ref name (`--upload-pack=x`,
  `a..b`) is left out and named in `notes`; the rest of the file still applies. A file that is
  not a JSON object of the right types, larger than 64 KiB, or that cannot be read is ignored:
  `context7` is null and `context7_warning` says why. An import lists both kinds as `context7`
  problems of its job (the import goes on). All of it is untrusted repository text.
- **Pinning the default version**: `PUT /libraries/{owner}/{repo}/default-version` (`{"ref"}`, an
  imported ref exactly as listed, or a unique short SHA of a commit version) makes that version
  what `/owner/repo` without a ref means, even after a higher stable tag is imported (LIB-10).
  `DELETE` on the same path unpins it, and the default follows the *Default version* rule again.
  Both answer 200 with the library; a ref the library has not imported (refs are case-sensitive)
  or an unknown library is 404 `not_found`; a missing or empty ref, a malformed library ID or ref,
  or a short SHA that matches more than one commit version is 422. Libraries carry
  `default_pinned` (also in the MCP `list_libraries` tool). Removing the pinned version unpins the
  library. Changing the pin does not re-derive the title and description from the new default's
  README (LIB-07); re-import the new default to refresh them.
- **Adding a library**: `POST /libraries` (`{"url", "library_id"?, "ref"?, "include_paths"?,
  "exclude_paths"?}`) validates everything first, then stores the library with its selection and
  queues an `import` job; it answers 201 with `library_id`, `ref`, `ref_kind` (`tag`, `branch`
  or `commit`), `commit_sha` and `job_id`, and a `Location` header with the library. `ref` is a tag,
  a branch (a tag wins over a branch of the same name), or a full or short (7+ characters) commit
  SHA that is the tip of a branch or tag; omitted, it is the default branch. A ref that is
  not found is 422 `unknown_ref`, a short SHA that starts two commits 422 `ambiguous_ref`, a bad
  pattern 422 `invalid_path_pattern`, a taken ID 409 `library_id_taken`. Patterns are repo-relative,
  case-sensitive, never absolute or with `..`: `docs/` (a folder), `docs/**`, `*.md`,
  `?`, `{a,b}`. A pattern without `*`, `?` or `{` is a path: it names a file, or a folder and
  everything below it, with or without a trailing `/`. `[` is a plain character (no character
  classes), so `app/[locale]` is a folder; no `include_paths` means every `.md`/`.mdx` file, only those are ever articles, and an
  exclusion always wins. The library has no versions until its import has run; the job records the
  pinned ref and commit. `GET /repositories/refs?url=` lists `default_branch`, `branches` and `tags`
  (name and `commit_sha`, sorted), 1000 of each at most, with `truncated` set when more exist.
  `POST /repositories/refs` (`url`, optional `credential`) gives the same answer for a private
  repository: the credential travels in the body, never in a URL, and is not stored.
  `POST /repositories/preview` (`url`, optional `ref`, `include_paths`, `exclude_paths`, `credential`)
  is a dry run: it fetches the commit and its trees only (`--filter=blob:none`, depth 1, no
  checkout; git's process limits, and the fetch deadline and size watchdog, apply), plus the
  root `context7.json` alone (see above, a second blob-less fetch under a preview slot), and answers `ref`, `ref_kind`, `commit_sha`, `files`
  (sorted, 1000 at most), `total`, `truncated`, `include_paths`, `exclude_paths`, `context7` and
  `context7_warning`. The
  same selection rules as the import decide, so nothing is stored. Sizes are not included: they
  would need the blobs. Paths are untrusted text; render them as text. Errors are those of
  adding a library, plus 422 `commit_unavailable`, and 422 `repository_too_large` when the
  fetch or the tree listing is too large. A `credential` needs a signed-in session, as for
  `/repositories/check`. It does a real fetch of the commit's trees, so it is slower than
  `/repositories/check`; at most two run at once, and a third waits a few seconds, then gets 429
  `preview_busy` with a `Retry-After` header (seconds).
  Like `/repositories/check`, all of them accept `file://`, localhost and private addresses (see
  SECURITY.md).
- **Re-syncing**: `POST /libraries/{owner}/{repo}/sync` (no body) asks the remote where each
  *branch* version of the library is now and queues an import pinned to the new commit for each
  one that moved. The import reuses the chunks of every unchanged file (by git blob SHA); the
  job reports `chunked` (chunk sets cut: one per distinct new file content) and `reused`
  (articles whose chunk set was stored before). Files are still fetched and read, but only the
  changed ones are parsed: a file stored before at the same path with the same parser (by git
  blob SHA and parser version) takes its title, front matter and text from the catalog, and its
  tags are derived again from the library's rules. The job reports `parsed` and `taken` (articles
  taken from the catalog). The new manifest is activated in place of the old one: the version
  keeps its ID, and chunk IDs of changed sections answer `409 stale_chunk`. Its `detail` names the section's
  article and new chunk ID when they can be found: same headings and text, else same headings
  and occurrence (marked "text changed"), else same text elsewhere in the article; a tie names
  only the article. A renamed article is followed through the rename map, which covers one hop
  (the version before), so an ID that is several re-syncs old may get no location.
  The body lists every version with a `status`; read it rather than the HTTP status:
  `queued` (with the `job_id`), `up_to_date`, `importing` (an import of that branch is already
  queued or running: it is left alone and the others still sync), `pinned` (commits, and tags
  that still name the commit they were imported at) or `failed` with an `error_code` and an
  `error`: `ref_deleted` (the branch or tag no longer exists upstream), `tag_moved` (the tag
  names another commit now; it is reported, **never re-imported by a sync**: confirm it with
  `versions/reimport`, below) or `unexpected` (its import could not be queued). A failed
  version keeps serving what it had. **202 Accepted** with `Location` (the import job, or the
  library's jobs when several were queued) when anything was queued, else **200**. At most one
  import per library and ref is unfinished at any time (a unique index), so concurrent syncs
  cannot queue it twice. Errors: 404 `not_found`; 409 `version_importing` when an import is
  running and nothing could be queued; and, when the remote cannot be read, 422
  `repo_unreachable` (the repository was deleted, made private, moved, or the server cannot be
  reached; a login prompt for a library stored without a credential counts too, because GitHub
  answers a missing repository that way) or `auth_failed` (the stored token or key was refused,
  e.g. expired or revoked, or cannot be read with the current secret key); an SSH host key that
  changed stays `host_key_changed`, and a server without git answers `git_not_installed`. The
  versions keep what they served, and a failed job with that code is recorded per branch and tag
  (once per distinct reason) and named in the message. A later sync that finds the version fine
  again records a succeeded no-op job, so the error no longer shows.
- **Scheduled check** (SYNC-02): `PUT /libraries/{owner}/{repo}/auto-sync` with
  `{"tag_pattern", "keep_last", "interval_minutes", "sync_branches"}` (what is left out takes its
  default: no pattern, 5, 60, false) checks the library on its own every `interval_minutes`
  (1 to 10080), starting at the next tick of the server's schedule (`EXACTDOCS_AUTO_SYNC_SCHEDULE`,
  every minute). Each check asks the repository for its refs once. Tags matching `tag_pattern`
  (a case-sensitive glob, `v*`) that have a version order (`v1.4.0`, `2.1`; pre-releases and other
  names do not) are imported as versions with `origin: "auto"`, oldest first, and only the newest
  `keep_last` (1 to 100) `auto` versions are kept: older ones are removed as by `DELETE
  .../versions/{ref}`, at the first check after their replacements are versions (so a failed
  import never leaves the library short; one being imported is left for the next check).
  Versions added by hand (`origin: "manual"`, in `GET /libraries/{owner}/{repo}`) and the pinned
  default version (`PUT .../default-version`) are never removed and do not count. A tag whose
  import failed for good (`no_articles`, `import_too_large`) is tried again only once it names
  another commit. One that failed `unexpected` (a bug) backs off: after the n-th such failure
  in a row at the same commit it waits 2^(n-1) - 1 more intervals, at most a day. Any other
  failure (an unreachable repository, a refused credential, a full disk...) is tried again at
  the next check. An `auto` version removed by hand
  comes back at the next check while it is among the newest `keep_last` matching tags: narrow
  the pattern or lower `keep_last` to keep it out. With `sync_branches`, every branch version is
  then re-synced as `POST .../sync` does, from the same list of refs (its failures are recorded
  on the versions' jobs the same way). The import jobs it queues carry `origin: "auto"`. While no
  library has a schedule, the server's tick is paused and writes nothing. `GET .../auto-sync` reads it (`enabled` false when the library is never checked on its
  own) with `checked_at`, `next_check_at` and `last_error` (what the last check could not do);
  `DELETE .../auto-sync` turns it off and keeps every version. 404 for an unknown library, 422
  for a value out of range. Saving it again makes the library due at the next tick; removing the
  library removes its schedule.
- **Re-importing a moved tag**: `POST /libraries/{owner}/{repo}/versions/reimport` (`{"ref"}`;
  the ref is in the body because a ref may hold slashes, so nothing could follow it in the path)
  is the confirmation a `tag_moved` asks for. The tag is checked against the remote again and a
  `refresh` import of the commit it names now is queued: **202 Accepted** with `library_id`,
  `ref`, `ref_kind` (`tag`), `previous_commit_sha`, `commit_sha` (the new one), `job_id` and
  `Location: /api/v1/jobs/{job_id}`. Like a re-synced branch, the version keeps its ID and serves
  the old commit until the import has finished, unchanged files reuse their chunks, and chunk IDs
  of changed sections then answer `409 stale_chunk`. The import is the version's newest job, so
  its `tag_moved` error no longer shows. Errors: 404 `not_found` (unknown library or version),
  422 `not_a_tag` (a branch, which a sync follows, or a commit, which never changes), 409
  `tag_not_moved` (the tag still names the commit the version serves), 422 `ref_deleted` (the tag
  is gone upstream), 409 `version_importing` (an import of it is queued or running), and the
  422 codes of reading a repository (`repository_unreachable`, `credentials_required`, ...).
  These are the codes adding a version answers, not the sync's own `repo_unreachable` /
  `auth_failed`: a script that branches on codes handles both sets.

- **Retrieval mode** (RET-06): `PUT /libraries/{owner}/{repo}/retrieval` with `{"mode": "hybrid"}`
  sets the mode the library's searches use when a call names none (`null` clears it: the
  instance's `EXACTDOCS_RETRIEVAL_MODE` applies, else the best mode configured). The mode must be
  available now: 422 `mode_unavailable` names the model role it needs that is not configured.
  `GET .../retrieval` returns the setting with `instance_mode`, the `effective_mode` a search
  without `mode` runs in now (with `fallback_reason` when a setting is skipped), the
  `available_modes` and the `configured_roles`. 404 for an unknown library. A search's own `mode`
  (`GET /libraries/{owner}/{repo}/search?mode=`) always wins; an unavailable one is a 422
  `mode_unavailable` as well.

## Jobs, access and health

- **Jobs**: `GET /jobs/{id}` is one job (kind `import`, `refresh`, `reprocess`, `rechunk`, `retag` or
  `collect`; state `queued`,
  `running`, `succeeded` or `failed`; `done` / `total` files; `chunked` / `reused`; `parsed` / `taken`; problems).
  A failed job has its `error` (for people), its `error_code` (stable, for scripts) and its
  `finished_at`. The code of an upstream problem is one of `repo_unreachable`, `auth_failed`,
  `ref_deleted` and `tag_moved`, the same for a sync and for an import that meets it; any other
  failure keeps the error's own code (`no_articles`, `commit_unavailable`, ...) or is
  `unexpected`. Jobs that failed before codes were recorded have `error_code: null`.
  `GET /jobs/latest` is the newest job of every library version in one call (`{"jobs": [...]}`,
  with `skipped` instead of the problem list), which the library list uses to show freshness and
  sync errors without a request per library. `GET /libraries/{owner}/{repo}/jobs` pages one
  library's jobs, newest first.
- **Private repositories**: a `credential` (`{"kind": "token", ...}` or `{"kind": "ssh_key", ...}`)
  is accepted by `POST /repositories/check`, `POST /repositories/refs`, `POST /repositories/preview`, `POST /libraries` and `POST /libraries/{owner}/{repo}/versions`,
  and only on a signed-in session: an API token gets 401. It is stored encrypted for that library
  and its host, and never returned. A deploy key keeps its line breaks (`\n` in JSON); one sent
  on a single line, or with a passphrase, is 422 `invalid_credential` with a sentence saying so. `GET /libraries/{owner}/{repo}/access` answers
  `{"private": true | false}`: whether the library has a stored credential.
- **Health**: the probes sit outside `/api/v1` and answer `GET` and `HEAD` without sign-in.
  `GET /healthz` (liveness; `GET /api/health` is its alias) answers 200 while the process runs,
  giving the database about 0.3 s for its details: `status`, `version`, `database_reachable`, the
  database's `schema_revision`, the `search_index_format` the search index was built in (`null`
  if none is recorded), and `reindex_required`: `true` when that format is older than this
  version's or not recorded, until `exactdocs reindex` has run (search keeps answering
  meanwhile). When the database did not answer in time, `database_reachable` is `false` and the
  three database fields are `null`. A request whose `Host` the instance does not trust gets only
  `{"status": "ok"}`. `GET /readyz` (readiness) answers 200 `{"status": "ready"}` when the
  database file exists, answers within 2 s and is at this version's schema revision, else 503
  `{"status": "not_ready", "reason": ...}` with a fixed sentence. Only exact `GET`/`HEAD`
  requests on these paths skip the `Host` check (README *Health checks*).

## Job problems

`GET /api/v1/jobs/{id}` lists the problems an import found per file as
`{path, code, reason, is_skip}`. `reason` is a sentence for people and may change; branch on
`code`. `is_skip` is true when the file was left out of the version, false when it was imported
anyway. `skipped` on `GET /api/v1/jobs/latest` is the number of skipped files, exact even when
the list is capped.

| `code` | `is_skip` | Meaning |
|---|---|---|
| `binary` | true | the file contains NUL bytes |
| `too_large` | true | the file is over the per-file size cap (2 MiB by default) |
| `undecodable` | true | the file is not text in UTF-8, UTF-16/32 with a BOM or Windows-1252 |
| `not_a_file` | true | not a regular file (for example a symlink) |
| `unreadable` | true | the file could not be read |
| `bad_file_name` | true | the file name is not valid UTF-8 |
| `front_matter` | false | the article was imported, its front matter is malformed or partly ignored |
| `truncated` | false | marker with an empty `path`: more files were skipped than are listed |

Text is decoded as UTF-8, then UTF-16/32 announced by a byte order mark, then Windows-1252
(which covers Latin-1 files). At most 1000 skips and 200 `front_matter` notes are listed.
New codes may be added: clients must treat an unknown `code` as a generic problem, using
`is_skip` to tell skips from notes.
- **Adding a version**: `POST /libraries/{owner}/{repo}/versions` (`{"ref"}`) imports another
  version of an existing library with the library's own include/exclude paths and tag rules (and
  chunking), so versions stay comparable. The ref is resolved like when adding a library (tag over
  branch, full or short SHA). It answers **202 Accepted** (the version exists once its import has
  run) with the same body as adding a library (`library_id` is the existing library) and
  `Location: /api/v1/jobs/{job_id}`, the import job to poll. The default version is computed from
  the versions, so it moves when the import finishes (a newer stable tag takes it; a branch does
  not take it from a release; a pinned default does not move). Errors: 404 `not_found` (unknown library), 422 `unknown_ref` /
  `ambiguous_ref` (also 422 for a malformed library ID), 409 `version_exists` (the library already
  has that ref; re-importing is a sync, not this call), 409 `version_importing` (an import of that
  ref is queued or running; enforced atomically, so two simultaneous requests queue one import), and 409
  `commit_already_imported` (a commit SHA that is already a version under another ref, named in
  the message; a tag and a branch at the same commit stay two versions).
- **Removing**: `DELETE /libraries/{owner}/{repo}/versions/{ref}` and `DELETE /libraries/{owner}/{repo}`
  answer 200 with `library`, `ref` (null for a library), `default_version` (what `/owner/repo`
  means now; null when no version is left) and `collection_job_id` (null if it could not be
  queued). The version or library is gone from browse, search and `list_libraries` (REST and
  MCP) when the call returns; a `collect` job (see `/jobs/{id}`) then frees the article texts and
  chunk sets no remaining version or library shares. A collection that is still queued for the
  library is reused. Removing the last version keeps the library, without versions.
- **Removal and imports**: an unknown library or version is 404. While an import of that version
  (of any version, for a library) is queued or running the call is refused with 409
  `import_in_progress`; removal never cancels a job. The removed version's (or library's) job
  history is deleted, so `/jobs/latest` shows no state for it. A re-sync of an existing version
  (E9-01) must be queued as a `refresh` job: it fails with 404 `not_found` at store time if the
  version was removed meanwhile, so a removal is never undone by a late sync. A first import is an
  `import` job.
- **Known limits**: chunk IDs of a removed version answer `not_found`; they are not kept as
  tombstones yet (E9-03 follow-up, the strict xfail in `test_chunk_store.py`). A library title
  derived from the default version's README (#33) is not re-derived by a removal.
