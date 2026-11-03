# User stories

Written as **"As _actor_, I want _capability_, because _reason_."** with short acceptance criteria.

!!! abstract "The main use case"
    **Point ExactDocs at a git repository, pick the folder or Markdown files you care about, and
    browse them** in the web UI and from your AI agent over MCP, pinned to the exact git ref
    (tag, branch or commit) you imported.

    Everything in the product serves this loop: **add a repo → choose docs → import → browse and
    search → keep in sync**. Other ways of getting documentation in (`llms.txt`, website crawls,
    package registries, prebuilt snapshots) come later.

!!! tip "From story to issue"
    A story becomes a **Feature** issue: the story is the *Context*, the acceptance criteria become
    *Expected behavior* (a behave scenario) and *Criteria of success*. Put the story ID
    (e.g. `SRC-01`) in the issue.

**Milestones:** **MVP** completes the main loop for one user; **Next** makes it work for a team;
**Later** adds other sources and extras.

## Actors

| Actor | Who |
|---|---|
| **User** | A developer who adds repositories and reads their docs in the web UI or CLI |
| **AI agent** | An MCP client (Claude Code, Cursor, VS Code...) reading the same docs on the user's behalf |
| **Admin** | Whoever runs a shared instance for a team |
| **ExactDocs** | The system itself: importer, sync scheduler, search |

---

## MVP: the main loop

### 1. Add a repository

- **[SRC-01]** As a user, I want to add a source by pasting a git URL (GitHub, Bitbucket, GitLab, Gitea or any HTTPS/SSH git server), because my documentation lives in repositories, not on one hosting platform.
    - Acceptance: `https://github.com/org/repo`, `https://bitbucket.org/org/repo`, `git@host:org/repo.git` and a self-hosted HTTPS URL are all accepted; the URL is checked (reachable, is a git repo) before anything is saved.
- **[SRC-02]** As a user, I want to choose which docs to import with a folder or glob patterns (`docs/`, `**/*.md`, `README.md`, exclusions like `docs/archive/**`), because a repo holds far more than documentation.
    - Acceptance: only matching `.md` / `.mdx` files are imported; exclusions win over inclusions; the default for an empty selection is `**/*.md`.
- **[SRC-03]** As a user, I want to preview the matching file tree (count and size) before importing, because I want to fix a wrong pattern before waiting for an import.
    - Acceptance: after entering URL, ref and patterns, the UI and `exactdocs add --dry-run` list the files that would be imported, without storing anything.
- **[SRC-04]** As a user, I want to pick the git ref to import (a tag, a branch, or a commit), because docs must match the version of the code I work with.
    - Acceptance: the ref is resolved to a commit SHA at import time and stored with every document; the UI lists tags and branches to choose from.
- **[SRC-05]** As a user, I want to import from private repositories with a personal access token or SSH deploy key, because most internal docs are not public.
    - Acceptance: credentials are stored encrypted, never shown again after saving, never logged, and used only for that source's host.
- **[SRC-06]** As a user, I want the same from the CLI (`exactdocs add <git-url> --ref v1.4.0 --path docs/`), because I script my setup and use ExactDocs without the UI.
    - Acceptance: the CLI and the UI create identical sources; `exactdocs sources` lists them.

### 2. Import

- **[IMP-01]** As ExactDocs, I want to fetch only what is needed (shallow clone of the chosen ref, sparse checkout of the selected paths), because large monorepos must not take minutes or gigabytes to import.
    - Acceptance: importing `docs/` from a large repo transfers only that ref's objects; no full history is cloned.
- **[IMP-02]** As ExactDocs, I want to split each Markdown file by its structure (headings, code blocks, tables) and keep each section's heading path, because search and agents need meaningful sections, not arbitrary text windows.
    - Acceptance: no code block is ever split; every section knows its file path and heading path (`Guide > Install > Docker`).
- **[IMP-03]** As a user, I want to see import progress and per-file problems (unreadable files, broken front matter), because I need to know whether everything I selected actually made it in.
    - Acceptance: the UI shows files done / total and lists failed files with the reason; one bad file does not fail the whole import.
- **[IMP-04]** As ExactDocs, I want an import to be all-or-nothing per version and resumable after a restart, because readers must never see half of a version, and a crash must not start a large import from zero.
    - Acceptance: while importing, the previous version keeps being served; after a killed worker restarts, the import continues and finishes with no duplicates.

### 3. Browse

- **[BRW-01]** As a user, I want to browse an imported source as a file tree and read each Markdown file rendered (code highlighting, tables, admonitions), because reading the docs is the point.
    - Acceptance: the tree mirrors the repo paths; a page renders headings, code blocks with language, tables and images.
- **[BRW-02]** As a user, I want relative links and images between docs to work inside ExactDocs, because docs written for GitHub link to each other with relative paths.
    - Acceptance: `[setup](../setup.md#docker)` opens the imported page at that heading; images from the repo display; links to files outside the selection open the file on the git host.
- **[BRW-03]** As a user, I want a "view on GitHub/Bitbucket" link on every page with the exact commit, because I sometimes need the surrounding code or history.
    - Acceptance: the link points at the file at the imported commit SHA, not at the branch head.
- **[BRW-04]** As a user, I want to switch between imported versions of the same source (e.g. `v1.3` and `v1.4`), because I work on projects pinned to different versions.
    - Acceptance: a version picker lists imported refs; switching keeps me on the same file path if it exists in the other version.
