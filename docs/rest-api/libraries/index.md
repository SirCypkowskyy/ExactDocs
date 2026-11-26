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

## Pages

| Page | What it covers |
|---|---|
| [Adding libraries and versions](adding.md) | `POST /libraries`, refs and paths, the preview, credentials, `context7.json`, adding a version |

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

[^readable]: ../It lists only libraries the caller holds a role on. See
    [Library roles](../users-and-access.md#library-roles).

[^credential]: ../A `credential` needs a signed-in session. See
    [Private repositories](adding.md#private-repositories).

Paths, tag rules and chunking are on [Library settings](../library-settings.md), retrieval settings
on [Search and answers](../search.md#retrieval-mode-and-ai-overrides), and syncing on
[Syncing](../sync.md).

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

Where the importer looks and what it keeps: [Architecture](../../architecture/import/images.md#project-logos-504), *Project logos*.

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
