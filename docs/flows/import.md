# Importing a version

!!! abstract "TL;DR"

    - Adding a library, adding another version and re-syncing a branch all end in the same worker.
    - Readers see the new version only once every step succeeded; on failure they keep the last good
      version.
    - A killed import resumes at its first unfinished step.
    - Skipped or unparsable files are job problems, not failures. A moved tag is reported, never
      re-imported without the user's confirmation.

Adding a library, adding another version and re-syncing a branch all end in the same worker. The
HTTP call only validates and queues; the work happens in a job
([Background jobs](../architecture/jobs/index.md)).

```mermaid
sequenceDiagram
    autonumber
    actor U as User (UI or REST)
    participant API as REST: POST /libraries
    participant Q as Job queue (ingestion_jobs)
    participant W as Worker (DBOS workflow)
    participant G as Git host
    participant C as Catalog
    participant R as Retrieval

    U->>API: url, ref, include and exclude paths, credential?
    API->>G: ls-remote: resolve the ref to a commit SHA
    API->>C: create the library with its selection
    API->>Q: queue an import job pinned to the commit
    API-->>U: 201 with library_id, commit_sha, job_id
    loop poll GET /jobs/{job_id}
        U->>Q: state, done / total, problems
    end
    W->>Q: start the oldest queued job whose library has none running
    W->>G: shallow, blobless fetch of the pinned commit, sparse checkout of the selected paths
    W->>W: read each file, parse the ones not stored before (front matter, tags), chunk by headings: 100 files per durable step
    W->>C: store the articles as a pending manifest
    W->>R: index the chunks (reusing chunk sets by blob SHA and chunking config)
    alt every step succeeded
        W->>C: activate the manifest (one transaction)
        Note over C: the previous manifest becomes superseded,<br/>readers now see the new version
        W->>Q: job succeeded
    else a step failed, or the process was stopped
        W->>R: discard the pending chunks
        W->>C: discard the pending manifest
        Note over C: readers still see the last good version
        W->>Q: job failed with a message, or resumed on the next start
    end
```

## Resuming

A process that stops or is killed mid-import resumes the job on the next start. The steps it
completed (files listed, batches parsed and chunked) are taken from DBOS's stored results, and the
import goes on from the first unfinished one.

## Skipped files

- Skipped files (binary, too large, undecodable...) do not fail the import. They are recorded as job
  problems with a code, and the version is published without them.
- So is a file the parser or the chunker fails on (`unparsable`, naming the file and the error's
  type, #430).
- A failure that is not about one file (the store, the repository, running out of memory) still
  fails the import.
- A re-chunk that meets such a file re-imports the version instead, which lists it.

## Editing a library's settings

`PUT /libraries/{owner}/{repo}/settings` stores new paths, tag rules and chunking, then queues one
job for the whole library:

| What changed | Job | Fetches |
|---|---|---|
| paths | `reprocess` | yes |
| chunking | `rechunk` | no[^reimport] |
| only tag rules | `retag` | no |

[^reimport]: A version stored by an older parser, or with an article only its file can rebuild
    exactly, is re-imported at its commit instead.

- **`reprocess`** runs the `refresh` pipeline for each version at the commit it serves, so each
  version's new manifest replaces the old one at once.
- **`rechunk`** copies each version's active manifest into a pending one, re-derives its imported
  tags, cuts the stored text with the new chunking (reusing chunk sets already cut with it), indexes
  the copy and activates it.
- **`retag`** re-derives each stored article's imported tags (front matter plus rules) and writes
  them per version in one transaction, then copies them onto the chunks.

Until a version is done it serves its previous state; one that fails keeps it.

### In the web UI

Paths and tag rules are edited in *Files and tags* on the library's settings page (it leaves the
chunking as stored).

- Saving a change first warns that every version is re-processed (naming them), then follows the
  job's progress.
- A Preview shows which files the typed paths take in the default version. Not for a private library
  yet: a preview cannot use its stored credential.
- When the newest re-processing failed, the section shows it with *Run again*, which sends the
  stored settings back.

## Re-sync

`POST /libraries/{owner}/{repo}/sync` compares each *branch* and *tag* version with the remote.

- **A branch that moved** gets a `refresh` job, which is the same pipeline pinned to the new commit.
  Unchanged files reuse their stored chunks, and the new manifest replaces the old one in place.
- **A tag that moved** is reported (`tag_moved`), never re-imported by a sync. The user confirms its
  re-import, which queues a `refresh` job of the tag pinned to its new commit. Ways to confirm:
    - `POST .../versions/reimport`;
    - the button on the error in the library list and in Re-sync;
    - `exactdocs sync --confirm`.
- **Every upstream problem** leaves the last good version served and is recorded on a failed job
  with a stable `error_code`.

```mermaid
flowchart TD
    sync["POST /libraries/owner/repo/sync"] --> each{"for each version"}
    each -->|commit| pinned["pinned: never moves"]
    each -->|branch with a job queued or running| importing["importing: left alone"]
    each -->|branch or tag| ask["ask the remote for the tip"]
    ask -->|remote unreadable| err422["422 repo_unreachable or auth_failed: versions keep what they served"]
    ask -->|branch or tag gone upstream| failed["failed ref_deleted: the version keeps serving"]
    ask -->|tag at another commit| moved["failed tag_moved: reported, not re-imported"]
    moved -->|user confirms: POST versions/reimport| queued
    ask -->|tag at the same commit| pinnedtag["pinned"]
    ask -->|branch at the same commit| uptodate["up_to_date"]
    ask -->|branch at a new commit| queued["queued: refresh job"]
    queued --> run["worker: import pinned to the new commit"]
    run -->|ok| swap["manifest activated, chunk IDs of changed sections answer stale_chunk"]
    run -->|error| keep["job failed, the last good manifest stays active"]
```
