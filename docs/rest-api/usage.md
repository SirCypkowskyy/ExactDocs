# Usage and leaderboard

!!! abstract "TL;DR"
    - Reads, searches and agent answers are counted per UTC day, account, API token, library and
      operation, and nothing else: no query, no path, no text.
    - `GET /stats/usage` is the instance's report for operators; `GET /account/usage` is the
      caller's own.
    - People are named only while the people leaderboard is on and only if they opted in.
    - `GET /stats/leaderboard` ranks libraries (always on) or people (off until the operator
      turns it on).

## Endpoints

| Method | Path | Purpose | Caller |
|---|---|---|---|
| `GET` | `/stats/usage` | the instance's usage | operator, session cookie |
| `GET` | `/account/usage` | the caller's own usage | session or API token |
| `GET` | `/stats/leaderboard` | rank libraries or people | any caller |
| `GET` | `/stats/settings` | leaderboard and retention settings | any caller |

## What is counted

Usage (#510) counts:

- every read: an article or a chunk, over REST, MCP or its resources
- every search: one library, several or all, `query-docs` and `/c7/docs` included
- every agent answer

Not counted:

- a request that fails
- the agent's own reads
- a stdio MCP process (read-only)

A search or an answer over more than one library counts to no library.

### Storage

- Counts are added up in memory and written every 10 s and when the server stops. A report writes
  the pending ones first.
- The days older than `EXACTDOCS_USAGE__RETENTION_MONTHS` (13 by default) are deleted every night.

## `GET /stats/usage`

The instance's usage for operators. Like `/users`, it needs the session cookie of an `admin`: an
API token is 401, anyone else 403.

| Parameter | Values | Default |
|---|---|---|
| `period` | `day`, `week` (ISO, Monday first), `month`, `year`; UTC | |
| `periods` | how many, 1 to 400 | 30 days, 12 weeks, 12 months or 2 years |
| `until` | a day of the last period | today |
| `by` | `none`, `library`, `account`, `token` | |
| `library` | one library | |
| `limit` | groups, 1 to 200 | 50 |

It answers `{"period", "since", "until", "by", "total", "series", "groups", "groups_total"}`:

- `series` has one bucket per period (`start`, `end`, `reads`, `searches`, `answers`), zeros
  included.
- `groups` is the breakdown over the whole range, most reads first.

!!! info "Privacy"
    People are named (`account_id`, `username`) only while the people leaderboard is on and only
    if they opted in. Everyone else, and requests without an account, are summed into one last
    group with `others: true`, so an operator sees them in aggregate only.

## `GET /account/usage`

The same report over the caller's own counts.

- `by`: `none`, `library`, `token`. `token_id: null` is their browser sessions and OAuth sign-ins.
- A session or an API token may ask, and nobody can ask for someone else's.

## `GET /stats/leaderboard`

```text
GET /stats/leaderboard?subject=libraries|people&metric=reads|searches|answers&period=day|week|month|year&at=&limit=
```

Ranks over the period holding `at`. The default is today, so the current period so far.

It answers:

```text
{"subject", "metric", "period", "start", "end", "previous_start", "previous_end",
 "total", "ranked", "entries", "you"}
```

Each entry has:

| Field | Meaning |
|---|---|
| `rank` | equal values share one: 1, 2, 2, 4 |
| `previous_rank` | among the same subjects in the period before;<br/>`null` when it had nothing counted |
| `value` | the metric |

| `subject` | Ranks |
|---|---|
| `libraries` (default) | always on; lists only libraries the caller may read |
| `people` | 403 `people_leaderboard_off` until the operator sets `EXACTDOCS_USAGE__PEOPLE_LEADERBOARD`;<br/>then only enabled accounts that opted in (`leaderboard_opt_in`) |

The caller's entry has `you: true`, and comes in `you` when ranked beyond `limit`.

## `GET /stats/settings`

Tells any caller `{"people_leaderboard", "retention_months"}`.
