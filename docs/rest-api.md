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
- **Errors** have one shape for every error under `/api`: `{"error": "<code>", "detail": "<message>", "fields": [], "close_matches": [], "library_id": null}`.
  Unknown routes and wrong methods are `not_found` / `method_not_allowed`; an unexpected failure
  is 500 `internal_error` (no internals in `detail`).
  `error` is the stable `DomainError.code` (`not_found` is 404, `conflict` 409, `validation_error`
  and every `ValidationError` 422, `unauthenticated` 401, `forbidden` 403 (a signed-in caller who
  may not do this), `rate_limited` 429 with a `Retry-After` header in seconds, anything else 400). Request validation failures are 422 with
  `error: "validation_error"` and one `fields` entry (`loc`, `msg`, `type`) per invalid field.
- **First run**: until the first admin account exists, every `/api/v1` request except
  `POST /api/v1/setup`, `GET /api/v1/session` and the OpenAPI document is refused with 403
  `setup_required`, whatever the method (HEAD and OPTIONS included). `POST /api/v1/setup` creates the
  admin once (409 `already_set_up` afterwards). Only `/api/v1` is guarded: `/mcp` is
  guarded by its own API-token check instead (see Authentication).
- **Authentication**: every `/api/v1` operation needs a caller (401 `unauthenticated` otherwise):
  the session cookie, or `Authorization: Bearer exd_...` with an API token (a wrong bearer is
  refused even if a valid cookie is sent too). Exempt: `POST /setup`, the three `/session`
  operations, `POST /tokens/login`, the two external sign-in navigations
  (`GET /auth/{provider}/start` and `/callback`) and the OpenAPI document; a test pins that list, and
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
  live in the server's memory on SQLite (a restart clears them) and in the database on
  PostgreSQL, where every server process shares them. Only these two operations document 429. `GET /session` returns `{"state": "setup_required" | "signed_out" |
  "signed_in", "account": ..., "providers": [{"name", "display_name"}]}` and never fails
  (`providers` lists the configured identity providers, empty while setup is due); `DELETE /session` ends the session on the server
  and is always 204. The cookie is an opaque random token (stored hashed), HttpOnly,
  SameSite=Lax, `Secure` over HTTPS (or with `EXACTDOCS_SECURE_COOKIES`), `Path=/api`, ends after
  7 days idle or 30 days in all. Unsafe requests with a foreign `Origin` are refused with 403
  (also sign-in and sign-out). `/mcp` never looks at the cookie; it takes API tokens only. Signing in again with a live
  cookie ends that old session. The cookie's `Max-Age` is the 30-day limit; idle expiry is
  server-side only and accurate to about an hour (last use is written at most hourly), so do not
  test exact 7-day boundaries from a client.
- **External sign-in** (OIDC, ACL-01): browser navigations, not API calls; both answer with a
  303 redirect, are reachable without a caller and stay behind the setup guard.
  `GET /auth/{provider}/start?return_to=/path` stores a sign-in attempt (random `state`, `nonce`
  and PKCE verifier, 10 minutes, usable once, in the database so any server process can finish
  it), sets the `exactdocs_sign_in` binding cookie (random, only its SHA-256 stored; HttpOnly,
  SameSite=Lax, `Path=/api/v1/auth`, `Max-Age=600`, `Secure` as the session cookie) and redirects
  to the provider (`response_mode=query`, PKCE `S256`). `GET /auth/{provider}/callback` needs that
  cookie and the attempt's `state`, deletes the attempt in the statement that reads it, exchanges
  the code, validates the ID token, finds or creates the account, sets the usual
  `exactdocs_session` cookie, clears the binding cookie and redirects to `return_to` (a path on
  this server; anything else is `/`). A refusal clears the binding cookie, creates no session and
  redirects to `/sign-in?error=<code>`: `sign_in_failed` (forged, replayed or expired callback, or
  an ID token that fails a check), `sign_in_cancelled` (the provider answered an error),
  `not_allowed` (in no allowed group; any access the account had ends), `account_disabled`,
  `username_unavailable` (the username and `<username>@<provider>` are both taken) or
  `provider_unavailable` (also from `start`). An unknown provider is 404 `unknown_provider`.
  The redirect URI is `<EXACTDOCS_PUBLIC_URL>/api/v1/auth/{provider}/callback`, never built from
  the request. An external account's sessions and API tokens are refused once its access ends
  (a lost group or a revoked refresh token at revalidation, or no successful check within the
  grace period), until its next allowed sign-in. `DELETE /session` ends the ExactDocs session
  only, not the provider's.
