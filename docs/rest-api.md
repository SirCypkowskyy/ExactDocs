# REST API

The REST API under `/api/v1` is the only API of the web UI and the CLI. Its OpenAPI description
is served at `/api/v1/openapi.json` and committed as `web/openapi.json`; the web client's types
(`web/src/shared/lib/api-schema.d.ts`) are generated from it. After changing a route or a DTO run
`just api` and commit both files (a test and a CI step fail otherwise).

## Conventions

- **Operation IDs** are `<tag>-<function name>` (for example `catalog-list_all`), one tag per
  domain. They never change once published, because generated clients are named after them.
- **Errors** have one shape for every status: `{"error": "<code>", "detail": "<message>", "fields": []}`.
  `error` is the stable `DomainError.code` (`not_found` is 404, `conflict` 409, `validation_error`
  and every `ValidationError` 422, anything else 400). Request validation failures are 422 with
  `error: "validation_error"` and one `fields` entry (`loc`, `msg`, `type`) per invalid field.
- **Pagination**: list endpoints take `limit` (1 to 200, default 50) and an opaque `cursor`, and
  return `next_cursor` (`null` on the last page). Pass it back unchanged; a cursor the API did not
  issue is a 422 `invalid_cursor`. Helper: `exactdocs_kernel.paginate`.
- **Refs containing `/`**: library IDs are `/{owner}/{repo}` in the path. A ref may only be the
  last path segment, declared `{ref:path}`; a route that needs a ref and an article path takes
  `?ref=` and `?path=`, because servers decode `%2F` before routing.
