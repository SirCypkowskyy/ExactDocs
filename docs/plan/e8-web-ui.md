# E8 Web UI

!!! abstract "TL;DR"
    - **Goal:** Setup, add and watch, browse and switch versions, read, search, manage.
    - **Stories:** AUTH-01/02 (UI), BRW-01 to BRW-05, LIB-*, IMP-06, SRCH-*, TAG-* (UI)
    - **Milestones:** MVP-1, MVP-2
    - **Issues, in build order:** E8-01 to E8-04, E8-06, E8-07, E8-09, E8-10b; MVP-2: E8-10a, E8-11 to E8-15
    - **Status:** the epic ([#8](https://github.com/SirCypkowskyy/ExactDocs/issues/8)) is closed; GitHub holds the current issue bodies.

All UI issues: features in `web/src/features/<feature>/` (vertical slices, see
[Architecture](../architecture.md#web-client-vertical-slices)), data only through the generated
`/api/v1` client (E6-01), vitest + Testing Library tests per feature, fallow and Biome boundary
rules green. Each Gherkin scenario maps to a vitest test against mocked API responses (built from
the generated OpenAPI types, so UI work can start before the endpoints exist) and is checked once
manually against `just dev`; the Playwright end-to-end test of the whole loop is in E10-03b.

## E8 · MVP-1

### E8-01 · feat: the web UI has setup, sign-in and sign-out

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | AUTH-01 | E2-02, E6-01 | M |

**Context.** The first thing a new user sees decides whether the instance is safe: a fresh
instance must show only setup, and everything else must sit behind sign-in.

**Expected behavior**

```gherkin
Scenario: A fresh instance shows only the setup page
  Given no account exists
  When a user opens any page
  Then the setup page is shown
  When the user creates the admin account
  Then the user is signed in and sees the home page

Scenario: An expired session returns to sign-in
  Given the admin's session expired
  When the admin opens a library
  Then the sign-in page is shown and returns to that library after sign-in
```

**Criteria of success**

- [ ] `features/auth`: setup page, sign-in page, sign-out action, session state from `GET /api/v1/session`
- [ ] router guard: `setup_required` → setup; `401` → sign-in with a return URL (same-origin paths only)
- [ ] app shell (header with libraries, settings, sign-out) in `app/`
- [ ] vitest for guard logic and forms (validation, error messages)

### E8-02 · feat: users create, list and revoke API tokens in the UI

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | AUTH-02 | E8-01, E2-03 | S |

**Context.** Connecting an agent should not require the CLI; the token must be easy to copy once
and impossible to see again.

**Expected behavior**

```gherkin
Scenario: A new token is shown once
  When the admin creates a token "laptop" expiring in 30 days under Settings → Tokens
  Then its value is shown once with a copy button
  And after closing the dialog only its name, expiry and last use are listed
```

**Criteria of success**

- [ ] `features/tokens`: list, create (name, optional expiry), revoke with confirmation
- [ ] the value never enters the query cache or local storage (test)
- [ ] vitest for the dialog and list

**Notes.** A ready-to-paste MCP config belongs to MCP-06 (E7-10, MVP-2), not here.

### E8-03 · feat: the home page lists libraries with versions, freshness and sync errors

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | BRW-05, SYNC-04 (error shown) | E8-01, E1-02, E1-05 | M |

**Context.** Users need to see what is available and how fresh it is, and spot a failing sync
before their agent gives stale answers.

**Expected behavior**

```gherkin
Scenario: Libraries with their status
  Given "/fixture/docs-repo" has versions "v1.3.0" and "v1.4.0" and its last sync failed
  When the user opens the home page
  Then the library shows its URL, refs with commit SHAs, article count, tags and last sync time
  And the sync error is shown with its reason
```

**Criteria of success**

- [ ] extend `features/libraries` (existing skeleton) to the real `/api/v1/libraries` shape
- [ ] last job status and error per library come from `GET /api/v1/libraries/{owner}/{repo}/jobs` (a separate query; catalog's `/libraries` carries no job state)
- [ ] empty state links to "Add library"; running imports show progress (E8-04)
- [ ] vitest for table rows, error badge and empty state

### E8-04 · feat: users add a library from the UI and watch its import, including skipped files (absorbs E8-05)

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | LIB-01, LIB-02, LIB-04, LIB-05, LIB-07, IMP-06, TAG-02 (rules set when adding) | E8-03, E3-01, E3-02, E3-04, E3-05b, E4-03 | L |

**Context.** Adding a library is the start of the main loop; it must catch a bad URL, a taken ID
or a wrong ref before anything is saved. Afterwards users need to know whether everything they
selected made it in, and why not.

**Expected behavior**

```gherkin
Scenario: Adding a library step by step
  When the user pastes the fixture repository URL
  Then the URL is checked and the ID "/fixture/docs-repo" is proposed
  When the user picks tag "v1.4.0" from the ref list and enters paths "docs/"
  And submits
  Then the import starts and its progress page opens

Scenario: A taken ID must be changed
  Given "/fixture/docs-repo" exists
  When the user pastes another URL that proposes "/fixture/docs-repo"
  Then submitting is blocked until another ID is entered

Scenario: Progress and problems
  Given an import of the fixture repository is running
  Then the job page shows files done of total, updating while it runs
  When it finishes
  Then skipped files are listed with "binary", "too large" or "undecodable"
```

**Criteria of success**

- [ ] `features/add-library`: URL check, editable ID, ref picker (tags, branches, free commit SHA), include/exclude paths, path tag rules (glob → tag; editing them later is MVP-2, E8-10a), optional token or SSH key (write-only fields; SSH host-key fingerprint shown from the check), title/description shown after the first import
- [ ] server errors mapped to field errors (`library_id_taken`, `unknown_ref`, `auth_required`, `host_key_changed`)
- [ ] `features/jobs`: polling `GET /api/v1/jobs/{id}` until finished (TanStack Query `refetchInterval`), problems table
- [ ] vitest for the form flow; vitest with fake timers for the job page

### E8-06 · feat: users browse a version as a file tree, switch versions on the same article, and open the exact commit (absorbs E8-08)

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | BRW-01 (tree), BRW-03, BRW-04, TAG-01 (shown), TAG-03 (tree filter) | E8-03, E1-03, E4-03 | L |

**Context.** Reading the docs is the point. The tree should mirror the repo, users sometimes need
the surrounding code at the exact imported commit, not the branch head, and they work on projects
pinned to different versions and compare them often.

**Expected behavior**

```gherkin
Scenario: Tree, article and source link
  When the user opens "/fixture/docs-repo" version "v1.4.0"
  Then the tree mirrors the repository paths and shows article titles and tags
  When the user opens "guide/install.md"
  Then a "View on GitHub" link points at the file at the commit SHA of "v1.4.0"

Scenario: Filtering the tree by tag
  When the user filters the tree by tag "api"
  Then only articles tagged "api" and their folders remain

Scenario: Switching keeps the path when it exists
  Given the user reads "guide/auth.md" in "v1.4.0"
  When the user switches to "v1.3.0"
  Then "guide/auth.md" of "v1.3.0" is shown
  And when the article does not exist there, the version's root is shown with a notice
```

**Criteria of success**

- [ ] routes `/libraries/$owner/$repo` with `?version=` and `?path=` search params (refs and paths never in path segments)
- [ ] `features/browse`: tree (lazy folders for large trees), article page (title, tags, front matter hidden, source link by host kind)
- [ ] version picker lists imported refs with kind and marks the default
- [ ] vitest for tree building, tag filter and the version fallback logic

### E8-07 · feat: articles render with code highlighting, tables, admonitions and inert MDX

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | BRW-01, IMP-04 (MDX inert) | E8-06 | M |

**Context.** Documentation written for MkDocs or GitHub must look right, and nothing in an
imported file may execute in the user's browser.

**Expected behavior**

```gherkin
Scenario: Both admonition syntaxes render
  When the user opens an article with "!!! note" and "> [!NOTE]" blocks
  Then both render as notes

Scenario: MDX components never run
  When the user opens an MDX article with a "<Tabs>" component
  Then the component is shown as code
```

**Criteria of success**

- [ ] Markdown renderer (proposal: `react-markdown` + `remark-gfm` + custom admonition plugins + a highlighter) with raw HTML disabled or sanitized
- [ ] headings get the same anchors as chunk anchors (E4-02) so search links land on sections
- [ ] images: the git host's raw URL at the commit for public repos, alt text for private ones
- [ ] vitest snapshots on fixture articles; an XSS test (script tags, `javascript:` links, event handlers)

### E8-09 · feat: users search a version with highlighted snippets and tag filters

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | SRCH-01, SRCH-02, TAG-03 (UI search) | E8-06, E5-03 | M |

**Context.** Users often know a term but not where it is documented, and must never get an
answer from a version they did not select.

**Expected behavior**

```gherkin
Scenario: No results in this version
  When the user searches "retry_policy" in "v1.3.0"
  Then "No results in v1.3.0" is shown

Scenario: A result opens the section
  When the user searches "retry_policy" in "v1.4.0"
  Then results show article, heading path and a highlighted snippet
  And opening a result scrolls to that section
```

**Criteria of success**

- [ ] `features/search`: query box in the library view, tag filter (any/all), result list
- [ ] snippet highlights rendered from offsets, never as HTML from the server
- [ ] vitest for empty state, highlighting and navigation

### E8-10b · feat: users edit a library's title, add versions, re-sync and remove in the UI

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: web` | web UI | LIB-07 (edit), LIB-11, SYNC-01, SYNC-03 | E8-06, E3-06, E3-07, E9-01, E9-03 | M |

**Context.** The loop does not end at import, and in MVP-1 the UI is the only client: users fix
titles, add releases, refresh branches and remove what is stale there. Removal must be hard to
do by accident.

**Expected behavior**

```gherkin
Scenario: Editing the title
  When the user changes the title of "/fixture/docs-repo" to "Payments SDK"
  Then the home page lists "Payments SDK"

Scenario: Adding a version
  When the user adds version "v1.3.0" to "/fixture/docs-repo"
  Then its import starts and "v1.3.0" appears in the version picker when done

Scenario: Re-syncing a branch
  When the user clicks "Re-sync" on "/fixture/docs-repo"
  Then a sync job starts and its progress is shown

Scenario: Removing a version asks for confirmation
  When the user removes version "v1.3.0" and confirms with the version name
  Then "v1.3.0" is no longer listed
```

**Criteria of success**

- [ ] `features/library-settings`: title/description edit (`PATCH`, E3-06), add version (ref picker reused from E8-04)
- [ ] re-sync action with job progress (the job view of E8-04); remove version/library with typed confirmation
- [ ] vitest for the forms, actions and confirmations

**Notes.** Editing paths and tag rules is MVP-2 (E8-10a).

## E8 · MVP-2

### E8-10a · feat: users edit a library's paths and tag rules in the UI

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: web` | web UI | LIB-09, TAG-02 (edit rules) | E8-06, E9-04 | S |

**Context.** The first selection is rarely perfect; users fix paths and tag rules without the
CLI.

**Expected behavior**

```gherkin
Scenario: Saving new paths warns about re-processing
  When the user adds the exclusion "docs/archive/**" in the library settings
  Then a warning says every version will be re-processed
  When the user confirms
  Then a re-processing job starts and its progress is shown
```

**Criteria of success**

- [ ] `features/library-settings` gains paths and tag rules; saving warns that every version is re-processed (`PUT …/settings`, E9-04)
- [ ] vitest for the form and the warning

### E8-11 · feat: the add-library form previews the matching files

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: web` | web UI | LIB-03, LIB-06 (`previousVersions` offered) | E3-08, E3-09 | S |

**Context.** Fix a wrong pattern before waiting for an import.

```gherkin
Scenario: Preview before import
  When the user enters URL, ref and paths and clicks "Preview"
  Then the matching tree is shown with its file count
```

- [ ] preview tree with counts; `context7.json` pre-fill and `previousVersions` checkboxes shown
- [ ] vitest

### E8-12 · feat: relative links and images work inside ExactDocs

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: web` | web UI | BRW-02, BRW-01 (MVP-2 images) | E3-10, E8-07 | M |

**Context.** Docs written for GitHub link to each other with relative paths.

```gherkin
Scenario: A relative link opens the imported article at its heading
  When the user clicks "[setup](../setup.md#docker)"
  Then the imported "setup.md" opens at "Docker" in the same version
  And links to files outside the selection open on the git host at the commit
```

- [ ] link resolver (pure function, table-tested) for relative paths, anchors, outside-selection files
- [ ] images from the imported copies (E3-10)

### E8-13 · feat: the version switcher follows renamed articles

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: web` | web UI | BRW-04 (MVP-2) | E3-12, E8-06 | S |

```gherkin
Scenario: Switching to a version where the article was renamed
  Given the user reads "guide/setup.md" in "v1.3.0"
  When the user switches to "v1.4.0"
  Then "guide/install.md" opens
```

- [ ] picker asks the rename map before falling back to the root; vitest

### E8-14 · feat: users tag articles by hand in the UI

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: web` | web UI | TAG-01 (MVP-2) | E4-06 | S |

```gherkin
Scenario: Adding a manual tag
  When the user adds the tag "onboarding" to "guide/install.md"
  Then the tag shows on the article and in the tree for every version
```

- [ ] tag editor on the article page distinguishing front-matter, rule and manual tags; vitest

### E8-15 · feat: one search box across all libraries

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: web` | web UI | SRCH-03 | E5-06 | S |

```gherkin
Scenario: Narrowing a global search to one library
  When the user searches "token" from the header
  Then results are grouped by library with counts
  When the user selects "/fixture/docs-repo"
  Then only its default version's results remain
```

- [ ] global search page with library facet; vitest
