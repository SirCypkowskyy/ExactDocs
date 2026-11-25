# Chunks and tags

!!! abstract "TL;DR"

    - Articles are chunked at their Markdown headings, never inside a code block or a table.
    - New libraries get split level `h3` and `max_chars` 4,000.
    - A section longer than 8,000 characters is always split again.
    - Tags come from front matter, path rules and by hand.

Articles are chunked at their Markdown headings with
[markdown-it-py](https://github.com/executablebooks/markdown-it-py), never inside a code block or
a table.[^chonkie]

Each library chooses its split level (`h1` to `h6`) and its chunk sizes with
`PUT /api/v1/libraries/{owner}/{repo}/settings`. `max_chars` cuts long sections again at deeper
headings, and `min_chars` merges tiny ones; settings left out keep the stored chunking. Every
version is then chunked again from the stored text, without fetching anything, and keeps serving
its old chunks until the new ones are in place.

A library added without chunking settings gets split level `h3` and `max_chars` 4,000, the
chunking the [retrieval benchmark](../benchmark/defaults.md) recommends (#381). The library stores
it, so a later change of the default changes no existing library: one added with ExactDocs 0.4 or
earlier keeps split level `h6` and no bound until its settings say otherwise.

Whatever the settings, a section longer than 8,000 characters (about 2,000 tokens) is split between
its top-level blocks, never inside a code block, table or MDX component, into parts that keep its
heading path. A `max_chars` or `min_chars` above 8,000 is refused (422).

Articles are tagged from front matter, from path rules and by hand. Articles, over REST and MCP,
say where each tag comes from in `tag_origins`, with several origins when a tag comes from several
places. The article page of the web UI shows each tag under each of its origins and adds or removes
manual tags, which hold for every version (`PUT`/`DELETE /api/v1/libraries/{owner}/{repo}/tags?path=`).
Listings and searches filter by tag.

[^chonkie]: An earlier design used Chonkie. Its Markdown recipe needs the Hugging Face Hub and the
    network, which a model-free, offline-capable image cannot have.
