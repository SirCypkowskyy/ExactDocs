# Documentation pages stay under 16 KiB

!!! abstract "TL;DR"
    - A page in `docs/` over 16 KiB (`wc -c`) is split into an index page, with a TL;DR and a
      *Pages* table, and sub-pages by topic.
    - A page split while other open PRs edit it keeps its file name, and its sub-pages go into a
      folder of the same name.
    - Old anchors keep working through a *Moved sections* list on the index page. There is no
      redirect plugin.

| | |
|---|---|
| **Status** | Accepted, 2026-11-26 |
| **Scope** | Every page under `docs/` |
| **Issue** | Refs #563 |
| **Decided by** | Proposed in #620 |

## Context

ExactDocs ingests its own docs, and agents read them with `read_article`. The importer caps a
chunk at 8,000 characters (`DEFAULT_MAX_SECTION_CHARS`, about 2,000 tokens), so a 16 KiB page
is about two full chunks, or about 4,000 tokens per `read_article`. Almost every page left after
#582 is already under that size.

## Decision

A page over 16 KiB, measured with `wc -c`, becomes an index page with a TL;DR and a *Pages*
table, plus sub-pages by topic.

When other open PRs edit a page being split, the page keeps its file name and its sub-pages go
into a folder with the same name (`decisions/ai-retrieval.md` and `decisions/ai-retrieval/`), so
those PRs get no delete/modify conflict. Anchors of sections that moved stay on the index page as
a *Moved sections* list that links on, because a redirect plugin would be a new dependency.
Outside bookmarks to old anchors on the other eight split pages land at the top of the page.

`user-stories.md` is a known exception (over 17 KiB), because of the Decisions table. The
follow-up is to move that table to its own page under `docs/decisions/`.

## Considered options

- **12 KiB.** Rejected: it would split again the pages #582 had just finished, for little gain.
- **A limit in tokens.** Rejected: people check byte sizes, and a token count does not match
  them.
