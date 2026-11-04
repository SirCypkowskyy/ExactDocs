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
- **Errors** have one shape for every error under `/api`: `{"error": "<code>", "detail": "<message>", "fields": []}`.
  Unknown routes and wrong methods are `not_found` / `method_not_allowed`; an unexpected failure
  is 500 `internal_error` (no internals in `detail`).
  `error` is the stable `DomainError.code` (`not_found` is 404, `conflict` 409, `validation_error`
  and every `ValidationError` 422, anything else 400). Request validation failures are 422 with
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
  `invalid_credentials`. `GET /session` returns `{"state": "setup_required" | "signed_out" |
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
  field is kept across re-imports instead of following the root README (LIB-07).
- **Adding a library**: `POST /libraries` (`{"url", "library_id"?, "ref"?, "include_paths"?,
  "exclude_paths"?}`) validates everything first, then stores the library with its selection and
  queues an `import` job; it answers 201 with `library_id`, `ref`, `ref_kind` (`tag`, `branch`
  or `commit`), `commit_sha` and `job_id`, and a `Location` header with the library. `ref` is a tag,
  a branch (a tag wins over a branch of the same name), or a full or short (7+ characters) commit
  SHA that is the tip of a branch or tag; omitted, it is the default branch. A ref that is
  not found is 422 `unknown_ref`, a short SHA that starts two commits 422 `ambiguous_ref`, a bad
  pattern 422 `invalid_path_pattern`, a taken ID 409 `library_id_taken`. Patterns are repo-relative,
  case-sensitive, never absolute or with `..`: `docs/` (a folder), `docs/**`, `*.md`,
  `{a,b}`; no `include_paths` means every `.md`/`.mdx` file, only those are ever articles, and an
  exclusion always wins. The library has no versions until its import has run; the job records the
  pinned ref and commit. `GET /repositories/refs?url=` lists `default_branch`, `branches` and `tags`
  (name and `commit_sha`, sorted), 1000 of each at most, with `truncated` set when more exist.
  Like `/repositories/check`, both accept `file://`, localhost and private addresses (see
  SECURITY.md).

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
  not take it from a release). Errors: 404 `not_found` (unknown library), 422 `unknown_ref` /
  `ambiguous_ref` (also 422 for a malformed library ID), 409 `version_exists` (the library already
  has that ref; re-importing is a sync, not this call), 409 `version_importing` (an import of that
  ref is queued or running; the check is not atomic, so two simultaneous requests may both pass
  and the later import replaces the first's version, wasting one import), and 409
  `commit_already_imported` (a commit SHA that is already a version under another ref, named in
  the message; a tag and a branch at the same commit stay two versions).
- **Removing**: `DELETE /libraries/{owner}/{repo}/versions/{ref}` and `DELETE /libraries/{owner}/{repo}`
  answer 200 with `library`, `ref` (null for a library), `default_version` (what `/owner/repo`
  means now; null when no version is left) and `collection_job_id`. The version or library is gone
  from browse, search and `list_libraries` (REST and MCP) when the call returns; a `collect` job
  (see `/jobs/{id}`) then frees the article texts and chunk sets no remaining version shares.
  Removing the last version keeps the library, without versions. An unknown library or version is
  404. While an import of that version (of any version, for a library) is queued or running the
  call is refused with 409 `import_in_progress`: removal never cancels a job, wait and retry.
  Chunk IDs of a removed version answer `not_found`; they are not kept as tombstones yet (E9-03 follow-up: the strict xfail in `test_chunk_store.py`). A library title derived from the default version (#33) is not re-derived by a removal.
