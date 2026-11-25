# Lists: pagination, sorting, filters

!!! abstract "TL;DR"
    - Every list takes `limit` (1 to 200, default 50) and an opaque `cursor`, and returns
      `next_cursor`.
    - Most lists also take `offset` (0 to 10000) to jump to a page; `offset` and `cursor` are
      exclusive.
    - `sort` is one whitelisted field (`-field` descends), filters run in the database, and every
      such page carries `total`.
    - A cursor only works with the `sort` and filters of the request that returned it.

## Parameters

| Parameter | Values | Lists |
|---|---|---|
| `limit` | 1 to 200, default 50 | every list |
| `cursor` | opaque, from `next_cursor` | every list |
| `offset` | 0 to 10000 | the lists below |
| `sort` | one whitelisted field, `-field` for descending | the lists below |
| filters | per list, named in the OpenAPI schema | the lists below |

The lists that take `offset`, `sort`, filters and carry `total`:

- libraries
- versions
- jobs (global and per library)
- articles
- users
- API tokens (the caller's and every account's)
- a library's grants
- both access logs (global and per library)

## Cursor pagination

List endpoints take `limit` and `cursor` and return `next_cursor` (`null` on the last page).

- Pass `next_cursor` back unchanged.
- A malformed cursor is a 422 `invalid_cursor`.
- Helper: `exactdocs_kernel.paginate`.

## Jumping to a page

`offset` skips that many matches and starts the page there.

| Page | `offset` |
|---|---|
| page *n* of size `limit` | `(n-1)*limit` |
| the last one (`total` > 0) | `⌊(total-1)/limit⌋*limit` |

??? example "233 jobs, 20 a page"
    The last page is `offset=220` and holds 13 jobs.

- The order, the filters and `total` are those of the cursor walk with the same `sort` and
  filters.
- The page's `next_cursor` goes on from its last item, so a client can jump and then walk on.
- An offset past the last match is an empty page with `next_cursor: null` and the same `total`.
- Helpers: `exactdocs_kernel.page_offset`, `MAX_OFFSET`.

| Request | Answer |
|---|---|
| `offset` and `cursor` both sent | 422 `cursor_with_offset` |
| `offset` below 0 or above 10000 | 422 `validation_error` naming `offset` |

!!! note "Why the bound"
    The bound keeps a deep page cheap: a database skips rows by reading them. Past it, walk on
    with `next_cursor` from the page at 10000, or reverse the `sort` to reach the end of a longer
    list.

## Sort, filter and total

`sort` takes one whitelisted field, `-field` for descending. Filters include:

- `q` (text, any case)
- `state`, `kind`, `role`, `disabled`, `provider`, `expired`, `unused`, `ai_enabled`,
  `has_versions`
- `origin` (jobs), `sync_state` (libraries)
- date ranges: `updated_after`, `created_before`, `at_after`, ...

Each parameter's description in the OpenAPI schema names its fields.

- They run in the database, and permissions apply before paging.
- A cursor only works with the `sort` and filters of the request that returned it.
- Every one of these pages carries `total`: the number of rows that match the filters across all
  pages.
- The users, tokens and grants lists are small enough to sort in memory once the caller's right
  to see them is checked. A caller who may not see a list gets no page and no count.

| Request | Answer |
|---|---|
| an unknown sort field | 422 `invalid_sort` naming it |
| an unknown filter, or a value a filter does not accept | 422 `validation_error` naming the parameter |

## In the web UI

The web UI keeps each list's view in its URL:

| Page | Kept in the URL |
|---|---|
| libraries | `q`, `sort`, `ai` |
| jobs (`/jobs`) | `q`, `state`, `kind`, `library`, `sort` |
| a library's settings (versions table) | `q`, `kind`, `sort` |
| a library's page (articles table) | `filter`, `sort`; its `tags` filter the file tree too |
| a library's sharing page (grants table) | `q`, `kind`, `role`, `sort` |
| users, token list | `q`, `sort` and filters |

The libraries, versions, jobs, articles and grants lists fetch the next page ahead, so "Load more"
shows it without waiting.
