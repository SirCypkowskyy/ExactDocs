# E3 · MVP-1

!!! abstract "TL;DR"
    - **Milestone:** MVP-1
    - **Issues, in build order:** E3-01 to E3-04, E3-05a, E3-05b, E3-06, E3-07
    - **Stories:** LIB-01, -02, -04, -05, -07, -11, IMP-01, IMP-05, IMP-06
    - A git URL is checked and gets a proposed ID, then only the chosen ref and paths are fetched
      (blobless, shallow, sparse) and published as a complete version or nothing.
    - Private repositories use an encrypted token or SSH deploy key; one bad file is skipped with
      its reason, never failing the import.

## E3-01 · feat: pasting a git URL validates the repository and proposes a library ID

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | LIB-01 | E1-02 | M |

**Context.** Docs live on GitHub, Bitbucket, GitLab, Gitea and self-hosted servers. A user should
paste any git URL and learn immediately whether it works, before anything is saved, with a
sensible library ID proposed.

**Expected behavior**

```gherkin
Scenario Outline: Common git URLs are accepted with a default ID
  When a user checks the repository URL "<url>"
  Then it is accepted with the proposed library ID "<id>"
  Examples:
    | url                                           | id                 |
    | https://github.com/acme/payments              | /acme/payments     |
    | https://bitbucket.org/acme/billing            | /acme/billing      |
    | https://gitlab.com/acme/platform/sub/docs     | /acme/docs         |
    | https://git.example.com/acme/handbook.git     | /acme/handbook     |
    | git@git.example.com:acme/payments.git         | /acme/payments     |
    | file://<fixtures>/fixture/docs-repo           | /fixture/docs-repo |
    | http://127.0.0.1:<port>/fixture/docs-repo.git | /fixture/docs-repo |

Scenario: A taken ID asks for another one
  Given library "/acme/payments" exists from GitHub
  When a user checks "https://bitbucket.org/acme/payments"
  Then the user is asked to choose another library ID
```

**Criteria of success**

- [ ] URL parser for HTTPS and SSH (`git@host:org/repo.git`, `ssh://`), plus `file://` and plain HTTP (used by the fixture servers and the smoke test; default ID from the last two path segments), host kind (GitHub, GitLab, Bitbucket, Gitea, other) for source links; the step fills `<fixtures>` and `<port>` from the running fixture servers
- [ ] default ID per Terms: owner (top-level group for nested GitLab groups) + repo name; collision → `409 library_id_taken`
- [ ] reachability check with `git ls-remote` (system git) and a 15 s timeout; "not a git repo", "unreachable" and "auth required" are distinct errors
- [ ] REST: `POST /api/v1/repositories/check` returns host kind, proposed ID, default branch (E3-04 adds the SSH host-key fingerprint)
- [ ] unit tests (parser table), integration test against the fixture HTTP git server

**Notes.** Decisions *Git*: no git hosting APIs, only `git`. A missing `git` binary is reported
clearly at start (also covered by E10-03b).

## E3-02 · feat: a library is created with its doc selection and a ref resolved to a commit

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion, backend / catalog | LIB-02, LIB-04 | E3-01, E1-05 | M |

**Context.** A repo holds far more than docs, and docs must match the code version a user works
with. Creating a library means choosing paths and a ref; the ref is pinned to a commit SHA so
everything later can say exactly what was imported.

**Expected behavior**

```gherkin
Scenario: Without a ref the default branch is imported
  When a user adds the fixture repository with paths "docs/" and no ref
  Then the library has a version for the default branch
  And that version records the branch head commit SHA

# Verified here by the pure-function table test; the scenario runs in E3-05a's `import.feature`.
Scenario: Exclusions win over inclusions
  When a user adds the fixture repository with paths "docs/**" and exclusion "docs/archive/**"
  Then no article under "docs/archive/" is imported
```

**Criteria of success**

- [ ] `AddLibrary` use case: URL, optional ID, ref, include/exclude patterns; empty selection means `**/*.{md,mdx}`; only `.md`/`.mdx` files are articles; exclusions win
- [ ] ref resolution via `ls-remote`: tag, branch, full or short commit SHA; unknown ref → `422 unknown_ref`
- [ ] the library is stored and an import job queued (job ID returned); `POST /api/v1/libraries`
- [ ] `GET /api/v1/repositories/refs?url=...` lists tags and branches for the UI picker
- [ ] pattern matching is a pure function with a table test (folders, globs, exclusions)
- [ ] behave `add_library.feature` against the fixture repo

