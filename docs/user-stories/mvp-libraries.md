# MVP: setup, libraries and imports

!!! abstract "TL;DR"
    - Stories without a marker are MVP-1. *(MVP-2)* marks stories that can wait, including every
      CLI command that talks to the server (CLI-01).
    - AUTH-01 to AUTH-02 and CLI-01: the first admin account, API tokens, and the CLI as a REST
      client.
    - LIB-01 to LIB-11: add a library from any git URL, choose paths and refs, private repository
      credentials, title and description from the README, pinned defaults and extra versions.
    - IMP-01 to IMP-06: shallow sparse fetch, heading-based chunking, front matter and MDX,
      reStructuredText, all-or-nothing resumable imports and per-file problems.
    - TAG-01 to TAG-03: tags from front matter and path rules, and tag filters.

- Stories without a marker are **MVP-1**.
- *(MVP-2)* marks whole stories.
- *MVP-2:* marks the part of an acceptance criterion that can wait.

!!! note "The CLI in MVP-1"
    In MVP-1 users manage tokens and libraries in the web UI (and over REST); stdio and HTTP MCP
    work. The CLI has only its local commands (`serve`, `admin create`, `admin reset-password`).
    Every `exactdocs` command that talks to the server (`login`, `token`, `add`, `libraries`,
    `version add`, `sync`, `remove`) is *MVP-2* (CLI-01).

## First run and access

- **[AUTH-01]** As a user starting ExactDocs for the first time, I want to create the first (admin) account in the web UI or with `exactdocs admin create`, because even a single-user instance on a network port must not be open to anyone.
    - Acceptance:
        - until an account exists, the UI shows only the setup page and the API refuses everything else
        - local accounts use hashed passwords
        - the UI has login and logout, sessions expire, and `exactdocs admin reset-password` (local command) recovers a lost password
        - the session cookie is HttpOnly and SameSite=Lax, state-changing requests are Origin-checked, and the cookie is never accepted on `/mcp`.
- **[AUTH-02]** As a user, I want to create, list and revoke API tokens in the UI and with `exactdocs token create|list|revoke`, because my agent (MCP over HTTP), the CLI and REST clients need credentials.
    - Acceptance:
        - a token is shown once, stored hashed, can have an expiry, and is accepted by MCP and REST
        - stdio MCP (`exactdocs serve --stdio`) needs no token.
    - *MVP-2:* the CLI: `exactdocs token create|list|revoke`, tokens accepted by the CLI, and `exactdocs login <url>` asks for username and password, calls a REST endpoint that issues a named API token, and stores it in the CLI config (`--token` accepts an existing token instead).
- **[CLI-01]** *(MVP-2)* As a user, I want the CLI to work as a client of the server's REST API (`/api/v1`, see Decisions) (server URL and token from flags, env, or a config file written by `exactdocs login`), because the CLI should behave exactly like the UI and work against a remote instance too.
    - Acceptance:
        - every command goes through the REST API except the local ones: `serve`, `admin create` and `admin reset-password` (plus `reindex`, `backup` and `restore` once RUN-04 and OPS-02 exist)
        - a CLI action and the same UI action produce identical results.

## Add a library

- **[LIB-01]** As a user, I want to add a library by pasting a git URL (GitHub, Bitbucket, GitLab, Gitea or any HTTPS/SSH git server), because my documentation lives in repositories, not on one hosting platform.
    - Acceptance:
        - `https://github.com/org/repo`, `https://bitbucket.org/org/repo`, `git@host:org/repo.git` and a self-hosted HTTPS URL are accepted
        - the URL is checked (reachable, a git repo) before anything is saved
        - the default library ID follows the Terms rules.
