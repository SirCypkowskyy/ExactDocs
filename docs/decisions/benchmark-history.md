# Benchmark history

!!! abstract "TL;DR"
    - Every recorded benchmark run is kept in one committed file,
      `packages/exactdocs/evals/results/history.json`, which `just bench-pages` writes and a pytest
      check keeps in step with the recorded runs.
    - Rows are deduplicated by content, so an identical re-run adds no point.
    - Each benchmark's *Every run* page is a Markdown table that a small script turns into a
      sortable, filterable table with a chart. Without JavaScript it stays a plain table.

| | |
|---|---|
| **Status** | Accepted, 2026-11-26 |
| **Scope** | `retrieval_eval/bench_history.py`, `results/history.json`, `docs/javascripts/bench-history.js` and the four `docs/benchmark/*/history.md` pages |
| **Issue** | #616 |
| **Decided by** | Proposed in #617 |

## Context

The benchmark pages showed only the latest recorded run of each benchmark. Earlier runs survived
only in git history, in report formats that changed over time.

## Decision

**A committed history file.** `retrieval_eval/bench_history.py`, run by `just bench-pages`,
writes every run to `packages/exactdocs/evals/results/history.json`. The existing check
`test_the_committed_pages_match_the_recorded_runs` fails when the file and the pages fall behind
the recorded runs. The file was backfilled once from the 23 commits since 13 November.

**Deduplicated rows.** Two rows with the same content are one row, whatever their date and
commit. A row keeps the date and commit of the run that first produced it, so re-running an
unchanged benchmark adds no new point to the history.

**An enhanced Markdown table.** The page script reads the table already on the page instead of
loading the JSON separately. There is one data source, the page works without JavaScript, and
ExactDocs' own importer reads the same table when it indexes these docs.

**No chart library.** Plain JavaScript draws an inline SVG. The theme loads no script besides
Mermaid, and a library would be a new pinned dependency for about 200 lines of code.

**One page per benchmark.** Ingestion, retrieval, agent and comparison each get their own
*Every run* page, since they measure different things.

## Considered options

- **Rebuild the history from `git log` at build time.** Rejected: the docs CI checks out a
  single commit, and every build would have to parse every old report format.

## Consequences

A PR that re-records a run must also run `just bench-pages`, or the pytest check fails.
