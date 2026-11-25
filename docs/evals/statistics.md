# Recommendation and statistics

!!! abstract "TL;DR"
    - For each budget, cheapest first, a dearer configuration becomes the default only when its
      recall@5 beats the cheaper budget's default by 5 points **and** McNemar's test (mid-p) says
      the difference is significant at 5% (#489).
    - Every rate and mean has a 95% percentile-bootstrap interval: 10,000 resamples, seed 489,
      paired across configurations.
    - Each result is tested against its budget's default: McNemar's test for recall@k, a paired
      sign-flip permutation test for MRR and nDCG@10.

## The recommendation

For each budget, cheapest first, the candidates are the results that ran with:

- no wrong version;
- no read outside the version;
- no error;
- no reranker fallback.

The best of a budget is ranked by recall@5, then nDCG@10, MRR, lower USD and lower p95. It becomes
the budget's default only when both hold:

- its recall@5 beats the cheaper budget's default by 5 points (the suite's
  `DEFAULT_MARGIN_POINTS`);
- McNemar's test (mid-p) of its recall@5 against that default, on the answerable cases both
  answered, is significant at 5% (#489).

Otherwise the cheaper default stays, and the reason says which it missed: by how much the dearer
one fell short of the margin, or that the difference is not significant, with its p-value.

- A result without per-case outcomes (`rows`) cannot be tested and does not become a default.
- Each recommendation gives its USD per 1000 questions, its numbers and the test (`test`).
- A budget nothing of which ran is "not measured yet". For hosted models that means a
  real-providers run is needed.

## Intervals and paired tests

### Intervals

Every rate and mean of `metrics`, `by_kind` and `by_project` has a 95% interval in `intervals`:

- recall@k, MRR, nDCG@10, section recall;
- the wrong-version, clean, no-answer and empty rates;
- tokens and USD per question;
- not the latency percentiles.

The interval is a percentile bootstrap over the cases, 10,000 resamples drawn from
`random.Random(489)`. The draws depend only on the seed and the number of cases, and the rows are
taken in case order. So every configuration that answered the same cases is resampled with the
same draws (paired).

### Tests against the default

Each result is then tested against its budget's default (`versus_default`) on the answerable cases
both answered:

| Metric | Test |
|---|---|
| recall@1, @5, @10 | McNemar's test (mid-p) |
| MRR, nDCG@10 | a paired sign-flip permutation test (10,000 random sign patterns, same seed) |

Each comes with the difference and its paired bootstrap interval. The summary shows the intervals
in brackets and the tests under *Against the budget's default*.

The definitions, and why mid-p and a permutation test, are in
[Intervals and significance](../benchmark/method.md#intervals-and-significance). The code is
`retrieval_eval/stats.py`, tested on synthetic runs with known answers in
`tests/evals/test_stats.py`.