- **[LIB-02]** As a user, I want to choose which docs to import with a folder or glob patterns (`docs/`, `**/*.md`, `README.md`, exclusions like `docs/archive/**`), because a repo holds far more than documentation.
    - Acceptance:
        - matching `.md` / `.mdx` / `.rst` files are imported (`.txt` only when a path names `.txt`, #435)
        - exclusions win over inclusions
        - an empty selection means `**/*.{md,mdx}`.
    - *MVP-2:* images referenced by imported articles are imported too (size-capped) so they render without access to the git host.
- **[LIB-03]** *(MVP-2)* As a user, I want to preview the matching file tree (count and size) before importing, because I want to fix a wrong pattern before waiting for an import.
    - Acceptance: after entering URL, ref and patterns, the UI and `exactdocs add --dry-run` list the files that would be imported, without storing anything.
- **[LIB-04]** As a user, I want to pick the git ref to import (tag, branch or commit), because docs must match the version of the code I work with.
    - Acceptance:
        - without a ref, the repository's default branch is used
        - the ref is resolved to a commit SHA stored with the version and carried by every article, chunk and search response
        - the UI offers tags and branches
        - a commit version can also be addressed by its short SHA. A branch version keeps its ID while its commit moves forward on sync (see IMP-05).
- **[LIB-05]** As a user, I want to import from private repositories with a personal access token or SSH deploy key, because most internal docs are not public.
    - Acceptance:
        - credentials are encrypted with a key from `EXACTDOCS_SECRET_KEY` (generated and stored in the data volume on first run if unset), never shown after saving, never logged, and sent only to that library's host
        - losing the key means re-entering credentials, not losing docs.
- **[LIB-06]** *(MVP-2)* As a user, I want ExactDocs to honor a `context7.json` in the repository (`projectTitle`, `description`, `folders`, `excludeFolders`, `excludeFiles`, `rules`, `previousVersions`), because many projects already describe their docs for context7 and I shouldn't repeat that.
    - Acceptance:
        - when the file exists it pre-fills title, description and path selection (all still editable)
        - `previousVersions` are offered for import
        - `rules` are stored and returned by `query-docs`.
- **[LIB-07]** As a user, I want each library to have a title and description, because agents choose libraries by them in `resolve-library-id`.
    - Acceptance:
        - defaults come from the root README's H1 (its text, or its image's alt text; else the alt text of a logo the README opens with; never a lower heading) and the first paragraph after it (the root README is always fetched for this, even outside the selected paths), else the repo name
        - both are editable.
    - *MVP-2:* `context7.json` values take precedence.
    - Decisions:
        - the README of the library's *default version* wins (the one `/owner/repo` resolves to, so a README of an older tag never overwrites it)
        - its text is refreshed whenever that version is imported. Removing the default version, or pinning or unpinning it (LIB-10), does not re-derive the text: it stays until the new default is imported again. `README.md` is preferred over `README.mdx`. Title = first heading, description = first paragraph after it (plain text, invisible characters stripped, cut at 120 / 500 characters; tables and link-only lines are skipped, HTML headings such as `<h1>` are ignored)
        - README text is untrusted. Text typed by a user is sanitized the same way (single-line title, no invisible characters). A field the user edited (`PATCH /api/v1/libraries/{owner}/{repo}`) is never overwritten again, per field
        - a missing heading or paragraph falls back to the repo name and an empty description.
- **[LIB-08]** *(MVP-2)* As a user, I want the same from the CLI (`exactdocs add <git-url> --id /acme/payments --ref v1.4.0 --path docs/`), because I script my setup.
    - Acceptance: `exactdocs libraries` lists what the UI shows (CLI-01).
- **[LIB-09]** *(MVP-2)* As a user, I want to edit a library's paths and path tag rules (TAG-02), because my first selection is rarely perfect.
    - Acceptance:
        - settings apply to the whole library: saving re-processes every version in the background
        - the previous state is served until the atomic swap (IMP-05). Versions are added with LIB-11 and removed with SYNC-03. Editing chunking settings (IMP-03) only re-chunks, without re-fetching. (In MVP-1, paths and tag rules are set when the library is added.)
- **[LIB-10]** *(MVP-2)* As a library owner, I want to pin the default version, because the newest tag is not always the one my team uses.
    - Acceptance:
        - a pinned default stays until unpinned
        - unpinned, it follows the *Default version* rule
        - the UI and `list_libraries` show whether it is pinned.
    - Decisions:
        - only an imported version can be pinned (its exact ref, or a unique short SHA of a commit version)
        - removing the pinned version unpins the library. Changing the pin does not re-derive the title and description (LIB-07): re-import the new default to refresh them.
- **[LIB-11]** As a user, I want to add another version (ref) to an existing library, because I need `v1.3.0` next to `v1.4.0`.
    - Acceptance:
        - in the UI and with `exactdocs version add /acme/payments v1.3.0`
        - same validation as LIB-04
        - uses the library's paths, path tag rules (TAG-02) and chunking.

## Import and chunking

- **[IMP-01]** As ExactDocs, I want to fetch only what is needed (shallow clone of the chosen ref, sparse checkout of the selected paths and the root README; *MVP-2:* referenced images), because large monorepos must not take minutes or gigabytes to import.
    - Acceptance:
        - importing `docs/` from a large repo transfers only that ref's objects
        - no full history is cloned.
