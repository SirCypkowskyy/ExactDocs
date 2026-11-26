# The import: a complete version or nothing

!!! abstract "TL;DR"

    - An import fetches the pinned commit, parses and chunks the selected files, then **stores** a
      pending manifest, **indexes** its chunks and **activates** it in one transaction. Readers see
      the previous state until then.
    - It runs as durable steps: a killed import resumes at its first unfinished step, and running a
      step twice changes nothing a reader sees.
    - Content is keyed by blob SHA, so unchanged files are neither parsed nor chunked again.
    - Hard limits keep it safe: 2 MiB per article, 256 MiB of text per import, sniffed image types,
      cleaned SVG logos, no symlinks.

The `import` kind is `ImportVersionUseCase` (built by `ingestion.import_job`, which also returns its
recovery hook). It imports the commit the job was pinned to:

1. fetch, read and parse every selected file;
2. tag and chunk;
3. **store** the articles as a pending catalog manifest;
4. **index** their chunks in retrieval;
5. **activate** the manifest.

Readers see the previous state until that last step, which is one transaction in the catalog.

## Steps (resumable, E3-11)

The import is a sequence of durable steps:

1. read the library's chunking settings, so a resumed import cuts and labels its chunks with the
   config its first run read, even if they were edited in between (`STEPS_VERSION` `jobs-4`);
2. list the selected files;
3. parse and chunk them `EXACTDOCS_IMPORT_BATCH_FILES` (100) at a time;
4. read the README and the images;
5. fetch the images outside the selection;
6. detect renames;
7. publish (store, index, activate).

What follows the publish is no step: renewing a newer version's rename map (#216), the
README/`context7.json` text and the default version's logo (#504). It never fails the import, works
on what is imported now and replaces whole maps, so a run killed there simply does it again.

How resuming works:

- A killed import resumes at its first unfinished step. An import killed after 120 of 200 files
  (batches of 20) parses and chunks files 121 to 200 only, and the version has each article once.
- A step's result carries everything later steps and the job's progress depend on (articles with
  their chunks, problems, bytes used), so a replay rebuilds the job as the first run left it.
- The commit is fetched only when a step needs its files: a resume with only publishing left fetches
  nothing.
- Each step reads the pinned commit. What publishing writes is keyed by content (contents by blob
  SHA and parser version, chunk sets by blob SHA and chunking config) or replaced as a whole (a new
  pending manifest), so running a step twice changes nothing a reader sees.
- Each image is kept by the one step that read it.

!!! note "Disk use of `jobs.sqlite`"

    The results stay in `jobs.sqlite` only while the job runs: at the peak about 3x the version's
    text on disk (the text, its chunks, pickled and base64-encoded by DBOS), plus its images. The
    workflow is deleted when the job ends and the file is compacted (`VACUUM`) once no workflow is
    left in it, so it does not keep that size.

## Steps of `reprocess`, `rechunk` and `retag`

\#61, #67, `STEPS_VERSION` `jobs-2`, then `jobs-4`.

1. First the library's versions, so a resumed job takes the same ones in the same order, even if one
   was added meanwhile.
2. Then **one step per version**:
    - `re-import <ref>` runs the refresh import inside it without steps of its own;
    - `re-chunk <ref>` runs the version's re-chunk;
    - `re-tag <ref>` runs its re-tag.

Details:

- The import's own steps are not used there. It reads the library and its credential before its
  first step, so a version that failed there and succeeded on a resume would take steps another
  version recorded.
- A version's result (files, chunk counters, problems, its failure) rebuilds the job's progress on a
  replay.
- A version killed halfway starts over (the recovery hook discards its pending manifest; a re-tag is
  safe to redo).
- The versions finished before are not done again, nor is a recorded failure retried by that job.

## Per-library chunking (E4-05)

A library's settings hold its chunking (`split_level`, `min_chars`, `max_chars`, `chunker`;
`ChunkingConfig`). `Chunker.configured(config)` gives the chunker an import cuts with; the config
hash keys its chunk sets.

