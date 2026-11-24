# Agent results

**Not measured yet.** No agent benchmark has run with a real model, so there are no results,
no accuracy per model and no judge agreement to show. This page gets its tables once a run is
recorded.

## What a run measures

The agent benchmark (#348) checks whether a coding agent that has ExactDocs reaches the right
answer. For each retrieval configuration it imports the golden corpus, starts ExactDocs as
shipped (`exactdocs serve --stdio`), and lets each agent model answer the
[golden set](golden-set.md)'s questions with the ExactDocs MCP tools as its only tools. The
prompt names the project and version, never the library ID or the answer. An LLM judge from
another vendor where possible grades each answer against the case's reference and facts
([Method](method.md#agent-metrics-and-the-judge)).

Per agent model and retrieval configuration, the report gives accuracy overall, per question kind
and per project; the answers true only of another version; how often the agent read every
part of the answer in full (a section of each part, or one of its alternatives); reads of another
version; and tool calls, tokens, USD and wall time per
question. Accuracy and every other rate and mean come with a 95% interval, and each retrieval
configuration's accuracy is tested against the run's first configuration for the same agent
model, on the same questions (McNemar's test, mid-p;
[Intervals and significance](method.md#intervals-and-significance)). With a few dozen questions
per kind, the per-kind intervals are wide.

## What produces the results

Only a run with real models, by hand:

- the manual workflow *Agent benchmark (real providers)*
  (`.github/workflows/agent-bench.yml`, `workflow_dispatch`, environment `eval-providers`), with
  the inputs `agent_models`, `judge_model`, `retrieval` and `args`; its report is the artifact
  `agent-bench`;
- or locally, `just agent-bench run --agent-model <provider:model> --judge-model <provider:model>
  --retrieval bm25:mode=bm25 ...` with the providers' keys in the environment.

Then at least 50 of its answers are labelled by hand to measure the judge's agreement
(`just agent-bench sample` and `just agent-bench agreement`). The flags, the keys the workflow
reads and the labelling rules are in [The agent benchmark](../evals.md#the-agent-benchmark).

The stand-in run (`just agent-bench run --offline`) uses scripted models to check the plumbing.
Its numbers say nothing about an agent and are not published.
