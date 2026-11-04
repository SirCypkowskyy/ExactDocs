# Architecture

ExactDocs is a **modular monolith**: one deployable (one Docker image, one `uvx exactdocs`), split
into **domains** with hard boundaries. Inside every domain we follow **hexagonal architecture**
(ports & adapters) with the dependency rule of clean architecture. The React client mirrors the
same idea with **vertical slices**. All of this is enforced by tests, not by convention.

## Repository layout

```
pyproject.toml                  uv workspace root: dev tools, ruff, ty, pytest, behave config
packages/
  exactdocs-kernel/             shared kernel (separate, published package)
    src/exactdocs_kernel/
  exactdocs/                    the application (published as `exactdocs`)
    src/exactdocs/
      bootstrap/                composition root: settings, wiring, HTTP/MCP/CLI entry points
      catalog/                  domain
      identity/                 domain: the admin account (later sessions, API tokens)
      retrieval/                domain
      _web/                     built web UI (gitignored, added by CI / Docker)
    tests/                      pytest: unit, integration, architecture
    features/                   behave: acceptance scenarios (Gherkin)
web/                            React client (Vite, TanStack Router + Query, shadcn)
deploy/                         Dockerfile, self-hosted runner scripts
```

## Domains and what may import what

```
                 ┌──────────────── bootstrap (composition root) ────────────────┐
                 │  picks adapters · wires domains via bridges · HTTP/MCP/CLI    │
                 └───────┬───────────────────────┬───────────────────────────────┘
                         │ imports               │ imports
                    ┌────▼─────┐   ✗ never   ┌────▼──────┐
                    │ catalog  │ ◄─────────► │ retrieval │   ... more domains
                    └────┬─────┘             └────┬──────┘
                         │                        │
                    ┌────▼────────────────────────▼────┐
                    │ exactdocs_kernel (shared kernel) │  stdlib only
                    └──────────────────────────────────┘
```

| From \ may import | own domain | other domain | `bootstrap` | `exactdocs_kernel` |
|---|---|---|---|---|
| a domain | yes | **no** | **no** | yes |
| `bootstrap` | yes (any domain) | yes | yes | yes |
| `exactdocs_kernel` | - | **no** | **no** | yes |

**How domains talk to each other.** The consumer declares what it needs as a *driven port* in its
own vocabulary (`retrieval.ports.driven.IndexedVersions`). The composition root implements it with
a **bridge** that calls the provider's *driving port* (`bootstrap/bridges.py:CatalogIndexedVersions`
uses `catalog.ports.driving.GetLibrary`). Neither domain knows the other exists, so a domain can
later move to its own package or service without touching the other.

### Bridges are one-way

Bridges point in one direction only: **retrieval → catalog** and **ingestion → catalog /
retrieval**. Catalog calls no other domain, and nothing calls ingestion, so the domain graph has
no cycles. An architecture test (planned in E1-03 of the [delivery plan](plan.md)) checks the
direction of every bridge in `bootstrap/bridges.py`.

The kernel `NOTICE` constant (the untrusted-content notice every MCP result carries, see the
*MCP-07* story) is a reviewed kernel addition: it is shared text, not business logic, so it lives
in the kernel instead of being duplicated per domain.

**Why not a `shared` domain?** Everything shared ends up there. The kernel is a separate
*package* on purpose: adding to it is a visible, reviewed decision, it may only use the
standard library, and it cannot import the app. If two domains need the same *business*
concept, that is usually a missing domain, or a port plus a bridge.

**When to make a domain its own package.** When it gets its own release cadence, consumers
outside the app, or heavy dependencies (e.g. ML models for embeddings). Move
`src/exactdocs/<domain>` to `packages/exactdocs-<domain>/`; the structure stays the same.

## Inside a domain: the fixed module set

Every domain has exactly these modules. Each may start as a module (`models.py`) and grow into a
package (`models/__init__.py` + submodules) with the same name. No other top-level names.

| Module | Holds | May import |
|---|---|---|
| `errors.py` | domain exceptions (subclasses of kernel errors) | kernel |
| `models.py` | entities, value objects: `@dataclass(frozen=True, slots=True)`, `NewType` ids, pure logic | `errors`, kernel |
| `dtos.py` | boundary data: frozen Pydantic models (commands, queries, results) + `from_model` mappers | `models`, `errors` |
| `ports/driving.py` | **driving (primary) ports**: `Protocol`s for use cases the outside world calls | `dtos`, `models`, `errors` |
| `ports/driven.py` | **driven (secondary) ports**: `Protocol`s for what the domain needs (repositories, gateways, other domains) | `models`, `errors` |
| `use_cases.py` | one frozen dataclass per use case, `async __call__`, implements a driving port | all of the above |
| `module.py` | `<Domain>Module`: `build(**driven_adapters)` returns the wired driving ports | all of the above |
| `adapters/driving/` | `http.py` (FastAPI router factory), `mcp.py` (FastMCP tool registration), `cli.py` | `ports`, `dtos` (never `use_cases`/`module`) |
| `adapters/driven/` | `memory.py`, `sqlite.py`, `postgres.py`, `http_client.py`... implement driven ports | `ports`, `models` (never driving adapters) |
| `__init__.py` | public API for `bootstrap`: the `Module` | |

The core (`errors`, `models`, `dtos`, `ports`, `use_cases`, `module`) never imports FastAPI,
FastMCP, Starlette, uvicorn, httpx, SQLAlchemy or DBOS. `models` and `errors` don't import Pydantic
either. Frameworks live in adapters and `bootstrap`.

Naming follows Alistair Cockburn's own terms from *Hexagonal Architecture Explained* (2024):
**driving** / **driven** ports and adapters, rather than primary/secondary or inbound/outbound.