- **[IMP-02]** As ExactDocs, I want to chunk each article by its Markdown headings (document-structure chunking), keeping each chunk's heading path, because header-based chunks are almost always the best retrieval unit for documentation.
    - Acceptance:
        - by default one chunk = one heading and its content, split with markdown-it-py (Chonkie was dropped in #27: it needs the network)
        - code blocks and tables are never split
        - every chunk stores article path, heading path (`Guide > Install > Docker`) and position
        - chunk IDs follow the Terms rule.
- **[IMP-03]** *(MVP-2)* As a user, I want to customize chunking per library (split level such as `h2` or `h3`, minimum/maximum chunk size with merging of tiny sections, or another chunker), because some docs have huge sections and others one-line headings.
    - Acceptance:
        - chunking settings are part of the library's configuration
        - changing them re-chunks without re-cloning
        - defaults apply when nothing is set.
- **[IMP-04]** As ExactDocs, I want to read front matter and MDX safely, because many doc sites use both.
    - Acceptance:
        - an article's title is front-matter `title`, else its first H1, else the file name
        - front matter is parsed (title, tags, description), hidden in the rendered view and returned as metadata by `read_article`
        - MDX is treated as Markdown, and JSX components are shown as inert code, never executed.
- **[IMP-06]** As a user, I want a Sphinx documentation set in reStructuredText (SQLAlchemy's `doc/build`, behave's `docs/`) imported like Markdown, because much of the Python ecosystem documents itself that way (#435).
    - Acceptance:
        - `.rst` files are parsed with docutils (no Sphinx build, no network) and written as the Markdown the chunker takes, so headings (any adornment style), paragraphs, lists, tables, code blocks with their language, chunks, heading paths, anchors, search, the outline and `read_article` work as for Markdown. `code-block` / `sourcecode` / `literalinclude` keep their language
        - `include` and `literalinclude` read files of the fetched paths (relative to the article, `/x` from the folder of `conf.py`), at most 8 levels and 64 files deep, and count toward the import's byte budget
        - admonitions (`note`, `warning`, `seealso`, `versionadded`, `deprecated`...) become GitHub alerts
        - `toctree` and `index` are not indexed
        - `:class:` / `:func:` / `:meth:`... are code, `:ref:` links to a section of the same file (else its title or label as text), `:doc:` links to the `.rst` file
        - substitutions are replaced. An unknown directive keeps its argument and content as text, an unknown role its text as code, and the file gets a `markup` problem
        - nothing about a file's markup fails the import. Markdown and reStructuredText under the selected paths are imported into the same version.
- **[IMP-05]** As ExactDocs, I want an import to be all-or-nothing per version and resumable after a restart, because readers must never see half a version, and a crash must not restart a large import from zero.
    - Acceptance:
        - while (re)importing, the previous state keeps being served and is swapped atomically when done
        - an interrupted import restarts cleanly.
    - *MVP-2:* a killed worker resumes where it stopped (durable jobs with DBOS) and finishes with no duplicates.
- **[IMP-06]** As a user, I want to see import progress and per-file problems, because I need to know whether everything I selected made it in.
    - Acceptance:
        - the UI shows files done / total and lists skipped files with the reason (too large, binary, undecodable: non-UTF-8 files are decoded by detected encoding or skipped)
        - one bad file does not fail the import.

## Tags

- **[TAG-01]** As a user, I want articles to be tagged, from their front matter (`tags: [api, auth]`) automatically and by hand in the UI, because I want to slice documentation by topic across folders.
    - Acceptance: front-matter tags are imported and shown on the article and in the tree.
    - *MVP-2:*
        - manual tags in the UI
        - they belong to the library (all versions) and are keyed by article path, following renames detected by git.
- **[TAG-02]** As a user, I want to assign tags by path rules in the library configuration (`docs/api/** → api`), because most repos have no front matter but a meaningful folder layout.
    - Acceptance:
        - rules apply on every import
        - tags from front matter and rules combine.
    - *MVP-2:* manual tags (TAG-01) combine with them.
- **[TAG-03]** As a user or AI agent, I want to filter browsing and search by tags (any of / all of), because "only the API reference" or "only ADRs" is a common need.
    - Acceptance: the UI tree, UI search and the MCP tools `list_articles` and `search_docs` accept tag filters, applied before ranking.
