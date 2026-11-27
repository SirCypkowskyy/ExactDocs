# Agents, per documentation arm

!!! abstract "TL;DR"
    - The same agent model answers 60 golden questions with no docs, with only the ExactDocs MCP
      tools and with only Grounded Docs' tools; a judge blind to the arm grades every answer.
    - Both tools lift accuracy far above no docs, for both models, and neither is significantly
      more accurate than the other.
    - Grounded Docs gets there with fewer tool calls and in significantly less time; for
      `kimi-k3` also with fewer output and input tokens.
    - The `context7` arm has not run, and no Context7 number is published (#493, #495).

The agent benchmark (#348, #495) as it compares documentation arms. How it works, every table
and every run: [Agent results](../agent/index.md). The judge is not checked against hand labels
yet, and Ollama Cloud's usage limit kept the run at 60 questions, so the intervals are wide.

## The run

<!-- bench:agent-run -->
- Started 2026-11-25T22:04:39+00:00; ExactDocs `0.0.0.post140.dev0+eee1e310` at `345de89ced05`. 347 of the answers were kept from an earlier run of the same command (`--resume`), at its commit and time.
- Agents: `ollama:gpt-oss:120b`, `ollama:kimi-k3`; judge `ollama:glm-5.3`; served by ollama at `https://ollama.com/v1`.
- Arms: `none`, `exactdocs`, `grounded-docs`; configurations of `exactdocs`: `bm25`; of `grounded-docs`: `full-text`.
- `exactdocs (bm25)`: exactdocs serve --stdio.
- `grounded-docs (full-text)`: @arabold/docs-mcp-server 3.4.1 (read-only, HTTP).
- Cases: 60 (2 per kind and project, seed 495); at most 20 model requests per question; thinking: medium; 3 questions at a time; 6 retries of a failed request.
<!-- /bench -->

ExactDocs ran with BM25, its default with no model; Grounded Docs with full-text search only, its
default when no embedding provider is configured. Neither was tuned for these questions.

## Results per arm

<!-- bench:comparison-agent -->
| Agent model | Arm | Accuracy | Correct | Partial | Wrong | Refused | No answer | Errors | Wrong for the version | Refused, answerable | Correct refusals, unanswerable | Read the answer | Read another version | Tool calls/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 13.3 % [5.0, 21.7] | 6 | 18 | 34 | 2 | 0 | 0 | 15 (25.0 % [15.0, 36.7]) | 0 (0.0 % [0.0, 0.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 40.0 % [28.3, 51.7] | 19 | 29 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 28.0 % [16.0, 40.0] | 0 | 4.0 [3.45, 4.683] |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 45.0 % [31.7, 56.7] | 22 | 26 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 8.0 % [2.0, 16.0] | 0 | 3.6 [2.817, 4.533] |
| `ollama:kimi-k3` | none | 33.3 % [21.7, 45.0] | 18 | 20 | 17 | 5 | 0 | 0 | 5 (8.3 % [1.7, 16.7]) | 3 (6.0 % [0.0, 14.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:kimi-k3` | exactdocs (bm25) | 83.3 % [73.3, 91.7] | 41 | 8 | 2 | 9 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 9 (90.0 % [70.0, 100.0]) | 58.0 % [44.0, 72.0] | 0 | 4.483 [4.033, 4.983] |
| `ollama:kimi-k3` | grounded-docs (full-text) | 81.7 % [71.7, 91.7] | 42 | 8 | 3 | 7 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 7 (70.0 % [40.0, 100.0]) | 10.0 % [2.0, 18.0] | 0 | 3.45 [2.917, 4.05] |

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
<!-- /bench -->

- **Against no docs**, both tools gain significantly for both models.
- **ExactDocs against Grounded Docs**: Grounded Docs is 5.0 points ahead with `gpt-oss:120b` and
  1.7 points behind with `kimi-k3`, neither significant.
- **Where ExactDocs loses**: Grounded Docs answers in significantly less time with both models,
  and with `kimi-k3` with significantly fewer output and input tokens.
- With ExactDocs the agent more often read a section that answers (*Read the answer*), though
  that did not make it more accurate.
- **Context7** is not in the table: its arm is built and tested against a stand-in, but needs a
  Context7 API key, and Upstash's terms forbid publishing benchmark results without its
  permission ([Terms of service](../../evals/context7.md#terms-of-service)).
