# Agent results

!!! abstract "TL;DR"
    - First run on 2026-11-24: 60 golden questions, two agent models, each with no docs (`none`)
      and with only the ExactDocs MCP tools (`exactdocs`), judged by `glm-5.3`.
    - With ExactDocs, accuracy rose significantly for both: `gpt-oss:120b` from 13.3% to 40.0%
      (+26.7 points [+15.0, +40.0], p = 7.6e-05; 43.3% in the first run), `kimi-k3` from 33.3% to
      83.3% (+50.0 points [+38.3, +63.3], p = 9.3e-10; 85.0% in the first run).
    - With ExactDocs two answers of the 120 were true of another version only; without, 15 of
      `gpt-oss:120b`'s 60 answers and 5 of `kimi-k3`'s were.
    - Grounded Docs, added on 2026-11-25 on the same questions: as accurate as ExactDocs on these
      60 (`gpt-oss:120b` 45.0%, +5.0 points [-5.0, +16.7], p = 0.39; `kimi-k3` 81.7%, -1.7 points
      [-11.7, +8.3], p = 0.77), with fewer tool calls, and 2 answers wrong for the version.
    - Tools that take loose arguments (#573, 2026-11-25): asked again, `gpt-oss:120b`'s ExactDocs
      runs hit a tool error in 1 of 60 instead of 21, and one ended without an answer instead of
      two; its accuracy did not change (41.7% against 43.3%, 5 gained, 6 lost, p = 0.77).
    - Search results grouped by article (#575) and `read_article`'s text (#588), 2026-11-25: asked
      again, both models were as accurate with ExactDocs as before (`gpt-oss:120b` 40.0% against
      41.7%, p = 0.77; `kimi-k3` 83.3% against 85.0%, p = 0.75) with significantly fewer tool calls
      (4.0 against 4.7 and 4.5 against 5.5 a question); `kimi-k3` also wrote 10% fewer output
      tokens (p = 0.012).
    - Context7's arm is built but has not run: no API key, and Upstash's terms forbid publishing
      its numbers without permission.
    - The judge is not checked against hand labels yet, and Ollama Cloud's usage limit kept the run
      at 60 questions.

Does a coding agent answer version-specific questions better with ExactDocs than from what it
already knows, or than with another documentation tool, and what does that cost in time and
tokens? The agent benchmark (#348, #495) asks the same model each [golden-set](../golden-set.md)
question with each **documentation arm**:

- **no documentation** (arm `none`);
- **only the ExactDocs MCP tools** (`exactdocs`);
- **only Grounded Docs' tools**, over its own index of the same pinned versions (`grounded-docs`);
- **only the official Context7 MCP server's tools** (`context7`).

An LLM judge, blind to the arm, grades every answer against the case's reference and facts.

!!! warning "The `context7` arm has not run"
    It is built and tested (against the official server, `@upstash/context7-mcp` 4.5.0, with a
    stand-in of Context7's API), but it needs a Context7 API key, which this run did not have, and
    Upstash's terms forbid publishing benchmark results without its permission. No Context7 number
    will be published here until it is given
    ([Terms of service](../../evals/context7.md#terms-of-service)).

## Which page do I need

| Page | What it holds |
|---|---|
| [Every table](results.md) | quality, tool errors, cost, the paired tests, accuracy per kind and project |
| [What each run found](findings.md) | the four runs in order, with their numbers |
| [Runs](runs.md) | the recorded run: settings, commands and how it went |
| [Every run](history.md) | every recorded agent model and arm of every run, sortable and filterable |

## Read this first

- **Three runs in one table.** The `none` answers are the run of 2026-11-24 (ExactDocs at
  `5394cd5aa246`); the `grounded-docs` answers were added on 2026-11-25 (at `c6188f4fccce`), and
  both models' `exactdocs` answers asked again that evening with #575's grouped results (at
  `345de89ced05`), each by `--resume`, which asks only the questions the checkpoint does not hold.
  The agents, judge, prompt, instructions apart from the tool's name, request limit and thinking
  setting are the same. Accuracy and tokens compare across the runs; wall time does not.
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
  sample twice ([how the run went](runs.md#the-run)); the recorded run is its complete 2-per-stratum part. With 10 questions per
  kind and 12 per project, those intervals are wide; the overall differences above are not.
- **The golden set has its own flaws** ([its review](../golden-set.md#the-independent-review)): in
  the reviewed sample no reference answer was wrong, but 3 cases had facts their sections did not
  state, and 17 lacked a section that answers as well; most cases are not reviewed. A missing
  section lowers *Read the answer* (which counts only the listed sections), not accuracy; a
  flawed fact weighs on both arms alike.

## What a run measures

Per agent model and arm:

- accuracy (correct, plus a refusal on an `unanswerable` case) overall, per question kind and per
  project;
- answers true only of another version;
- refusals on answerable cases, and correct refusals on `unanswerable` cases;
- how often the agent read every part of the answer in full (a section of each part, or one of
  its alternatives; for `grounded-docs`, a whole page; not measured for `context7`);
- tool calls, and the calls that failed (*Tool errors*);
- the cost per question: wall time, input tokens, output tokens with the thinking, thinking
  tokens on their own, USD.

Every rate and mean has a 95% interval, and every cost its median and 95th percentile.
Each arm is compared with `none` on the same cases, and `grounded-docs` (and `context7`) with
`exactdocs` too: McNemar's test for accuracy, a paired permutation test for time and tokens ([Method](../method/metrics.md#agent-metrics-and-the-judge),
[Intervals and significance](../method/metrics.md#intervals-and-significance)).

A question the provider failed on is an error, left out of every rate and test, never a wrong
answer.

## What produces the results

A run with real models, by hand:

- the manual workflow *Agent benchmark (real providers)*
  (`.github/workflows/agent-bench.yml`, `workflow_dispatch`, environment `eval-providers`), with
  the inputs `agent_models`, `judge_model`, `arms`, `thinking`, `retrieval` and `args`; its report
  is the artifact `agent-bench`;
- or locally, with the commands on [Runs](runs.md#the-run) and the providers' keys in the environment (the report never records
  one).

The recorded run is `packages/exactdocs/evals/results/agent.json` (and `agent.md`); `just
bench-pages` fills this page's tables from it. The flags, the keys the workflow reads and the
labelling rules are in [The agent benchmark](../../evals/agent-bench.md).

!!! note "The stand-in run"
    `just agent-bench run --offline` uses scripted models to check the plumbing. Its numbers say
    nothing about an agent and are not published.
