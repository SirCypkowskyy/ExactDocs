# Every retrieval run

!!! abstract "TL;DR"
    - Every result of every recorded retrieval benchmark and grid run, newest first, one row per result.
    - Sort by any column, filter by its values or by date, and follow a metric over time in the
      chart; the address keeps the state, so a filtered view can be linked.
    - `just bench-pages` adds a re-recorded run's new rows, and the pull request test fails until it
      has.

Each row is one result as its run recorded it in
`packages/exactdocs/evals/results/retrieval.json`, `retrieval-grid-rank1.json` and `retrieval-grid-grouped.json`. The history of all of them is
[`results/history.json`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/evals/results/history.json),
back-filled from git for the runs recorded before it existed
([Refreshing these pages](../method/runs.md#refreshing-these-pages)).

- **Date** is the day the run says it ran; for a report that does not record one, the day the
  run was committed (for the back-filled runs) or added to the history.
- A result a later run kept unchanged (`--resume`, a result recorded by another run) is not
  repeated: its row keeps the date and commit of the run that first gave it.
- Numbers of different scoring rules sit side by side: the result pages say when a rule changed,
  and **Golden** names the golden set's fingerprint each row was scored on.

<!-- bench:history-retrieval -->
<div class="bench-history" markdown>

| Date | Report | Configuration | Chunking | Budget | Mode | Golden | Commit | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | Wrong version | Context tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-25 | retrieval | `bm25` | `default` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 58.8% | 87.6% | 93.6% | 0.711 | 0.714 | 0.0% | 3,464.2 |
| 2026-11-25 | retrieval | `bm25` | `h6` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 56.9% | 85.8% | 92.1% | 0.689 | 0.692 | 0.0% | 2,875.7 |
| 2026-11-25 | retrieval | `bm25` | `h2` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 61.8% | 89.1% | 94.0% | 0.737 | 0.724 | 0.0% | 7,065.0 |
| 2026-11-25 | retrieval | `bm25` | `merge-400` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 59.6% | 87.6% | 93.3% | 0.715 | 0.720 | 0.0% | 3,534.0 |
| 2026-11-25 | retrieval-grid-rank1 | `bm25` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 58.8% | 87.6% | 93.6% | 0.711 | 0.714 | 0.0% | 3,464.2 |
| 2026-11-25 | retrieval-grid-rank1 | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 64.4% | 90.3% | 93.6% | 0.756 | 0.749 | 0.0% | 3,202.4 |
| 2026-11-25 | retrieval-grid-rank1 | `default/bm25` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 58.8% | 87.6% | 93.3% | 0.710 | 0.714 | 0.0% | 3,436.6 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 65.9% | 90.6% | 94.0% | 0.765 | 0.755 | 0.0% | 3,121.0 |
| 2026-11-25 | retrieval-grid-rank1 | `default/bm25+context-indexed` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 59.6% | 87.6% | 94.4% | 0.714 | 0.717 | 0.0% | 3,484.1 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+context-indexed` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 65.9% | 91.0% | 94.4% | 0.769 | 0.760 | 0.0% | 3,122.9 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+context-embedded` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 63.3% | 91.0% | 94.0% | 0.751 | 0.747 | 0.0% | 3,217.9 |
| 2026-11-25 | retrieval-grid-rank1 | `h6/bm25+parent` | `h6` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 62.2% | 88.8% | 94.8% | 0.732 | 0.734 | 0.0% | 12,448.3 |
| 2026-11-25 | retrieval-grid-rank1 | `default/bm25+parent` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 63.3% | 91.0% | 95.5% | 0.749 | 0.748 | 0.0% | 14,232.2 |
| 2026-11-25 | retrieval-grid-rank1 | `default/bm25+article` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 72.3% | 92.9% | 95.9% | 0.812 | 0.779 | 0.0% | 6,881.0 |
| 2026-11-25 | retrieval-grid-rank1 | `default/bm25+article-hits` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 70.8% | 91.0% | 93.3% | 0.794 | 0.758 | 0.0% | 3,439.5 |
| 2026-11-25 | retrieval-grid-rank1 | `default/bm25+context-indexed+article` | `default` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 73.4% | 93.3% | 95.9% | 0.817 | 0.780 | 0.0% | 6,936.7 |
| 2026-11-25 | retrieval-grid-rank1 | `h6/bm25+article` | `h6` | none | bm25 | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 70.4% | 91.8% | 94.8% | 0.795 | 0.760 | 0.0% | 5,776.9 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+context` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 64.8% | 91.4% | 94.8% | 0.763 | 0.757 | 0.0% | 3,235.0 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+parent` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 71.2% | 92.9% | 95.9% | 0.806 | 0.786 | 0.0% | 12,832.4 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+article` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 79.0% | 94.4% | 95.5% | 0.859 | 0.812 | 0.0% | 6,239.2 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+article-hits` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 78.3% | 93.3% | 94.0% | 0.849 | 0.798 | 0.0% | 3,118.9 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+context-embedded+article` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 76.4% | 95.5% | 95.5% | 0.845 | 0.804 | 0.0% | 6,115.3 |
| 2026-11-25 | retrieval-grid-rank1 | `default/hybrid:bge-small+context-embedded+article-hits` | `default` | local | hybrid | `a0099785` | [`01ee7c6`](https://github.com/SirCypkowskyy/ExactDocs/commit/01ee7c6aaccd3ad861e5c8ce63a20ce6c0c3bd11) | 75.7% | 94.0% | 94.0% | 0.836 | 0.790 | 0.0% | 3,213.1 |
| 2026-11-25 | retrieval | `bm25` | `default` | none | bm25 | `a0099785` | [`ce81d93`](https://github.com/SirCypkowskyy/ExactDocs/commit/ce81d93fcd4c433b348c26923c33bba33906d40d) | 70.4% | 91.0% | 93.3% | 0.792 | 0.754 | 0.0% | 3,464.2 |
| 2026-11-25 | retrieval | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `a0099785` | [`ce81d93`](https://github.com/SirCypkowskyy/ExactDocs/commit/ce81d93fcd4c433b348c26923c33bba33906d40d) | 76.0% | 92.5% | 93.3% | 0.832 | 0.787 | 0.0% | 3,206.5 |
| 2026-11-25 | retrieval | `bm25` | `h6` | none | bm25 | `a0099785` | [`ce81d93`](https://github.com/SirCypkowskyy/ExactDocs/commit/ce81d93fcd4c433b348c26923c33bba33906d40d) | 68.5% | 89.9% | 91.8% | 0.776 | 0.734 | 0.0% | 2,874.4 |
| 2026-11-25 | retrieval | `bm25` | `h2` | none | bm25 | `a0099785` | [`ce81d93`](https://github.com/SirCypkowskyy/ExactDocs/commit/ce81d93fcd4c433b348c26923c33bba33906d40d) | 71.5% | 92.5% | 93.6% | 0.799 | 0.760 | 0.0% | 7,065.0 |
| 2026-11-25 | retrieval | `bm25` | `merge-400` | none | bm25 | `a0099785` | [`ce81d93`](https://github.com/SirCypkowskyy/ExactDocs/commit/ce81d93fcd4c433b348c26923c33bba33906d40d) | 70.8% | 91.4% | 92.9% | 0.796 | 0.757 | 0.0% | 3,534.9 |
| 2026-11-25 | retrieval-grid-grouped | `bm25` | `default` | none | bm25 | `a0099785` | [`8eaf089`](https://github.com/SirCypkowskyy/ExactDocs/commit/8eaf089bcdba766ab65d9339b5c9f3716247d9c9) | 70.4% | 91.0% | 93.3% | 0.792 | 0.754 | 0.0% | 3,464.2 |
| 2026-11-25 | retrieval-grid-grouped | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `a0099785` | [`8eaf089`](https://github.com/SirCypkowskyy/ExactDocs/commit/8eaf089bcdba766ab65d9339b5c9f3716247d9c9) | 76.0% | 92.5% | 93.3% | 0.832 | 0.787 | 0.0% | 3,206.5 |
| 2026-11-25 | retrieval-grid-grouped | `bm25@default+by-chunk` | `default` | none | bm25 | `a0099785` | [`8eaf089`](https://github.com/SirCypkowskyy/ExactDocs/commit/8eaf089bcdba766ab65d9339b5c9f3716247d9c9) | 58.4% | 87.3% | 93.3% | 0.707 | 0.711 | 0.0% | 3,464.2 |
| 2026-11-25 | retrieval-grid-grouped | `hybrid:bge-small-en-v1.5@default+by-chunk` | `default` | local | hybrid | `a0099785` | [`8eaf089`](https://github.com/SirCypkowskyy/ExactDocs/commit/8eaf089bcdba766ab65d9339b5c9f3716247d9c9) | 64.0% | 89.5% | 93.3% | 0.752 | 0.746 | 0.0% | 3,206.5 |
| 2026-11-24 | retrieval | `bm25` | `default` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 52.1% | 81.7% | 89.1% | 0.651 | 0.705 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25+ce` | `default` | local | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 55.8% | 84.6% | 90.6% | 0.680 | 0.723 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 56.5% | 84.3% | 89.9% | 0.688 | 0.741 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5+ce` | `default` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 55.4% | 83.2% | 88.8% | 0.675 | 0.715 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `h6` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 49.8% | 79.8% | 86.9% | 0.626 | 0.683 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25+ce` | `h6` | local | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 57.7% | 84.6% | 90.3% | 0.692 | 0.730 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `h6` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 54.7% | 84.6% | 91.4% | 0.676 | 0.738 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5+ce` | `h6` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 57.3% | 83.5% | 90.3% | 0.689 | 0.728 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:snowflake-arctic-embed-s` | `h6` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 40.1% | 75.3% | 84.6% | 0.547 | 0.607 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `h2` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 51.7% | 76.0% | 81.7% | 0.626 | 0.663 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25+ce` | `h2` | local | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 48.3% | 72.7% | 79.8% | 0.590 | 0.646 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `h2` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 52.1% | 73.4% | 80.5% | 0.614 | 0.673 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `merge-400` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 49.1% | 74.2% | 80.5% | 0.602 | 0.644 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `merge-400` | local | hybrid | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 52.1% | 78.3% | 83.5% | 0.638 | 0.683 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `default` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 52.1% | 81.7% | 89.1% | 0.651 | 0.706 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `h2` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 55.4% | 82.8% | 90.3% | 0.677 | 0.714 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `merge-400` | none | bm25 | `7dd51c59` | [`861b5ea`](https://github.com/SirCypkowskyy/ExactDocs/commit/861b5ea2b502338380ef73b801397d58a6e4030f) | 53.9% | 81.7% | 88.8% | 0.662 | 0.713 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `default` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 58.8% | 87.6% | 93.6% | 0.711 | 0.714 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25+ce` | `default` | local | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 62.2% | 89.5% | 94.8% | 0.737 | 0.732 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 64.4% | 90.3% | 93.6% | 0.756 | 0.749 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5+ce` | `default` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 61.8% | 88.4% | 93.3% | 0.732 | 0.725 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `h6` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 56.9% | 85.8% | 92.1% | 0.689 | 0.692 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25+ce` | `h6` | local | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 64.0% | 89.1% | 94.4% | 0.749 | 0.740 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `h6` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 63.3% | 90.6% | 95.1% | 0.750 | 0.747 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5+ce` | `h6` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 63.7% | 88.4% | 94.8% | 0.746 | 0.739 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:snowflake-arctic-embed-s` | `h6` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 44.6% | 79.8% | 88.4% | 0.595 | 0.617 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `h2` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 61.8% | 89.1% | 94.0% | 0.737 | 0.724 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25+ce` | `h2` | local | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 56.9% | 85.4% | 90.6% | 0.685 | 0.679 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `h2` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 64.4% | 86.1% | 91.4% | 0.741 | 0.715 | 0.0% |  |
| 2026-11-24 | retrieval | `bm25` | `merge-400` | none | bm25 | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 59.6% | 87.6% | 93.3% | 0.715 | 0.720 | 0.0% |  |
| 2026-11-24 | retrieval | `hybrid:bge-small-en-v1.5` | `merge-400` | local | hybrid | `a0099785` | [`8e789e6`](https://github.com/SirCypkowskyy/ExactDocs/commit/8e789e67177adf9514418b566473dca937ca638d) | 64.8% | 91.0% | 94.8% | 0.764 | 0.758 | 0.0% |  |
| 2026-11-23 | retrieval | `bm25` | `default` | none | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 52.1% | 81.7% | 89.1% | 0.651 | 0.705 | 0.0% |  |
| 2026-11-23 | retrieval | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 56.5% | 84.3% | 90.3% | 0.687 | 0.742 | 0.0% |  |
| 2026-11-23 | retrieval | `bm25` | `h6` | none | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 49.8% | 79.8% | 86.9% | 0.626 | 0.684 | 0.0% |  |
| 2026-11-23 | retrieval | `bm25+ce` | `h6` | local | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 57.7% | 84.6% | 90.3% | 0.692 | 0.732 | 0.0% |  |
| 2026-11-23 | retrieval | `hybrid:bge-small-en-v1.5` | `h6` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 54.7% | 84.6% | 91.4% | 0.675 | 0.738 | 0.0% |  |
| 2026-11-23 | retrieval | `hybrid:bge-small-en-v1.5+ce` | `h6` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 57.3% | 83.5% | 90.3% | 0.689 | 0.730 | 0.0% |  |
| 2026-11-23 | retrieval | `hybrid:snowflake-arctic-embed-s` | `h6` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 40.1% | 75.3% | 84.6% | 0.547 | 0.611 | 0.0% |  |
| 2026-11-13 | retrieval | `bm25` | `default` | none | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 49.8% | 79.8% | 86.9% | 0.626 | 0.684 | 0.0% |  |
| 2026-11-13 | retrieval | `bm25+ce` | `default` | local | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 57.7% | 84.6% | 90.3% | 0.692 | 0.732 | 0.0% |  |
| 2026-11-13 | retrieval | `hybrid:bge-small-en-v1.5` | `default` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 54.7% | 84.6% | 91.4% | 0.675 | 0.738 | 0.0% |  |
| 2026-11-13 | retrieval | `hybrid:bge-small-en-v1.5+ce` | `default` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 57.3% | 83.5% | 90.3% | 0.689 | 0.730 | 0.0% |  |
| 2026-11-13 | retrieval | `hybrid:snowflake-arctic-embed-s` | `default` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 40.1% | 75.3% | 84.6% | 0.547 | 0.611 | 0.0% |  |
| 2026-11-13 | retrieval | `bm25` | `h2` | none | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 51.7% | 76.0% | 81.7% | 0.626 | 0.665 | 0.0% |  |
| 2026-11-13 | retrieval | `bm25+ce` | `h2` | local | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 48.3% | 72.7% | 79.8% | 0.590 | 0.645 | 0.0% |  |
| 2026-11-13 | retrieval | `hybrid:bge-small-en-v1.5` | `h2` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 51.7% | 73.4% | 80.5% | 0.612 | 0.670 | 0.0% |  |
| 2026-11-13 | retrieval | `bm25` | `h3-max-4000` | none | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 52.1% | 81.7% | 89.1% | 0.651 | 0.705 | 0.0% |  |
| 2026-11-13 | retrieval | `hybrid:bge-small-en-v1.5` | `h3-max-4000` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 56.5% | 84.3% | 90.3% | 0.687 | 0.742 | 0.0% |  |
| 2026-11-13 | retrieval | `bm25` | `merge-400` | none | bm25 | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 49.1% | 74.2% | 80.5% | 0.602 | 0.645 | 0.0% |  |
| 2026-11-13 | retrieval | `hybrid:bge-small-en-v1.5` | `merge-400` | local | hybrid | `39f6f9d5` | [`fe156aa`](https://github.com/SirCypkowskyy/ExactDocs/commit/fe156aa8aed0ebd86bcb45e930be9769e4056535) | 52.1% | 78.3% | 83.5% | 0.638 | 0.687 | 0.0% |  |

</div>
<!-- /bench -->
