# Library settings

!!! abstract "TL;DR"
    - `PUT /libraries/{owner}/{repo}/settings` replaces a library's include and exclude paths and
      tag rules as a whole set, and its chunking when `chunking` is sent.
    - Chunking defaults to `split_level` 3, `min_chars` 0, `max_chars` 4000; no chunk is ever
      longer than 8,000 characters.
    - A change re-processes every version with one job: `reprocess`, `rechunk` or `retag`, the
      widest one needed.
    - Each version keeps serving its old state until its new one is complete.

## Endpoint

| Method | Path | Purpose | Role |
|---|---|---|---|
| `PUT` | `/libraries/{owner}/{repo}/settings` | replace paths, tag rules and chunking | `admin` |

`GET /libraries/{owner}/{repo}` has the current `settings`.

## The request

`PUT /libraries/{owner}/{repo}/settings` (LIB-09, TAG-02, IMP-03) takes
`{"include_paths", "exclude_paths", "tag_rules", "chunking"}`.

- The paths and tag rules are replaced as a whole set: what is left out is cleared.
- The chunking is replaced only when it is sent. `chunking` left out or `null` keeps the stored
  one, so a client that edits only paths and tag rules (the web UI) never resets it.
- It is validated like `POST /libraries`. Nothing is stored on a failure:
    - 422 `invalid_path_pattern`, `invalid_tag` or `invalid_chunking_config`
    - or a field error
- 404 for an unknown library.

<figure class="xd-shot" markdown>

![A library's settings page with its title, description and the paths it imports from the repository](../assets/screenshots/library-settings-light.webp#only-light){ loading=lazy }
![A library's settings page with its title, description and the paths it imports from the repository](../assets/screenshots/library-settings-dark.webp#only-dark){ loading=lazy }

<figcaption>The same settings in the web UI: title, description and the paths to import.</figcaption>

</figure>

## Chunking

`chunking` is `{"split_level": 1-6, "min_chars": 0, "max_chars": 4000, "chunker": "markdown"}`
with `split_level` 3.

| Field | Default | Meaning |
|---|---|---|
| `split_level` | 3 | the deepest heading that starts a chunk;<br/>`2` cuts at `#` and `##` only |
| `min_chars` | 0 | chunks shorter than this are merged |
| `max_chars` | 4000 | a longer chunk is cut again at its deeper headings;<br/>`null` for no bound |
| `chunker` | `markdown` | markdown-it-py, the only chunker |

- These are the defaults, also for a library added without `chunking` (#381). Before #381 the
  defaults were `split_level` 6 and `max_chars` null, which libraries added then keep.
- A field left out of a sent `chunking` takes its default, so send `"max_chars": null` for no
  bound.

### How a version is cut

- A chunk longer than `max_chars` is cut again at its deeper headings, never inside a code block
  or table. A section without deeper headings stays whole.
- Chunks shorter than `min_chars` are merged with the next one (the last with the one before), as
  long as the result stays within `max_chars`.
    - The text before the first heading is never merged.
    - A merged chunk keeps the heading path and anchor of its first section, so a hit in a later
      section of it links to that first heading.

### Limits

- `max_chars` must not be smaller than `min_chars`.
- Both are at most 1,000,000, and at most 8,000 when sent, or 422 `invalid_chunking_config`. No
  chunk is longer, so a bigger `max_chars` would never cut and a bigger `min_chars` never merge.
- Settings stored before that limit still load, and their larger sizes have no effect.

!!! info "The 8,000-character ceiling"
    Whatever the settings, a chunk is at most 8,000 characters (about 2,000 tokens;
    `max_section_chars` in `ChunkingConfig`, not yet a setting).

    - A longer group of sections is cut again at its deeper headings, and merges stop there.
    - A section still longer is split between its top-level blocks, never inside a code block,
      table, list or MDX component. Only a single block longer than that makes a longer chunk.
    - Every part keeps the section's heading path, anchor and occurrence index, and only the
      first records the heading in the outline.

## Re-processing

Every version is then re-processed by one job, at the commit it serves. A branch is not synced.

| What changed | Job | What it does |
|---|---|---|
| paths | `reprocess` | fetches each version again and re-imports it;<br/>unchanged blobs reuse their chunks |
| chunking (paths unchanged) | `rechunk` | copies what each version serves into a new manifest,<br/>re-derives its tags, cuts the stored text again |
| only tag rules | `retag` | derives each stored article's tags again<br/>from its stored front matter and the new rules |

- `rechunk` fetches nothing. A blob already cut with that chunking reuses its chunks.
    - A version stored by an older parser, or holding a rare article whose stored text cannot be
      cut exactly as its import cut it, is re-imported at its commit instead. Such a version needs
      the repository to be reachable whenever its chunking changes.
- `retag` fetches and chunks nothing, and manual tags stay.

### Switching over

Each version keeps serving its old state (its old chunks too) until its new one is complete, and
then switches at once:

- a new manifest is activated
- or, for a `retag`, the version's catalog entries are re-tagged in one transaction, with
  search's tag copies following a moment later under the same lock (as for manual tags; a rerun of
  the job always brings them in line)

### Failures

- A version that cannot be re-processed keeps what it had, the others go on, and the job fails
  naming it. `error_code` is the failures' shared code, else `reprocess_failed`.
- Sending the same settings again then queues that job again.
- A job redoes what the smaller ones do (`reprocess` > `rechunk` > `retag`). While a wider one
  failed and has not been redone, a retry or a smaller edit queues the wider one, so a smaller job
  never hides that failure.

The jobs count `done` / `total` in versions.

## The answer

| Status | When | Body |
|---|---|---|
| 202 | a job was queued | the job in `Location`; `job_id`, `reprocess` (`paths`, `chunking` or `tags`),<br/>the stored `chunking`, `versions` (the refs the job re-processes) |
| 200 | nothing changed and the last re-processing did not fail,<br/>or the library has no version yet | `job_id: null` |

- With no version yet, imports to come use the new settings.
- Edits of one library take turns.
- A queued job that does at least what is needed is reused.
- Removal waits for these jobs like for an import.
