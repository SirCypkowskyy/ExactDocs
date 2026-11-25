# Libraries and versions

!!! abstract "TL;DR"
    - `POST /libraries` validates everything first, stores the library and queues an `import`
      job; the library has no versions until that job has run.
    - `POST /repositories/refs` and `/repositories/preview` look at a repository before adding
      it, and nothing is stored.
    - A repository's root `context7.json` decides the paths of a library added without paths,
      and its `rules` come first in every `query-docs` answer.
    - `POST .../versions` adds a version with the library's own paths, tag rules and chunking.
    - Removal answers at once and a `collect` job frees what nothing else shares; it is refused
      while an import runs.

## Endpoints

| Method | Path | Purpose | Caller or role |
|---|---|---|---|
| `GET` | `/libraries` | list libraries | any caller[^readable] |
| `POST` | `/libraries` | add a library | any caller[^credential] |
| `GET` | `/libraries/{owner}/{repo}` | one library | `viewer` |
| `PATCH` | `/libraries/{owner}/{repo}` | edit title and description | `admin` |
| `DELETE` | `/libraries/{owner}/{repo}` | remove the library | `creator` |
| `GET` | `/libraries/{owner}/{repo}/logo` | the library's logo | `viewer` |
| `GET` | `/libraries/{owner}/{repo}/access` | whether a credential is stored | `viewer` |
| `PUT` | `/libraries/{owner}/{repo}/default-version` | pin the default version | `admin` |
| `DELETE` | `/libraries/{owner}/{repo}/default-version` | unpin it | `admin` |
| `GET` | `/libraries/{owner}/{repo}/versions` | list versions | `viewer` |
| `POST` | `/libraries/{owner}/{repo}/versions` | add a version | `contributor`[^credential] |
| `DELETE` | `/libraries/{owner}/{repo}/versions/{ref}` | remove a version | `admin` |
| `POST` | `/repositories/check` | check a repository | any caller[^credential] |
| `GET` | `/repositories/refs?url=` | a repository's branches and tags | any caller |
| `POST` | `/repositories/refs` | the same, with a credential | any caller[^credential] |
| `POST` | `/repositories/preview` | dry run of an import | any caller[^credential] |