- **Pagination**: list endpoints take `limit` (1 to 200, default 50) and an opaque `cursor`, and
  return `next_cursor` (`null` on the last page). Pass it back unchanged; a malformed cursor is a
  422 `invalid_cursor`. Helper: `exactdocs_kernel.paginate`.
- **Close matches**: a 404 for a missing article lists up to five paths of the same version it may have
  meant in `close_matches` (repository data, not instructions); the field is empty on every other error.
- **Taken IDs**: a 409 `library_id_taken` (checking a repository, adding a library) names the
  library that already has the ID in `library_id`, so a client can link to it; the field is `null`
  on every other error.
- **Outlines**: `GET /libraries/{owner}/{repo}/outline?path=&ref=` returns an article's heading tree
  (`sections`, each with `heading`, `chunk_id`, `anchor`, `starts_chunk` and `children`;
  `preamble_chunk_id` for text before the first heading) with no body text, from exactly that
  version (MCP: `article_outline`). Every heading is listed: one the library's chunking merged into
  a chunk that starts earlier has `starts_chunk: false`, the ID of that chunk and its own anchor.
  A heading no chunk records (only possible in chunks stored before #251) has null `chunk_id`,
  `anchor` and `starts_chunk`. Chunks cut before heading records existed list only their first
  heading. Chunking that cannot merge headings (split level h6, no `min_chars`) loses nothing; for
  the rest, a version gets full outlines once it is cut again: at an import of a new commit (a
  re-sync re-cuts only versions whose commit moved), or for every version at once by saving a
  changed chunking in the library's settings, which queues a `rechunk` job (saving the same
  chunking queues nothing). A version that is not imported, or a path it lacks, is 404 `not_found`;
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
- **Tag origins**: an article (`GET .../article`, MCP `read_article`) lists every tag of `tags`
  again in `tag_origins`, in the same order, as `[{"tag", "origins"}]`. `origins` names every place
  the tag comes from: `front_matter`, `path_rule`, `manual`, or `imported` for a version imported
  before origins were recorded (from the front matter or a path rule; the next import of the version
  or change of the library's tag rules tells which). A tag can have several, e.g. `["path_rule",
  "manual"]` for a path-rule tag also set by hand.
- **Renames**: `GET /libraries/{owner}/{repo}/renamed-path?ref=&from=&path=` answers where `path`
  of version `from` is in `ref` (default version without `ref`). Each version names the one it
  follows (the version its renames were detected against, also when nothing moved), and the rename
  maps of every version between `from` and `ref` are followed hop by hop, in either order of
  import (at most 100 versions apart): `new_path` is the path in `ref`, `old_path` the path asked
  about, `similarity` the lowest of the moves. Versions with no import link between them (two
  branches, a branch and a tag, a version removed in between) answer `null`, and so does a path
  renamed and later dropped before `ref`: never a path of another version. Without `from`, one hop across the renames git saw when `ref` was imported:
  `direction=forward` (default): `path` is from the version imported before `ref`; `back`: `path`
  is an article of `ref`. It answers 200 `{"renamed": {"library", "ref", "from_ref", "old_path",
  "new_path", "similarity"} | null}`; `null` means the path was not moved (or no renames are
  known; nothing is guessed). An unknown library or version (`ref` or `from`), or a `ref` without
  an active manifest, is 404 `not_found`. A branch's map builds up over its syncs; it links to no
  other version. A version imported before #201 where nothing moved has no link until it is
  imported again. Adding an older tag after a newer one (`v1.3.0` after
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
- **Users** (ACL-06): the local accounts, managed by an operator (an account with role `admin`;
  the first admin is one). There is **no self-signup** route: an account is made by the setup
  (the first admin only), by `exactdocs user create`, by a first sign-in through an identity
  provider, or here. `GET /users` lists every account (`id`, `username`, `role`, `created_at`,
  `disabled`, `provider` (`null` for a local account) and `groups` (the provider's, as of the
  latest sign-in or revalidation); oldest first). `POST /users`
  (`{"username", "password", "role"?}`, role `user` (default) or `admin`) answers 201 with the
  account; a taken name (compared case-insensitively) is 409 `username_taken`, and a name holding
  `@address:` (the sign-in throttle's own key separator) is 422 `invalid_username`.
  `POST /users/{id}/disable` locks the account out at once: its sessions are deleted, its API
  tokens revoked, and sign-in answers it with the same 401 `invalid_credentials` as a wrong
  password; a session or token that slipped through is refused on use. Disabling the last
  enabled admin is 409 `last_operator`. `POST /users/{id}/enable` lets it sign in again with its
  password (revoked tokens stay revoked). `PUT /users/{id}/password` (`{"password"}`) sets a new
  password, ends every session, revokes the tokens and clears the username's sign-in throttle
  count and remembered addresses, like `exactdocs admin reset-password`; it answers
  `{"account", "throttle"}` (`cleared`, `busy` or `failed`; the password changed in every case).
  An account of an identity provider has no password: 409 `external_account`.
  An unknown id is 404 `unknown_account`. Every `/users` route needs the **session cookie** of an
  operator: an API token is 401 (a stolen token cannot create accounts), and a signed-in account
  that is not an `admin` gets 403 `forbidden`. Library roles (who may read or change a library)
  are separate and not enforced yet (E12-05): every signed-in account may use every library.
- **Editing a library**: `PATCH /libraries/{owner}/{repo}` (`{"title"?, "description"?}`). An edited
  field is kept across re-imports instead of following the default version's `context7.json` or
  root README (LIB-07).
- **Editing paths, tag rules and chunking** (LIB-09, TAG-02, IMP-03): `PUT
  /libraries/{owner}/{repo}/settings` with `{"include_paths", "exclude_paths", "tag_rules",
  "chunking"}` replaces the paths and tag rules as a whole set (what is left out is cleared; `GET
  /libraries/{owner}/{repo}` has the current `settings`) and the chunking when it is sent:
  `chunking` left out or `null` keeps the stored one, so a client that edits only paths and tag
  rules (the web UI) never resets it, validated like `POST /libraries` (422 `invalid_path_pattern`
  / `invalid_tag` / `invalid_chunking_config` or a field error, nothing stored), 404 for an unknown
  library. `chunking` is `{"split_level": 1-6, "min_chars": 0, "max_chars": null, "chunker":
  "markdown"}` (the defaults): `split_level` is the deepest heading that starts a chunk (`2` cuts
  at `#` and `##` only); a chunk longer than `max_chars` is cut again at its deeper headings (never
  inside a code block or table, so a section without deeper headings stays whole); chunks shorter
  than `min_chars` are merged with the next one (the last with the one before) as long as the
  result stays within `max_chars`, and the text before the first heading is never merged (a merged
  chunk keeps the heading path and anchor of its first section, so a hit in a later section of it
  links to that first heading); `max_chars` must not be smaller than `min_chars` (both at most
  1,000,000, and at most 8,000 when sent, or 422 `invalid_chunking_config`: no chunk is longer, so
  a bigger `max_chars` would never cut and a bigger `min_chars` never merge; settings stored before
  that limit still load, and their larger sizes have no effect). Whatever the settings, a chunk is
  at most 8,000 characters (about 2,000 tokens; `max_section_chars` in `ChunkingConfig`, not yet a
  setting): a longer group of sections is cut again at its deeper headings and merges stop there,
  and a section still longer is split between its top-level blocks (never inside a code block,
  table, list or MDX component, so only a single block longer than that makes a longer chunk);
  every part keeps the section's heading path, anchor and occurrence index, and only the first
  records the heading in the outline. `markdown` (markdown-it-py) is the only chunker. Every
  version is then re-processed by **one** job, at the commit it serves (a branch is not synced):
  changed paths queue a `reprocess` job that fetches each version again and re-imports it
  (unchanged blobs reuse their chunks); a changed chunking (paths unchanged) queues a `rechunk` job
  that copies what each version serves into a new manifest, re-derives its tags and cuts the
  **stored** text again, fetching nothing (a blob already cut with that chunking reuses its chunks;
  a version stored by an older parser, or holding a rare article whose stored text cannot be cut
  exactly as its import cut it, is re-imported at its commit instead, so such a version needs the
  repository to be reachable whenever its chunking changes); only tag rules changed queue a `retag`
  job that derives each stored article's tags again from its stored front matter and the new rules,
  fetching and chunking nothing (manual tags stay). Each version keeps serving its old state (its
  old chunks too) until its new one is complete and then switches at once: a new manifest
  activated, or, for a `retag`, the version's catalog entries re-tagged in one transaction, with
  search's tag copies following a moment later under the same lock (as for manual tags; a rerun of
  the job always brings them in line). A version that cannot be re-processed keeps what it had, the
  others go on, and the job fails naming it (`error_code` the failures' shared code, else
  `reprocess_failed`); sending the same settings again then queues that job again. A job redoes
  what the smaller ones do (`reprocess` > `rechunk` > `retag`): while a wider one failed and has
  not been redone, a retry or a smaller edit queues the wider one, so a smaller job never hides
  that failure. The jobs count `done` / `total` in versions. The answer is **202** with the job in
  `Location` and the body's `job_id`, `reprocess` (`paths`, `chunking` or `tags`), the stored
  `chunking` and `versions` (the library's refs, which the job re-processes), or **200** with
  `job_id: null` when nothing changed and the last re-processing did not fail, or the library has
  no version yet (imports to come use the new settings). Edits of one library take turns. A queued
  job that does at least what is needed is reused. Removal waits for these jobs like for an import.
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

- **Retrieval mode and AI overrides** (RET-06): `PUT /libraries/{owner}/{repo}/retrieval` with
  `{"mode": "hybrid", "ai_enabled": true, "llm": "corp:small", "judge": null, "reranker": null,
  "rerank_top_n": 16, "rerank_with": "judge", "budgets": {"daily_usd": 1, "monthly_tokens": 500000},
  "repo_guidance": "notes"}` replaces the library's settings (every field is optional; an omitted one takes its default).
  `mode` is the mode its searches use when a call names none (`null`: the instance's
  `EXACTDOCS_AI__MODE` applies, else the best default mode configured, which is BM25 unless a
  mode the eval suite made a default can run, and none is yet); it must be available with the
  settings sent: 422 `mode_unavailable` names the model role it needs that is not configured, or
  says the vector store is unavailable (its extension cannot be loaded: sqlite-vec on SQLite,
  pgvector's `vector` on PostgreSQL; `fallback_reason` `vector_store_unavailable` where a setting
  is skipped for that reason).
  `ai_enabled: false` sends nothing of the library to any AI provider: its searches are BM25.
  `llm`, `judge` and `reranker` (`<profile>:<model>`) replace the instance's role for this library
  (404 `unknown_provider` for a profile that does not exist, 422 `provider_unsupported` for one this
  installation cannot call (an extra or SDK is missing), 422 `invalid_model` when not written
  `<profile>:<model>`); there is no `embedding` override (one vector space per instance).
  `rerank_top_n` (1 to 200) is how many of its best candidates the reranker reorders (`null`: the
  instance's `EXACTDOCS_AI__RERANKER__TOP_N`, 32 by default).
  `rerank_with` chooses what reranks its searches: `cross_encoder` (the `reranker` role) or
  `judge` (the `judge` role, else the `llm` role: an LLM rates every candidate in one call);
  `null`: the instance's `EXACTDOCS_AI__RERANK_WITH` (`cross_encoder` by default). The judge
  reranks only when chosen; chosen without a judge configured, the cross-encoder reranks.
  `repo_guidance` is what the repository's `AGENTS.md` / `CLAUDE.md` do for agentic search (RET-08):
  `off` (the default: imports keep none), `notes` (each version keeps the root's and the selected
  folders' files, even outside the selected paths, and a folder's file reaches the agent as an
  untrusted user-channel note when it opens that folder) or `trusted` (as `notes`, and the root's
  file is also part of the agent's system instructions). 422 for any other value. Turning it on
  (`off` to `notes` / `trusted`) queues a `reprocess` job of the library (see
  `GET /libraries/{owner}/{repo}/jobs`), which re-imports every version at its commit so it keeps
  its files; `notes` / `trusted` / `off` otherwise apply at the next search.
  `budgets` are the library's own spend limits per UTC day and month (`daily_usd`, `monthly_usd`,
  `daily_tokens`, `monthly_tokens`; `null`: not limited by the library). Each may be at most the
  instance's: the lowest of `[ai.budgets]`'s instance and `per_library_...` ceilings of that
  window and unit, 422 `budget_above_instance` otherwise. A stored budget the instance's limit was
  lowered below since may be sent again unchanged or lowered (the instance's, the tighter, applies);
  only raising it is refused, so other settings can still be saved. The tighter of the library's and the
  instance's per-library limit applies, to its LLM steps, paid reranks and embedding alike.
  `GET .../retrieval` returns the settings with `instance_mode`, the `effective_mode` a search
  without `mode` runs in now (with `fallback_reason` when a setting is skipped), the
  `available_modes`, the `configured_roles` of the library, the `effective_rerank_top_n`,
  `instance_rerank_with` and the `effective_reranker` (`cross_encoder`, `judge`, or `null` when
  nothing reranks), its `budgets` and the
  `budget_ceilings` they may not exceed (`null`: no ceiling), and its `repo_guidance`. 404 for an unknown library. A
  search's own `mode` (`GET /libraries/{owner}/{repo}/search?mode=`) always wins; an unavailable
  one is a 422 `mode_unavailable` as well. A `hybrid` search fuses the version's 50 best BM25
  chunks with its 50 nearest by vector (reciprocal rank fusion, `k` = 60); its `coverage.candidates`
  counts the chunks of both, once each. The vector half always runs, so a word no chunk of the
  version contains still gets the version's nearest chunks (never another version's). It never
  fails for its model: BM25 answers instead, with
  `fallback_reason` `embedding_in_progress` while the version is not embedded with the configured
  model, `llm_budget_reached` when a budget its query embedding counts to (embedding, instance,
  library or user) is used up, or `embedding_unavailable` when the model fails or times out on the
  query. A `hybrid_hyde` search embeds the LLM's hypothetical answer to the query instead of the
  query (BM25 still searches the query); the answer is cached per query, version and LLM, so a
  repeated query calls no LLM. Without that answer it answers `hybrid` (or BM25, as above) with
  `fallback_reason` `llm_budget_reached`, `llm_rate_limited`, or `llm_unavailable` when the LLM
  fails, answers nothing or does not answer within 10 s.
  A budget or the LLM search rate limit never fails a
  search: one that would run an LLM step answers in the best mode without one, with
  `fallback_reason` `llm_budget_reached` or `llm_rate_limited`, and a paid rerank over budget is
  skipped (`reranked: false`, `fallback_reason: llm_budget_reached`).
- **Agentic search** (RET-04): `mode=agentic` (never a default) lets an agent on the `llm` role
  browse the version (outlines, articles, chunks and BM25, all of that version only) and pick the
  chunks that answer the question. Its results are the picks the version holds and the call's
  tags allow, in the agent's order (`score` 1, 1/2, 1/3...), each with `justification` (the model's
  own sentence, untrusted text) and `explored_path` (the read calls up to the one that reached its
  article); other modes return `justification: null` and `explored_path: []`. Both are model
  output: control characters are removed, a justification is at most 600 characters, a path at
  most 50 calls of at most 120 characters of argument each. The call's tags apply to the agent's
  reads too.
  `coverage.candidates` counts the chunks the agent saw. A run past one of its limits
  (`[ai.agentic]`: tool calls, model requests, tokens, the sandbox's time, memory or host calls,
  its timeout) is answered by the best mode without an LLM step with `fallback_reason`
  `agent_limit_reached`; a budget reached during the run gives `llm_budget_reached`; the same
  call (tool and arguments) made `max_repeated_calls` times (3 by default) gives
  `agent_loop_detected`; a model that fails or answers nothing usable, or a read that fails on
  the server, gives `agent_failed`. The agent's reads are bound to the version and the call's
  tags (its `deps`, never a tool argument), and an output guardrail removes any pick outside
  them before the answer is used. A question that asks again (the same content words in the same
  order, numbers and negations; with an embedding model, its cosine confirms it at
  `[ai.agentic_cache] threshold`) what one answered agentically before asked for the same version (manifest), tags, `llm` model and limits
  is answered from that answer with `cache_hit: true` (every other search: `false`), its chunks
  checked again against the version and the tags; it calls no LLM and uses no budget. `query-docs`
  and the MCP tools carry `cache_hit` too.
- **Reranking** (RET-02): with a `reranker` role, a search's best candidates are reordered by the
  reranker (`reranked: true`, `coverage.reranked` counts them, and each reranked result's `score`
  is the reranker's). When `limit` is more than the top N, the reranked results come first and the
  rest follow in the mode's order with the mode's scores, which are not comparable with the
  reranker's. A reranker that times out or fails never fails the search: results keep
  the mode's order with `reranked: false` and `fallback_reason` `reranker_timeout` or
  `reranker_failed` (unless the mode itself fell back, whose reason is kept). With
  `rerank_with: judge` (#96), the LLM judge reorders them instead: each reranked result's `score`
  is its rating over 10 (0 to 1). It rates only the best candidates that fit one bounded call
  (at most 64, about 32 full-size English or code chunks, or 9 CJK; `coverage.reranked` counts them), and the rest keep the
  mode's order after them. Ratings that name an ID it was not given (it sees `c1` to `cN`, never
  chunk IDs), or are not one score from 0 to 10 per candidate, are refused (`reranker_failed`); a used-up budget or the LLM
  search rate limit skips it (`llm_budget_reached`, `llm_rate_limited`).

### AI providers

Admins only (every account is one until library roles exist). See [AI retrieval
decisions](decisions/ai-retrieval.md) for the kinds and what each needs.

- `GET /ai/providers`: every profile, the environment's and the TOML file's first
  (`origin: configuration`, `read_only: true`), then those stored here (`origin: api`). Never a
  key or a header value: `key` says where the key comes from (`none`, `sealed`, `file`,
  `environment`), `header_names` lists the headers; `roles` lists the instance roles that use the
  profile, `unsupported` says what this installation lacks to call it.
- `POST /ai/providers` (201) with `{"name": "gw", "kind": "openai-compatible", "base_url": ...,
  "api_key": ...}`: create one (409 `provider_exists`). `PUT /ai/providers/{name}`: create or
  replace (no `name` in the body). The key is sealed with the instance's secret key and never
  returned; without `api_key` the stored key is kept (`keep_key: false` removes it), unless the
  endpoint (kind, platform, `base_url`, `resource`, `project`, `location`, `proxy`) changed: then
  422 `invalid_provider` asks for the key again, so a stored key never follows a profile
  elsewhere. 409 `provider_read_only` for a configured name; 422 `invalid_provider` with the field
  at fault; 422 `provider_unsupported` when this installation cannot call the kind (the `[ai]`
  extra, boto3 for Bedrock); 422 `secret_key_required` for a key when the process has no secret
  key. A change counts at the next call, without a restart. The server's own cloud identity
  (`credentials: "adc"`, `credentials_file`, `auth: "entra"`, Claude on Bedrock) is refused here with 422
  `invalid_provider`: it is configured in the environment or the TOML file only, without a
  `base_url`. Extra `headers` that carry a credential (`Authorization`, `Cookie`, `x-api-key`,
  `api-key`, `*-key`, `*-token`, `*-secret`, `*-password`) are refused too: the key goes in
  `api_key`. `resource`, `location` and `project` must each be one DNS label (422
  `invalid_provider` otherwise): they become part of the endpoint's host or path.
- `GET /ai/providers/{name}`; `DELETE /ai/providers/{name}` (204; 409 `provider_in_use` while an
  instance role uses it; a library override naming it stops counting until it exists again).
- `POST /ai/providers/{name}/check`, optionally with `{"role": "embedding", "model": "e5"}`: one
  minimal call per instance role that uses the profile (or to the model named), each reported as
  `{"role", "profile", "model", "status": "ok" | "error", "latency_ms", "served_model",
  "dimensions", "error"}`. A failed call is a check with `status: error` (its text never holds a
  key), not a failed request; 422 `nothing_to_check` when no role uses the profile and no model is
  named.
- `GET /ai/roles`: the instance roles (`embedding`, `reranker`, `llm`, `judge`), each with its
  `model` (`<profile>:<model>`), its `source` (`instance`, or `llm` for a judge that defaults to
  the LLM) and whether its profile exists.
- `GET /ai/embedding/estimate`: what embedding every version not embedded yet would send and cost,
  before it runs (`exactdocs ai estimate` over REST): `{"model", "space_id", "versions", "chunks",
  "characters", "estimated_tokens", "usd_per_million_tokens", "estimated_usd", "note"}`;
  `characters` counts each chunk's text, heading path and article title, as embedded. Only
  active versions of libraries with AI on count, and each stored chunk once (a blob held by many
  versions is embedded once). Tokens are 4 characters each and the price is the bundled price
  list's (`null` for a model it does not know): an estimate, as `note` says. No model or
  tokenizer is called. `model` is `null` and the counts 0 when no embedding model is configured;
  400 `vector_store_unavailable` on an instance without a vector store. On PostgreSQL the
  estimate counts from the stored chunks, with or without pgvector's extension.
- `GET /ai/embedding`: the configured embedding model and how far each embedding space has got:
  `{"model", "spaces": [{"id", "profile_kind", "model", "dimensions", "state", "current",
  "created_at", "activated_at", "versions", "versions_embedded", "chunks", "chunks_embedded"}]}`.
  One entry per space that is not retired, oldest first; `current` marks the configured model's
  (while it is `building`, the older `active` one answers searches). `versions` counts the active
  versions of libraries with AI on and `versions_embedded` those it has a vector for every chunk
  of; `chunks` and `chunks_embedded` count per version, so a chunk two versions share counts
  twice. `spaces` is empty without a vector store or before anything was embedded.
- `GET /ai/usage`: what AI calls spent and what is left of each budget (`[ai.budgets]`):
  `{"at", "llm_searches_per_minute", "scopes": [{"scope", "id", "day", "month", "budgets"}]}`.
  `scope` is `instance`, `embedding` (embedding runs, instance-wide), `library` (`id` the library
  ID) or `user` (`id` the account ID); the instance and embedding come first, then every library
  and account that spent something this month. `day` and `month` are the current UTC windows:
  `{"input_tokens", "output_tokens", "tokens", "local_tokens", "requests", "usd",
  "unpriced_requests"}`, as the providers reported (an LLM step's tokens, which the harness does
  not split, are input tokens). `local_tokens` are those of in-process (`local`) models, included
  in the input and output tokens; `tokens`, what token budgets count, leaves them out.
  Each budget: `{"window", "window_start", "resets_at", "usd_limit", "usd_left", "tokens_limit",
  "tokens_left", "reached", "own_usd_limit", "own_tokens_limit"}` (`null` for a ceiling that is
  not set). A library with budgets of its own shows the tighter of its own and the instance's
  per-library ones, with `usd_left` and `tokens_left` against it; where the instance's is lower (it was lowered after
  the library set its own), `own_usd_limit` / `own_tokens_limit` give the library's own ceiling,
  otherwise they are `null`.

## Jobs, access and health

- **Jobs**: `GET /jobs/{id}` is one job (kind `import`, `refresh`, `reprocess`, `rechunk`, `retag`,
  `collect` or `embed`; state `queued`,
  `running`, `succeeded` or `failed`; `done` / `total` files, or chunks for `embed`; `chunked` / `reused`; `parsed` / `taken`; problems).
  An `embed` job embeds one version with the instance's embedding model; a failed one has
  `error_code` `embedding_failed` (its error names the model and the HTTP status, never a key) and
  is queued again at the next start, or `ai_budget_reached` when a budget its embedding counts to
  (embedding, instance or library) was used up before its next batch: it is queued again just
  after the UTC midnight that resets the window.
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
  if none is recorded), `reindex_required`: `true` when that format is older than this
  version's or not recorded, until `exactdocs reindex` has run (search keeps answering
  meanwhile), `search_engine`: the engine that answers searches, `fts5` (SQLite), `pg_search`
  (ParadeDB's BM25 on PostgreSQL) or `postgres_fts` (PostgreSQL full-text search, when the
  database has no `pg_search`), and `vector_store_missing`: once an embedding model is configured,
  the extension the vector store needs and cannot load (`sqlite-vec` on SQLite, `vector` on
  PostgreSQL), else `null`. When the database did not answer in time, `database_reachable` is
  `false` and the database fields are `null`. A request whose `Host` the instance does not trust gets only
  `{"status": "ok"}`. `GET /readyz` (readiness) answers 200 `{"status": "ready"}` when the
  database file exists, answers within 2 s and is at this version's schema revision, else 503
  `{"status": "not_ready", "reason": ...}` with a fixed sentence. Both keep their budget while a
  database statement is still running. Only exact `GET`/`HEAD`
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
