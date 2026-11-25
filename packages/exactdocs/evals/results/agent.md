# Agent benchmark

60 golden questions (2 per kind and project, seed 495) per agent model and arm (none, exactdocs, grounded-docs); judge `ollama:glm-5.3`; ExactDocs 0.0.0.post139.dev0+124ff7da at `970c77058145`; at most 20 model requests per question; thinking: medium. 300 of the answers were kept from an earlier run (`--resume`).

## Quality

| Agent model | Arm | Accuracy | Correct | Partial | Wrong | Refused | No answer | Errors | Wrong for the version | Refused, answerable | Correct refusals, unanswerable | Read the answer | Read another version | Tool calls/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 13.3 % [5.0, 21.7] | 6 | 18 | 34 | 2 | 0 | 0 | 15 (25.0 % [15.0, 36.7]) | 0 (0.0 % [0.0, 0.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 41.7 % [30.0, 53.3] | 19 | 25 | 9 | 6 | 1 | 0 | 1 (1.7 % [0.0, 5.0]) | 0 (0.0 % [0.0, 0.0]) | 6 (60.0 % [30.0, 90.0]) | 36.0 % [24.0, 50.0] | 0 | 4.667 [4.15, 5.267] |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 45.0 % [31.7, 56.7] | 22 | 26 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 8.0 % [2.0, 16.0] | 0 | 3.6 [2.817, 4.533] |
| `ollama:kimi-k3` | none | 33.3 % [21.7, 45.0] | 18 | 20 | 17 | 5 | 0 | 0 | 5 (8.3 % [1.7, 16.7]) | 3 (6.0 % [0.0, 14.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:kimi-k3` | exactdocs (bm25) | 85.0 % [75.0, 93.3] | 42 | 8 | 1 | 9 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 9 (90.0 % [70.0, 100.0]) | 52.0 % [38.0, 66.0] | 0 | 5.533 [4.767, 6.417] |
| `ollama:kimi-k3` | grounded-docs (full-text) | 81.7 % [71.7, 91.7] | 42 | 8 | 3 | 7 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 7 (70.0 % [40.0, 100.0]) | 10.0 % [2.0, 18.0] | 0 | 3.45 [2.917, 4.05] |

## Tool errors

Tool calls the server refused or could not answer (an argument it does not take, a path the version lacks...), over the answered questions. Each costs the agent a turn, and the harness ends a run whose tool fails twice.

| Agent model | Arm | Runs with a tool error | Tool errors | By tool |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 1 of 60 | 2 | `read_article` 2 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 4 of 60 | 4 | `read_page` 1, `search_docs` 3 |
| `ollama:kimi-k3` | exactdocs (bm25) | 2 of 60 | 2 | `search_docs` 2 |
| `ollama:kimi-k3` | grounded-docs (full-text) | 14 of 60 | 23 | `find_version` 9, `read_page` 4, `search_docs` 10 |

## Cost per question

Each: mean [95% interval of the mean]; median; 95th percentile, over the questions without a provider failure. Wall time leaves out the time lost to provider retries.

| Agent model | Arm | Wall time (s) | Input tokens | Output tokens, thinking included | Thinking tokens | USD | Retried requests |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 2.9 [2.6, 3.2]; p50 2.7; p95 5.1 | 177 [176, 179]; p50 178; p95 184 | 745 [651, 842]; p50 696; p95 1,362 | 356 [307, 411]; p50 330; p95 646 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 5.3 [4.8, 6.0]; p50 4.9; p95 7.7 | 43,023 [34,322, 54,096]; p50 32,351; p95 86,010 | 839 [752, 940]; p50 783; p95 1,422 | 490 [433, 557]; p50 425; p95 784 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 4.2 [3.6, 5.0]; p50 3.4; p95 8.7 | 41,413 [24,766, 64,716]; p50 13,677; p95 177,336 | 784 [680, 901]; p50 703; p95 1,415 | 358 [301, 429]; p50 318; p95 725 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | none | 19.1 [13.8, 25.9]; p50 9.8; p95 56.1 | 255 [254, 257]; p50 256; p95 263 | 1,913 [1,381, 2,584]; p50 966; p95 5,723 | 1,655 [1,132, 2,315]; p50 714; p95 5,443 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | exactdocs (bm25) | 14.6 [12.4, 17.2]; p50 12.5; p95 32.9 | 37,754 [28,714, 49,149]; p50 23,327; p95 117,684 | 1,318 [1,138, 1,522]; p50 1,051; p95 3,175 | 784 [647, 941]; p50 570; p95 2,161 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | grounded-docs (full-text) | 8.4 [7.2, 9.9]; p50 6.5; p95 19.2 | 16,065 [12,153, 20,731]; p50 8,685; p95 57,412 | 1,008 [866, 1,170]; p50 790; p95 2,596 | 560 [449, 688]; p50 383; p95 1,901 (estimated) | unpriced | 0 |

## Against the other arms, on the same cases

Each arm against `none` (and `exactdocs`), for the same agent model and the cases both answered without a provider failure: the difference (this arm minus the other), its paired bootstrap interval and the p-value; accuracy by McNemar's test (mid-p), time and tokens by a paired sign-flip permutation test. The ratio is this arm's mean over the other's. **Bold**: significant at 5%.

| Agent model | Arm | Against | Cases | Accuracy (points) | Gained / lost | Wall time (s) | Time ratio | Output tokens | Output ratio | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | none | 60 | **+28.3** [+16.7, +40.0]; p 4e-05 | 18 / 1 | **+2.5** [+1.9, +3.1]; p 0.0001 | 1.85x | **+94** [+4, +183]; p 0.043 | 1.13x | **+42,846** [+34,145, +53,918]; p 0.0001 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | none | 60 | **+31.7** [+20.0, +43.3]; p 1.9e-06 | 19 / 0 | **+1.3** [+0.7, +2.0]; p 0.0001 | 1.45x | +38 [-46, +129]; p 0.39 | 1.05x | **+41,236** [+24,589, +64,538]; p 0.0001 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | exactdocs (bm25) | 60 | +3.3 [-8.3, +15.0]; p 0.58 | 7 / 5 | **-1.1** [-1.7, -0.6]; p 0.0001 | 0.79x | -56 [-144, +47]; p 0.25 | 0.93x | -1,610 [-15,911, +15,463]; p 0.85 |
| `ollama:kimi-k3` | exactdocs (bm25) | none | 60 | **+51.7** [+40.0, +65.0]; p 4.7e-10 | 31 / 0 | -4.5 [-11.6, +1.1]; p 0.19 | 0.76x | -595 [-1,299, -31]; p 0.073 | 0.69x | **+37,499** [+28,459, +48,892]; p 0.0001 |
| `ollama:kimi-k3` | grounded-docs (full-text) | none | 60 | **+48.3** [+35.0, +61.7]; p 1.9e-09 | 29 / 0 | **-10.6** [-17.4, -5.4]; p 0.0001 | 0.44x | **-905** [-1,570, -375]; p 0.0005 | 0.53x | **+15,809** [+11,897, +20,476]; p 0.0001 |
| `ollama:kimi-k3` | grounded-docs (full-text) | exactdocs (bm25) | 60 | -3.3 [-13.3, +5.0]; p 0.51 | 3 / 5 | **-6.1** [-7.9, -4.6]; p 0.0001 | 0.58x | **-310** [-409, -217]; p 0.0001 | 0.76x | **-21,690** [-30,864, -14,830]; p 0.0001 |

In brackets: the 95% interval, a percentile bootstrap over the questions (10,000 resamples, seed 489); with a few dozen questions per kind or project, theirs are wide.

## Accuracy per kind

| Agent model | Arm | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 30.0 % [0.0, 60.0] (10) | 0.0 % [0.0, 0.0] (10) | 20.0 % [0.0, 50.0] (10) | 10.0 % [0.0, 30.0] (10) | 20.0 % [0.0, 50.0] (10) | 0.0 % [0.0, 0.0] (10) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 70.0 % [40.0, 100.0] (10) | 40.0 % [10.0, 70.0] (10) | 50.0 % [20.0, 80.0] (10) | 10.0 % [0.0, 30.0] (10) | 60.0 % [30.0, 90.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 80.0 % [50.0, 100.0] (10) | 40.0 % [10.0, 70.0] (10) | 70.0 % [40.0, 90.2] (10) | 20.0 % [0.0, 50.0] (10) | 50.0 % [20.0, 80.0] (10) | 10.0 % [0.0, 30.0] (10) |
| `ollama:kimi-k3` | none | 70.0 % [40.0, 100.0] (10) | 20.0 % [0.0, 50.0] (10) | 40.0 % [10.0, 70.0] (10) | 30.0 % [0.0, 60.0] (10) | 20.0 % [0.0, 50.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:kimi-k3` | exactdocs (bm25) | 100.0 % [100.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 100.0 % [100.0, 100.0] (10) | 80.0 % [50.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) |
| `ollama:kimi-k3` | grounded-docs (full-text) | 90.0 % [70.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 100.0 % [100.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) |

## Accuracy per project

| Agent model | Arm | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 16.7 % [0.0, 41.7] (12) | 25.0 % [0.0, 50.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 41.7 % [16.7, 66.7] (12) | 41.7 % [16.7, 66.7] (12) | 41.7 % [16.7, 66.7] (12) | 41.7 % [16.7, 66.7] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 33.3 % [8.3, 58.3] (12) | 66.7 % [41.7, 91.7] (12) | 33.3 % [8.3, 58.3] (12) | 50.0 % [25.0, 75.0] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | none | 25.0 % [0.0, 50.0] (12) | 25.0 % [0.0, 50.0] (12) | 41.7 % [16.7, 66.7] (12) | 33.3 % [8.3, 58.3] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | exactdocs (bm25) | 75.0 % [50.0, 100.0] (12) | 91.7 % [75.0, 100.0] (12) | 75.0 % [50.0, 100.0] (12) | 83.3 % [58.3, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |
| `ollama:kimi-k3` | grounded-docs (full-text) | 66.7 % [41.7, 91.7] (12) | 83.3 % [58.3, 100.0] (12) | 66.7 % [41.7, 91.7] (12) | 91.7 % [75.0, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |

## Runs without an answer

2 runs: `no_answer` is the agent's (a miss, counted), `error` the provider's or the judge's (left out of every rate and test).

| Agent model | Arm | Case | Grade | Why |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | pydantic v1.10.22: How do I create a model from an ORM object? | no_answer | no answer: UnexpectedModelBehavior: Tool 'read_article' exceeded max retries count of 1. Consider raising the retry limit, or see the docs on tool retries: http |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | zod v4.0.17: How do I define a two-way schema so I can decode an ISO string into a Date and .encode() it back? | no_answer | no answer: UsageLimitExceeded: The next request would exceed the request_limit of 20. Consider raising the limit, or see the docs on usage limits for budget-awa |

## Documentation servers

- **exactdocs (bm25)**: server: exactdocs serve --stdio; version: 0.0.0.post139.dev0+124ff7da; tools: article_outline, list_articles, list_libraries, query-docs, read_article, read_chunk, resolve-library-id, search_all_docs, search_docs, view_article, view_search
- **grounded-docs (full-text)**: server: @arabold/docs-mcp-server 3.4.1 (read-only, HTTP); integrity: `sha512-IZQKYKs3p939Tt7N14JDLdukWzDmjOyp1QLARdpFZljh25eAT7cfY0Krtajg0UPpzJOIsHWpp0UBslioskmNzA==`; configuration: full-text: no embedding model: full-text search only, what it does when no provider credentials are set; indexed: 15 pinned versions, 6,263 chunks; node: v22.23.5; tools: find_version, list_libraries, list_pages, read_page, search_docs

## Retrieval configurations

- **bm25**: `EXACTDOCS_AI__MODE=bm25`; searches answered by bm25: 223
