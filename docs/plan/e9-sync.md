# E9 Sync & lifecycle

!!! abstract "TL;DR"
    - **Goal:** Keep versions fresh, survive upstream failures, remove cleanly, edit settings safely.
    - **Stories:** SYNC-01 to SYNC-04, LIB-09, LIB-10
    - **Milestones:** MVP-1, MVP-2
    - **Issues, in build order:** E9-01, E9-03; MVP-2: E9-02, E9-04 to E9-07
    - **Status:** the epic ([#9](https://github.com/SirCypkowskyy/ExactDocs/issues/9)) is closed; GitHub holds the current issue bodies.

## E9 · MVP-1

### E9-01 · feat: a branch version re-syncs on demand and re-processes only what changed

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | SYNC-01, LIB-04 (branch keeps its ID), MCP-04 (`stale_chunk`), SYNC-04 (last good version kept, error on the job) | E3-05a, E7-03 | M |

**Context.** Docs change; users want the latest state of a branch with one click, without paying
for a full re-import every time, and an upstream problem must never take their docs away.

**Expected behavior**

```gherkin
Scenario: Nothing to do when the head did not move
  Given "/fixture/docs-repo/next" is imported at the branch head
  When the user syncs the library
  Then no import runs and the version is reported up to date

Scenario: Only changed articles are re-chunked
  Given a commit changed "guide/install.md" on branch "next"
  When the user syncs "/fixture/docs-repo"
  Then only "guide/install.md" is re-chunked
  And the version keeps its ID with the new commit SHA

Scenario: A changed section's old chunk ID is stale
  Given an agent holds the chunk ID of a section of "/fixture/docs-repo/next"
  And the branch was re-synced after that section changed
  When the agent reads that chunk ID
  Then it gets the error "stale_chunk"

Scenario: A failed sync keeps the last good version
  Given "/fixture/docs-repo/next" is imported
  And the fixture HTTP git server no longer serves the repository
  When the user syncs the library
  Then "/fixture/docs-repo/next" still serves the previous commit
  And the sync job is failed with its reason
```

**Criteria of success**

- [ ] `SyncLibrary` use case: for each branch version, `ls-remote` the head; import only if moved
- [ ] unchanged blobs reuse chunk sets (assert by counters on the job)
- [ ] `POST /api/v1/libraries/{owner}/{repo}/sync` (the CLI command is MVP-2, E6-03)
- [ ] a failed sync (any upstream error) leaves the last good version served and records the error on the job (shown on the home page by E8-03); distinct error codes and moved tags are MVP-2 (E9-02)
- [ ] behave `sync.feature` on the fixture branch, including the stale-chunk scenario (moved here from the former E5-05; `read_chunk` is E7-03)

### E9-03 · feat: removing a version or library removes it everywhere and frees its content

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | SYNC-03 | E3-05a, E5-02, E7-04 | M |

**Context.** Stale docs found by a user or an agent are worse than none; removed content must
disappear from every surface and from disk.

**Expected behavior**

```gherkin
Scenario: A removed version is gone everywhere
  When the user removes version "v1.3.0" of "/fixture/docs-repo"
  Then it does not appear in browse, search, list_libraries or search_docs
  And content used only by "v1.3.0" is garbage-collected
  And content shared with "v1.4.0" is kept
```

**Criteria of success**

- [ ] `RemoveVersion` / `RemoveLibrary` use cases; `DELETE` REST routes (the CLI command is MVP-2, E6-03)
- [ ] use cases live in ingestion and call catalog and retrieval through bridges
- [ ] GC job run by ingestion, calling each domain's `CollectGarbage` through bridges: superseded manifests past their grace period, blobs, chunk sets and FTS rows not referenced by any manifest are deleted; chunk IDs kept as tombstones (E7-03) together with their version, article path, heading path, occurrence and content hash, so a stale ID can still be pointed to its section (E7-09); credentials of a removed library deleted
- [ ] default version recomputed after removal
- [ ] behave scenario over REST and MCP; GC unit tests on shared content

## E9 · MVP-2

### E9-02 · feat: sync failures get distinct error codes, and moved tags are reported

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | SYNC-04 (error codes, moved tags) | E9-01, E6-03 | M |

**Context.** An upstream problem (repo deleted or private, credential expired, branch deleted, tag
moved) must never take a team's docs away, and users need to know which one it was. E9-01 keeps
the last good version and records the error; this issue makes the reason precise.

**Expected behavior**

```gherkin
Scenario Outline: Upstream failures keep serving docs
  Given "/fixture/docs-repo" is imported
  And <problem>
  When the library is synced
  Then the last good version is still served
  And the library shows the error "<code>"
  Examples:
    | problem                           | code             |
    | the repository was deleted        | repo_unreachable |
    | the credential expired            | auth_failed      |
    | branch "next" was deleted         | ref_deleted      |
    | tag "v1.4.0" now points elsewhere | tag_moved        |
```

**Criteria of success**

- [ ] error codes stored on the sync job with time and message (shown by E8-03 through `GET …/jobs`)
- [ ] `exactdocs sync` exits non-zero with the reason
- [ ] sync checks tag versions for moved tags; a moved tag is reported, never silently re-imported
- [ ] behave scenarios using the fixture HTTP server (delete repo, rotate token, delete branch, move tag)

### E9-04 · feat: editing a library's paths or tag rules re-processes every version safely

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | LIB-09, TAG-02 (edit rules) | E9-01, E4-03 | M |

**Context.** The first selection is rarely perfect. Settings belong to the library, so every
version must follow, while users keep reading the old state until the new one is complete.

**Expected behavior**

```gherkin
Scenario: Adding an exclusion re-processes every version
  Given "/fixture/docs-repo" has versions "v1.3.0" and "v1.4.0"
  When the user adds the exclusion "docs/archive/**"
  Then a job re-processes both versions
  And until it finishes, both versions still list "docs/archive/" articles
  And afterwards neither does
```

**Criteria of success**

- [ ] `UpdateLibrarySettings` use case: validated paths and tag rules; one job re-processes all versions at their recorded commit SHAs (re-fetch when paths changed, tag-only changes re-use stored blobs)
- [ ] each version swapped atomically (E1-03)
- [ ] `PUT /api/v1/libraries/{owner}/{repo}/settings`; behave scenario

**Notes.** Owns `PUT …/settings` (in MVP-1 paths and tag rules are set only when adding,
E3-02 and E4-03). Chunking settings (re-chunk only) come with E4-05. Branch versions are
re-processed at their current commit, not synced.

### E9-05 · feat: new tags are imported automatically and branches re-synced on a schedule

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | SYNC-02 | E9-01, E3-11 | M |

**Context.** Users don't want to add every release by hand.

```gherkin
Scenario: A new matching tag becomes a version, old ones are pruned
  Given "/fixture/docs-repo" auto-imports tags "v*" keeping the last 2
  When tag "v1.5.0" is pushed and the scheduled check runs
  Then "v1.5.0" is imported
  And the oldest auto-imported version is removed
  And manually imported versions are kept
```

- [ ] per-library tag pattern, retention N, branch sync interval; scheduler (DBOS scheduled workflow)
- [ ] `auto` vs `manual` origin on versions; retention only removes `auto`
- [ ] tests with the kernel clock

### E9-06 · feat: a moved tag can be re-imported after confirmation

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend`<br/>`area: web` | backend / ingestion, web UI | SYNC-04 (MVP-2) | E9-02 | S |

```gherkin
Scenario: Confirming a moved tag
  Given tag "v1.4.0" was reported as moved
  When the user confirms the re-import
  Then "v1.4.0" is re-imported at its new commit and the error clears
```

- [ ] `POST /api/v1/libraries/{owner}/{repo}/versions/reimport` with body `{ref}` (the ref cannot be followed by a path segment); UI button on the error; CLI `--confirm`

### E9-07 · feat: library owners pin the default version

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend`<br/>`area: web` | backend / catalog, web UI | LIB-10 | E1-02, E8-06 | S |

**Context.** The newest tag is not always the one a team uses.

```gherkin
Scenario: A pinned default stays when a higher tag arrives
  Given the default of "/fixture/docs-repo" is pinned to "v1.3.0"
  When "v1.5.0" is imported
  Then "/fixture/docs-repo" still answers with "v1.3.0"
  And list_libraries shows the default as pinned
```

- [ ] pin/unpin use case + REST; unpinned follows the *Default version* rule
- [ ] UI pin action in the version picker; `list_libraries` field `default_pinned`
