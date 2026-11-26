# Every ingestion run

!!! abstract "TL;DR"
    - Every result of every recorded ingestion run, newest first, one row per result.
    - Sort by any column, filter by its values or by date, and follow a metric over time in the
      chart; the address keeps the state, so a filtered view can be linked.
    - `just bench-pages` adds a re-recorded run's new rows, and the pull request test fails until it
      has.

Each row is one result as its run recorded it in
`packages/exactdocs/evals/results/ingestion.json`. The history of all of them is
[`results/history.json`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/evals/results/history.json),
back-filled from git for the runs recorded before it existed
([Refreshing these pages](../method/runs.md#refreshing-these-pages)).

- **Date** is the day the run says it ran; for a report that does not record one, the day the
  run was committed (for the back-filled runs) or added to the history.
- A result a later run kept unchanged (`--resume`, a result recorded by another run) is not
  repeated: its row keeps the date and commit of the run that first gave it.
- Numbers of different scoring rules sit side by side: the result pages say when a rule changed,
  and **Golden** names the golden set's fingerprint each row was scored on.

<!-- bench:history-ingestion -->
<div class="bench-history" markdown>

| Date | Chunking | Golden | Chunks | Coverage | Tokens p50 | Tokens p95 | Small chunks | Wrong heading paths | BM25 recall@5 | BM25 MRR |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-26 | `default` | `100484c7` | 11,748 | 91.6% | 114 | 738 | 23.1% | 8 | 91.4% | 0.796 |
| 2026-11-26 | `h6` | `100484c7` | 15,465 | 100.0% | 88 | 516 | 32.2% | 8 | 90.3% | 0.779 |
| 2026-11-26 | `h2` | `100484c7` | 6,229 | 53.0% | 179 | 1,699 | 14.3% | 5 | 92.9% | 0.803 |
| 2026-11-26 | `merge-400` | `100484c7` | 9,322 | 77.4% | 183 | 654 | 3.0% | 7 | 91.8% | 0.800 |
| 2026-11-24 | `default` | `7dd51c59` | 11,748 | 91.6% | 114 | 738 | 23.1% | 102 | 81.7% | 0.651 |
| 2026-11-24 | `h6` | `7dd51c59` | 15,465 | 100.0% | 88 | 516 | 32.2% | 103 | 79.8% | 0.626 |
| 2026-11-24 | `h2` | `7dd51c59` | 6,229 | 53.0% | 179 | 1,699 | 14.3% | 95 | 76.0% | 0.626 |
| 2026-11-24 | `merge-400` | `7dd51c59` | 9,322 | 77.4% | 183 | 654 | 3.0% | 88 | 74.2% | 0.602 |
| 2026-11-24 | `h2` | `7dd51c59` | 6,229 | 53.0% | 179 | 1,699 | 14.3% | 95 | 82.8% | 0.677 |
| 2026-11-24 | `merge-400` | `7dd51c59` | 9,322 | 77.4% | 183 | 654 | 3.0% | 88 | 81.7% | 0.662 |
| 2026-11-24 | `default` | `a0099785` | 11,748 | 91.6% | 114 | 738 | 23.1% | 102 | 87.6% | 0.711 |
| 2026-11-24 | `h6` | `a0099785` | 15,465 | 100.0% | 88 | 516 | 32.2% | 103 | 85.8% | 0.689 |
| 2026-11-24 | `h2` | `a0099785` | 6,229 | 53.0% | 179 | 1,699 | 14.3% | 95 | 89.1% | 0.737 |
| 2026-11-24 | `merge-400` | `a0099785` | 9,322 | 77.4% | 183 | 654 | 3.0% | 88 | 87.6% | 0.715 |
| 2026-11-23 | `default` | `39f6f9d5` | 11,748 | 91.3% | 114 | 738 | 23.1% | 102 | 81.7% | 0.651 |
| 2026-11-23 | `h6` | `39f6f9d5` | 15,465 | 100.0% | 88 | 516 | 32.2% | 103 | 79.8% | 0.626 |
| 2026-11-14 | `default` | `39f6f9d5` | 15,465 | 100.0% | 88 | 516 | 32.2% | 103 | 79.8% | 0.626 |
| 2026-11-14 | `h2` | `39f6f9d5` | 6,229 | 51.8% | 179 | 1,699 | 14.3% | 95 | 76.0% | 0.626 |
| 2026-11-14 | `h3-max-4000` | `39f6f9d5` | 11,748 | 91.3% | 114 | 738 | 23.1% | 102 | 81.7% | 0.651 |
| 2026-11-14 | `merge-400` | `39f6f9d5` | 9,322 | 77.1% | 183 | 654 | 3.0% | 88 | 74.2% | 0.602 |
| 2026-11-13 | `default` | `39f6f9d5` | 15,425 | 100.0% | 88 | 507 | 32.2% | 103 | 79.4% | 0.626 |
| 2026-11-13 | `h2` | `39f6f9d5` | 5,877 | 49.9% | 166 | 1,311 | 15.1% | 95 | 81.3% | 0.670 |
| 2026-11-13 | `h3-max-4000` | `39f6f9d5` | 11,708 | 91.3% | 114 | 727 | 23.1% | 102 | 81.3% | 0.651 |
| 2026-11-13 | `merge-400` | `39f6f9d5` | 9,283 | 77.1% | 183 | 651 | 3.0% | 88 | 74.2% | 0.604 |

</div>
<!-- /bench -->
