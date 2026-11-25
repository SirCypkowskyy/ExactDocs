# Agent results

Does a coding agent answer version-specific questions better with ExactDocs than from what it
already knows, and what does that cost in time and tokens? The agent benchmark (#348, #495) asks
the same model each [golden-set](golden-set.md) question twice: once with **no documentation**
(arm `none`) and once with **only the ExactDocs MCP tools** (arm `exactdocs`), and an LLM judge,
blind to the arm, grades every answer against the case's reference and facts. Context7 (#493) and
Grounded Docs (#492) are the next arms.

**The first run** (2026-11-24): two agent models from different vendors, `gpt-oss:120b` (OpenAI;
its model card gives a June 2024 knowledge cutoff, before the newest pinned version of every
project) and `kimi-k3` (Moonshot AI), judged by `glm-5.3` (Z.ai), on 60 golden questions (2 of
each kind in each project, a seeded stratified sample), 240 answers. With the ExactDocs tools:

- **Accuracy rose for both models, significantly.** `gpt-oss:120b` went from 13.3% [5.0, 21.7]
  to 43.3% [31.7, 56.7] (+30.0 points [+18.3, +43.3]; 19 questions gained, 1 lost; McNemar
  p = 2.1e-05). `kimi-k3` went from 33.3% [21.7, 45.0] to 85.0% [75.0, 93.3] (+51.7 points
  [+40.0, +65.0]; 31 gained, 0 lost; p = 4.7e-10).
- **No answer was true of another version only.** Without documentation the judge flagged 15 of
  `gpt-oss:120b`'s 60 answers (25%) and 5 of `kimi-k3`'s (8%) as stating what holds for another
  version; with ExactDocs, none of either model's.
- **More right refusals.** On the 10 `unanswerable` questions, `kimi-k3` said the documentation
  does not cover it 9 times with ExactDocs against 2 without; `gpt-oss:120b` 4 against 2. Neither
  model refused an answerable question with ExactDocs.
- **What it costs depends on the model.** `gpt-oss:120b` took twice as long (2.9 s to 6.0 s a
  question on average, p95 5.1 s to 10.3 s; +3.1 s [+2.4, +3.7], p = 0.0001) and wrote 21% more
  output tokens (745 to 901, thinking included; p = 0.002). `kimi-k3` was not slower: its mean
  fell from 19.1 s to 14.6 s and its output from 1,913 to 1,318 tokens, neither significant
  (p = 0.19 and 0.073). Without documentation it thinks at length about versions it does not
  know (p95: 56 s and an estimated 5,400 thinking tokens); with it, the median rose (9.8 s to
  12.5 s) and the long tail shrank (p95 33 s). Both made about 5.5 tool calls a question, and
  what the tools returned grew the input from about 200 tokens to 38,000 (`kimi-k3`) and 50,000
  (`gpt-oss:120b`) a question: the bulk of the cost on a per-token price.
- **The judge is strict.** `correct` needs every fact the case lists, and the facts often go
  beyond the literal question; a brief, right answer is often `partially_correct` (24 of
  `gpt-oss:120b`'s 60 answers with ExactDocs). That lowers the accuracy of both arms alike.

## Read this first

- **`read_article` gave the agents its metadata, not its text.** pydantic-ai, which runs the
  agents, gives the model only a tool's structured content when every block of the result is text,
  and the structured content of `read_article` left the article out until a fix made after this
  run. In this run, as in every run recorded before the fix, each `read_article` call of the
  `exactdocs` arm (39 that succeeded by `gpt-oss:120b`, in 34 questions; 22 by `kimi-k3`, in 17)
  gave the agent the article's version, commit SHA, front matter and source link only;
  `gpt-oss:120b` followed 20 of its calls with `view_article` of the same article, whose UI holds
  the text. *Read the answer* still counted those articles as read: of the 16 and 26 questions it
  counts, 12 and 6 include a `read_article` of an article that answers them, so only 4 and 20
  (8 % and 40 % of the 50 answerable questions) surely read every part. Accuracy, time and tokens
  are those of agents that could not read a whole article with `read_article`; a run after the fix
  measures them with it.
- **Open-weight models, served by Ollama Cloud.** The agents and the judge are open-weight models
  as [Ollama Cloud](https://ollama.com/) serves them (its API at `https://ollama.com/v1`), not the
  vendors' own APIs; how it quantises and serves them is not ours to see. Hosted frontier models
  have not run yet.
- **The judge is not checked against people yet.** The accuracies rest on one LLM judge
  (`glm-5.3`, a third vendor) that has not been compared with hand labels: the agreement
  criterion of #348 (at least 50 hand-labelled answers) is still open, and until it is met a
  difference of a few points can be the judge's. The answers are in the JSON report for
  labelling (`just agent-bench sample`).
- **Thinking tokens are estimated.** Ollama returns a model's thinking as text and counts it
  inside the output tokens, with no separate count. The thinking tokens below are an estimate:
  each response's output tokens times the thinking's share of the characters it produced. The
  output tokens are as reported, thinking included.
- **No price.** Ollama Cloud bills by plan, not per token, so USD is *unpriced* (`null`), not 0.
- **Wall time is Ollama Cloud's.** It includes the provider's latency and queueing at the time of
  the run, with 3 questions in flight; the time lost to retried requests is left out. Compare the
  arms with each other, not with another day's run.
- **60 questions, not 321.** Ollama Cloud's session usage limit stopped the planned 90-question
  sample twice (below); the recorded run is its complete 2-per-stratum part. With 10 questions per
  kind and 12 per project, those intervals are wide; the overall differences above are not.
- **The golden set has its own flaws** ([its review](golden-set.md#the-independent-review)): in
  the reviewed sample no reference answer was wrong, but 3 cases had facts their sections did not
  state, and 17 lacked a section that answers as well; most cases are not reviewed. A missing
  section lowers *Read the answer* (which counts only the listed sections), not accuracy; a
  flawed fact weighs on both arms alike.

## The run

<!-- bench:agent-run -->
- Started 2026-11-24T11:09:22+00:00; ExactDocs `0.0.0.post113.dev0+590f41d` at `5394cd5aa246`.
- Agents: `ollama:gpt-oss:120b`, `ollama:kimi-k3`; judge `ollama:glm-5.3`; served by ollama at `https://ollama.com/v1`.
- Arms: `none`, `exactdocs`; retrieval configurations of `exactdocs`: `bm25`.
- Cases: 60 (2 per kind and project, seed 495); at most 20 model requests per question; thinking: medium; 3 questions at a time; 6 retries of a failed request.
<!-- /bench -->

The judge ran with its model's default thinking; the agents with `--thinking medium` (sent as
`reasoning_effort`; the models think whatever it says). ExactDocs ran with BM25, its default with
no model. The run was planned on 90 questions (3 per kind and project, seed 495):

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 3 --concurrency 3 --report reports/evals/agent-bench.json
```

It started at 08:16 UTC; at 08:40, after about 155 answers, every request got
`429 ... reached your session usage limit`, recorded as provider errors (not wrong answers). When
the limit lifted (11:08), `--per-stratum 2 --resume` asked again what had failed and finished the
60-question sample (the first two of each stratum's three draws: the same seed) at 11:29, with no
provider error left; the start time above is that resumed run's. Extending it to 90 with
`--per-stratum 3 --resume` hit the limit again after 17 more answers: on the plan used, an Ollama
Cloud session held about 155 answers with their judgements. The 90-question sample (about 50
answers short) and all 321 questions (about six more sessions) are left for a later run, which
`--resume` lets span sessions. Each question's four answers (two models, two arms) were asked
together, so both arms of a question ran in the same session, except for one question whose
answers straddle the limit.

<!-- bench:agent -->
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
<!-- /bench -->

## What a run measures

Per agent model and arm: accuracy (correct, plus a refusal on an `unanswerable` case) overall,
per question kind and per project; answers true only of another version; refusals on answerable
cases; correct refusals on `unanswerable` cases; how often the agent read every part of the
answer in full (a section of each part, or one of its alternatives); tool calls; and the cost per
question: wall time, input tokens, output tokens with the
thinking, thinking tokens on their own, USD. Every rate and mean has a 95% interval, every cost
its median and 95th percentile, and `exactdocs` is compared with `none` on the same cases:
McNemar's test for accuracy, a paired permutation test for time and tokens
([Method](method.md#agent-metrics-and-the-judge),
[Intervals and significance](method.md#intervals-and-significance)). A question the provider
failed on is an error, left out of every rate and test, never a wrong answer.

## What produces the results

A run with real models, by hand:

- the manual workflow *Agent benchmark (real providers)*
  (`.github/workflows/agent-bench.yml`, `workflow_dispatch`, environment `eval-providers`), with
  the inputs `agent_models`, `judge_model`, `arms`, `thinking`, `retrieval` and `args`; its report
  is the artifact `agent-bench`;
- or locally, as above, with the providers' keys in the environment (the report never records
  one).

The recorded run is `packages/exactdocs/evals/results/agent.json` (and `agent.md`); `just
bench-pages` fills this page's tables from it. The flags, the keys the workflow reads and the
labelling rules are in [The agent benchmark](../evals.md#the-agent-benchmark).

The stand-in run (`just agent-bench run --offline`) uses scripted models to check the plumbing.
Its numbers say nothing about an agent and are not published.
