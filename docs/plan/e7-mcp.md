# E7 MCP & context7 parity

!!! abstract "TL;DR"
    - **Goal:** Agents read docs over MCP, including drop-in context7 tools.
    - **Stories:** MCP-01 to MCP-07, C7-01, C7-02
    - **Milestones:** MVP-1, MVP-2
    - **Issues, in build order:** E7-02 to E7-07 (E7-01 merged into E7-02); MVP-2: E7-08, E7-09, E7-10
    - **Status:** the epic ([#7](https://github.com/SirCypkowskyy/ExactDocs/issues/7)) is closed; GitHub holds the current issue bodies.

## E7 · MVP-1

### E7-02 · feat: agents list libraries and browse a version's article tree, marked as untrusted content (absorbs E7-01)

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | MCP tools, backend / catalog | MCP-01, MCP-02, MCP-07, TAG-03 (MCP), RUN-03 (update check off), Terms (Version in responses), Decisions *MCP endpoint* | E1-03, E4-03 | L |

**Context.** Agents navigate docs like humans: overview first, then the relevant article. They
must see what exists, which version is default, and page through big trees. A doc file can also
contain instructions aimed at the user's agent, so every result must tell the agent that the text
is external content, in a place every client actually reads.

**Expected behavior**

```gherkin
Scenario: Listing libraries
  When an agent calls "list_libraries"
  Then "/fixture/docs-repo" is listed with title, description, tags and versions with commit SHAs
  And "v1.4.0" is marked as the default version

Scenario: Paging through a version's articles
  When an agent calls "list_articles" for "/fixture/docs-repo" with limit 2
  Then it gets 2 articles of the default version and a cursor
  When it calls again with that cursor
  Then it gets the next articles

Scenario: ExactDocs tools carry the notice in structured content
  When an agent calls "list_articles"
  Then its structured result has a "notice" field and the version used
```

**Criteria of success**

- [ ] `list_libraries(limit?, cursor?)` (default limit 20): ID, title, description, source URL, tags, `refs` (ref, kind, commit SHA, default flag; at most 50 per library, plus `version_count`)
- [ ] `list_articles(library, ref?, path_prefix?, tags?, tags_match?, limit?, cursor?)` (`ref` like `search_docs`; blank means the default version): path, title, tags, size; tags filter as TAG-03 (catalog `TagFilter`, E4-03)
- [ ] each domain's result DTO carries a `notice` field whose text is the kernel `NOTICE` constant (a reviewed kernel addition, see [Architecture](../architecture/domains.md#the-notice-constant)); no shared MCP helper module (the context7 two-block `ToolResult` lives in retrieval's MCP adapter, E7-05)
- [ ] all tools annotated read-only; `mask_error_details=True` kept; `DomainError`s pass as tool errors (existing middleware) — test both paths
- [ ] `FASTMCP_CHECK_FOR_UPDATES=off` set in code; stdio banner off — test
- [ ] tool schemas snapshot-tested; behave `mcp_browse.feature` (MCP steps via FastMCP `Client`)

**Notes.** MCP over HTTP is guarded by the token verifier from E2-03; tests that run before it
lands use an unauthenticated in-process FastMCP `Client`.

### E7-03 · feat: agents and REST clients read whole articles and single chunks verbatim, and old chunk IDs say they are stale (absorbs E5-05)

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | MCP tools, backend / retrieval | MCP-03, MCP-04 (`read_chunk`, `stale_chunk`), IMP-04 (front matter as metadata) | E7-02, E5-03 | L |

**Context.** Once an agent knows where the answer is, it wants the whole article, unescaped, with
proof of where it came from; a typo in a path should point to the right file. A matching section
often needs its neighbor, and after a re-sync an agent holding an old chunk ID must learn it is
stale rather than get a confusing "not found" or wrong text.

**Expected behavior**

```gherkin
Scenario: Reading an article
  When an agent reads "guide/install.md" of "/fixture/docs-repo/v1.4.0"
  Then the Markdown arrives as a plain text block, identical to the imported file
  And the structured content has its front matter, commit SHA and source link

Scenario: A wrong path suggests close matches
  When an agent reads "guide/instal.md"
  Then the tool error lists "guide/install.md" as a close match

Scenario: Reading a neighbor chunk
  Given a search result for "retry_policy" in "/fixture/docs-repo/v1.4.0"
  When the agent reads its next chunk ID
  Then it gets that chunk verbatim with its location and the IDs of its own neighbors
```

**Criteria of success**

- [ ] `ReadChunk` use case (retrieval): verbatim content, location fields as in search results
- [ ] IDs in a superseded manifest of the same version but not in the active one → `stale_chunk` (domain error); unknown IDs → `not_found` (pytest with a superseded manifest stored through the ports; the behave scenario over a real re-sync is in E9-01)
- [ ] REST `GET /api/v1/chunks/{chunk_id}` and the article route of E1-03 (`?ref=&path=`)
- [ ] MCP `read_article(library, ref?, path)` and `read_chunk(chunk_id)`: text block + structured content (metadata, commit SHA, link, version, notice)
- [ ] `stale_chunk` and `not_found` surface as tool errors with messages
- [ ] close matches (edit distance / same basename), at most 5
- [ ] unit, integration and behave tests

**Notes.** The new location in the `stale_chunk` error is MVP-2 (E7-09). Chunk IDs of superseded
manifests are kept as tombstones when GC (E9-03) removes the manifests after their grace period.

### E7-04 · feat: agents search one version with `search_docs`

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | MCP tools, backend / retrieval | MCP-05, MCP-04, TAG-03 (MCP) | E7-02, E5-03 | S |

**Context.** Agents should get the best results the instance can give and know how they were
found, so they can tell "nothing exists" from "not everything was checked".

**Expected behavior**

```gherkin
Scenario: Searching a version with nothing configured
  When an agent calls "search_docs" for "/fixture/docs-repo/v1.3.0" and "retry_policy"
  Then the result is explicitly empty for "v1.3.0" with retrieval mode "bm25"

Scenario: Asking for a mode that is not configured
  When an agent calls "search_docs" with mode "hybrid"
  Then the tool error lists the available modes "bm25"
```

**Criteria of success**

- [ ] `search_docs(library, query, ref?, tags?, mode?)` returns the E5-03 shape + notice (retrieval DTO field, E7-02)
- [ ] `mode` validated against available modes (only `bm25` in MVP-1)
- [ ] behave `mcp_search.feature` incl. wrong-version case

### E7-05 · feat: `resolve-library-id` finds library IDs like context7 does

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | MCP tools, backend / retrieval | C7-01, MCP-07 (context7 tools), LIB-07 (titles used for matching) | E7-02, E3-06, E5-03 | M |

**Context.** Every context7-style prompt starts with `resolve-library-id`; ExactDocs must answer it
with the same tool name and arguments so switching is a URL change.

**Expected behavior**

```gherkin
Background:
  Given the fixture repository is imported as "/acme/payments" at "v1.3.0"
  And the fixture repository is imported as "/acme/payments-sdk" at "v1.4.0"

Scenario: A library name resolves to its ID
  Given the fixture repository is also imported as "/fixture/docs-repo"
  When an agent calls "resolve-library-id" with libraryName "docs repo" and query "retry policy"
  Then "/fixture/docs-repo" is the first match with its title, description, versions, article and chunk counts

Scenario: The query changes the order
  Given only "/acme/payments-sdk" documents "retry_policy" in its default version
  When an agent calls "resolve-library-id" with libraryName "payments" and query "retry_policy"
  Then "/acme/payments-sdk" is ranked first
  When the agent calls it with libraryName "payments" and query "invoices"
  Then "/acme/payments" is ranked first

Scenario: context7-compatible tools keep their payload shape
  When an agent calls "resolve-library-id"
  Then the result has two text blocks: the notice with the version, then the payload
  And the tool has no output schema
```

**Criteria of success**

- [ ] `ResolveLibraryId` use case in **retrieval**: reads libraries through a bridge to catalog's `ListLibraries` and matches the name in memory (ID, title, description; no catalog FTS); `query` re-ranks by matching docs (hits in each candidate's default version, retrieval's own search)
- [ ] context7-shaped text payload (ID, title, description, versions, counts) in a two-block `ToolResult` (notice from the kernel constant, then the payload) built in retrieval's MCP adapter and reused by E7-06
- [ ] contract test: tool name and argument schema are a superset of a vendored context7 schema in `tests/contracts/context7/` pinned to a context7 version, with a README on how to update it deliberately

**Notes.** The bridge goes retrieval → catalog (one-way rule); catalog never calls retrieval.

### E7-06 · feat: `query-docs` returns version-exact documentation within a size budget

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | MCP tools, backend / retrieval | C7-02 | E7-05, E5-03 | M |

**Context.** The second call of every context7-style prompt. It must never answer from another
version and must stay small enough for the agent's context.

**Expected behavior**

```gherkin
Scenario: An exact version answers only from that version
  When an agent calls "query-docs" with libraryId "/fixture/docs-repo/v1.3.0" and query "retry_policy"
  Then no text that exists only in "v1.4.0" is returned

Scenario: The response stays within the budget
  Given the size budget is 2000 tokens
  When an agent calls "query-docs" with a broad query
  Then the payload is at most 8000 characters
```

**Criteria of success**

- [ ] `QueryDocs` use case (retrieval): `/owner/repo` → default version, `/owner/repo/<ref>` → exactly that version; instance retrieval mode
- [ ] `language` ranks chunks with code blocks in that language first (from E4-02 code languages)
- [ ] budget (default ~10k tokens = characters / 4, setting `EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET`) enforced in the use case, whole chunks only; no response-limiting middleware
- [ ] replay test: a recorded context7 session (both tools, real arguments) in `tests/contracts/context7/` runs without errors
- [ ] docs: README *MCP tools*

**Notes.** Library `rules` are MVP-2 (E3-09); per-library mode is Next (E11-01).

### E7-07 · feat: `exactdocs serve --stdio` serves MCP from the local database without a token

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | MCP tools | AUTH-02 (stdio), Decisions *stdio MCP*, *Data location* | E7-02, E7-03, E7-04, E7-06 | S |

**Context.** Local setups run the agent and ExactDocs on one machine without a network port; the
stdio server must be safe next to a running HTTP server.

**Expected behavior**

```gherkin
Scenario: stdio MCP reads the same libraries as the server
  Given "/fixture/docs-repo" was imported by a running server
  When an agent starts "exactdocs serve --stdio"
  Then "list_libraries" lists "/fixture/docs-repo" without any token
```

**Criteria of success**

- [ ] stdio builds the read-only tool set over the same data dir; SQLite opened read-only (WAL), no worker, no migrations
- [ ] read-only WAL tested both next to a running HTTP server and with the HTTP server stopped
- [ ] works before any account exists; stdio needs the database to exist (created by the first `exactdocs serve` or `admin create`): a missing database is a clear error on stderr naming the path
- [ ] docs: README states that stdio needs an existing database
- [ ] nothing written to stdout except MCP frames (test)
- [ ] docs: README *Connect your agent*

## E7 · MVP-2

### E7-08 · feat: articles are exposed as MCP resources

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | MCP tools | MCP-03 (MVP-2) | E7-03 | S |

**Context.** Some clients browse resources rather than call tools.

```gherkin
Scenario: Reading an article as a resource
  When a client reads "exactdocs://fixture/docs-repo/guide/install.md?ref=v1.4.0"
  Then it gets the same Markdown as "read_article"
```

- [ ] resource template `exactdocs://{owner}/{repo}/{path*}{?ref}`; no ref → default version
- [ ] equality test with `read_article`

### E7-09 · feat: a stale chunk error points to the section's new location

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | MCP tools, backend / retrieval | MCP-04 (MVP-2) | E7-03, E3-12 | S |

**Context.** After a re-sync, an agent holding an old chunk ID should be able to continue, not
start its search over.

```gherkin
Scenario: The stale error carries the new chunk ID
  Given a section moved within its article during a re-sync
  When an agent reads its old chunk ID
  Then the "stale_chunk" error includes the new chunk ID and heading path
```

- [ ] match by heading path (and rename map for moved articles); no match → error without location
- [ ] unit + MCP tests

### E7-10 · feat: users get a ready-to-paste MCP config and agents get a usage skill

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | MCP tools | MCP-06 | E6-02 | S |

**Context.** Hand-written JSON is where setups break.

```gherkin
Scenario: A working snippet for Claude Code
  When the user runs "exactdocs config --client claude"
  Then a JSON snippet with the server URL and a newly created token is printed
  And an MCP client configured with it can list libraries
```

- [x] clients `claude`, `cursor`, `vscode` (also `claude-desktop`, `codex`); the token is a placeholder, `--show-token` uses the login token; `--new-token` creates a dedicated token via REST (AUTH-02, asks for the password)
- [x] a short "how to use ExactDocs" skill offered over MCP for clients that load skills
- [x] snippet validity test per client
