# Adding libraries and versions

!!! abstract "TL;DR"
    - `POST /libraries` validates first, stores the library with its selection and queues an
      `import` job; the library has no versions until that import has run.
    - A ref is a tag (which wins over a branch of the same name), a branch, a full or short commit
      SHA, or omitted for the default branch; no `include_paths` means every `.md`/`.mdx` file, and
      an exclusion always wins.
    - `POST /repositories/preview` is a dry run that stores nothing; at most two run at once, and a
      third gets 429 `preview_busy`.
    - A `credential` is accepted only on a signed-in session, stored encrypted and never returned.
    - A root `context7.json` sets paths when none are sent, and its title and description win over
      the README; `POST /libraries/{owner}/{repo}/versions` adds a version with the library's own
      settings.

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
| 409 `library_id_taken` | a taken ID ([Errors](../errors.md#taken-ids)) |

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

[^atomic]: ../Enforced atomically, so two simultaneous requests queue one import.

A tag and a branch at the same commit stay two versions.

<figure class="xd-shot" markdown>

![The Add a version form in a library's settings, with a branch or tag picker above the table of imported versions](../../assets/screenshots/add-version-light.webp#only-light){ loading=lazy }
![The Add a version form in a library's settings, with a branch or tag picker above the table of imported versions](../../assets/screenshots/add-version-dark.webp#only-dark){ loading=lazy }

<figcaption>Adding a version from a library's settings in the web UI.</figcaption>

</figure>
