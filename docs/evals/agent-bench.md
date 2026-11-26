# The agent benchmark

!!! abstract "TL;DR"
    - Retrieval numbers do not show that a coding agent reaches the right answer, nor that it
      reaches it more often with ExactDocs than without. The agent benchmark (#348, #495) measures
      both.
    - A [pydantic-ai](https://ai.pydantic.dev/) agent answers the golden-set questions with each
      documentation arm. An LLM judge, blind to the arm, grades each answer against the case's
      reference answer and facts.
    - Four arms: `none` (no tools), and only the MCP tools of `exactdocs` (`exactdocs serve
      --stdio`), `context7` (the official Context7 MCP server) or `grounded-docs` (Grounded Docs,
      read-only, over its index of the pinned versions), each server as shipped.
    - Every arm gets the same prompt, limits and instructions apart from the tool's name, and
      only its own tools. Each arm is compared with `none`, and `context7` and `grounded-docs`
      with `exactdocs` too, on the same cases.
    - No Context7 number is published until Upstash permits it
      ([Terms of service](context7.md#terms-of-service)).
    - It never runs in CI with a model. The recorded runs and their caveats are on
      [Agent results](../benchmark/agent/index.md); flags and the workflow are on
      [Running the agent benchmark](agent-bench-running.md).

It lives in
[`packages/exactdocs/evals/agent_bench/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/agent_bench).
It runs locally, or from the manual *Agent benchmark (real providers)* workflow.

## The arms

| Arm | The agent's tools | Configurations |
|---|---|---|
| `none` | none: it answers from what it knows of that version, or says it does not know | - |
| `exactdocs` | every ExactDocs MCP tool, `exactdocs serve --stdio` | `--retrieval` (BM25, hybrid, ...) |
| `context7` | `resolve-library-id` and `query-docs` of the official Context7 MCP server, `@upstash/context7-mcp` 4.5.0 | - |
| `grounded-docs` | `search_docs`, `read_page`, `list_pages`, `list_libraries` and `find_version` of Grounded Docs 3.4.1, read-only, over its own index of the pinned versions | `--grounded-docs` (`full-text`, `bge-small-en-v1.5`) |

Every arm gets the same prompt, the same usage limits (`--max-requests`) and only its own tools:
the agent's toolset is filtered to the arm's tools (`Arm.tools`, `harness.only_its_tools`), so a
stand-in server's extra tools are filtered out just as a real server's are.

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
- No server's own instructions reach the agent: pydantic-ai's `include_instructions` stays off
  for every arm.

The arms are declared in `agent_bench/arms.py`; their servers are started in
`agent_bench/servers.py` (`ArmServers.tools`).

## How a run works

### Setting up the arms

- For the `exactdocs` arm and each retrieval configuration, the projects of the asked cases are
  imported with the real importer at their pinned commits (as `golden-import` does). They are
  embedded when the configuration names an embedding model.
- Configurations that share an embedding model share one import.
- Then ExactDocs is started **as shipped**: `exactdocs serve --stdio` on that data directory with
  the configuration's settings (and none of the agents' API keys).
- The agent reaches it through a pydantic-ai `MCPToolset`. The `none` arm has no toolset.

#### The `context7` arm (#493)

- The official Context7 MCP server, `@upstash/context7-mcp` 4.5.0: the release ExactDocs' own
  context7-compatible tools mirror (`tests/contracts/context7`).
- Installed from npm into `~/.cache/exactdocs/context7-mcp/4.5.0`, with the registry's integrity
  hash checked (`grounded_docs_cli.npm_install`, as Grounded Docs is installed), and started over
  stdio with Node.js 22.
- It answers from Context7's hosted index, so it needs `CONTEXT7_API_KEY`: the run refuses the arm
  without it (exit 2).
    - The key is the only credential its process gets: none of the agents' or the judge's keys.
    - Its OpenTelemetry metrics are off (`OTEL_SDK_DISABLED`).
    - `CONTEXT7_API_URL` points it at another API, as the integration test does with a stand-in.
- Context7 serves a pinned version only where someone added it ([Context7](context7.md)). The agent
  picks the version from what `resolve-library-id` lists, as any agent does.
- What it reads cannot be traced to the pinned commits' sections (Context7 indexes its own
  sources), so *Read the answer* and *Read another version* are `n/a` for this arm.
- No Context7 number is published until Upstash permits it
  ([Terms of service](context7.md#terms-of-service)).

#### The `grounded-docs` arm (#492)

- Grounded Docs runs as in the [Grounded Docs run](grounded-docs.md), on the same data
  directories: `@arabold/docs-mcp-server` 3.4.1 from npm, integrity checked.
- Each pinned version of the asked projects is indexed from the files the ExactDocs importer takes
  at the pinned commit (`grounded_docs_cli.indexed`), in `<home>/stores/<configuration>`
  (`--grounded-docs-home`, `~/.cache/exactdocs/grounded-docs` by default).
    - A version already indexed at its commit is kept, so after `just grounded-bench` nothing is
      indexed again.
- Its MCP server then runs over HTTP on loopback, in its **read-only** mode
  (`DOCS_MCP_READ_ONLY`, which lists no indexing tool), with no inherited credential.
- The agent gets its five read tools. `fetch_url`, which reads any web page, is left out: it would
  give this arm alone the web.
- Configurations: `full-text` (the default) runs with no model, as `exactdocs` defaults to BM25;
  `bge-small-en-v1.5` serves that model locally to embed the questions (`--models-dir`, as
  `grounded-bench`).
- The library names Grounded Docs lists are the project IDs (`starlette`, `tanstack-query`).
  Finding them is part of the task, as for ExactDocs.
- *Read the answer* counts a `read_page` answer that held a whole page of the asked version (a page
  in Grounded Docs is an article; a page read in parts does not count). Its `search_docs` results
  are passages with context, like ExactDocs' snippets, and do not count.

What each setup's server was (its release and integrity hash, its configuration, the tools the
agent got) is recorded in `meta.servers` and listed under *Documentation servers* in the Markdown.

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
- the sections read in full, with their version:
    - `exactdocs`: `read_chunk`, the chunks `query-docs` returned, whole articles from
      `read_article`;
    - `grounded-docs`: whole pages from `read_page`;
    - `context7`: none;
- how each ExactDocs search was answered: `bm25`, or `bm25 (mode_unavailable)` when the server
  fell back.

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

- One cell per agent model and arm (and configuration, for `exactdocs` and `grounded-docs`).
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
    - `n/a` for `none` and `context7` ([How a run works](#how-a-run-works)).
- *Read another version*.
- Tool calls per question.

### Tool errors

Per arm with tools (#573):

- the runs with a tool call that failed: an argument the server refused, a path the version
  lacks... (`runs_with_tool_errors`);
- how many calls failed (`tool_errors`), and which tools (`tool_errors_by_tool`).

Each costs the agent a turn, and the harness ends a run whose tool fails twice (pydantic-ai's one
retry), so a tool's strictness shows up as `no_answer`.

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
- **Against the other arms, on the same cases** (`versus`): each arm against `none`, and
  `context7` and `grounded-docs` against `exactdocs` too, for the same agent model and the cases
  both answered (a baseline arm's first configuration).
    - The accuracy difference, by McNemar's test (mid-p).
    - The wall time, output tokens and input tokens, by a paired sign-flip permutation test.
    - Each with its paired bootstrap interval, and the ratio of the means.
    - This answers "how much longer does the agent take with the tool, and is it worth it".
- **Against the first retrieval configuration**: for each retrieval configuration of an arm but
  its first, McNemar's test of its accuracy against the first one's (`reference`,
  `versus_reference`). Put the baseline first (`--retrieval`), e.g. BM25 when comparing models.
- *Runs without an answer*: the `no_answer` and `error` runs and why.
- *Documentation servers*: what each setup's server was (`meta.servers`).

### What a rerun needs

- `statistics` records the seed, resamples, confidence and level of the intervals and tests.
- `meta` holds what a rerun needs:
    - the agent models, the judge model, the arms and their instructions;
    - each `exactdocs` retrieval configuration's settings;
    - each arm's server (`servers`: release, integrity hash, configuration, the tools the agent
      got; empty with stand-in tools);
    - the selection of cases, the thinking setting, the limits and retries;
    - where the models are served (`providers`: base URLs only);
    - the ExactDocs version and the repository commit the run started from;
    - every imported version with its pinned and recorded commit;
    - how many answers were kept from an earlier run of the same command (`resumed`: those ran at
      that run's commit and time).
- `questions` holds every question's record: tool calls, chunks read as `<chunk ID>@<version>`,
  tokens, thinking, wall and retry time, USD, the answer as given, the judge's reason.

!!! info "No credential is recorded"
    - A retrieval setting whose name holds `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `HEADER`
      and the like is recorded as `<redacted>`.
    - Base URLs lose their user, password and query.
    - Error messages and the judge's reasons have every secret-named environment value and
      `Bearer <token>` replaced (`agent_bench/redact.py`).
    - The API keys are read from the environment only.
    - Each documentation server gets none of the agents' keys: ExactDocs only its own settings,
      Context7 only `CONTEXT7_API_KEY` (recorded as `CONTEXT7_API_KEY set`), Grounded Docs no
      credential.
