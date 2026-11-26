# REST API

!!! abstract "TL;DR"
    - Everything lives under `/api/v1`; the web UI and the CLI use nothing else.
    - The OpenAPI document is at `/api/v1/openapi.json` and in `web/openapi.json`. Run `just api`
      after changing a route or a DTO.
    - Callers sign in with the session cookie or an `exd_...` API token.
    - Each resource has its own page, listed below.

The REST API under `/api/v1` is the only API of the web UI and the CLI.

- Its OpenAPI description is served at `/api/v1/openapi.json` and committed as `web/openapi.json`.
- The web client's types (`web/src/shared/lib/api-schema.d.ts`) are generated from it.
- After changing a route or a DTO, run `just api` and commit both files. A test and a CI step
  fail otherwise.

!!! note "No Swagger UI or ReDoc"
    There is deliberately no interactive Swagger UI or ReDoc: they load their assets from a CDN,
    and ExactDocs makes no third-party requests by default. Open the JSON in any OpenAPI viewer.

## Base URL and callers

| What | Where |
|---|---|
| API base | `/api/v1` |
| OpenAPI document | `GET /api/v1/openapi.json` (no caller needed) |
| MCP endpoint | `/mcp`, API tokens only, outside this API |
| Health probes | `/healthz`, `/api/health`, `/readyz`, outside `/api/v1` ([Health](health.md)) |

Every `/api/v1` operation needs a caller: the session cookie or `Authorization: Bearer exd_...`
with an API token. A handful of sign-in and setup routes are exempt, and until the first admin
exists almost everything answers 403 `setup_required`. The details are on
[Authentication and tokens](authentication.md).

## Pages

| Page | What it covers |
|---|---|
| [Authentication and tokens](authentication.md) | first run, sessions, the sign-in throttle, external sign-in (OIDC), API tokens and their library scope |
| [Account](account.md) | interface preferences, own password, linked sign-in providers |
| [Users, roles and access log](users-and-access.md) | operator user management, library roles and grants, transfers, the access log |
| [Lists: pagination, sorting, filters](pagination.md) | `limit` and `cursor`, `offset`, `sort`, filters and `total` |
| [Errors](errors.md) | the error shape, status codes, `close_matches`, `library_id` |
| [Libraries and versions](libraries/index.md) | adding, editing, logos, `context7.json`, private repositories, default version, versions, removal |
| [Library settings](library-settings.md) | include and exclude paths, tag rules, chunking, the re-processing jobs |
| [Articles, outlines and tags](articles.md) | outlines, tags, manual tags, tag origins, renames |
| [Syncing, schedules and webhooks](sync.md) | re-syncing, re-importing a moved tag, the scheduled check, push webhooks, the sources file |
| [Search and answers](search.md) | retrieval settings, search modes, search across libraries, agentic answer and search, reranking |
| [AI providers](ai.md) | `/ai`: provider profiles, roles, embedding, spend |
| [Jobs](jobs.md) | job fields, who queued a job, statistics, cancelling, failures, import problems |
| [Usage and leaderboard](usage.md) | usage counts, reports, the leaderboard |
| [Health](health.md) | `/healthz` and `/readyz` |

## Conventions

- **Operation IDs** are `<tag>-<function name>`, for example `catalog-list_all`, with one tag per
  domain.
    - They never change once published, because generated clients are named after them.
    - Renaming a handler function renames its operation ID, which is a breaking change.
- **Errors** have one shape under `/api`. See [Errors](errors.md).
- **Lists** page with `limit` and `cursor`, and most also take `offset`, `sort` and filters. See
  [Lists](pagination.md).
- **Refs containing `/`**: library IDs are `/{owner}/{repo}` in the path.
    - A ref may only be the last path segment, declared `{ref:path}`.
    - A route that needs a ref and an article path takes `?ref=` and `?path=`, because servers
      decode `%2F` before routing.
