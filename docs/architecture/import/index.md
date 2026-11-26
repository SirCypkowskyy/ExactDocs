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

## Pages

| Page | What it covers |
|---|---|
| [Chunking](chunking.md) | per-library chunking and `rechunk`, heading records, long sections, chunk identity |
| [Images and logos](images.md) | article images and `/asset`, project logos, relative links and images in the UI |

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

## Undo

- Any failure after the store (an exception or a cancellation) discards the pending chunks and then
  the pending manifest.
- The order matters: retrieval asks the catalog and only removes a manifest it is told is still
  pending.
- After a crash the recovery hook does the same for the library's pending data before the job
  resumes or runs again (a library has one running job).

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
