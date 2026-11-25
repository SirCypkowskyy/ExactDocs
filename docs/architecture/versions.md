# Version storage

!!! abstract "TL;DR"

    - A version's articles are a **manifest** over article content shared by git blob SHA, stored once.
    - A manifest stays `pending` (invisible) until `ActivateManifest` flips it in one transaction.
      Readers only ever see the active manifest.
    - Manual tags survive re-imports and follow articles across renames.
    - On import, git detects which Markdown files moved between versions. Detection never fails an
      import.

## Manifests (catalog)

- A version's articles are a **manifest** (`catalog_manifests`, `catalog_manifest_entries`: path,
  blob SHA, title, tags, front matter, size) over article content shared by git blob SHA
  (`catalog_article_contents`, stored once).
- A manifest is `pending` (invisible) until `ActivateManifest` flips it in one transaction:
    - the previous manifest becomes `superseded`;
    - this one becomes `active` (a partial unique index allows one active manifest per version);
    - the version moves to the manifest's commit.
- Readers only ever see the active manifest. Other domains hold manifest IDs by value.
- Superseded manifests stay for a grace period, then `CollectGarbage` deletes them and the contents
  no manifest uses.
- `RemoveVersion` and `RemoveLibrary` delete a version's manifests at once (no grace: nothing serves
  them), and ingestion's `collect` job then runs each domain's collector, catalog first.

## Library logos (#504)

`catalog_library_logos` keeps one logo per library (its bytes, type, digest and where it was found),
deleted with the library. It is written through the `LibraryLogos` port and read into `Library.logo`
by the library repository. See [Project logos](import.md#project-logos-504) under the import.

## Manual tags (E4-06)

`catalog_manual_tags` holds the tags users set by hand per library and article path
(`SetManualTags`).

A manifest entry keeps:

| Column | Holds |
|---|---|
| `tags` | every tag of the article (what listings filter and count) |
| `manual_tags` | each manual tag with the path it was set on, which is where it is changed |
| `imported_tags` | the imported tags, only while it has manual ones, so removing them brings back exactly what the import gave |
| `front_matter_tags`, `rule_tags` | where the imported tags come from (#215) |

- Readers get each tag's origins (`ManifestEntry.tag_origins`) without the client re-deriving them.
- `front_matter_tags` and `rule_tags` are NULL in entries stored before #215. Their imported tags
  read as `imported` until the next import or tag-rule change of their version writes them.
- An entry gets the manual tags of its path and of every path the rename maps trace it back to,
  version by version (`ManualTagger`).
- Retrieval keeps a copy of the tags on each chunk row.
- Ingestion's `TagArticle` (REST `PUT/DELETE .../tags?path=`) has the catalog re-tag the pending
  and active manifests and then the chunk rows (`RetagArticles`, an `UPDATE`, no re-chunking).
- An import applies them last (`ApplyManualTags`, then the chunk rows, then activation) under its
  library's lock, so the older of two re-tags never lands last. The lock is the `LibraryLocks` port,
  one object shared with `TagArticle`:
    - `TagLocks` on SQLite, where one process runs jobs and serves the API;
    - a PostgreSQL advisory lock per library that every process shares.

## Renames between versions (E3-12)

On import, `RenameSource.renames` (the system-`git` adapter) asks git which Markdown files (any
letter case) moved between two commits.

### Which two commits

The previous version (`previous_version`) is chosen like this:

- **A numeric tag** (`v1.4.0`, `2.1`; `1.4` equals `1.4.0`) is compared with the highest lower
  numeric tag, never with itself, so a re-sync gives the same map.
- **A branch or commit** is compared with the commit the ref served before. Its map **builds up**
  over syncs (`compose_renames`):
    - earlier renames are kept;
    - they are chained (A to B, then B to C gives A to C, the lower similarity);
    - they are dropped when their target is no longer an article.
- **Pre-releases and other names** have no order and get none.
- Old paths are filtered by the library's current selection.

### An older tag imported later

The previous version is the closest one imported *so far*. An older tag imported later (add
`v1.4.0`, then `v1.3.0`) is closer to the newer tags than what they were compared with. So after its
activation the import:

1. detects the map of each version whose previous version it now is again (git only, no
   re-chunking);
2. replaces it (`ReplaceRenames`, which also re-tags the manifest from the new map);
3. copies the tags to the chunk rows, under the library's tag lock;
4. re-tags every pending and active manifest of the library, because a version after the newer one
   follows its map too (`v1.5.0` gets a tag through `v1.4.0`'s new map).

A map git cannot give leaves the newer version as it was; this never fails the older import. Each
import of a tag does this, a re-import too.

!!! note "Repairing maps built in the wrong order (#216)"

    A sync never re-imports a tag, so a map built in the wrong order before this existed is
    repaired by importing the older tag again: remove it and add it again, or re-import it when it
    moved (`versions/reimport`).

### Where the map is stored and read

- The map (`from_ref`, old path, new path, similarity) is stored with the new version's manifest
  (`catalog_manifest_renames`, indexed both ways), so it is replaced, collected and removed with it.
- So is the link to the version it was detected against (`catalog_manifests.renamed_from`), kept
  also when nothing moved.
- It is read through the `ResolveRenamedPath` port (forward: old to new; back: new to old),
  `ListRenames`, and REST `GET /libraries/{owner}/{repo}/renamed-path`.

### Across several versions (`from`, #201)

1. The library's active manifests are read in one query.
2. The links are walked from the newer of the two versions back to the older (at most
   `MAX_RENAME_HOPS`).
3. One indexed rename lookup per version crossed moves the path.
4. A path the chain ends at is confirmed with one lookup in the target's articles.

These count as "did not move":

- no link between the two (branches, a version removed in between, a version without one);
- a rename that names another version than the link (a manifest with one is refused when stored);
- a path renamed and then dropped. The answer is never a path of another version.

### Failures, cost and bounds

Detection never fails an import: any error means "no renames known" (a branch keeps its earlier
map).

??? info "Measured cost on `fastapi/fastapi` 0.100.0 to 0.115.0"

    About 1,400 Markdown files, 12 renames, 4 of them exact.

    - Fetching the two trees (`--depth=1 --filter=blob:none`, no checkout) takes about 1 s and
      250 KB.
    - `git diff-tree -M --diff-filter=R` over a case-insensitive `*.md`/`*.mdx` pathspec then
      fetches only the added and deleted Markdown files' blobs (about 1 MB, 1 s) to score renames
      with edits. Exact renames need no blobs.

Bounds:

- one fetch slot (the import has released its own first);
- a 60 s deadline;
- the fetch size watchdog, which, with the deadline, bounds the download of a hostile repository;
- git's rename limit (400): above 400 x 400 added x deleted files the scoring is skipped and only
  exact renames are kept. It bounds CPU, not downloads;
- a 16 MiB cap on git's list;
- 10,000 renames kept.
