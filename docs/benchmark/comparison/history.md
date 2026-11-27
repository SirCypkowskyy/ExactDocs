# Every comparison run

!!! abstract "TL;DR"
    - Every result of every recorded comparison run, newest first, one row per result.
    - Sort by any column, filter by its values or by date, and follow a metric over time in the
      chart; the address keeps the state, so a filtered view can be linked.
    - `just bench-pages` adds a re-recorded run's new rows, and the pull request test fails until it
      has.

Each row is one result as its run recorded it in
`packages/exactdocs/evals/results/grounded-docs.json`. The history of all of them is
[`results/history.json`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/evals/results/history.json),
back-filled from git for the runs recorded before it existed
([Refreshing these pages](../method/runs.md#refreshing-these-pages)).

- **Date** is the day the run says it ran; for a report that does not record one, the day the
  run was committed (for the back-filled runs) or added to the history.
- A result a later run kept unchanged (`--resume`, a result recorded by another run) is not
  repeated: its row keeps the date and commit of the run that first gave it.
- Numbers of different scoring rules sit side by side: the result pages say when a rule changed,
  and **Golden** names the golden set's fingerprint each row was scored on.

<!-- bench:history-comparison -->
<div class="bench-history" markdown>

| Date | Tool | Configuration | Golden | Commit | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | Context tokens | Facts found |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-27 | Grounded Docs 3.4.1 | `full-text` | `100484c7` | [`aea221a`](https://github.com/SirCypkowskyy/ExactDocs/commit/aea221ac47d2c7bd29862eebce61925d37e4ad2f) | 59.2% | 83.5% | 85.4% | 0.693 | 0.660 | 7,964.3 | 92.3% |
| 2026-11-27 | Grounded Docs 3.4.1 | `bge-small-en-v1.5` | `100484c7` | [`aea221a`](https://github.com/SirCypkowskyy/ExactDocs/commit/aea221ac47d2c7bd29862eebce61925d37e4ad2f) | 71.9% | 87.3% | 90.6% | 0.795 | 0.742 | 7,351.7 | 93.3% |
| 2026-11-27 | ExactDocs | `ExactDocs bm25 @ default` | `100484c7` | [`aea221a`](https://github.com/SirCypkowskyy/ExactDocs/commit/aea221ac47d2c7bd29862eebce61925d37e4ad2f) | 70.8% | 91.4% | 93.6% | 0.796 | 0.757 | 3,464.6 | 87.0% |
| 2026-11-25 | Grounded Docs 3.4.1 | `full-text` | `a0099785` | [`bdefaa9`](https://github.com/SirCypkowskyy/ExactDocs/commit/bdefaa90e0630622c5d4c87d1bb7cb6ab764ad87) | 58.4% | 83.2% | 85.0% | 0.685 | 0.655 | 7,935.2 | 92.3% |
| 2026-11-25 | Grounded Docs 3.4.1 | `bge-small-en-v1.5` | `a0099785` | [`bdefaa9`](https://github.com/SirCypkowskyy/ExactDocs/commit/bdefaa90e0630622c5d4c87d1bb7cb6ab764ad87) | 71.2% | 85.4% | 88.8% | 0.781 | 0.727 | 7,359.9 | 93.5% |
| 2026-11-25 | ExactDocs | `ExactDocs bm25 @ default` | `a0099785` | [`bdefaa9`](https://github.com/SirCypkowskyy/ExactDocs/commit/bdefaa90e0630622c5d4c87d1bb7cb6ab764ad87) | 70.4% | 91.0% | 93.3% | 0.792 | 0.754 | 3,464.6 | 87.0% |
| 2026-11-24 | Grounded Docs 3.4.1 | `full-text` | `a0099785` | [`d2de6fd`](https://github.com/SirCypkowskyy/ExactDocs/commit/d2de6fdf9335f83261a061c7fd9876705d87b998) | 58.8% | 83.5% | 85.4% | 0.689 | 0.659 | 7,935.2 | 92.3% |
| 2026-11-24 | Grounded Docs 3.4.1 | `bge-small-en-v1.5` | `a0099785` | [`d2de6fd`](https://github.com/SirCypkowskyy/ExactDocs/commit/d2de6fdf9335f83261a061c7fd9876705d87b998) | 71.5% | 85.8% | 89.1% | 0.785 | 0.731 | 7,359.9 | 93.5% |
| 2026-11-24 | ExactDocs | `ExactDocs bm25 @ default` | `a0099785` | [`d2de6fd`](https://github.com/SirCypkowskyy/ExactDocs/commit/d2de6fdf9335f83261a061c7fd9876705d87b998) | 58.8% | 87.6% | 93.6% | 0.711 | 0.714 | 3,464.2 | 87.0% |

</div>
<!-- /bench -->
