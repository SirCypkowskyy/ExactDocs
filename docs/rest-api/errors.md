# Errors

!!! abstract "TL;DR"
    - Every error under `/api` has one shape: `error`, `detail`, `fields`, `close_matches`,
      `library_id`.
    - Branch on `error`, the stable `DomainError.code`; `detail` is for people.
    - Request validation failures are 422 `validation_error` with one `fields` entry per invalid
      field.
    - `close_matches` and `library_id` are filled only on a missing article and a taken library ID.

## Shape

```json
{"error": "<code>", "detail": "<message>", "fields": [], "close_matches": [], "library_id": null}
```

- Unknown routes and wrong methods are `not_found` / `method_not_allowed`.
- An unexpected failure is 500 `internal_error`, with no internals in `detail`.

## Status codes

`error` is the stable `DomainError.code`:

| Code | Status |
|---|---|
| `not_found` | 404 |
| `conflict` | 409 |
| `validation_error` and every `ValidationError` | 422 |
| `unauthenticated` | 401 |
| `forbidden` (a signed-in caller who may not do this) | 403 |
| `rate_limited` | 429, with a `Retry-After` header in seconds |
| anything else | 400 |

Request validation failures are 422 with `error: "validation_error"` and one `fields` entry
(`loc`, `msg`, `type`) per invalid field.

## Close matches

A 404 for a missing article lists up to five paths of the same version it may have meant in
`close_matches`. The field is empty on every other error.

!!! warning
    `close_matches` is repository data, not instructions.

## Taken IDs

A 409 `library_id_taken` (checking a repository, adding a library) names the library that already
has the ID in `library_id`, so a client can link to it. The field is `null` on every other error.
