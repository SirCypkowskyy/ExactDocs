# E4 Parsing, chunking & tags

!!! abstract "TL;DR"
    - **Goal:** Safe parsing, heading-based chunks, and tags from front matter, path rules and by hand.
    - **Stories:** IMP-02, IMP-03, IMP-04, TAG-01, TAG-02, TAG-03
    - **Milestones:** MVP-1, MVP-2
    - **Issues, in build order:** E4-01 to E4-03; MVP-2: E4-05, E4-06 (E4-04 dissolved into E4-03 and E5-03)
    - **Status:** the epic ([#4](https://github.com/SirCypkowskyy/ExactDocs/issues/4)) is closed; GitHub holds the current issue bodies.

## E4 · MVP-1

### E4-01 · feat: articles are parsed safely: front matter, MDX as inert text, invisible characters removed

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | IMP-04, Terms (Verbatim), MCP-07 (import part) | - | M |

**Context.** Doc sites use front matter and MDX. Titles must be right, JSX must never run, and a
doc file must not smuggle invisible instructions (zero-width, bidi) to an agent.

**Expected behavior**

```gherkin
Scenario: The article title follows front matter, then H1, then file name
  Then the title of "guide/install.md" is its front-matter title
  And the title of "guide/auth.md" is its first H1
  And the title of "notes.md" is "notes"

Scenario: Hidden characters are removed on import
  Given an article contains a zero-width space and a bidi override
  When it is imported
  Then the stored Markdown contains neither
  And is otherwise byte-identical to the source
```

**Criteria of success**

- [ ] pure parser in `ingestion/models`: front matter (YAML safe load; `title`, `tags`, `description`, others kept as metadata), title rule, body without front matter
- [ ] invisible control characters (zero-width, bidi controls) removed; nothing else changed (verbatim test)
- [ ] `.mdx` treated as Markdown; JSX blocks kept as text (rendered as inert code by the UI, E8-07); imports/exports never evaluated
- [ ] malformed front matter → article imported, problem listed (IMP-06)
- [ ] table-driven unit tests over fixture files

**Notes.** Front matter is hidden in the rendered view (E8-07) and returned as metadata by
`read_article` (E7-03). The parser is pure and starts on day 1: whichever of E1-05 and E4-01
merges first creates the `ingestion` package. The parser and sanitizer carry a version constant
that feeds the chunking-config hash (E4-02).

### E4-02 · feat: articles are split into heading-based chunks that never split code blocks or tables

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | IMP-02, RUN-02 (no ML extras), Decisions *Chunker* | E4-01, E1-04, E1-06 | M |

**Context.** Header-based chunks are the best retrieval unit for documentation; a result that
cuts a code block in half is useless to an agent.

**Expected behavior** (pytest guarantee tests against the `Chunker` port, on fixture articles)

- Chunking `guide/install.md` yields a chunk with heading path `Guide > Install > Docker`.
- No fenced code block or table of any fixture article is split between two chunks.
- Text before the first heading is kept in a chunk of its own.
- Two headings with the same text get occurrence indexes 0 and 1.
- Changing the parser/sanitizer version constant changes the chunking-config hash.

**Criteria of success**

- [ ] driven port `Chunker`; default adapter on markdown-it-py (issue #27: Chonkie's Markdown recipe needs the HF Hub and network, which breaks RUN-02)
- [ ] each chunk: heading path, occurrence index (repeated headings), position, content, content hash, GitHub-style anchor, code-block languages
- [ ] chunking-config hash computed from the effective config plus the parser/sanitizer version (E4-01), so a parser fix re-chunks instead of reusing stale chunk sets (default config now; IMP-03 in MVP-2)
- [ ] guarantee tests on the fixture repo run against the port (heading paths, never-split code/tables, text before the first heading kept), so any chunker adapter must pass them
- [ ] dependency `markdown-it-py` added to `pyproject.toml`; no dependency that pulls ML models (RUN-02, see issue #27)

**Notes.** Chunk IDs are computed by retrieval (E1-04), not by the chunker.

### E4-03 · feat: articles carry tags from front matter and path rules, and listings filter by them

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion, backend / catalog | TAG-01 (MVP-1), TAG-02, TAG-03 (listing) | E4-01, E3-02, E1-03 | M |

**Context.** Most repos have no front matter but a meaningful folder layout; users slice docs by
topic (API reference, ADRs) across folders, and "only the API reference" is a common need for both
users and agents browsing a version.

**Expected behavior**

```gherkin
# Verified here by the pure-function table test; the scenario runs in E3-05a's `import.feature`.
Scenario: Front-matter and path-rule tags combine
  Given the library has the tag rule "docs/api/** -> api"
  And "docs/api/auth.md" has front-matter tags "auth"
  When the library is imported
  Then "docs/api/auth.md" is tagged "api" and "auth"

Scenario: Listing with an any-of filter
  When an agent lists articles with any of tags "adr, api"
  Then only articles tagged "adr" or "api" are listed
```

**Criteria of success**

- [ ] tag rules (glob → tag) stored in library settings and set only through `AddLibrary` (`POST /api/v1/libraries` accepts them); editing them later is `PUT /api/v1/libraries/{owner}/{repo}/settings`, owned by E9-04 (MVP-2)
- [ ] tags normalized (lower-case, trimmed, deduplicated); applied on every import
- [ ] tags stored on manifest entries and copied to chunk rows
- [ ] catalog `TagFilter` value object (`any` / `all`) in the catalog DTOs; `ListArticles` applies it before pagination; REST query params `tags` and `tags_match=any|all`
- [ ] unit tests (rule matching, filter), behave scenarios

**Notes.** Absorbs the listing half of the dissolved E4-04; the search half is in E5-03. Each
domain has its own `TagFilter`; bridges map between them. MCP (E7-02) and UI (E8-06) expose it.

## E4 · MVP-2

### E4-05 · feat: chunking can be customized per library without re-cloning

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | IMP-03, LIB-09 (chunking) | E9-04 | M |

**Context.** Some docs have huge sections, others one-line headings; one default does not fit all.

```gherkin
Scenario: Changing the split level re-chunks without fetching
  Given "/fixture/docs-repo" is imported with default chunking
  When the user sets the split level to "h2"
  Then every version is re-chunked from stored content without a git fetch
  And the previous chunks are served until the swap
```

- [ ] settings: split level (`h1`…`h6`), min/max size with merging of tiny sections, chunker choice among the supported chunkers (Chonkie was dropped in #27); validated
- [ ] new config hash → new chunk sets from stored blobs; manifests re-indexed and swapped (E1-04)
- [ ] guarantee tests (E4-02) pass for every supported setting

### E4-06 · feat: users tag articles by hand, and manual tags follow renames

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / catalog | TAG-01 (MVP-2), TAG-02 (combine) | E3-12, E4-03 | M |

**Context.** Some topics are not visible in paths or front matter; users want to add them once for
all versions.

```gherkin
Scenario: A manual tag applies to all versions and follows a rename
  Given the user tagged "guide/setup.md" with "onboarding"
  Then "guide/setup.md" in "v1.3.0" is tagged "onboarding"
  And "guide/install.md" in "v1.4.0" (its renamed successor) is tagged "onboarding"
```

- [ ] manual tags per library keyed by article path; rename map (E3-12) carries them forward
- [ ] `PUT/DELETE /api/v1/libraries/{owner}/{repo}/tags?path=` ; chunk-row tag copies refreshed without re-chunking
- [ ] unit + behave tests; UI in E8-14
