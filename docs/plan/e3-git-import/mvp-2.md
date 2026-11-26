# E3 · MVP-2

!!! abstract "TL;DR"
    - **Milestone:** MVP-2
    - **Issues, in build order:** E3-08 to E3-12
    - **Stories:** LIB-02, -03, -06, -07, IMP-01, IMP-05, C7-02; E3-12 supports TAG-01, BRW-04,
      MCP-04
    - A dry-run preview of the matching files, `context7.json` pre-filling the library, and images
      referenced by imported articles.
    - Killed imports resume through a DBOS durable workflow, and renames between versions are
      detected from git.

## E3-08 · feat: users preview the matching files before importing

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | LIB-03 | E3-03 | M |

**Context.** A wrong glob is only noticed after a long import. A dry run shows count, size and the
file tree first, without storing anything. No sizes: `git ls-tree -l` lazily downloads every blob it
lists (measured on a `--filter=blob:none --depth=1` clone), which defeats a dry run.

```gherkin
Scenario: A dry run lists files without storing anything
  When a user previews the fixture repository at "v1.4.0" with paths "docs/**"
  Then the matching files are listed with their count
  And no library, version or job exists afterwards
```

- [ ] `POST /api/v1/repositories/preview` (URL, ref, patterns, optional credentials) fetches the tree only (no blobs) and returns paths, the total count and a truncated flag (no sizes: `ls-tree -l` downloads the blobs)
- [ ] `exactdocs add --dry-run` prints the same list (moved to a follow-up issue, which depends on E6-02 and E3-08)
- [ ] behave scenario; test that the database is unchanged

## E3-09 · feat: a repository's `context7.json` pre-fills the library

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | LIB-06, LIB-07 (MVP-2), C7-02 (MVP-2 rules) | E3-02, E7-06 | M |

**Context.** Many projects already describe their docs for context7; users should not repeat it.

```gherkin
Scenario: context7.json pre-fills the selection and rules
  Given the fixture repository has a context7.json with folders "docs" and rules "Use v2 client"
  When a user adds it
  Then title, description and paths are pre-filled and still editable
  And "query-docs" for the library includes the rule "Use v2 client"
```

- [ ] parses `projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`, `previousVersions`; invalid file → warning, ignored
- [ ] `context7.json` values take precedence over README defaults (LIB-07), user edits over both
- [ ] `previousVersions` offered for import (REST field + UI list in E8-11)
- [ ] `rules` stored on the library and returned by `query-docs`
- [ ] fixture repo gains a `context7.json` on branch `next`

## E3-10 · feat: images referenced by imported articles are imported too

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | LIB-02 (MVP-2), IMP-01 (MVP-2) | E3-05a | M |

**Context.** Private-repo images do not load from the git host, and offline instances should
render diagrams too.

```gherkin
Scenario: A referenced image is served from ExactDocs
  Given an imported article references "img/flow.png" in the repository
  When the article is read
  Then the image is served by ExactDocs at the imported commit
```

- [ ] relative image references collected at parse time; sparse checkout adds them; per-image (default 2 MiB, as E3-05b) and per-version size caps, oversize listed as skipped
- [ ] images stored by blob SHA (dedup) and served by `GET /api/v1/libraries/{owner}/{repo}/asset?ref=&path=` with the correct content type; SVG served with a restrictive CSP
- [ ] tests on the fixture repo

## E3-11 · feat: a killed import resumes where it stopped

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | IMP-05 (MVP-2), Decisions *Background jobs* | E3-05a | L |

**Context.** Large imports should not restart from zero after a crash or deploy.

```gherkin
Scenario: A killed worker resumes without duplicates
  Given an import of 200 files was killed after 120 files
  When ExactDocs starts again
  Then the import finishes from file 121
  And the version has each article exactly once
```

- [ ] DBOS durable workflow replaces the in-process worker behind the job port (steps: fetch, per-batch parse/chunk, publish)
- [ ] steps idempotent (content-addressed writes); the test kills the process mid-import
- [ ] DBOS used only in `ingestion/adapters` and `bootstrap`; architecture tests green

## E3-12 · feat: renames between versions are detected from git

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-2 | `type: feature`<br/>`status: triage`<br/>`area: backend` | backend / ingestion | supports TAG-01 (MVP-2), BRW-04 (MVP-2), MCP-04 (MVP-2) | E3-05a | M |

**Context.** Manual tags, the version switcher and stale-chunk hints should follow a file that was
moved, not lose it.

```gherkin
Scenario: A renamed article is linked across versions
  Given "guide/setup.md" in "v1.3.0" was renamed to "guide/install.md" in "v1.4.0"
  Then the rename map of "v1.4.0" maps "guide/setup.md" to "guide/install.md"
```

- [ ] on import, `git diff -M --name-status` against the previous version's commit (fetched shallowly) gives a rename map stored with the manifest
- [ ] catalog port `ResolveRenamedPath(version, old_path)`; tests on the fixture rename
