# Articles, outlines and tags

!!! abstract "TL;DR"
    - `GET .../outline` returns an article's heading tree with chunk IDs and anchors, and no body
      text.
    - `GET .../tags` counts a version's tags; `PUT .../tags?path=` sets manual tags on a path for
      every version.
    - Articles list where each tag came from in `tag_origins`.
    - `GET .../renamed-path` follows git's renames between versions and never guesses.
    - A ref may only be the last path segment; routes that need a ref and a path take `?ref=` and
      `?path=`.

## Endpoints

| Method | Path | Purpose | Role |
|---|---|---|---|
| `GET` | `/libraries/{owner}/{repo}/articles` | list a version's articles | `viewer` |
| `GET` | `/libraries/{owner}/{repo}/article?path=&ref=` | one article | `viewer` |
| `GET` | `/libraries/{owner}/{repo}/outline?path=&ref=` | an article's heading tree | `viewer` |
| `GET` | `/libraries/{owner}/{repo}/tags?ref=` | a version's tags | `viewer` |
| `PUT` | `/libraries/{owner}/{repo}/tags?path=` | set manual tags on a path | `contributor` |
| `DELETE` | `/libraries/{owner}/{repo}/tags?path=` | remove manual tags | `contributor` |
| `GET` | `/libraries/{owner}/{repo}/renamed-path` | where a path moved | `viewer` |

Library IDs are `/{owner}/{repo}` in the path. A ref may only be the last path segment, declared
`{ref:path}`. A route that needs a ref and an article path takes `?ref=` and `?path=`, because
servers decode `%2F` before routing.

A ref that names no imported version but differs from exactly one of them only by a missing or
extra leading `v` or `V` (`v1.10.0` for `1.10.0`, never `V1.0` for `v1.0`) reads that version, and the response says so in `notes` (absent
otherwise). A ref that names no version is `404 not_found`, naming the library's versions, the
most recently imported first (at most 20), and its default version. Search, `query-docs` and the
MCP tools read refs the same way ([MCP](../mcp/tools.md)).

## Outlines

`GET /libraries/{owner}/{repo}/outline?path=&ref=` returns an article's heading tree with no body
text, from exactly that version (MCP: `article_outline`).

| Field | Meaning |
|---|---|
| `sections` | each with `heading`, `chunk_id`, `anchor`, `starts_chunk` and `children` |
| `preamble_chunk_id` | the chunk with the text before the first heading |

- Every heading is listed. One the library's chunking merged into a chunk that starts earlier has
  `starts_chunk: false`, the ID of that chunk and its own anchor.
- A heading no chunk records (only possible in chunks stored before #251) has null `chunk_id`,
  `anchor` and `starts_chunk`.
- Chunks cut before heading records existed list only their first heading.
- A version that is not imported, or a path it lacks, is 404 `not_found`. A missing path lists
  `close_matches` like the article route.

!!! info "Getting full outlines"
    Chunking that cannot merge headings (split level h6, no `min_chars`) loses nothing. For the
    rest, a version gets full outlines once it is cut again:

    - at an import of a new commit (a re-sync re-cuts only versions whose commit moved)
    - or for every version at once, by saving a changed chunking in the library's settings, which
      queues a `rechunk` job (saving the same chunking queues nothing)

## Tags

`GET /libraries/{owner}/{repo}/tags?ref=` lists the version's tags with how many articles carry
each, most used first, 100 at most:

```text
{"tags": [{"tag", "count"}], "truncated"}
```

## Manual tags

`PUT /libraries/{owner}/{repo}/tags?path=` with `{"tags": [...]}` sets the tags of an article path
by hand, for every version of the library.

- At most 20 tags, normalized like every tag.
- It replaces the path's earlier manual tags.
- It answers `{"library", "path", "tags"}`.
- `DELETE` on the same URL removes them (204). Imported tags stay.

### Where they apply

They combine with the imported tags (front matter, path rules) of:

- the article at `path` in every version
- the article git saw it renamed to in a later version. Rename maps are followed back across
  versions, never from a new name to an old one.

Later imports get them too.

### How articles show them

- Articles show every tag in `tags`.
- The manual ones come again in `manual_tags` as `[{"tag", "path"}]`, where `path` is the path the
  tag was set on: the article's own, or an older one it was renamed from.

!!! warning "Removing a tag that came with a rename"
    `PUT` and `DELETE` act on the path that was tagged, never on its successors. To remove a tag
    that came with a rename, remove it on the `path` it names, which removes it from every
    version.

### Other rules

- Listings, tag counts and search see them at once: the tag copies on chunks are refreshed,
  nothing is chunked again.
- A path no version has is accepted and waits for one.
- An unknown library is 404; a value that cannot be a tag is 422 `invalid_tags`.

## Tag origins

An article (`GET .../article`, MCP `read_article`) lists every tag of `tags` again in
`tag_origins`, in the same order, as `[{"tag", "origins"}]`.

`origins` names every place the tag comes from:

| Origin | Source |
|---|---|
| `front_matter` | the article's front matter |
| `path_rule` | a path rule of the library |
| `manual` | set by hand |
| `imported` | a version imported before origins were recorded[^imported] |

[^imported]: From the front matter or a path rule. The next import of the version or change of
    the library's tag rules tells which.

A tag can have several, e.g. `["path_rule", "manual"]` for a path-rule tag also set by hand.

## Renames

`GET /libraries/{owner}/{repo}/renamed-path?ref=&from=&path=` answers where `path` of version
`from` is in `ref` (the default version without `ref`).

### With `from`

- Each version names the one it follows: the version its renames were detected against, also when
  nothing moved.
- The rename maps of every version between `from` and `ref` are followed hop by hop, in either
  order of import, at most 100 versions apart.
- `new_path` is the path in `ref`, `old_path` the path asked about, `similarity` the lowest of the
  moves.
- These answer `null`, never a path of another version:
    - versions with no import link between them (two branches, a branch and a tag, a version
      removed in between)
    - a path renamed and later dropped before `ref`

### Without `from`

One hop across the renames git saw when `ref` was imported:

| `direction` | `path` is |
|---|---|
| `forward` (default) | from the version imported before `ref` |
| `back` | an article of `ref` |

### The answer

```text
200 {"renamed": {"library", "ref", "from_ref", "old_path", "new_path", "similarity"} | null}
```

`null` means the path was not moved, or no renames are known. Nothing is guessed.

An unknown library or version (`ref` or `from`), or a `ref` without an active manifest, is 404
`not_found`.

!!! note "How rename maps build up"
    - A branch's map builds up over its syncs; it links to no other version.
    - A version imported before #201 where nothing moved has no link until it is imported again.
    - Adding an older tag after a newer one (`v1.3.0` after `v1.4.0`) also detects the newer tag's
      map again, against the older one, so the order versions are added in does not matter.
