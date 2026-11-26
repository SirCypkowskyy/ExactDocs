# Agent results: every table

The tables of the recorded run (`packages/exactdocs/evals/results/agent.json`); read
[Read this first](index.md#read-this-first) before comparing them.

<!-- bench:agent -->
## Quality

| Agent model | Arm | Accuracy | Correct | Partial | Wrong | Refused | No answer | Errors | Wrong for the version | Refused, answerable | Correct refusals, unanswerable | Read the answer | Read another version | Tool calls/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 13.3 % [5.0, 21.7] | 6 | 18 | 34 | 2 | 0 | 0 | 15 (25.0 % [15.0, 36.7]) | 0 (0.0 % [0.0, 0.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 40.0 % [28.3, 51.7] | 19 | 29 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 28.0 % [16.0, 40.0] | 0 | 4.0 [3.45, 4.683] |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 45.0 % [31.7, 56.7] | 22 | 26 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 8.0 % [2.0, 16.0] | 0 | 3.6 [2.817, 4.533] |
| `ollama:kimi-k3` | none | 33.3 % [21.7, 45.0] | 18 | 20 | 17 | 5 | 0 | 0 | 5 (8.3 % [1.7, 16.7]) | 3 (6.0 % [0.0, 14.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:kimi-k3` | exactdocs (bm25) | 83.3 % [73.3, 91.7] | 41 | 8 | 2 | 9 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 9 (90.0 % [70.0, 100.0]) | 58.0 % [44.0, 72.0] | 0 | 4.483 [4.033, 4.983] |
| `ollama:kimi-k3` | grounded-docs (full-text) | 81.7 % [71.7, 91.7] | 42 | 8 | 3 | 7 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 7 (70.0 % [40.0, 100.0]) | 10.0 % [2.0, 18.0] | 0 | 3.45 [2.917, 4.05] |

## Tool errors

Tool calls the server refused or could not answer (an argument it does not take, a path the version lacks...), over the answered questions. Each costs the agent a turn, and the harness ends a run whose tool fails twice.

| Agent model | Arm | Runs with a tool error | Tool errors | By tool |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 1 of 60 | 2 | `search_docs` 2 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 4 of 60 | 4 | `read_page` 1, `search_docs` 3 |
| `ollama:kimi-k3` | exactdocs (bm25) | 1 of 60 | 1 | `read_article` 1 |
| `ollama:kimi-k3` | grounded-docs (full-text) | 14 of 60 | 23 | `find_version` 9, `read_page` 4, `search_docs` 10 |

## Cost per question

Each: mean [95% interval of the mean]; median; 95th percentile, over the questions without a provider failure. Wall time leaves out the time lost to provider retries.

| Agent model | Arm | Wall time (s) | Input tokens | Output tokens, thinking included | Thinking tokens | USD | Retried requests |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 2.9 [2.6, 3.2]; p50 2.7; p95 5.1 | 177 [176, 179]; p50 178; p95 184 | 745 [651, 842]; p50 696; p95 1,362 | 356 [307, 411]; p50 330; p95 646 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 5.0 [4.4, 5.8]; p50 4.2; p95 9.7 | 50,381 [34,420, 72,490]; p50 28,027; p95 143,133 | 824 [726, 945]; p50 724; p95 1,758 | 467 [404, 548]; p50 384; p95 834 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 4.2 [3.6, 5.0]; p50 3.4; p95 8.7 | 41,413 [24,766, 64,716]; p50 13,677; p95 177,336 | 784 [680, 901]; p50 703; p95 1,415 | 358 [301, 429]; p50 318; p95 725 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | none | 19.1 [13.8, 25.9]; p50 9.8; p95 56.1 | 255 [254, 257]; p50 256; p95 263 | 1,913 [1,381, 2,584]; p50 966; p95 5,723 | 1,655 [1,132, 2,315]; p50 714; p95 5,443 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | exactdocs (bm25) | 13.3 [11.6, 15.2]; p50 10.2; p95 30.1 | 33,107 [28,356, 38,938]; p50 24,519; p95 62,474 | 1,186 [1,049, 1,346]; p50 965; p95 2,329 | 671 [566, 795]; p50 509; p95 1,646 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | grounded-docs (full-text) | 8.4 [7.2, 9.9]; p50 6.5; p95 19.2 | 16,065 [12,153, 20,731]; p50 8,685; p95 57,412 | 1,008 [866, 1,170]; p50 790; p95 2,596 | 560 [449, 688]; p50 383; p95 1,901 (estimated) | unpriced | 0 |

## Against the other arms, on the same cases

Each arm against `none` (and `exactdocs`), for the same agent model and the cases both answered without a provider failure: the difference (this arm minus the other), its paired bootstrap interval and the p-value; accuracy by McNemar's test (mid-p), time and tokens by a paired sign-flip permutation test. The ratio is this arm's mean over the other's. **Bold**: significant at 5%.

| Agent model | Arm | Against | Cases | Accuracy (points) | Gained / lost | Wall time (s) | Time ratio | Output tokens | Output ratio | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | none | 60 | **+26.7** [+15.0, +40.0]; p 7.6e-05 | 17 / 1 | **+2.1** [+1.5, +2.9]; p 0.0001 | 1.74x | +79 [-22, +187]; p 0.14 | 1.11x | **+50,204** [+34,243, +72,313]; p 0.0001 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | none | 60 | **+31.7** [+20.0, +43.3]; p 1.9e-06 | 19 / 0 | **+1.3** [+0.7, +2.0]; p 0.0001 | 1.45x | +38 [-46, +129]; p 0.39 | 1.05x | **+41,236** [+24,589, +64,538]; p 0.0001 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | exactdocs (bm25) | 60 | +5.0 [-5.0, +16.7]; p 0.39 | 7 / 4 | **-0.8** [-1.4, -0.3]; p 0.003 | 0.84x | -41 [-132, +57]; p 0.4 | 0.95x | -8,968 [-20,714, +1,925]; p 0.13 |
| `ollama:kimi-k3` | exactdocs (bm25) | none | 60 | **+50.0** [+38.3, +63.3]; p 9.3e-10 | 30 / 0 | -5.8 [-12.6, -0.4]; p 0.067 | 0.7x | **-727** [-1,395, -193]; p 0.013 | 0.62x | **+32,851** [+28,102, +38,681]; p 0.0001 |
| `ollama:kimi-k3` | grounded-docs (full-text) | none | 60 | **+48.3** [+35.0, +61.7]; p 1.9e-09 | 29 / 0 | **-10.6** [-17.4, -5.4]; p 0.0001 | 0.44x | **-905** [-1,570, -375]; p 0.0005 | 0.53x | **+15,809** [+11,897, +20,476]; p 0.0001 |
| `ollama:kimi-k3` | grounded-docs (full-text) | exactdocs (bm25) | 60 | -1.7 [-11.7, +8.3]; p 0.77 | 5 / 6 | **-4.9** [-6.4, -3.5]; p 0.0001 | 0.64x | **-179** [-262, -95]; p 0.0003 | 0.85x | **-17,042** [-20,451, -14,073]; p 0.0001 |

In brackets: the 95% interval, a percentile bootstrap over the questions (10,000 resamples, seed 489); with a few dozen questions per kind or project, theirs are wide.

## Accuracy per kind

| Agent model | Arm | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 30.0 % [0.0, 60.0] (10) | 0.0 % [0.0, 0.0] (10) | 20.0 % [0.0, 50.0] (10) | 10.0 % [0.0, 30.0] (10) | 20.0 % [0.0, 50.0] (10) | 0.0 % [0.0, 0.0] (10) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 60.0 % [30.0, 90.0] (10) | 30.0 % [0.0, 60.0] (10) | 50.0 % [20.0, 80.0] (10) | 30.0 % [0.0, 60.0] (10) | 50.0 % [20.0, 80.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 80.0 % [50.0, 100.0] (10) | 40.0 % [10.0, 70.0] (10) | 70.0 % [40.0, 90.2] (10) | 20.0 % [0.0, 50.0] (10) | 50.0 % [20.0, 80.0] (10) | 10.0 % [0.0, 30.0] (10) |
| `ollama:kimi-k3` | none | 70.0 % [40.0, 100.0] (10) | 20.0 % [0.0, 50.0] (10) | 40.0 % [10.0, 70.0] (10) | 30.0 % [0.0, 60.0] (10) | 20.0 % [0.0, 50.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:kimi-k3` | exactdocs (bm25) | 90.0 % [70.0, 100.0] (10) | 80.0 % [50.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 80.0 % [50.0, 100.0] (10) |
| `ollama:kimi-k3` | grounded-docs (full-text) | 90.0 % [70.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 100.0 % [100.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) |

## Accuracy per project

| Agent model | Arm | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 16.7 % [0.0, 41.7] (12) | 25.0 % [0.0, 50.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 33.3 % [8.3, 58.3] (12) | 58.3 % [33.3, 83.3] (12) | 25.0 % [0.0, 50.0] (12) | 58.3 % [33.3, 83.3] (12) | 25.0 % [0.0, 50.0] (12) |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 33.3 % [8.3, 58.3] (12) | 66.7 % [41.7, 91.7] (12) | 33.3 % [8.3, 58.3] (12) | 50.0 % [25.0, 75.0] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | none | 25.0 % [0.0, 50.0] (12) | 25.0 % [0.0, 50.0] (12) | 41.7 % [16.7, 66.7] (12) | 33.3 % [8.3, 58.3] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | exactdocs (bm25) | 66.7 % [41.7, 91.7] (12) | 83.3 % [58.3, 100.0] (12) | 66.7 % [41.7, 91.7] (12) | 100.0 % [100.0, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |
| `ollama:kimi-k3` | grounded-docs (full-text) | 66.7 % [41.7, 91.7] (12) | 83.3 % [58.3, 100.0] (12) | 66.7 % [41.7, 91.7] (12) | 91.7 % [75.0, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |

## Runs without an answer

2 runs: `no_answer` is the agent's (a miss, counted), `error` the provider's or the judge's (left out of every rate and test).

| Agent model | Arm | Case | Grade | Why |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | starlette 1.10.0: If the first of several background tasks raises, do the others still run? | no_answer | no answer: UnexpectedModelBehavior: Tool 'search_docs' exceeded max retries count of 1. Consider raising the retry limit, or see the docs on tool retries: https |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | zod v4.0.17: How do I define a two-way schema so I can decode an ISO string into a Date and .encode() it back? | no_answer | no answer: UsageLimitExceeded: The next request would exceed the request_limit of 20. Consider raising the limit, or see the docs on usage limits for budget-awa |

## Documentation servers

- **exactdocs (bm25)**: server: exactdocs serve --stdio; version: 0.0.0.post140.dev0+eee1e310; tools: article_outline, list_articles, list_libraries, query-docs, read_article, read_chunk, resolve-library-id, search_all_docs, search_docs, view_article, view_search
- **grounded-docs (full-text)**: server: @arabold/docs-mcp-server 3.4.1 (read-only, HTTP); integrity: `sha512-IZQKYKs3p939Tt7N14JDLdukWzDmjOyp1QLARdpFZljh25eAT7cfY0Krtajg0UPpzJOIsHWpp0UBslioskmNzA==`; configuration: full-text: no embedding model: full-text search only, what it does when no provider credentials are set; indexed: 15 pinned versions, 6,263 chunks; node: v22.23.5; tools: find_version, list_libraries, list_pages, read_page, search_docs

## Retrieval configurations

- **bm25**: `EXACTDOCS_AI__MODE=bm25`; searches answered by bm25: 217
<!-- /bench -->
