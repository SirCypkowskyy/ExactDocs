# Every agent run

!!! abstract "TL;DR"
    - Every result of every recorded agent benchmark run, newest first, one row per result.
    - Sort by any column, filter by its values or by date, and follow a metric over time in the
      chart; the address keeps the state, so a filtered view can be linked.
    - `just bench-pages` adds a re-recorded run's new rows, and the pull request test fails until it
      has.

Each row is one result as its run recorded it in
`packages/exactdocs/evals/results/agent.json`. The history of all of them is
[`results/history.json`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/evals/results/history.json),
back-filled from git for the runs recorded before it existed
([Refreshing these pages](../method/runs.md#refreshing-these-pages)).

- **Date** is the day the run says it ran; for a report that does not record one, the day the
  run was committed (for the back-filled runs) or added to the history.
- A result a later run kept unchanged (`--resume`, a result recorded by another run) is not
  repeated: its row keeps the date and commit of the run that first gave it.
- Numbers of different scoring rules sit side by side: the result pages say when a rule changed,
  and **Golden** names the golden set's fingerprint each row was scored on.

<!-- bench:history-agent -->
<div class="bench-history" markdown>

| Date | Agent model | Arm | Retrieval | Judge | Commit | Questions | Accuracy | Wrong version | Read the answer | Tool calls / question | Tokens / question |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-25 | `ollama:gpt-oss:120b` | `grounded-docs` | `full-text` | `ollama:glm-5.3` | [`c6188f4`](https://github.com/SirCypkowskyy/ExactDocs/commit/c6188f4fcccef931fea2958d141e50aee8efe4af) | 60 | 45.0% | 3.3% | 8.0% | 3.6 | 42,196.8 |
| 2026-11-25 | `ollama:kimi-k3` | `grounded-docs` | `full-text` | `ollama:glm-5.3` | [`c6188f4`](https://github.com/SirCypkowskyy/ExactDocs/commit/c6188f4fcccef931fea2958d141e50aee8efe4af) | 60 | 81.7% | 0.0% | 10.0% | 3.5 | 17,072.3 |
| 2026-11-25 | `ollama:gpt-oss:120b` | `exactdocs` | `bm25` | `ollama:glm-5.3` | [`970c770`](https://github.com/SirCypkowskyy/ExactDocs/commit/970c770581458ebb4acdd70216fa5d294b1e8464) | 60 | 41.7% | 1.7% | 36.0% | 4.7 | 43,862.5 |
| 2026-11-25 | `ollama:gpt-oss:120b` | `exactdocs` | `bm25` | `ollama:glm-5.3` | [`345de89`](https://github.com/SirCypkowskyy/ExactDocs/commit/345de89ced05732d8eeca9725498a8952790344b) | 60 | 40.0% | 3.3% | 28.0% | 4.0 | 51,205.3 |
| 2026-11-25 | `ollama:kimi-k3` | `exactdocs` | `bm25` | `ollama:glm-5.3` | [`345de89`](https://github.com/SirCypkowskyy/ExactDocs/commit/345de89ced05732d8eeca9725498a8952790344b) | 60 | 83.3% | 0.0% | 58.0% | 4.5 | 34,292.6 |
| 2026-11-24 | `ollama:gpt-oss:120b` | `none` |  | `ollama:glm-5.3` | [`5394cd5`](https://github.com/SirCypkowskyy/ExactDocs/commit/5394cd5aa246c0ec2cb0f44bca643c7820a5c521) | 60 | 13.3% | 25.0% | 0.0% | 0.0 | 922.5 |
| 2026-11-24 | `ollama:gpt-oss:120b` | `exactdocs` | `bm25` | `ollama:glm-5.3` | [`5394cd5`](https://github.com/SirCypkowskyy/ExactDocs/commit/5394cd5aa246c0ec2cb0f44bca643c7820a5c521) | 60 | 43.3% | 0.0% | 32.0% | 5.5 | 51,333.6 |
| 2026-11-24 | `ollama:kimi-k3` | `none` |  | `ollama:glm-5.3` | [`5394cd5`](https://github.com/SirCypkowskyy/ExactDocs/commit/5394cd5aa246c0ec2cb0f44bca643c7820a5c521) | 60 | 33.3% | 8.3% | 0.0% | 0.0 | 2,168.0 |
| 2026-11-24 | `ollama:kimi-k3` | `exactdocs` | `bm25` | `ollama:glm-5.3` | [`5394cd5`](https://github.com/SirCypkowskyy/ExactDocs/commit/5394cd5aa246c0ec2cb0f44bca643c7820a5c521) | 60 | 85.0% | 0.0% | 52.0% | 5.5 | 39,072.2 |

</div>
<!-- /bench -->
