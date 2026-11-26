# Chunking

!!! abstract "TL;DR"
    - Editing a library's chunking queues a `rechunk` job that cuts a copy of the active manifest
      from the stored text; nothing is fetched.
    - `max_section_chars` bounds every chunk, 8,000 characters by default; a longer section is split
      between top-level blocks, and a fence, table, list or MDX component is never cut.
    - The parts of a split section are numbered by `part`, which is in the chunk ID only above 0;
      part IDs are not edit-stable.
    - The settings API refuses a `max_chars` or `min_chars` above the bound (422
      `invalid_chunking_config`).
    - The bundled local model embeds only about the first 1,800 characters of a chunk; lexical
      search, the reranker and the agent see all of it.

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
