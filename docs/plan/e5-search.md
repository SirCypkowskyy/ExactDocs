# E5 Search

!!! abstract "TL;DR"
    - **Goal:** BM25 behind one search port, identifier-aware, pinned to a version, proven by a ranking suite.
    - **Stories:** SRCH-01, SRCH-02, SRCH-03, MCP-04, TAG-03 (search)
    - **Milestones:** MVP-1, MVP-2
    - **Issues, in build order:** E5-01 to E5-04; MVP-2: E5-06 (E5-05 merged into E7-03)
    - **Status:** the epic ([#5](https://github.com/SirCypkowskyy/ExactDocs/issues/5)) is closed; GitHub holds the current issue bodies.

## E5 · MVP-1

### E5-01 · feat: identifiers are searchable whole and by their parts

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / retrieval | SRCH-01, Decisions *Identifier tokenizer* | - | S |

**Context.** Developers search for `retryPolicy`, `max_retries`, `--dry-run` or `pkg.mod.fn`.
Standard tokenizers either glue or shred these; both the whole identifier and its parts must match.

**Expected behavior** (pytest table-driven unit tests)

Tokenizing each identifier for indexing yields both the whole token and its parts:

| identifier | whole | parts |
|---|---|---|
| `retryPolicy` | `retrypolicy` | `retry policy` |
| `max_retries` | `max_retries` | `max retries` |
| `--dry-run` | `--dry-run` | `dry run` |
| `pkg.mod.fn` | `pkg.mod.fn` | `pkg mod fn` |
| `HTTPServer` | `httpserver` | `http server` |

The same function applied to a query yields the same tokens as applied to the indexed text.

**Criteria of success**

- [ ] pure function in `retrieval/models` producing the extra indexed column text, applied to both chunk text and queries
- [ ] handles acronyms (`HTTPServer` → `http server`), digits, Unicode letters
- [ ] table-driven unit tests; the same function will feed pg_search (E12-02)

### E5-02 · feat: BM25 search runs on SQLite FTS5 behind one search port

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / retrieval | SRCH-01, SRCH-02, Decisions *BM25 engine* | E1-04, E5-01 | L |

**Context.** Search must work with nothing configured and run identically on SQLite now and
ParadeDB later; one port with a shared contract keeps the engines interchangeable.

**Expected behavior** (pytest port contract tests, memory reference and FTS5)

- With two manifests indexed through `IndexManifest` (test chunk sets shaped like fixture
  `v1.3.0` and `v1.4.0`; no import needed), `search(<v1.3.0 manifest>, "retry_policy")`
  returns no hit.
- `search(<v1.4.0 manifest>, "retry_policy")` returns the defining section first, with a snippet
  and highlight offsets.
- Queries containing `"`, `NEAR`, `*` or `(` are matched as text and never raise an FTS5 syntax
  error.
- A chunk set shared by two manifests is indexed once and found from both.

**Criteria of success**

- [ ] driven port `SearchIndex`: `index(chunk_set)`, `search(manifest_id, query, tag_filter, limit)` → hits (chunk ID, score, snippet with highlight offsets)
- [ ] FTS5 adapter: content-addressed table over chunk sets (text, heading path, identifier column), scoped by the active manifest's chunk rows; snippets via `snippet()` with safe escaping
- [ ] queries are escaped (no FTS5 syntax injection: quotes, `NEAR`, `*`) — test
- [ ] indexing hooked into `IndexManifest` (E1-04); removal hook for GC (E9-03)
- [ ] port contract test (memory reference implementation + FTS5)

**Notes.** BM25 statistics are global over deduplicated content (not per version); acceptable,
and the ranking suite (E5-04) guards it.

### E5-03 · feat: search answers within the selected version, with locations and neighbors

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / retrieval | SRCH-01, SRCH-02, MCP-04, MCP-05 (result shape), TAG-03 (search), BRW-03 (source links) | E5-02, E1-03 | M |

**Context.** An answer from another version is worse than none. Every result must say exactly
where it comes from and how it was found, so an agent can read around it and trust it.

**Expected behavior**

```gherkin
Scenario: No results in the selected version, even if another version matches
  When a user searches "/fixture/docs-repo/v1.3.0" for "retry_policy"
  Then the result is explicitly empty for version "v1.3.0"
  And no result from "v1.4.0" is returned

Scenario: A result carries its location
  When a user searches "/fixture/docs-repo/v1.4.0" for "retry_policy"
  Then each result has chunk ID, article path, heading path, position of total, previous and next chunk IDs, commit SHA and a source link to the section anchor
  And the response states retrieval mode "bm25", not reranked, and its coverage

Scenario: Search with an all-of tag filter
  When a user searches "token" in "/fixture/docs-repo/v1.4.0" with all of tags "api, auth"
  Then every result is tagged "api" and "auth"
```

**Criteria of success**

- [ ] `SearchDocs` use case rewritten on the new model: library + optional ref (default version), query, tag filter, limit; unknown version → `not_found`, known version without hits → empty result
- [ ] retrieval's own `TagFilter` (`any` / `all`) applied before ranking; search-port contract test: filtered top-k is computed after filtering
- [ ] result shape (one for every future mode): chunks as above + `version`, `retrieval_mode`, `reranked`, `coverage` (candidates considered, reranked, complete/cut short), optional `fallback_reason`
- [ ] source link at the commit SHA and section anchor for GitHub, GitLab, Bitbucket, Gitea; none for unknown hosts
- [ ] REST `GET /api/v1/libraries/{owner}/{repo}/search?ref=&q=&tags=&tags_match=any|all`
- [ ] behave `search.feature` rewritten on the fixture repo with "wrong version gets nothing" and the tag filter

**Notes.** Absorbs the search half of the dissolved E4-04 (the listing half is in E4-03).
Background seeds `/fixture/docs-repo` v1.3.0/v1.4.0 through the driving ports (ground rules).

### E5-04 · feat: a shared ranking suite proves exact identifiers find their defining section first

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend`<br/>`area: infra` | backend / retrieval, CI / release / infra | SRCH-01, RUN-05 | E5-03, E1-06, E3-05a | M |

**Context.** Ranking regressions are silent. A suite written against the search port, driven by
the fixture's expected-queries table, keeps BM25 honest now and proves PostgreSQL parity later.

**Expected behavior**

```gherkin
Scenario: Every expected query ranks its section first
  Given the fixture repository is imported at "v1.3.0" and "v1.4.0"
  When each query of the expected-queries table is searched in its version
  Then its expected section is the top result
```

**Criteria of success**

- [ ] `tests/retrieval/ranking/` parametrized over search adapters (FTS5 now; ParadeDB in E12-02)
- [ ] covers all four identifier shapes, a phrase query, a tag-filtered query and the version-isolation cases
- [ ] runs in `just check` and CI; failures print the actual top-5
- [ ] docs: how to add a query to the table (fixture README)

## E5 · MVP-2

### E5-06 · feat: users search all libraries at once and see which library answers

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / retrieval | SRCH-03 | E5-03 | M |

**Context.** Users don't always know which library documents something.

```gherkin
Scenario: Results across libraries with a library facet
  Given two libraries are imported
  When a user searches all libraries for "token"
  Then results come from each library's default version
  And each result names its library and version, with counts per library
```

- [ ] `SearchAllLibraries` use case: union over default versions' active manifests, facet counts per library
- [ ] `GET /api/v1/search?q=&library=`; selecting a library narrows to it
- [ ] version-isolation test: a non-default version never appears