- **[BRW-05]** As a user, I want a home page listing my sources with their version, file count and last sync time, because I need to see at a glance what is available and how fresh it is.
    - Acceptance: each source shows URL, imported refs, commit SHAs, file count and last sync status.

### 4. Search

- **[SRCH-01]** As a user, I want full-text search across a source and version, with results showing the file, heading and a highlighted snippet, because I often know a term but not where it is documented.
    - Acceptance: exact identifiers (`useActionState`, `--no-verify`) rank the defining section first; results link to the section anchor.
- **[SRCH-02]** As a user, I want search to stay within the version I selected, because an answer from another version is worse than none.
    - Acceptance: searching `v1.3` never returns text that exists only in `v1.4`; "no results in v1.3" is shown even when other versions match.

### 5. Use it from my AI agent (MCP)

- **[MCP-01]** As an AI agent, I want to list available sources and their imported versions, because I must know what documentation exists before reading it.
    - Acceptance: `list_sources` returns name, git URL, refs and commit SHA per version.
- **[MCP-02]** As an AI agent, I want to list a source's file tree and read a whole file or one section by heading, because I navigate docs like a human: overview first, then the relevant page.
    - Acceptance: `list_files(source, version)` and `read_doc(source, version, path, heading?)` return the original Markdown verbatim with its path and commit SHA.
- **[MCP-03]** As an AI agent, I want to search one source and version and get verbatim sections with their location, because I quote documentation, I don't paraphrase it.
    - Acceptance: `search_docs(source, version, query)` returns sections with path, heading path, commit SHA and a link; a version with no match returns an explicit empty result, never another version.
- **[MCP-04]** As a user, I want a ready-to-paste MCP config for my agent, because hand-written JSON is where setups break.
    - Acceptance: `exactdocs config --client claude|cursor|vscode` prints a working snippet with URL and token; stdio mode (`uvx exactdocs serve --stdio`) needs no token.
- **[MCP-05]** As a user, I want agent-facing text to be treated as untrusted (invisible Unicode stripped, results marked as external content), because a doc file can contain instructions aimed at my agent.
    - Acceptance: every MCP result is wrapped in an external-content marker; zero-width and bidi control characters are removed on import.

### 6. Keep it in sync

- **[SYNC-01]** As a user, I want to re-sync a source with one click (or `exactdocs sync <source>`), because docs change and I want the latest version of a branch.
    - Acceptance: a branch source re-imports only when the branch head moved; unchanged files are not re-processed.
- **[SYNC-02]** As a user, I want new tags matching a pattern (e.g. `v*`) to be imported automatically as new versions, because I don't want to add every release by hand.
    - Acceptance: a scheduled check finds new matching tags and imports them; older versions stay available until removed.
- **[SYNC-03]** As a user, I want to remove a version or a whole source, because I don't want stale docs to be found by me or my agent.
    - Acceptance: after removal nothing from it appears in browse, search or MCP results.

### 7. Run it

- **[RUN-01]** As a user, I want to start ExactDocs with one command (`uvx exactdocs serve` or one `docker run`) and add my first repo in under five minutes, because I won't adopt a tool that takes an afternoon to set up.
    - Acceptance: from a clean machine, the first repo is browsable and searchable within five minutes; SQLite needs no setup.
- **[RUN-02]** As a user, I want everything to stay on my machine or server, because my docs and queries are private.
    - Acceptance: no outbound connections except to the git hosts I added (and telemetry only if I enable it).

---

## Next: teams

- **[TEAM-01]** As an admin, I want one shared instance on PostgreSQL with user accounts and API tokens, because the whole team should browse the same imported docs.
- **[TEAM-02]** As an admin, I want sources grouped into namespaces and tokens scoped to them, because internal docs of one team should not be visible to everyone.
    - Acceptance: a token never sees sources outside its namespaces, not even their names.
- **[TEAM-03]** As an admin, I want to declare sources in a `exactdocs.sources.yaml` kept in our own repo (URL, ref or tag pattern, paths) and apply it with a dry-run diff, because the list of imported docs should go through code review.
- **[TEAM-04]** As a user, I want a push to the docs repository (webhook from GitHub/Bitbucket/GitLab) to trigger a sync, because teammates should read the merged docs, not last night's.
- **[TEAM-05]** As an admin, I want sign-in through our identity provider (OIDC) or a trusted proxy, because we don't want another set of passwords.
- **[TEAM-06]** As an admin, I want health/readiness endpoints, backups and upgrades that don't require re-importing, because the instance becomes something the team depends on.

## Later: beyond Markdown in git

These are good ideas that do not belong to the main loop yet.

| Idea | Why later |
|---|---|
| Import from `llms.txt` / `llms-full.txt` | A second source type; the git importer comes first |
| Crawl documentation websites (with a domain allowlist and SSRF protection) | Needs a crawler, rate limiting and HTML-to-Markdown conversion |
| Resolve library docs from package registries (PyPI, npm) and lockfiles | Requires a curated registry that maps packages to repos and paths |
| Semantic (vector) search and reranking next to full-text search | Full-text is enough to prove the loop; add vectors when evals show the gain |
| Prebuilt, signed index snapshots and a public registry of popular libraries | Depends on the registry and a stable index format |
| Context7-compatible tool aliases | Useful for migration once the MCP tools are stable |
| Accuracy eval suite in CI (recall@k, wrong-version rate) | Starts once search quality, not import, is the bottleneck |
| Other formats: reStructuredText, AsciiDoc, Jupyter notebooks | Markdown covers most repositories |
