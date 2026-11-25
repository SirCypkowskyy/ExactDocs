# Agent benchmark

60 golden questions (2 per kind and project, seed 495) per agent model and arm (none, exactdocs); judge `ollama:glm-5.3`; ExactDocs 0.0.0.post113.dev0+590f41d at `5394cd5aa246`; at most 20 model requests per question; thinking: medium.

## Quality

| Agent model | Arm | Accuracy | Correct | Partial | Wrong | Refused | No answer | Errors | Wrong for the version | Refused, answerable | Correct refusals, unanswerable | Read the answer | Read another version | Tool calls/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 13.3 % [5.0, 21.7] | 6 | 18 | 34 | 2 | 0 | 0 | 15 (25.0 % [15.0, 36.7]) | 0 (0.0 % [0.0, 0.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 43.3 % [31.7, 56.7] | 22 | 24 | 8 | 4 | 2 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 4 (40.0 % [10.0, 70.0]) | 32.0 % [20.0, 46.0] | 0 | 5.467 [4.8, 6.2] |
| `ollama:kimi-k3` | none | 33.3 % [21.7, 45.0] | 18 | 20 | 17 | 5 | 0 | 0 | 5 (8.3 % [1.7, 16.7]) | 3 (6.0 % [0.0, 14.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:kimi-k3` | exactdocs (bm25) | 85.0 % [75.0, 93.3] | 42 | 8 | 1 | 9 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 9 (90.0 % [70.0, 100.0]) | 52.0 % [38.0, 66.0] | 0 | 5.533 [4.767, 6.417] |

## Cost per question

Each: mean [95% interval of the mean]; median; 95th percentile, over the questions without a provider failure. Wall time leaves out the time lost to provider retries.

| Agent model | Arm | Wall time (s) | Input tokens | Output tokens, thinking included | Thinking tokens | USD | Retried requests |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 2.9 [2.6, 3.2]; p50 2.7; p95 5.1 | 177 [176, 179]; p50 178; p95 184 | 745 [651, 842]; p50 696; p95 1,362 | 356 [307, 411]; p50 330; p95 646 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 6.0 [5.3, 6.7]; p50 5.2; p95 10.3 | 50,433 [41,271, 60,654]; p50 36,716; p95 144,137 | 901 [806, 1,008]; p50 787; p95 1,550 | 505 [443, 578]; p50 417; p95 977 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | none | 19.1 [13.8, 25.9]; p50 9.8; p95 56.1 | 255 [254, 257]; p50 256; p95 263 | 1,913 [1,381, 2,584]; p50 966; p95 5,723 | 1,655 [1,132, 2,315]; p50 714; p95 5,443 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | exactdocs (bm25) | 14.6 [12.4, 17.2]; p50 12.5; p95 32.9 | 37,754 [28,714, 49,149]; p50 23,327; p95 117,684 | 1,318 [1,138, 1,522]; p50 1,051; p95 3,175 | 784 [647, 941]; p50 570; p95 2,161 (estimated) | unpriced | 0 |

## Against the other arms, on the same cases

Each arm against `none` (and `exactdocs`), for the same agent model and the cases both answered without a provider failure: the difference (this arm minus the other), its paired bootstrap interval and the p-value; accuracy by McNemar's test (mid-p), time and tokens by a paired sign-flip permutation test. The ratio is this arm's mean over the other's. **Bold**: significant at 5%.

| Agent model | Arm | Against | Cases | Accuracy (points) | Gained / lost | Wall time (s) | Time ratio | Output tokens | Output ratio | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | none | 60 | **+30.0** [+18.3, +43.3]; p 2.1e-05 | 19 / 1 | **+3.1** [+2.4, +3.7]; p 0.0001 | 2.06x | **+156** [+59, +252]; p 0.002 | 1.21x | **+50,255** [+41,094, +60,476]; p 0.0001 |
| `ollama:kimi-k3` | exactdocs (bm25) | none | 60 | **+51.7** [+40.0, +65.0]; p 4.7e-10 | 31 / 0 | -4.5 [-11.6, +1.1]; p 0.19 | 0.76x | -595 [-1,299, -31]; p 0.073 | 0.69x | **+37,499** [+28,459, +48,892]; p 0.0001 |

In brackets: the 95% interval, a percentile bootstrap over the questions (10,000 resamples, seed 489); with a few dozen questions per kind or project, theirs are wide.

## Accuracy per kind

| Agent model | Arm | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 30.0 % [0.0, 60.0] (10) | 0.0 % [0.0, 0.0] (10) | 20.0 % [0.0, 50.0] (10) | 10.0 % [0.0, 30.0] (10) | 20.0 % [0.0, 50.0] (10) | 0.0 % [0.0, 0.0] (10) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 60.0 % [30.0, 90.0] (10) | 40.0 % [10.0, 70.0] (10) | 90.0 % [70.0, 100.0] (10) | 10.0 % [0.0, 30.0] (10) | 40.0 % [10.0, 70.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:kimi-k3` | none | 70.0 % [40.0, 100.0] (10) | 20.0 % [0.0, 50.0] (10) | 40.0 % [10.0, 70.0] (10) | 30.0 % [0.0, 60.0] (10) | 20.0 % [0.0, 50.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:kimi-k3` | exactdocs (bm25) | 100.0 % [100.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 100.0 % [100.0, 100.0] (10) | 80.0 % [50.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) |

## Accuracy per project

| Agent model | Arm | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 16.7 % [0.0, 41.7] (12) | 25.0 % [0.0, 50.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 25.0 % [0.0, 50.0] (12) | 50.0 % [25.0, 75.0] (12) | 41.7 % [16.7, 66.7] (12) | 58.3 % [33.3, 83.3] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | none | 25.0 % [0.0, 50.0] (12) | 25.0 % [0.0, 50.0] (12) | 41.7 % [16.7, 66.7] (12) | 33.3 % [8.3, 58.3] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | exactdocs (bm25) | 75.0 % [50.0, 100.0] (12) | 91.7 % [75.0, 100.0] (12) | 75.0 % [50.0, 100.0] (12) | 83.3 % [58.3, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |

## Runs without an answer

2 runs: `no_answer` is the agent's (a miss, counted), `error` the provider's or the judge's (left out of every rate and test).

| Agent model | Arm | Case | Grade | Why |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | pydantic v1.10.22: How do I create a model from an ORM object? | no_answer | no answer: UnexpectedModelBehavior: Tool 'read_article' exceeded max retries count of 1. Consider raising the retry limit, or see the docs on tool retries: http |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | starlette 0.52.1: Since when can lifespan state be read as request.state["key"]? | no_answer | no answer: UnexpectedModelBehavior: Tool 'resolve-library-id' exceeded max retries count of 1. Consider raising the retry limit, or see the docs on tool retries |

## Retrieval configurations

- **bm25**: `EXACTDOCS_AI__MODE=bm25`; searches answered by bm25: 244
