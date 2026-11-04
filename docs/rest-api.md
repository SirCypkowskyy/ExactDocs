# REST API

The REST API under `/api/v1` is the only API of the web UI and the CLI. Its OpenAPI description
is served at `/api/v1/openapi.json` and committed as `web/openapi.json`; the web client's types
(`web/src/shared/lib/api-schema.d.ts`) are generated from it. After changing a route or a DTO run
`just api` and commit both files (a test and a CI step fail otherwise).

There is deliberately no interactive Swagger UI or ReDoc: they load their assets from a CDN, and
ExactDocs makes no third-party requests by default. Open the JSON in any OpenAPI viewer.

## Conventions

- **Operation IDs** are `<tag>-<function name>` (for example `catalog-list_all`), one tag per
  domain. They never change once published, because generated clients are named after them:
  renaming a handler function renames its operation ID, which is a breaking change.
- **Errors** have one shape for every error under `/api`: `{"error": "<code>", "detail": "<message>", "fields": []}`.
  Unknown routes and wrong methods are `not_found` / `method_not_allowed`; an unexpected failure
  is 500 `internal_error` (no internals in `detail`).
  `error` is the stable `DomainError.code` (`not_found` is 404, `conflict` 409, `validation_error`
  and every `ValidationError` 422, anything else 400). Request validation failures are 422 with
  `error: "validation_error"` and one `fields` entry (`loc`, `msg`, `type`) per invalid field.
- **First run**: until the first admin account exists, every `/api/v1` request except
  `POST /api/v1/setup`, `GET /api/v1/session` and the OpenAPI document is refused with 403
  `setup_required`, whatever the method (HEAD and OPTIONS included). `POST /api/v1/setup` creates the
  admin once (409 `already_set_up` afterwards). Only `/api/v1` is guarded: `/mcp` and
  `/.well-known/...` are not guarded by the setup yet; MCP access control comes with E2-03 (API
  tokens).
- **Authentication**: every `/api/v1` operation needs a signed-in caller (401 `unauthenticated`
  otherwise) except `POST /setup` and the three `/session` operations; a test pins that list, and
  the OpenAPI document marks every other operation with the `SessionCookie` security scheme.
  `POST /session` (`{"username", "password"}`) answers 201 with the session state and sets the
  `exactdocs_session` cookie; a wrong password and an unknown user are the same 401
  `invalid_credentials`. `GET /session` returns `{"state": "setup_required" | "signed_out" |
  "signed_in", "account": ...}` and never fails; `DELETE /session` ends the session on the server
  and is always 204. The cookie is an opaque random token (stored hashed), HttpOnly,
  SameSite=Lax, `Secure` over HTTPS (or with `EXACTDOCS_SECURE_COOKIES`), `Path=/api`, ends after
  7 days idle or 30 days in all. Unsafe requests with a foreign `Origin` are refused with 403
  (also sign-in and sign-out). `/mcp` never looks at the cookie. Signing in again with a live
  cookie ends that old session. The cookie's `Max-Age` is the 30-day limit; idle expiry is
  server-side only and accurate to about an hour (last use is written at most hourly), so do not
  test exact 7-day boundaries from a client.
- **Pagination**: list endpoints take `limit` (1 to 200, default 50) and an opaque `cursor`, and
  return `next_cursor` (`null` on the last page). Pass it back unchanged; a malformed cursor is a
  422 `invalid_cursor`. Helper: `exactdocs_kernel.paginate`.
- **Refs containing `/`**: library IDs are `/{owner}/{repo}` in the path. A ref may only be the
  last path segment, declared `{ref:path}`; a route that needs a ref and an article path takes
  `?ref=` and `?path=`, because servers decode `%2F` before routing.
