# E1 Foundation & data model

!!! abstract "TL;DR"
    - **Goal:** A persistent data directory and schema, IDs and the default version, manifests over deduplicated content, version-scoped chunk IDs, the job worker and the fixture repository that later issues build on.
    - **Stories:** RUN-05, IMP-05 (atomic swap), LIB-04 (IDs, SHA), Terms
    - **Milestones:** MVP-1
    - **Issues, in build order:** E1-01 to E1-06; MVP-2: E1-07
    - **Status:** the epic ([#1](https://github.com/SirCypkowskyy/ExactDocs/issues/1)) is closed; GitHub holds the current issue bodies.

## E1 · MVP-1

### E1-01 · feat: ExactDocs keeps its data in one data directory with a migrated SQLite database

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / catalog | RUN-01 (data location) | - | M |

**Context.** Today the catalog is an in-memory demo, so nothing survives a restart. Every later
story (imports, tokens, sync) needs durable storage in the place the [Decisions](../decisions/index.md) table promises:
`/data` in Docker, the platform user-data directory for `uvx`, the same path for stdio MCP.

**Expected behavior** (pytest integration tests)

- Starting the app on an empty data directory creates the database there at the Alembic head
  revision.
- A library stored before a restart (new app instance on the same data dir) is listed after it.
- A non-writable data directory makes start fail with a message naming the path.
- The same `LibraryRepository` contract cases pass on the memory and the SQLite adapter.

**Criteria of success**

- [ ] data dir from `EXACTDOCS_DATA_DIR`, else `/data` in the image, else the platform user-data dir; created if missing; a non-writable dir fails start with a clear message
- [ ] `EXACTDOCS_DATABASE_URL` overrides the SQLite path in the data directory
- [ ] SQLite opened in WAL mode with foreign keys (within a domain only) and a busy timeout; schema migrations run on start; `/api/health` reports the schema revision
- [ ] SQLAlchemy Core (async, no ORM) on aiosqlite; one Alembic history owned by `bootstrap`, `render_as_batch=True`; FTS5 tables created via `op.execute`
- [ ] SQLite `LibraryRepository` adapter; the adapter contract test runs the same cases on memory and SQLite
- [ ] the container wires SQLite; the demo catalog exists only as test data (behave `Background`)
- [ ] architecture tests green (database libraries only in `adapters/driven` and `bootstrap`)
- [ ] docs: README *Configuration* lists `EXACTDOCS_DATA_DIR` and `EXACTDOCS_DATABASE_URL`

**Notes.** Decisions *Persistence*: one database, each domain owns its tables (prefixed
`catalog_`, `retrieval_`, ...), never reads another domain's tables, and has no foreign keys to
them.

### E1-02 · feat: libraries and versions are addressed by context7-style IDs with a predictable default version

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / catalog | LIB-04, Terms (Library ID, Version, Default version) | E1-01 | M |

**Context.** Agents and users address docs as `/owner/repo` or `/owner/repo/<ref>`, exactly like
context7. If the ID parsing or the default-version rule is fuzzy, an agent gets docs for the wrong
version, which is the one thing ExactDocs promises never to do.

**Expected behavior** (pytest unit and contract tests)

- Parsing `/acme/payments/v1.4.0` gives library `/acme/payments` and ref `v1.4.0`; parsing
  `/acme/payments/release/1.4` gives ref `release/1.4` (everything after two segments is the ref).
- `/Acme/Payments` resolves to the stored `/acme/payments`; refs stay case-sensitive (`V1.4.0` is
  not `v1.4.0`); an ID segment outside `[a-z0-9._-]` (after lower-casing) is a validation error.
- With versions `v1.3.0`, `v1.4.0`, `v1.5.0-rc.1` and branch `main`, `/acme/payments` resolves to
  `v1.4.0`, and the response states `v1.4.0` (default-version rule table test).
- A unique short SHA (≥ 7 chars) finds its commit version; an ambiguous prefix is a validation
  error.

**Criteria of success**

- [ ] models: `LibraryId` (exactly two segments, each `[a-z0-9._-]+`, stored lower-case, matched case-insensitively), `VersionRef` (case-sensitive), `RefKind` (tag, branch, commit), `Version` with commit SHA, `Library` with title, description, source URL, host kind and settings (include/exclude paths, tag rules, chunking config)
- [ ] default version per Terms: highest stable semver tag (pre-releases excluded), else default-branch version, else most recently imported; unit-tested as a table
- [ ] a commit version is also found by a unique short SHA (≥ 7 chars); an ambiguous prefix is a validation error
- [ ] REST: `GET /api/v1/libraries`, `/libraries/{owner}/{repo}`, `/libraries/{owner}/{repo}/versions/{ref:path}` (ref always last); unknown → `404 not_found`
- [ ] existing behave features (`catalog.feature`, `search.feature`) move from the `/reactjs/react.dev 19.1` demo to fixture-shaped data
- [ ] unit + adapter contract tests (memory, SQLite)

**Notes.** Pinning (LIB-10) is MVP-2 (E9-07); keep a nullable `pinned_version` column now.
Decided: library IDs are stored lower-case and matched case-insensitively; refs stay
case-sensitive; ID charset `[a-z0-9._-]` per segment.

### E1-03 · feat: each version is a manifest over deduplicated article content, activated atomically

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / catalog | IMP-05 (atomic swap), LIB-04 (commit SHA per version), Decisions *Version storage* | E1-02 | M |

**Context.** Libraries get many tags and frequent re-syncs. Storing each version as a manifest
over shared, content-addressed files keeps that cheap, and activating a manifest in one step is
what guarantees readers never see half a version.

**Expected behavior** (pytest contract tests, memory and SQLite)

- With `/acme/payments/main` active at commit `aaa111` and a manifest for `bbb222` stored but not
  activated, `GetArticle("guide/install.md")` returns the `aaa111` content.
- After `ActivateManifest(bbb222)`, the same call returns the `bbb222` content and the version
  reports commit `bbb222`.
- A failure injected during activation leaves `aaa111` active.
- When `v1.3.0` and `v1.4.0` contain the same blob of `guide/install.md`, the content store holds
  it once.

**Criteria of success**

- [ ] `Manifest`: entries (article path, blob SHA, title, tags, front matter, size), commit SHA, state (pending, active, superseded)
- [ ] article content store keyed by git blob SHA; writes are idempotent
- [ ] driving ports `StoreManifest`, `ActivateManifest` (one transaction flips the version's active manifest and commit SHA), `ListArticles` (path prefix, `limit` + `cursor`), `GetArticle` (version + path), `DiscardPendingManifests`, `CollectGarbage`
- [ ] a failure during activation leaves the previous manifest active (test)
- [ ] REST: `GET /api/v1/libraries/{owner}/{repo}/articles?ref=<ref>&path_prefix=...` (tree) and `GET .../article?ref=<ref>&path=<path>` (one article); no `ref` means the default version
- [ ] architecture test for bridge direction: bridges in `bootstrap/bridges.py` go only retrieval → catalog and ingestion → catalog / retrieval, with no cycles (see [Architecture](../architecture/domains.md#bridges-are-one-way))
- [ ] unit + adapter contract tests (memory, SQLite)

**Notes.** The catalog knows nothing about chunks and holds no foreign keys to other domains;
other domains keep manifest IDs by value. Pending-manifest discard and GC are per domain and
triggered by ingestion through bridges (the import job's recovery hook in E3-05a, GC in E9-03). Superseded manifests are kept for a grace
period (configurable) so stale chunk IDs can be recognized (E7-03), then collected. Routes follow
Decisions *Refs containing `/`*: a route that needs both a ref and an article path takes `?ref=`
and `?path=`.

### E1-04 · feat: chunks are stored once per content and addressed by version-scoped chunk IDs

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / retrieval | Terms (Chunk), Decisions *Version storage*, MCP-04, IMP-02 (chunk IDs) | E1-03 | M |

**Context.** Search results must be addressable (`read_chunk`, neighbors) and must stay valid
across a branch re-sync when the section did not change. Chunk IDs scoped to one version make
`read_chunk` unambiguous, while deduplicated chunk content keeps many versions cheap.

**Expected behavior** (pytest contract tests, memory and SQLite)

- `/acme/payments/main` indexed at `aaa111`, then re-indexed at `bbb222` where only
  `guide/install.md` changed: every chunk of `guide/auth.md` has the same chunk ID in both
  manifests.
- When `v1.3.0` and `v1.4.0` contain the same blob of `guide/install.md`, its chunk set is stored
  once, and its chunks have a different chunk ID in each version.
- `IndexManifest` called twice with the same input stores nothing new.
- The `ChunkId` golden test pins the hash of a known input.

**Criteria of success**

- [ ] `ChunkSet` keyed by (blob SHA, chunking-config hash): ordered chunks with heading path, occurrence index, content, content hash, anchor, code-block languages
- [ ] `ChunkId` = hash(version ID, article path, heading path, occurrence index, content hash), a pure function with a golden test
- [ ] per-manifest chunk rows: chunk ID, article path, `position`/`total`, `prev_chunk_id`/`next_chunk_id`, a copy of the article's tags
- [ ] driving ports `IndexManifest` (idempotent), `DiscardPendingManifests`, `CollectGarbage`; driven port `ActiveManifests` implemented by a bridge to the catalog
- [ ] contract tests (memory, SQLite), including the dedup case

**Notes.** Atomicity without a cross-domain transaction: chunk rows are written for the *new*
manifest ID first (invisible), then the catalog activates the manifest (E1-03); retrieval always
scopes queries to the version's active manifest ID. Manifest IDs are held by value (no foreign
key to catalog tables). Retrieval's pending-manifest discard and GC are triggered by ingestion
through a bridge, like the catalog's; chunk rows of superseded manifests stay for the same grace
period as the manifests.

### E1-05 · feat: imports and other long tasks run as background jobs with visible progress

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: feature`<br/>`status: ready`<br/>`area: backend` | backend / ingestion | IMP-05 (restart cleanly), IMP-06 (progress), Decisions *Background jobs* | E1-01 | M |

**Context.** Imports of large repos take time; a request must not block on them, and a restart
must not leave a library stuck "importing" forever. Users need to see how far a job got.

**Expected behavior** (pytest unit and integration tests)

- A job over 10 files that has finished 4 reports `done=4, total=10` through
  `GET /api/v1/jobs/{id}`.
- A job left `running` when the app stopped is re-queued on the next start and runs from the
  beginning, after the recovery hook registered for its job kind ran (tested with a fake job
  kind whose hook records the call).
- Two jobs for the same library never run at the same time.

**Criteria of success**

- [ ] new `ingestion` domain with the standard module set; architecture tests green
- [ ] `Job`: kind, library/version target, state (queued, running, succeeded, failed), done/total, per-file problems (path, reason), error, timestamps
- [ ] in-process worker started in the app lifespan, at most one job per library at a time
- [ ] a recovery hook per job kind: on start, each `running` job's hook runs (no-op by default), then the job is re-queued; the import's hook (pending-manifest discard) is registered by E3-05a
- [ ] REST: `GET /api/v1/jobs/{id}`, `GET /api/v1/libraries/{owner}/{repo}/jobs`
- [ ] unit tests with the kernel clock; integration test for restart recovery
- [ ] docs: `docs/architecture/domains.md` lists the `ingestion` domain

**Notes.** DBOS replaces the worker behind the same port in MVP-2 (E3-11). The worker is a
driving adapter (`ingestion/adapters/driving/worker.py`).

### E1-06 · feat: a versioned fixture docs repository backs every import and search test

| Milestone | Labels | Area | Stories | Depends on | Size |
|---|---|---|---|---|---|
| MVP-1 | `type: chore`<br/>`status: ready`<br/>`area: infra`<br/>`area: backend` | CI / release / infra | RUN-05 | - | M |

**Context.** Search quality, chunking and version isolation can only be asserted against stable,
known content. A real git repository with tags and a branch makes import, sync and ranking tests
reproducible on every machine and in CI.

**Expected behavior** (pytest tests on the built fixture)

- The built repository has tags `v1.3.0` and `v1.4.0` and a branch `next`, with the same commit
  SHAs on every machine (golden SHAs asserted).
- The identifier `retry_policy` occurs only in `v1.4.0`.
- Both fixture git servers (`file://` and smart HTTP on 127.0.0.1) serve `git ls-remote` for it.

**Criteria of success**

- [ ] `tests/fixtures/docs-repo/` holds per-commit trees; a pytest fixture and a behave hook build them into a git repo with fixed author and dates (stable SHAs)
- [ ] content: code blocks, tables, front matter (title, tags, description), MDX with JSX, both admonition syntaxes, `snake_case`, `camelCase`, `--flag`, `pkg.mod.fn`, a root README, a file renamed between tags, one Latin-1 file that decodes by detected encoding, one truly undecodable file, a binary file, an oversized file (> 2 MiB), an `AGENTS.md`
- [ ] `expected-queries.yaml`: query → expected top section (article path + heading path) per version
- [ ] fixture git servers: `file://` and smart HTTP on 127.0.0.1 (`git http-backend`) for network tests
- [ ] fixture README explains how to add content without breaking expected SHAs

**Notes.** Article paths are repo-relative: the scenario shorthand `guide/install.md` means
`docs/guide/install.md` in the fixture (`docs/api/auth.md` and `docs/guide/auth.md` both exist,
and `--path docs/` and `docs/archive/**` need the prefix). The suite is used by E4-02, E5-04, E3-05a, E3-05b, E9-01, E10-01, E10-03a (mounted
into the container), E10-03b and RET-09 (E11-02).

---

## E1 · MVP-2

### E1-07 · chore: Python conventions for constants, docstrings and data classes are enforced automatically

| Milestone | Labels | Area | Stories | Depends on | Size | Issue |
|---|---|---|---|---|---|---|
| MVP-2 | `type: chore`<br/>`status: triage`<br/>`area: backend` | backend (all Python packages) | - (engineering quality) | - | L | [#121](https://github.com/SirCypkowskyy/ExactDocs/issues/121) |

**Context.** Many agents write code in parallel; conventions must be checked by CI, not reviewers.

- [ ] constants only in `constants.py` or a `constants/` package (`__init__.py` re-exporting private topic modules like `_auth.py`, `_identity.py`); each typed `Final[...]` with an attribute docstring
- [ ] private by default: non-API modules, functions, classes and constants are `_private`; public APIs re-exported via `__init__.py`
- [ ] every function and method, private ones included, has a Google-style docstring with `Args:` and `Returns:` (and `Raises:`) whenever it has them; ruff `convention = "google"`, DOC201/DOC501 re-enabled
- [ ] every dataclass is `frozen=True, slots=True, kw_only=True` unless marked `# conventions: allow-... -- <reason>`; every dataclass and pydantic field has an attribute docstring; pydantic models use `use_attribute_docstrings=True`
- [ ] enforced by an AST checker in `tests/architecture/test_conventions.py` with good/bad fixtures per rule; existing code brought into compliance; rules documented in `docs/architecture/conventions.md`