## Persistence: one data directory, one database

Everything ExactDocs stores lives in the **data directory**: `EXACTDOCS_DATA_DIR`, which the Docker
image sets to `/data`, else the platform user-data directory (so `uvx` and stdio MCP share it).
`bootstrap/database.py` creates it, refuses to start if it is not writable, and opens one SQLite
file in it (`EXACTDOCS_DATABASE_URL` overrides the path): SQLAlchemy **Core**, async, no ORM,
on aiosqlite, in WAL mode with a busy timeout and `foreign_keys=ON`.

- **Each domain owns its tables**, prefixed with its name (`catalog_libraries`, `retrieval_...`).
  Foreign keys only between tables of the same domain; another domain's IDs are held by value
  and its tables are never read.
- **One Alembic history, owned by `bootstrap`** (`bootstrap/migrations/versions`), run on start
  (`Container.running()`) and reported by `/api/health` as `schema_revision`. A domain's
  revision is plain `op.create_table(...)`, not an import of the adapter's `Table` objects, so
  old revisions never change. Use `op.batch_alter_table` to change an existing table,
  `op.execute("CREATE VIRTUAL TABLE ... USING fts5(...)")` for FTS5. `migrate()` runs the
  revisions in one `BEGIN IMMEDIATE` transaction with `foreign_keys` off (a batch alteration
  recreates the table, and with the pragma on SQLite would cascade-delete the rows of tables
  that reference it) and fails, rolling back, if `PRAGMA foreign_key_check` finds a violation
  before the commit.
- **Adding a table:** `just migration "add jobs table"`, fill in `upgrade()`/`downgrade()`, set
  `down_revision` to the current head if you rebased over another revision (a test fails if the
  history ever has two heads), then write the adapter.
- **Adapters** live in `adapters/driven/sqlite.py`, take the `AsyncEngine` and describe their
  tables with Core `Table` objects (`catalog.adapters.driven.sqlite` is the reference). They run
  in the same adapter contract test as the in-memory adapter. SQLAlchemy, Alembic and aiosqlite
  are imported only by driven adapters and `bootstrap` (architecture test).
- Tests build a container on an empty temporary data directory (`tests/conftest.py` points
  `EXACTDOCS_DATA_DIR` at one for every test) and seed data through the repository, so the
  catalog starts empty in production.

## Identity: accounts and the setup guard

`identity` owns accounts (`identity_accounts`: username, password hash, `role`, created time).
Passwords are hashed by the `PasswordHasher` driven port; its adapter is **argon2id**
(`argon2-cffi`, RFC 9106 low-memory profile: 64 MiB, 3 passes), run in a thread, with `verify`
constant-time. The use cases take the password as a `SecretStr`, an unknown username costs one
hash like a real check, and wrong password and unknown user raise the same error.

`AccountRepository.add_first` stores an account only while the table is empty, in one atomic
statement under `BEGIN IMMEDIATE`, so two concurrent setups (or `exactdocs admin create` next to
the running server) can never create two admins. `bootstrap/rest.py:SetupGuard` answers
`403 setup_required` for everything under `/api/v1` until an account exists (default deny; the
exemptions are `POST /setup`, `GET /session` and `openapi.json`) and stops asking the database
once one does.

## Python conventions

- **`Protocol`, not ABC.** Ports are structural. Adapters and use cases never inherit from them;
  `ty` checks conformance where they are wired (`CatalogModule.build(repository=...)`).
  Importing `abc.ABC` is banned by ruff. The only inheritance in the codebase is exceptions.
- **Immutable by default.** `@dataclass(frozen=True, slots=True, kw_only=True)` for entities,
  value objects, use cases and modules; `ConfigDict(frozen=True, extra="forbid")` for DTOs.
- **Use cases are callables.** `await catalog.list_libraries()` reads like the port name, and any
  `async def` with the same signature is a valid test double.
- **Explicit composition root, no DI container.** `bootstrap/container.py` builds everything
  once, in plain code. Tests build modules directly with in-memory adapters.
- **Python 3.14 idioms.** Lazy annotations (PEP 649, no `from __future__` and no
  `TYPE_CHECKING` blocks), `type` aliases (PEP 695), `typing.Self`, `NewType` for identifiers.
- **Errors.** Domains raise kernel error subclasses (`NotFoundError`...). The HTTP adapter maps
  them to status codes in one place (`bootstrap/http.py`); MCP returns them as tool errors.
- **Async all the way.** Ports are `async`; synchronous libraries are wrapped in adapters.

## What enforces it

| Rule | Tool |
|---|---|
| Domain isolation, layer direction, adapter rules, framework-free core, no cycles, kernel purity | ArchUnitPython, `packages/exactdocs/tests/architecture/test_architecture.py` |
| Fixed module set per domain, driving/driven split | same file (filesystem check) |
| No `abc.ABC`, no relative imports, every ruff rule incl. preview | ruff (`select = ["ALL"]`, `preview = true`) |
| Protocol conformance, types | ty |
| Web: features don't import each other; `shared` imports no feature; routes use feature public APIs | fallow (`web/.fallowrc.json`) + Biome `noRestrictedImports` |

## Web client: vertical slices

```
web/src/
  app/                       providers, router, QueryClient: composition only
  routes/                    TanStack Router file routes: thin, compose feature public APIs
  features/<feature>/
    api/                     queryOptions, fetchers (one place that knows the endpoint)
    components/  hooks/  model/
    index.ts                 the only import path other code may use
  shared/ui/ shared/lib/ shared/config/   shadcn components, http client, utilities
```

A feature mirrors a backend use case or domain view. Features never import each other; if two
need the same thing it moves to `shared` (when generic) or stays duplicated (when it is business
logic that only looks the same). Details: [web/README.md](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/web/README.md).