**Notes.** The selection belongs to the library (Decisions *Library settings*). Import itself is
E3-05a.

## E3-03 · feat: imports fetch only the chosen ref and paths

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | IMP-01 | E3-02 | M |

**Context.** Large monorepos must not take minutes or gigabytes to import. Fetching one ref,
without history, and only the selected paths keeps imports fast and the data dir small.

**Expected behavior**

```gherkin
Scenario: Only the selected paths of one ref are fetched
  Given the fixture repository has history and files outside "docs/"
  When "docs/" at "v1.4.0" is fetched
  Then the working copy contains "docs/" and the root README only
  And no commit older than "v1.4.0" was fetched
```

**Criteria of success**

- [ ] driven port `GitGateway` with a system-`git` adapter: blobless (`--filter=blob:none`), shallow (`--depth 1`), sparse checkout (non-cone patterns from the selection plus the root README); commits fetched by SHA
- [ ] each fetch uses its own temp dir under the data dir, removed afterwards (also on failure)
- [ ] git runs with a timeout, no interactive prompts (`GIT_TERMINAL_PROMPT=0`), no global/system config influence
- [ ] integration test on the fixture HTTP server asserts the object count / no history
- [ ] docs: README states the `git` requirement for `uvx`

**Notes.** Decisions *Git*. Referenced images are MVP-2 (E3-10).

## E3-04 · feat: private repositories import with an encrypted access token or SSH deploy key

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | LIB-05 | E3-03, E3-07 | M |

**Context.** Most internal docs are private. Users must be able to give ExactDocs a token or deploy
key without it ever being shown again, logged, or sent to another host.

**Expected behavior**

```gherkin
Scenario: A private repository imports with a token
  Given the fixture HTTP git server requires a token
  When a user adds it with that token
  Then the library imports
  And the token is never returned by the API

Scenario: Losing the secret key keeps the docs
  Given a private library was imported
  When ExactDocs restarts with a different secret key
  Then the library is still readable
  And adding a version to it fails with "credentials_required"
```

**Criteria of success**