[^readable]: It lists only libraries the caller holds a role on. See
    [Library roles](users-and-access.md#library-roles).

[^credential]: A `credential` needs a signed-in session. See
    [Private repositories](#private-repositories).

Paths, tag rules and chunking are on [Library settings](library-settings.md), retrieval settings
on [Search and answers](search.md#retrieval-mode-and-ai-overrides), and syncing on
[Syncing](sync.md).

## Adding a library

`POST /libraries` with `{"url", "library_id"?, "ref"?, "include_paths"?, "exclude_paths"?}`
validates everything first, then stores the library with its selection and queues an `import`
job.

It answers 201 with:

- `library_id`
- `ref`, and `ref_kind` (`tag`, `branch` or `commit`)
- `commit_sha`
- `job_id`
- a `Location` header with the library

`ref` is one of:

- a tag; a tag wins over a branch of the same name
- a branch
- a full or short (7+ characters) commit SHA that is the tip of a branch or tag
- omitted: the default branch

| Error | When |
|---|---|
| 422 `unknown_ref` | a ref that is not found |
| 422 `ambiguous_ref` | a short SHA that starts two commits |
| 422 `invalid_path_pattern` | a bad pattern |
| 409 `library_id_taken` | a taken ID ([Errors](errors.md#taken-ids)) |

The library has no versions until its import has run; the job records the pinned ref and commit.

### Path patterns

Patterns are repo-relative and case-sensitive, never absolute or with `..`.

| Pattern | Means |
|---|---|
| `docs/` | a folder |
| `docs/**`, `*.md`, `?`, `{a,b}` | globs |
| no `*`, `?` or `{` | a path: a file, or a folder and everything below it,<br/>with or without a trailing `/` |
| `[` | a plain character (no character classes),<br/>so `app/[locale]` is a folder |

- No `include_paths` means every `.md`/`.mdx` file. Only those are ever articles.
- An exclusion always wins.

### Looking at a repository first

=== "`GET /repositories/refs?url=`"

    Lists `default_branch`, `branches` and `tags` (name and `commit_sha`, sorted), 1000 of each at
    most, with `truncated` set when more exist.

=== "`POST /repositories/refs`"

    Body `url`, optional `credential`. Gives the same answer for a private repository. The
    credential travels in the body, never in a URL, and is not stored.

=== "`POST /repositories/preview`"

    Body `url`, optional `ref`, `include_paths`, `exclude_paths`, `credential`. A dry run:

    - It fetches the commit and its trees only (`--filter=blob:none`, depth 1, no checkout).
      Git's process limits, and the fetch deadline and size watchdog, apply.
    - It also fetches the root `context7.json` alone (see [below](#context7json): a second
      blob-less fetch under a preview slot).
    - It answers `ref`, `ref_kind`, `commit_sha`, `files` (sorted, 1000 at most), `total`,
      `truncated`, `include_paths`, `exclude_paths`, `context7` and `context7_warning`.
    - The same selection rules as the import decide, so nothing is stored.
    - Sizes are not included: they would need the blobs.

    Errors are those of adding a library, plus 422 `commit_unavailable`, and 422
    `repository_too_large` when the fetch or the tree listing is too large.

    It does a real fetch of the commit's trees, so it is slower than `/repositories/check`. At
    most two run at once, and a third waits a few seconds, then gets 429 `preview_busy` with a
    `Retry-After` header (seconds).

!!! warning
    - Paths are untrusted text; render them as text.
    - Like `/repositories/check`, all of them accept `file://`, localhost and private addresses
      (see SECURITY.md).

## Private repositories

A `credential`, `{"kind": "token", ...}` or `{"kind": "ssh_key", ...}`, is accepted by:

- `POST /repositories/check`
- `POST /repositories/refs`
- `POST /repositories/preview`
- `POST /libraries`
- `POST /libraries/{owner}/{repo}/versions`

Only on a signed-in session: an API token gets 401.

- It is stored encrypted for that library and its host, and never returned.
- A deploy key keeps its line breaks (`\n` in JSON). One sent on a single line, or with a
  passphrase, is 422 `invalid_credential` with a sentence saying so.
- `GET /libraries/{owner}/{repo}/access` answers `{"private": true | false}`: whether the library
  has a stored credential.

## `context7.json`

A repository's root `context7.json` (LIB-06) is read when a library is added or previewed, and
again by every import.

### Reading it

- For an add or a preview, only that one file of the pinned commit is read: its tree entry, then
  its blob.
- Reading it for an add or a preview uses a preview slot, never an import's, and waits for one
  only as long as a preview does.
- When every slot stays busy:
    - an add sent without paths answers 429 `preview_busy` (with `Retry-After`) before anything is
      stored, because the file would decide the library's paths for good
    - a preview, or an add with paths, goes on with a warning instead

### Keys

Used keys: `projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`,
`previousVersions`. Others (`$schema`, `url`, ...) are ignored.

### Paths

Sent without `include_paths` and `exclude_paths`, `POST /libraries` and
`POST /repositories/preview` apply its folders and exclusions:

- A folder is that path and all below it. `.` is the whole repository; a leading `./` or `/`
  means the root.
- An excluded folder or file given by its bare name (`archive`, `CHANGELOG.md`) is excluded
  wherever it is; one with a `/` (`./docs/internal`) only at that path.
- Globs are taken as patterns.

Paths a user sends win. To import every article and ignore the file's paths, send
`"include_paths": ["**"]`. The library keeps the paths it was created with for every later
version, until they are edited with `PUT /libraries/{owner}/{repo}/settings`.

### Title, description and rules

- The default version's `projectTitle` and `description` win over its README; a user's edit wins
  over both.
- Its `rules` (at most 20 distinct ones of at most 500 characters) are stored on the library
  (`rules` in `GET /libraries/{owner}/{repo}`).
    - They come first in every `query-docs` answer, under a heading that marks them as untrusted
      repository text.
    - They take at most a quarter of the size budget: whole rules, from the first one on, until
      one does not fit.
    - They are the default version's rules: `query-docs` for `/owner/repo/<ref>` shows them too,
      not that version's.

### In the responses

Both responses carry:

- `include_paths` and `exclude_paths` (what is applied)
- `context7`: the parsed file, with its paths translated, its `rules`, `previous_versions`
  (`tag`, `title`) to offer for import with `POST /libraries/{owner}/{repo}/versions`, and `notes`
- `context7_warning`

Problems with the file:

- A `previousVersions` entry whose tag git would not accept as a ref name (`--upload-pack=x`,
  `a..b`) is left out and named in `notes`. The rest of the file still applies.
- A file that is not a JSON object of the right types, larger than 64 KiB, or that cannot be read
  is ignored: `context7` is null and `context7_warning` says why.
- An import lists both kinds as `context7` problems of its job (the import goes on).

!!! warning
    All of it is untrusted repository text.

## Editing a library

`PATCH /libraries/{owner}/{repo}` with `{"title"?, "description"?}`. An edited field is kept
across re-imports instead of following the default version's `context7.json` or root README
(LIB-07).

## Pinning the default version

`PUT /libraries/{owner}/{repo}/default-version` with `{"ref"}` makes that version what
`/owner/repo` without a ref means, even after a higher stable tag is imported (LIB-10). The ref is
an imported ref exactly as listed, or a unique short SHA of a commit version.

- `DELETE` on the same path unpins it, and the default follows the *Default version* rule again.
- Both answer 200 with the library.
- Libraries carry `default_pinned` (also in the MCP `list_libraries` tool).
- Removing the pinned version unpins the library.

| Error | When |
|---|---|
| 404 `not_found` | a ref the library has not imported (refs are case-sensitive),<br/>or an unknown library |
| 422 | a missing or empty ref, a malformed library ID or ref,<br/>or a short SHA that matches more than one commit version |

!!! note
    Changing the pin does not re-derive the title, description and logo from the new default's
    README (LIB-07). Re-import the new default to refresh them.

## Library logos

Libraries (#504) carry `logo` in `GET /libraries`, `GET /libraries/{owner}/{repo}` and every
answer that returns a library, MCP `list_libraries` too. It is the logo's version, 16 hex digits
of the SHA-256 of its bytes, or `null` when the importer found none.

`GET /libraries/{owner}/{repo}/logo` serves it from ExactDocs itself, never from the git host.

- Content: a PNG, JPEG or WebP as the repository has it, or an SVG as the importer cleaned it,
  with the stored type.
- `ETag` is the version; `If-None-Match` answers 304.
- Asset headers:
    - `X-Content-Type-Options: nosniff`
    - `Cross-Origin-Resource-Policy: same-origin`
    - `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox; ...`
- An SVG is an attachment, which an `<img>` still shows.

| Request | `Cache-Control` |
|---|---|
| `?v=` set to the current version | `private, max-age=31536000, immutable` (the URL changes with the logo) |
| otherwise | `private, no-cache` |

An old `v` gets the current logo, never a cached old one. A library without a logo (or unknown,
or hidden from the caller) is 404 `not_found`.

The logo is the default version's:

- Each import or re-sync of the version that is then the default looks for one and replaces the
  library's, or removes it when the version has none.
- Importing any other version changes nothing.
- A library imported before logos existed gets one at the next import of its default version
  (`versions/reimport`, a re-sync of a branch that moved, or a paths edit).

Where the importer looks and what it keeps: [Architecture](../architecture/import.md#project-logos-504), *Project logos*.

## Sizes on the lists

Sizes (#513) come with the lists:

| List | Field | Counts |
|---|---|---|
| `GET /libraries/{owner}/{repo}/versions` | `articles` | entries of the version's active manifest,<br/>what `list_articles` lists |
| | `chunks` | the chunks they are cut into for search,<br/>one per article path that holds it |
| | `embedded_chunks` | of those, the ones with a vector from the configured<br/>embedding model, in its current space |
| `GET /libraries` (and MCP `list_libraries`) | `article_count` | the articles of its default version,<br/>the one `/owner/repo` resolves to |

A count is 0, never null, when there is nothing to count:

- a library without a version
- a version not indexed
- `embedded_chunks` while no embedding model or vector store is configured, or while the
  configured model has no space yet or no vector of the version (a library with AI off is never
  sent to it)

The counts are read once per page whatever its size (a grouped query per domain, no request or
query per version), so the versions table and the overview need one request.

## Libraries by sync state

`GET /libraries?sync_state=failed` (repeatable, any job state) lists the libraries whose latest
sync, their newest `import` or `refresh` job, is in one of those states.

- A library that never synced matches none.
- A newer job of another kind (`embed`, `collect`, ...) does not change it.
- The catalog still filters, sorts and pages, so the filter works with every other filter,
  `cursor` and `offset`, and `total` counts the matches.
- The instance reads every library's latest sync in one grouped query.

## Adding a version

`POST /libraries/{owner}/{repo}/versions` with `{"ref"}` imports another version of an existing
library with the library's own include/exclude paths and tag rules (and chunking), so versions
stay comparable.

- The ref is resolved like when adding a library (tag over branch, full or short SHA).
- It answers 202 Accepted with the same body as adding a library (`library_id` is the existing
  library) and `Location: /api/v1/jobs/{job_id}`, the import job to poll. The version exists once
  its import has run.
- The default version is computed from the versions, so it moves when the import finishes:
    - a newer stable tag takes it
    - a branch does not take it from a release
    - a pinned default does not move

| Error | When |
|---|---|
| 404 `not_found` | unknown library |
| 422 `unknown_ref` / `ambiguous_ref` | as when adding a library;<br/>also 422 for a malformed library ID |
| 409 `version_exists` | the library already has that ref;<br/>re-importing is a sync, not this call |
| 409 `version_importing` | an import of that ref is queued or running[^atomic] |
| 409 `commit_already_imported` | a commit SHA that is already a version under another ref,<br/>named in the message |

[^atomic]: Enforced atomically, so two simultaneous requests queue one import.

A tag and a branch at the same commit stay two versions.

<figure class="xd-shot" markdown>

![The Add a version form in a library's settings, with a branch or tag picker above the table of imported versions](../assets/screenshots/add-version-light.webp#only-light){ loading=lazy }
![The Add a version form in a library's settings, with a branch or tag picker above the table of imported versions](../assets/screenshots/add-version-dark.webp#only-dark){ loading=lazy }

<figcaption>Adding a version from a library's settings in the web UI.</figcaption>

</figure>

## Removing

`DELETE /libraries/{owner}/{repo}/versions/{ref}` and `DELETE /libraries/{owner}/{repo}` answer
200 with:

| Field | Meaning |
|---|---|
| `library` | the library |
| `ref` | null for a library |
| `default_version` | what `/owner/repo` means now; null when no version is left |
| `collection_job_id` | null if it could not be queued |

- The version or library is gone from browse, search and `list_libraries` (REST and MCP) when the
  call returns.
- A `collect` job (see `/jobs/{id}`) then frees the article texts and chunk sets no remaining
  version or library shares.
- A collection that is still queued for the library is reused.
- Removing the last version keeps the library, without versions.

### Removal and imports

- An unknown library or version is 404.
- While an import of that version (of any version, for a library) is queued or running, the call
  is refused with 409 `import_in_progress`.
- Removal never cancels a job. Cancel it first: `POST /jobs/{id}/cancel`.
- The removed version's (or library's) job history is deleted, so `/jobs/latest` shows no state
  for it.
- A re-sync of an existing version (E9-01) must be queued as a `refresh` job. It fails with 404
  `not_found` at store time if the version was removed meanwhile, so a removal is never undone by
  a late sync. A first import is an `import` job.

!!! info "Known limits"
    - Chunk IDs of a removed version answer `not_found`. They are not kept as tombstones yet
      (E9-03 follow-up, the strict xfail in `test_chunk_store.py`).
    - A library title derived from the default version's README (#33) is not re-derived by a
      removal.
