# The agent benchmark

!!! abstract "TL;DR"
    - Retrieval numbers do not show that a coding agent reaches the right answer, nor that it
      reaches it more often with ExactDocs than without. The agent benchmark (#348, #495) measures
      both.
    - A [pydantic-ai](https://ai.pydantic.dev/) agent answers the golden-set questions with each
      documentation arm. An LLM judge, blind to the arm, grades each answer against the case's
      reference answer and facts.
    - Two arms are built: `none` (no tools) and `exactdocs` (only the ExactDocs MCP tools,
      `exactdocs serve --stdio`, as shipped).
    - It never runs in CI with a model. The recorded runs and their caveats are on
      [Agent results](../benchmark/agent.md); flags and the workflow are on
      [Running the agent benchmark](agent-bench-running.md).

It lives in
[`packages/exactdocs/evals/agent_bench/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/agent_bench).
It runs locally, or from the manual *Agent benchmark (real providers)* workflow.

## The arms

| Arm | The agent's tools | Status |
|---|---|---|
| `none` | none: it answers from what it knows of that version, or says it does not know | built |
| `exactdocs` | only the ExactDocs MCP tools, `exactdocs serve --stdio`, under each retrieval configuration | built |
| `context7` | the official Context7 MCP server at a pinned version | #493 |
| `grounded-docs` | Grounded Docs' MCP server over its own index | #492 |

Every arm gets the same prompt, the same usage limits (`--max-requests`) and only its own tools.

The instructions are the same for every arm and model apart from one sentence:

- An arm with a tool is told:
    - its only source of documentation is *that tool's* tools (only the name differs between
      `exactdocs`, `context7` and `grounded-docs`);
    - to search exactly the version the project uses, read what it needs, and answer from what it
      read;
    - to say when that version's documentation does not cover the question.
- `none` is told it has no tools, and to answer from what it knows about that version or say that
  it does not know.
- Both end with "answer briefly; do not answer from another version".

The arms are declared in `agent_bench/arms.py`.

- An arm whose toolset is not built yet is refused on the command line with its issue.
- Building one only adds its server to `ArmServers.tools` (`agent_bench/harness.py`).

## How a run works

### Setting up the arms

- For the `exactdocs` arm and each retrieval configuration, the projects of the asked cases are
  imported with the real importer at their pinned commits (as `golden-import` does). They are
  embedded when the configuration names an embedding model.
- Configurations that share an embedding model share one import.
- Then ExactDocs is started **as shipped**: `exactdocs serve --stdio` on that data directory with
  the configuration's settings (and none of the agents' API keys).
- The agent reaches it through a pydantic-ai `MCPToolset`. The `none` arm has no toolset.

### Asking the questions

- The questions are interleaved: each case is asked of every agent model with every arm before the
  next case, `--concurrency` at a time. So a slow hour of the provider weighs on every arm alike.
- Each finished question is appended to `<report>.rows.jsonl` next to the report.
- `--resume` keeps the questions a previous run of the same command answered, and asks only the
  others and those the provider failed on. So a long run survives a restart or a rate limit.

What the agent is told is what a coding agent knows from a project, never the answer:

- the instructions of its arm (above);
- the prompt: `My project uses <project title> at version <version>.` and the question.

The ExactDocs library ID is not given: finding it (`list_libraries`, `resolve-library-id`) is part
of the task. Both the instructions and the prompt are recorded in the report
(`meta.agent_instructions` per arm, `meta.prompt`).

### What is recorded

A `process_tool_call` hook records, per question:

- every tool call: name, arguments cut to 200 characters, time, error;
- the sections read in full (`read_chunk`, the chunks `query-docs` returned, whole articles from
  `read_article`), with their version;
- how each search was answered: `bm25`, or `bm25 (mode_unavailable)` when the server fell back.

Over every model request the run also records:

| Measure | How |
|---|---|
| input tokens, output tokens | as the provider reports them; the output includes the thinking (Ollama counts the `reasoning` text inside `completion_tokens`) |
| thinking tokens on their own | the provider's count, or an estimate ([below](#thinking-tokens)) |
| wall time | with the time lost to provider retries left out ([below](#retries)) |
| USD | from ExactDocs' own price list (`GenaiPrices`, the bundled `genai-prices` data) |

#### Thinking tokens

- Where the provider's usage reports a count, it is used (OpenAI's `reasoning_tokens`).
- Otherwise, where the model returns its thinking as text (Ollama's `reasoning` field, a
  pydantic-ai `ThinkingPart`), it is an **estimate**: each response's reported output tokens
  times the thinking's share of the characters that response produced (thinking, text and
  tool-call arguments).
    - It assumes the thinking costs as many tokens per character as the rest, so it never exceeds
      the output.
- A model that returns no thinking and whose provider reports none is recorded as *not returned*
  (`null`), not 0.

#### Retries

- The time lost to provider retries is `retry_seconds`, with `provider_retries`.
- An Ollama model's client retries a 408, 409, 429 or 5xx with backoff, up to `--max-retries`
  times (default 6, `Retry-After` honoured).
- The client's event hooks add up, per run, the time from each failed request to its retry.
- The report's wall time leaves it out.

#### USD

USD is `null` (shown *unpriced*) when the model is not in the price list, as for Ollama Cloud and
the stand-ins. It is never 0 for an unpriced model.

### Runs without an answer

A run that ends without an answer is not judged.

| Side | Examples | Graded | Counts as |
|---|---|---|---|
| the agent's | the request limit, a tool call or output it never got right, a request the provider refused for its content (400, 413) | `no_answer` | a miss |
| the provider's (after the retries) | rate limited, a server error, a lost connection | `error` | a failure, never a wrong answer |

An `error` run is:

- left out of every rate, mean and paired test;
- counted in *Errors* and listed under *Runs without an answer*;
- asked again by `--resume`.

## The judge

The judge is a pydantic-ai agent with a typed output (grade, `wrong_version`, reason), run as a
Pydantic Evals evaluator.

- It gets the question, the library and version, the kind, the reference answer, the facts and the
  answer as JSON.
- It does not get the documentation, nor anything of the run: no model, no arm, no tool call.
- It is **blind to the arm**. Before it reads an answer, every arm's product and tool names
  (`ExactDocs`, `search_docs`, `read_chunk`, `Context7`, `get-library-docs`, `Grounded Docs`, ...
  as whole words, ignoring case) are replaced by `[redacted]`, the same names for every arm
  (`arms.blind`).

It grades:

| Grade | When |
|---|---|
| `correct` | every required fact, in any wording, and nothing the reference contradicts |
| `partially_correct` | some of the facts, nothing contradicted |
| `wrong` | none of them, something the reference contradicts, or an invented API or behaviour |
| `refused` | says the documentation does not cover it or that it does not know, or declines, and states no facts |

For an `unanswerable` case:

- an answer that says the documentation of that version does not cover it, or that the agent does
  not know, is graded `refused`;
- one that answers anyway (from another version, from memory, invented) is graded `wrong`.

The report counts `refused` as accurate for an `unanswerable` case only: there it is the right
answer, for any other kind it is a miss. Each question keeps its raw grade.

`wrong_version` is set when the answer states something true of another version only. The report
counts those separately (*Wrong for the version*). The judge's instructions are in
`agent_bench/judge.py`.

## The report

`reports/evals/agent-bench.json`, and `.md` next to it (also appended to `$GITHUB_STEP_SUMMARY`).

- One cell per agent model and arm (and retrieval configuration, for `exactdocs`).
- Every rate and mean is over the questions without a provider failure (`answered`).

### Quality

- Grades and accuracy (share `correct`, plus `refused` on `unanswerable` cases), overall, per kind
  and per project.
- *No answer* and *Errors*.
- *Wrong for the version*: answers the judge flagged `wrong_version`, and their share.
- *Refused, answerable*: answerable questions the agent refused (misses).
- *Correct refusals, unanswerable*.
- *Read the answer*: of the answerable questions, the share where the agent read in full every
  part the case names, at its version: a section of each part, or one of its alternatives (#501).
    - Search snippets do not count.
    - A case's sections are, by construction, where its facts are stated, so this measures whether
      the cited text holds the required facts.
- *Read another version*.
- Tool calls per question.

### Cost per question

Each as mean with its 95% interval, p50 and p95 (nearest rank):

- wall time (retries left out);
- input tokens;
- output tokens with the thinking;
- thinking tokens on their own (marked *estimated*, or *not returned*);
- USD;
- the provider retries.

### Intervals and comparisons

- Every rate and mean has its 95% interval (`intervals`, a percentile bootstrap over the questions,
  as in [Intervals and paired tests](statistics.md#intervals-and-paired-tests)).
- **Against the other arms, on the same cases** (`versus`): each arm against `none` (and every arm
  but these two against `exactdocs` too), for the same agent model and the cases both answered.
    - The accuracy difference, by McNemar's test (mid-p).
    - The wall time, output tokens and input tokens, by a paired sign-flip permutation test.
    - Each with its paired bootstrap interval, and the ratio of the means.
    - This answers "how much longer does the agent take with the tool, and is it worth it".
- **Against the first retrieval configuration**: for each retrieval configuration of an arm but
  its first, McNemar's test of its accuracy against the first one's (`reference`,
  `versus_reference`). Put the baseline first (`--retrieval`), e.g. BM25 when comparing models.
- *Runs without an answer*: the `no_answer` and `error` runs and why.

### What a rerun needs

- `statistics` records the seed, resamples, confidence and level of the intervals and tests.
- `meta` holds what a rerun needs:
    - the agent models, the judge model, the arms and their instructions;
    - each retrieval configuration's settings;
    - the selection of cases, the thinking setting, the limits and retries;
    - where the models are served (`providers`: base URLs only);
    - the ExactDocs version and repository commit;
    - every imported version with its pinned and recorded commit.
- `questions` holds every question's record: tool calls, chunks read as `<chunk ID>@<version>`,
  tokens, thinking, wall and retry time, USD, the answer as given, the judge's reason.

!!! info "No credential is recorded"
    - A retrieval setting whose name holds `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `HEADER`
      and the like is recorded as `<redacted>`.
    - Base URLs lose their user, password and query.
    - Error messages and the judge's reasons have every secret-named environment value and
      `Bearer <token>` replaced (`agent_bench/redact.py`).
    - The API keys are read from the environment only.