- [ ] credentials encrypted with a key from `EXACTDOCS_SECRET_KEY`, generated into the data dir on first run if unset (file mode 0600)
- [ ] HTTPS tokens passed through a credential helper/`GIT_ASKPASS` env, never in the URL or argv; SSH keys via a temp key file and `GIT_SSH_COMMAND`, deleted after use
- [ ] credentials sent only to the library's host (redirects to other hosts fail)
- [ ] SSH host keys: `StrictHostKeyChecking=accept-new`, `UserKnownHostsFile=<data>/known_hosts`, `GlobalKnownHostsFile=/dev/null`; the published GitHub, GitLab and Bitbucket host keys are pre-seeded; `POST /api/v1/repositories/check` returns the host-key fingerprint; a changed key is a hard error `host_key_changed` (unit tests for the SSH options and for mapping ssh's "host key changed" failure to that error)
- [ ] a log-capture test proves secrets never appear in logs or error messages
- [ ] undecryptable credentials → library error `credentials_required`, docs keep being served
- [ ] docs: README *Configuration* (`EXACTDOCS_SECRET_KEY`, the known-hosts file)

**Notes.** Decided SSH host-key policy: trust on first use for unknown hosts, pinned keys for
the big three hosts, never silently accept a changed key.

## E3-05a · feat: an import publishes a complete version or nothing

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | IMP-05, LIB-04 (SHA carried) | E1-03, E1-04, E1-05, E3-03, E4-01, E4-02, E4-03 | L |

**Context.** Readers must never see half a version. This issue wires fetch, parse, chunk and tag
into one job that publishes atomically and reuses everything already stored.

**Expected behavior**

```gherkin
Scenario: An import publishes the whole version at once
  When "docs/" of the fixture repository at "v1.3.0" is imported
  Then "/fixture/docs-repo/v1.3.0" lists every selected article
  And every article and chunk carries the commit SHA of "v1.3.0"

Scenario: A failed import leaves the previous state served
  Given "/fixture/docs-repo/next" is imported
  When a re-import of "next" fails before activation
  Then "/fixture/docs-repo/next" still serves the previous commit
```

**Criteria of success**

- [ ] `ImportVersion` use case: fetch → enumerate → decode → parse → tag → chunk → store blobs and chunk sets → `IndexManifest` → `ActivateManifest`
- [ ] progress done/total updated per file
- [ ] a crash before activation leaves the previous state served (test with a failing fake gateway); the pending manifest is discarded in catalog and retrieval through bridges
- [ ] registers the pending-manifest discard (catalog and retrieval `DiscardPendingManifests`) as the import job kind's recovery hook (E1-05), so a restart discards it before the job re-runs (integration test)
- [ ] blobs already stored are not re-parsed or re-chunked (dedup test: importing `v1.4.0` after `v1.3.0` chunks only changed blobs)
- [ ] files over the size cap (default 2 MiB, configurable) are not read into memory (the skip reason and listing come with E3-05b)
- [ ] behave `import.feature` on the fixture repo (publish, version isolation, failed import, E3-02's exclusion scenario, E4-03's tag-combination scenario)

**Notes.** Bridges: ingestion → catalog (`StoreManifest`, `ActivateManifest`,
`DiscardPendingManifests`), ingestion → retrieval (`IndexManifest`, `DiscardPendingManifests`).
`IndexManifest` already feeds the FTS5 index (E5-02), so imported versions are searchable.

## E3-05b · feat: one bad file never fails an import, and the job lists every skipped file with its reason

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | IMP-06 (incl. decoding) | E3-05a | M |

**Context.** One bad file must not cost a user the whole import, and users need to know whether
everything they selected made it in, and why not.

**Expected behavior**

```gherkin
Scenario: One bad file does not fail the import
  When the fixture repository is imported with its binary, oversized and undecodable files
  Then the import succeeds
  And the job lists the skipped files with reasons "binary", "too large" and "undecodable"

Scenario: A Latin-1 file is decoded, not skipped
  When the fixture repository is imported
  Then its Latin-1 article is imported with its accented characters intact
```

**Criteria of success**

- [ ] decode: UTF-8, else the detected encoding, else skip as `undecodable`
- [ ] skip reasons: `too_large` (default cap 2 MiB per file, configurable), `binary`, `undecodable`; malformed front matter imports the article and lists a problem (E4-01)
- [ ] per-file problems (path, reason) stored on the job (E1-05) and returned by `GET /api/v1/jobs/{id}`
- [ ] behave scenarios on the fixture repo

**Notes.** The UI list is in E8-04.

## E3-06 · feat: libraries get a title and description from the root README

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion, backend / catalog | LIB-07 | E3-05a | S |

**Context.** Agents pick libraries by title and description in `resolve-library-id`. Users should
get good defaults without typing, and be able to fix them.

**Expected behavior**

```gherkin
Scenario: Defaults come from the root README even outside the selection
  When the fixture repository is added with paths "docs/"
  Then its title is the README's first heading
  And its description is the README's first paragraph

Scenario: The user can edit them
  When the user changes the title to "Payments SDK"
  Then "list_libraries" shows "Payments SDK"
```

**Criteria of success**

- [ ] root README always fetched (E3-03) and parsed for first heading and first paragraph; fallback: repo name, empty description
- [ ] user edits are kept across re-imports (a set flag per field)
- [ ] `PATCH /api/v1/libraries/{owner}/{repo}` for title and description
- [ ] unit tests (README extraction table), behave scenario

**Notes.** `context7.json` precedence is MVP-2 (E3-09). The UI edit is E8-10b.

## E3-07 · feat: users add another version to an existing library

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | LIB-11 | E3-05a | S |

**Context.** Teams work on projects pinned to different releases and need `v1.3.0` next to
`v1.4.0`, imported with exactly the same settings so versions stay comparable.

**Expected behavior**

```gherkin
Scenario: A second version uses the library's settings
  Given "/fixture/docs-repo" is imported at "v1.4.0"
  When the user adds version "v1.3.0"
  Then both versions are listed
  And "v1.3.0" contains only articles matching the library's paths
```

**Criteria of success**

- [ ] `AddVersion` use case: same ref validation as LIB-04; uses the library's paths, tag rules and chunking; duplicate ref → `409`
- [ ] `POST /api/v1/libraries/{owner}/{repo}/versions`
- [ ] default version recomputed after the import (test: adding `v1.5.0` moves the default)
- [ ] behave scenario on the fixture repo

**Notes.** UI in E8-10b; CLI `exactdocs version add` is MVP-2 (E6-03).
