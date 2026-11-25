# Usage counts

!!! abstract "TL;DR"

    - `usage` (#510) keeps one number per UTC day, account, API token, library and operation
      (`read`, `search`, `answer`). Never a query, a path or any text.
    - No domain knows it is counted: bootstrap wraps the driving ports and counts after the request
      is served.
    - Counts are written in the background every 10 s, never on the request's path.
    - The people leaderboard is opt-in, per person and per instance.

`usage` (#510) counts how ExactDocs is used: one number per UTC day, account, API token, library and
operation (`read`, `search`, `answer`) in `usage_daily_counts`, never a query, a path or any text.
Accounts, tokens and libraries are held by value (empty for none: no person, a browser session, an
operation over several libraries), so the table depends on no other domain's.

## Who counts

- No domain knows it is counted. `bootstrap/usage_meter.py` wraps the driving ports the REST and MCP
  adapters serve reads, searches and answers with: catalog's `GetArticle`, retrieval's `ReadChunk`,
  `SearchDocs`, `SearchAllLibraries`, `QueryDocs` and `AnswerQuestion`.
- The request is served, then counted with the account and token of the request (`bootstrap.caller`).
- Not counted:
    - a request that fails;
    - calls made inside the server (the answering agent's own reads, jobs), which use the plain
      ports;
    - anything in a stdio MCP process (read-only).

## Never on the request's path

- `RecordUsage` adds to an in-memory `UsageTally`, at most 100,000 counters. Past that, new ones are
  dropped and logged.
- `bootstrap.usage_meter.flushing` writes it every `USAGE_FLUSH_SECONDS` (10 s) and once more when
  the server stops.
- Each write is one `INSERT ... ON CONFLICT DO UPDATE` transaction, in key order, so processes
  sharing a PostgreSQL database never deadlock.
- A failed write keeps its counts for the next one.
- A report writes the pending counts first, so it includes the requests just served.

## Retention

The nightly upkeep runs `PruneUsage`, deleting the days before `EXACTDOCS_USAGE__RETENTION_MONTHS`
(13 by default).

## Reports and leaderboards

- Counts are summed in SQL by day and operation, then bucketed into days, ISO weeks, months or years
  in UTC.
- A leaderboard ranks either:
    - libraries: always, and only those the caller may read (the `LibraryAccess` port, bridged to
      identity's library roles by `IdentityAccessPolicy.readable`);
    - or people: only while `EXACTDOCS_USAGE__PEOPLE_LEADERBOARD` is on.
- Each subject also gets its rank in the previous period among the same subjects.

## People are opt-in

- The `People` port (`bootstrap/bridges.py:IdentityLeaderboardPeople`, over identity's
  `FindLeaderboardPeople`) answers which accounts exist, are enabled and set the
  `leaderboard_opt_in` interface preference.
- Whether the board is on is usage's own setting (`UsagePolicy`); identity only knows who agreed.
- Anyone not shown by name is summed into one `others` group of the operators' report.
