# Agent results

Does a coding agent answer version-specific questions better with ExactDocs than from what it
already knows, and what does that cost in time and tokens? The agent benchmark (#348, #495) asks
the same model each [golden-set](golden-set.md) question twice: once with **no documentation**
(arm `none`) and once with **only the ExactDocs MCP tools** (arm `exactdocs`), and an LLM judge,
blind to the arm, grades every answer against the case's reference and facts. Context7 (#493) and
Grounded Docs (#492) are the next arms.

FINDINGS

## Read this first

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
- **The golden set has its own flaws** ([its review](golden-set.md#the-independent-review)): in
  the reviewed sample no reference answer was wrong, but 3 cases had facts their sections did not
  state, and 17 lacked a section that answers as well; most cases are not reviewed. A missing
  section lowers *Read the answer* (which counts only the listed sections), not accuracy; a
  flawed fact weighs on both arms alike.

## The run

<!-- bench:agent-run -->
<!-- /bench -->

The judge ran with its model's default thinking; the agents with `--thinking medium` (sent as
`reasoning_effort`; the models think whatever it says). The exact command:

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 3 --concurrency 3 --report reports/evals/agent-bench.json
```

## Results

<!-- bench:agent -->
<!-- /bench -->

## What a run measures

Per agent model and arm: accuracy (correct, plus a refusal on an `unanswerable` case) overall,
per question kind and per project; answers true only of another version; refusals on answerable
cases; correct refusals on `unanswerable` cases; how often the agent read every expected section
in full; tool calls; and the cost per question: wall time, input tokens, output tokens with the
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