Editing it queues a `rechunk` job. Per version:

1. The catalog's `CopyManifest` copies the active manifest into a pending one in one transaction
   (entries with their tags, images, renames; `INSERT ... SELECT`) and returns the stored text.
2. Ingestion re-derives the imported tags (`SetImportedTags` on the copy).
3. It takes the chunk sets retrieval already has for the new hash (`GetChunkSets`) and cuts the other
   blobs.
4. It indexes the copy and activates it like an import (manual tags last, under the tag lock).

Nothing is fetched: the stored text is what the parser gave. Whether its front matter was malformed
is recovered from the text and the blob SHA (`CopiedArticle.parsed`: the file was exactly that text).

When a version is re-imported at its commit instead:

- **The re-chunk cannot tell** (#228): a front matter that loaded to nothing, then a block YAML
  refuses; or invisible characters the parser stripped. So a re-chunk never cuts a blob differently
  from its import.
- **Another parser version** stored the text (`content_version`): the copy refuses it, since a chunk
  set keyed with the current parser must not be cut from older text.

!!! note "The cost of #228's fallback"

    A version holding such a file is fetched again by every re-chunk to a config its blob has no
    chunk set for yet, and that re-chunk fails while the repository is unreachable. Recording at
    import whether the front matter was malformed (with the manifest entry) would remove this; that
    is a possible follow-up.

- The copy is pending, so readers keep the old chunks until the activation; the recovery hook
  discards it after a crash.
- `reprocess` re-imports with the new chunking too, and `rechunk` re-tags, so one job of the widest
  kind needed is queued.

## Undo

- Any failure after the store (an exception or a cancellation) discards the pending chunks and then
  the pending manifest.
- The order matters: retrieval asks the catalog and only removes a manifest it is told is still
  pending.
- After a crash the recovery hook does the same for the library's pending data before the job
  resumes or runs again (a library has one running job).

## Chunks

### Heading records (#251)

- Each chunk records every heading it holds, in order (heading path, anchor, whether it starts the
  chunk), so `article_outline` lists headings a chunking config merged into one chunk.
- They are stored with the chunk set (`retrieval_chunks.headings`, NULL for chunks stored before)
  and travel back through `GetChunkSets`.
- They are not part of the set's digest: a set stored without them and one cut again with them share
  a key; the first write wins.
- A config that cannot merge headings (split level h6 and no `min_chars`; `max_chars` only cuts
  whole sections) kept its hash until #141 added the section bound (below).
- The others' hash names `MERGED_HEADINGS_VERSION`, so their chunk sets are cut again, with the
  records:
    - when a version is imported at a new commit (a re-sync of an unmoved version re-cuts nothing);
    - or when the library's chunking is changed, which queues a `rechunk` of every version.

    Until then their outlines list each chunk's first heading.

### Long sections (#141)

`ChunkingConfig.max_section_chars` bounds every chunk. The default is 8,000 characters
(`DEFAULT_MAX_SECTION_CHARS`): about 2,000 tokens at retrieval's `CHARS_PER_TOKEN`, the same as what a
reranker and the search agent are given of a chunk.

- Groups of sections are cut at deeper headings and merges stop there, as with `max_chars`.
- A section still longer is split between its top-level blocks (markdown-it tokens at level 0),
  parts as long as fit. A fence, table or list is never cut, and a single longer block is a chunk of
  its own.
- A heading is never left alone: the first part holds it and the block after it.
- Nor is an MDX component or block HTML element cut (`<Tabs>` ... `</Tabs>`, `<details>`):
    - CommonMark ends an HTML block at a blank line, so the chunker counts the open JSX components
      and block tags across top-level HTML blocks;
    - it also counts the tags that start a line of a top-level paragraph, not those in running text
      such as `Promise<Response>`;
    - it cuts nowhere while one is open;
    - the count starts again at each top-level heading, so a tag never closed keeps only the rest of
      its section whole.

### Chunk identity of parts (#141)

- A section is `(heading_path, occurrence_index)`. The occurrence counts the chunks that start a
  section with that heading path, so a section merged into the chunk before (by `min_chars` or
  `split_depth`) takes none.
- The first part of a split section is never merged into the chunk before, so a split section always
  starts a chunk and takes an occurrence.
- Its parts follow that chunk, share both and are numbered by `part` (`ArticleChunk.part`,
  `ChunkIn.part`, `Chunk.part`, `retrieval_chunks.part`, 0 for a whole section).
- `part` is in the chunk ID and the set digest only when above 0. A section that is not split keeps
  the ID and digest it had before, and a section growing past the bound changes no later section's
  ID.
- Only the first part records the heading: `ChunkIn` refuses a starting record on a part above 0,
  and a first part without its own.
- A stale ID's moved-section lookup (`_pick`) matches the same section, then the same part of it,
  else its first part.

!!! warning "Part IDs are not edit-stable"

    Parts are packed greedily from the start of the section, so a paragraph inserted near the top
    moves every later part boundary, and every part of that section gets a new ID (and is embedded
    again).

On upgrade to #141:

- The bound is in the config hash whenever it is set, so the default config's hash changed.
- Nothing is re-cut at once and stored versions keep serving their chunks.
- A version imported at a new commit, a re-import, or a `rechunk` (a chunking change) cuts every
  article again instead of reusing chunk sets, and libraries with embeddings embed the new chunks.
- A config without the bound (`None`) cuts as before and keeps its hash.

The chunker runs in `asyncio.to_thread` in both the import and the re-chunk (`_cut`).

### Sizes above the bound

- The settings API refuses a `max_chars` or `min_chars` above the bound (422
  `invalid_chunking_config`, `ChunkingConfig.refuse_sizes_above_section_bound`): such a `max_chars`
  would never cut and such a `min_chars` never merge.
- A config stored before the bound existed still loads and cuts; its larger sizes have no effect.

### Embedding window

- The bound follows what retrieval reads of a chunk, not an embedding model's input.
- The bundled local model (bge-small, 512 tokens) embeds only about the first 1,800 characters of a
  chunk. `embedding_text` prepends the title and heading path, which helps the parts after the
  first.
- Lexical search, the reranker and the agent still see the whole chunk.
- Embedding the rest (several windows per chunk) is left to the embedding side (#347).

## Reuse

- Content is keyed by git blob SHA and the parser version, chunk sets by blob SHA and the chunking
  config, so a blob that an earlier import chunked is not chunked again. The stored chunks are read
  back through retrieval's `GetChunkSets`.
- **Parsing is skipped too** (#164) for a file some manifest of the library holds at the same path,
  blob SHA and parser version (`FindStoredArticles`). The title and the image links depend on the
  path, the rest on the bytes and the parser.
    - The version's own active manifest is looked in first (by primary key), then the library's
      other manifests, one probe per file through the blob-SHA index. The lookup stays far cheaper
      than the parse whatever the size of the catalog.
    - Title, front matter and text are taken as stored. The tags are derived again from the stored
      front matter and the library's rules now, the image links from the text.
    - Whether a text that starts with a `---` block was malformed front matter (kept in the text,
      with a note to list again) is told from the blob SHA (`stored_front_matter_problems`, shared
      with the re-chunk).
    - A text it cannot tell (a front matter that loaded to nothing before a block YAML refuses, or
      invisible characters the parser stripped, #228) is parsed anyway.
- Importing a commit again changes nothing a reader can see.

## Memory

- The selected text is held in memory until stored, and again as chunks, as DTOs in the bridges and
  as SQL parameters: several times over. The worker runs two jobs at once, and a resumed import loads
  its stored steps back into memory the same way.
- `EXACTDOCS_MAX_IMPORT_BYTES` (256 MiB) bounds the text an import takes. Above it the import fails
  with `import_too_large` instead of the process being killed.
- The CPU-heavy part of storing and indexing (DTO validation, sorting, chunk-ID hashing) runs in a
  thread so the event loop keeps serving requests.
- Progress is stored every 100 files or 250 ms, and at the end.

## Images

### Collecting

- Articles' relative `![](...)` images are collected at parse time, resolved against the article's
  folder, as the web renderer does. Absolute URLs, `data:` and paths leaving the repository are
  ignored.
- The first checkout already holds those inside the selected paths. The rest come from a second,
  literal-path `GitGateway.fetch_files` (glob characters escaped, no README, its own download
  limit).

### Limits

| Limit | Value |
|---|---|
| per image | `EXACTDOCS_MAX_IMAGE_BYTES` (2 MiB); a plain file, never a symlink |
| type | **sniffed from the bytes**: PNG, JPEG, GIF, WebP or SVG; anything else is `not_an_image` |
| per version | 1000 images and `EXACTDOCS_MAX_IMAGES_BYTES` (64 MiB) |

The rest, and images the repository lacks, are listed as skipped problems of the job and never fail
it.

### Storing

The catalog stores each blob once (`catalog_image_blobs`, keyed by git blob SHA) and lists them per
manifest (`catalog_manifest_images`), so they are activated, superseded, removed and collected (#45)
together with the articles.

### Serving

`GET /api/v1/libraries/{owner}/{repo}/asset?ref=&path=` serves them to signed-in callers only, like
every `/api/v1` route. No `ref` means the default version. The response carries:

- the stored type;
- `X-Content-Type-Options: nosniff`;
- `Cache-Control: private, no-cache`;
- `ETag` = blob SHA (`If-None-Match` answers 304);
- `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`.

!!! info "Why SVG is served"

    **SVG** is served, not rasterized or refused: it is what diagrams are made of. In an `<img>` a
    browser runs no script and loads nothing, and opened directly it is an attachment under that
    CSP, so a hostile SVG can neither run nor phone home. SVGs declaring entities are refused.

Not stored: images in raw HTML, MDX components or front matter.

## Project logos (#504)

A library carries the logo of its **default version**, as it takes that version's title and
description (LIB-07), so an import of an older tag never replaces it.

### Where it is found

After the publish, an import or re-sync of the version that is the default then
(`LibraryLogos.wants_logo`, so no other import reads anything) looks, in order, at:

1. **Images at the top of the root README** (before the first heading below H1) whose `src` or `alt`
   says "logo" and that are no badge. Markdown or HTML `<img>`, also in an `<h1>` or a `<picture>`;
   at most 4 (`ReadmeSummary.logos`, read with the README).
    - A relative `src` resolves against the root.
    - An absolute URL counts only when it points into the library's own GitHub repository
      (`raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>`,
      `github.com/.../raw|blob/<ref>/<path>`). It names `<path>` of the **imported commit**: no URL
      is ever fetched.
2. **The conventional files** `LOGO_FILES` (`logo.svg`, `.github/logo.png`, `assets/logo.*`,
   `docs/public/logo.svg`, `docs/assets/logo.png`, `static/img/logo.svg`, ...).

All candidates are read in one `RepositoryFiles.read_files` (the commit's trees, then each existing
file's blob, also outside the selected paths), at most `MAX_LOGO_BYTES` (512 KiB) each.

### What is kept

`check_logo`, in a thread, keeps the first candidate whose sniffed type is PNG, JPEG, WebP or SVG (no
GIF).

- **A raster image** is kept byte for byte when its header (never decoded) says 16 to 4096 pixels a
  side and at most 2048 x 2048 pixels in all. A 1 x 1 spacer is no logo and a decompression bomb is
  refused.
- **An SVG is cleaned** (`clean_svg`):
    - expat parses it and refuses any DTD internal subset, entity declaration or undeclared entity
      before anything is expanded, and more than 10,000 elements;
    - only SVG-namespace shapes, text, paint servers, clipping, masks, filters and `<style>` are
      kept. Scripts, `foreignObject`, `image`, animations, metadata and editors' elements go with
      their content;
    - event handlers and foreign-namespace attributes go;
    - any value or `<style>` with `url()` to another document, `javascript:`, `@import`, an
      expression or a CSS escape goes;
    - `href` stays only as `#fragment`;
    - `<use>` may neither copy another `<use>` nor copy more than 10,000 elements in all (copies of
      copies multiply);
    - the result is written anew as UTF-8.

### Never fatal

- The logo step is no durable step: like the README text it reads what is imported now and replaces
  the logo whole.
- Any failure (the remote, the catalog) is logged and the library keeps the logo it had.
- A version with no usable candidate removes the library's logo.
- `ReadmeSummary.logos` changed the import's step results: `STEPS_VERSION` `jobs-12`.

### Stored

- `catalog_library_logos`: one row per library (`digest`, `content_type`, `data`, `path`, `ref`),
  with a foreign key to `catalog_libraries` with `ON DELETE CASCADE`, so a removed library loses it.
- Behind the catalog's `LibraryLogos` port. `ApplyLogo` re-checks type and size, keeps only the
  default version's and skips identical bytes.
- The library repository reads the digest with a left join into `Library.logo`, so `LibrarySummary`
  and `LibraryDetail` carry `logo` (16 hex digits of the SHA-256) without reading the bytes.

### Served

- `GET /api/v1/libraries/{owner}/{repo}/logo` (`GetLogo`, library read access) with the asset
  headers above.
- `?v=<logo>` makes it `immutable` for a year, so a list of libraries costs no request once seen.
- Pinning another default or removing the default version does not re-derive the logo until that
  version is imported again, as for the title.

## Relative links and images in the UI

- **Links.** A link to `.md`/`.mdx` stays in the app (same version, resolved path, same `#anchor`).
  Any other repository file opens on the host's blob page at the commit. A link to an article the
  import left out lands on "Not in this version", which offers the same file on the host.
- **Images** load from `/asset` first (public and private libraries alike). If that fails (404: a
  version imported before #64, or an image skipped as too large):
    - a **public** library falls back to the host's raw URL at the commit;
    - a private one, or a failed fallback, shows the alt text.
- Images are `loading="lazy" decoding="async"`. Their size is not stored, so CSS bounds them
  (`max-width: 100%`) and no `width`/`height` is set.
- **Moved articles.** A path the version does not have is first looked up in the version's renames
  (`renamed-path`, forward, one hop, short timeout, no retry).
    - An article git saw moved when the version was imported opens at its new path, same version and
      `#anchor`.
    - The URL is replaced, so Back skips the old path, and a "Moved from" line above the article
      (carried in history state) names it.
    - No rename, or a failed lookup, keeps the "Not in this version" page.

## Other rules

- **Kind of ref.** `AddLibrary` records on the job whether the version is a tag, a branch or a bare
  commit, so the import never asks the remote again; a deleted tag does not break it.
- **Replays.** A crash right after the activation commits, before the publish step's result is
  stored, publishes again on resume. Storing the same commit again activates an equal manifest, so
  nothing a reader sees changes.
- **Files.**
    - Only regular files are read (a symlink could point out of the checkout), none over
      `EXACTDOCS_MAX_ARTICLE_BYTES` (2 MiB), and only valid UTF-8.
    - A skipped file (also an unreadable one or one with a file name that is not UTF-8) is recorded
      as a job problem (the first 1000) and counted as processed.
    - A folder that cannot be listed fails the import.
    - `done`/`total` count the selected files.
- **Bridges** (`bootstrap/bridges.py`):

    | Bridge | Calls |
    |---|---|
    | `CatalogLibrarySources` | |
    | `CatalogVersionPublisher` | `StoreManifest`, `ActivateManifest`, `DiscardPendingManifests` |
    | `CatalogVersionCopier` | `CopyManifest` |
    | `RetrievalChunkIndex` | `IndexManifest`, `GetChunkSets`, `DiscardPendingChunks` |
