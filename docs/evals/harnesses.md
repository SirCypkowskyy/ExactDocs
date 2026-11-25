# Coding-agent CLIs (harnesses)

!!! abstract "TL;DR"
    - People reach ExactDocs through a coding-agent CLI: Claude Code, Codex CLI, Gemini CLI or
      OpenCode. Each has its own system prompt, tools and way of loading MCP tools, and that decides
      whether a documentation server gets called at all. The harness benchmark (#497) runs those
      CLIs, headless, on the [coding tasks](coding-tasks.md) and the
      [golden questions](agent-bench.md), with each documentation arm.
    - Each CLI is pinned to one npm release. Each run gets its own container on its own internal
      network, whose only way out is a gate in the benchmark's process: the model provider's host,
      and the arm's MCP server. Built-in web search and fetch are off in all four CLIs.
    - Each transcript is parsed into tool calls, MCP calls, wall time, input tokens, output tokens
      with the thinking, the thinking on its own where the CLI reports it, and USD. The report gives
      each with its interval, compares every arm with the same harness's `none` arm, and compares
      every cell with the same model without a harness (#495, #496).
    - Pull request CI parses recorded transcripts; real runs go through `just harness-bench run` or
      the manual *Harness benchmark (real providers)* workflow, with API keys only.

It lives in
[`packages/exactdocs/evals/harness_bench/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/harness_bench).

## The harnesses

A harness is the `Harness` protocol (`harness_bench/harness.py`): it writes its CLI's
configuration for one run into the run's own home, gives the command that runs it headless, and
parses what it printed. `just harness-bench list` prints this table.

| Harness | CLI (pinned) | Released | Headless | Providers | Built-in web tools |
|---|---|---|---|---|---|
| `claude-code` | `@anthropic-ai/claude-code@2.1.330` | 2026-11-20 | `claude -p --output-format stream-json --verbose`, `--mcp-config` with `--strict-mcp-config` | Anthropic | off: `--disallowedTools WebSearch WebFetch` |
| `codex` | `@openai/codex@0.171.0` | 2026-11-20 | `codex exec --json`, its own `CODEX_HOME/config.toml` | OpenAI; Ollama as a custom provider on the Responses API | off: `web_search = "disabled"`; Codex has no fetch tool |
| `gemini-cli` | `@google/gemini-cli@0.70.0` | 2026-11-19 | `gemini -p --output-format stream-json`, `~/.gemini/settings.json` | Google (Gemini API key) | off: `tools.exclude` `google_web_search`, `web_fetch` |
| `opencode` | `opencode-ai@1.19.6` | 2026-11-17 | `opencode run --format json --thinking --auto`, `OPENCODE_CONFIG` | Anthropic, OpenAI, Google; Ollama as an OpenAI-compatible provider | off: `tools` `webfetch`, `websearch` false, `permission.webfetch` deny |

- Every release is at least four days old when pinned, installed once into
  `~/.cache/exactdocs/harnesses/<harness>/<version>` with the registry's integrity hash checked
  (`grounded_docs_cli.npm_install`), and mounted read-only into each run's container.
- Every CLI can turn its web tools off, so no arm has the web. The report still counts any
  built-in web call (`web_calls`) and every host the gate refused.
- The arm's MCP server is the only one each CLI loads. A tool the server lists that the arm must
  not get (Grounded Docs' `fetch_url`) is turned off by name in each CLI's configuration.
- Permissions and each CLI's own sandbox are off (`bypassPermissions`, Codex's
  `--dangerously-bypass-approvals-and-sandbox`, Gemini's `yolo`, OpenCode's `--auto`): the
  container is the sandbox. Updates, telemetry and sharing are off where the CLI allows.

How the turn limit (`--max-turns`, 40 by default) and the thinking setting (`--thinking`) reach
each CLI:

| Harness | Turn limit | Thinking setting |
|---|---|---|
| `claude-code` | `--max-turns` | `--effort` |
| `codex` | none: the run's wall limit stops it | `model_reasoning_effort` |
| `gemini-cli` | `model.maxSessionTurns` | not settable on its command line: the model thinks as Gemini CLI configures it |
| `opencode` | the build agent's `steps` | the model's `reasoningEffort` (OpenAI-compatible provider) or `--variant` |

The setting asked for, or *model default*, is recorded per model (`meta.thinking`).

## A run

Each run of one job by one harness with one model and one arm:

1. builds the job's workspace and a home of its own in `<work dir>/runs/<run>`;
2. creates an internal Docker network (`docker network create --internal`: no route out) and opens
   the gate on its gateway (`harness_bench/gate.py`);
3. writes the CLI's configuration in the home and runs it in a container (`container.py`);
4. keeps the transcript and standard error, scrubbed of secrets, next to the workspace, and
   removes the home: its configuration holds the arm's credentials;
5. grades the workspace or judges the answer.

### Isolation

| | How |
|---|---|
| container | `debian:trixie-slim` pinned by digest (the coding tasks' sandbox image), one per run, removed after it |
| filesystem | read-only root and a small `/tmp`; the workspace and the run's home writable; the CLI, Node.js, a pinned ripgrep, the task's environment and the host's CA certificates read-only, at the paths they have on the host |
| limits | `--cpus 2`, `--memory 4g` with swap, `--pids-limit 1024`, no capabilities, `no-new-privileges`, a wall limit (`--wall-seconds`, 900 s) after which the container is killed |
| network | the internal network; `HTTPS_PROXY` points at the gate |
| the gate | tunnels `CONNECT` only to the model provider's host and port, refuses every other host and records it; forwards one port to the arm's MCP server on the host's loopback, reached as `services.harness.internal` |
| environment | the harness's variables, the proxy, the CA bundle, and the provider's key passed by name (`docker run --env NAME`), never on a command line or in a file |

- Where the benchmark's own process reaches the internet through a proxy (`HTTPS_PROXY`), the gate's
  tunnels go through it.
- The network's gateway is the host: a service on the host that listens on every interface could
  be reached from a run too. Run nothing else that listens so on the machine that runs the
  benchmark.
- The pinned ripgrep (14.1.1, its SHA-256 checked) is there because OpenCode's and Gemini CLI's
  search tools run `rg`, and OpenCode would otherwise download it, which the gate refuses.

What the gate refused is in the report (*Network*). In the first run, OpenCode tried
`registry.npmjs.org` and `github.com`; Codex tried `api.github.com` and `chatgpt.com`.

### The arms' servers

The arms are the agent benchmark's ([The arms](agent-bench.md#the-arms)), served over HTTP on the
host's loopback (`harness_bench/endpoints.py`, on `agent_bench.servers.ArmServers`), because the
CLI in its container reaches them through the gate:

| Arm | Server | Credential |
|---|---|---|
| `exactdocs` | `exactdocs serve` over the golden corpus imported at the pinned commits (the agent benchmark's import), told to answer `services.harness.internal` (`EXACTDOCS_ALLOWED_HOSTS`) | an API token: an admin and a token are created in the imported data directory, and the token goes in the CLI's MCP configuration, as a team's CLI would hold it |
| `context7` | the pinned official server, `@upstash/context7-mcp` 4.5.0 `--transport http` | over HTTP it reads the key from each request, so the CLI's configuration sends `CONTEXT7_API_KEY` as a header, as Context7 documents for its remote server; it sits in the run's home for the run |
| `grounded-docs` | Grounded Docs 3.4.1, read-only, over its index of the pinned versions | none |

What each server was, and the tools the arm got, is recorded in `meta.servers`.

## The jobs

- **Coding tasks** (`--jobs tasks`, the default): the CLI gets the task's workspace, the task's
  pinned environment mounted read-only and on `PATH`, and the prompt the pydantic-ai agent gets
  (the sentence about the arm's documentation tool, `My project uses <title> at version
  <version>.`, the request), plus how to run the project's own tests (`sh .home/run-tests.sh`,
  outside what is graded). The workspace is then graded exactly as the coding tasks grade it:
  the hidden tests in the coding tasks' sandbox (Docker by default), the forbidden APIs and the
  files changed, by their own evaluators.
- **Golden questions** (`--jobs questions`, with `--judge-model`): the CLI gets an empty workspace
  and the agent benchmark's instructions and prompt; its final message is graded by the agent
  benchmark's judge, blind to the arm. *Read the answer* is not measured: a CLI's transcript does
  not keep what each tool returned in a form traced to the golden sections.

Selection: `--tasks`, `--projects`, `--limit` (per project), `--post-cutoff` (only tasks pinning a
version released after `--cutoff`); for questions `--kinds`, `--question-limit`, `--per-stratum`.

## The transcript

Each CLI's output is parsed into the same `Transcript` (`harness_bench/transcript.py`):

| Measure | Claude Code | Codex CLI | Gemini CLI | OpenCode |
|---|---|---|---|---|
| tool calls | `tool_use` blocks, errors from `tool_result` | `command_execution`, `file_change`, `mcp_tool_call`, `web_search` items | `tool_use` / `tool_result` events | `tool_use` parts (`completed` or `error`) |
| MCP calls | `mcp__<server>__<tool>` | `mcp_tool_call` with `server`, `tool` | `mcp_<server>_<tool>` | `<server>_<tool>` |
| input tokens (cached included) | `result.usage`: input + cache creation + cache read | sum of `turn.completed` `input_tokens` | `stats.input_tokens` (the prompt) | sum of steps' input + cache read + cache write |
| output tokens with thinking | `result.usage.output_tokens` | sum of `output_tokens` | `output_tokens` + the derived thinking | sum of steps' output + reasoning |
| thinking on its own | *not reported* (Claude Code counts it in the output) | `reasoning_output_tokens` where reported | *derived*: `total_tokens - input_tokens - output_tokens` | `tokens.reasoning` where reported |
| USD | `total_cost_usd` (Claude Code's own) | the bundled price list | the bundled price list | its `cost` when not 0, else the price list |
| model requests | `num_turns` | not reported | not reported | steps |

- A count of 0 next to thinking text is *not reported*: Ollama's OpenAI-compatible and Responses
  APIs report no reasoning tokens, so OpenCode and Codex give 0 while the model returned its
  thinking. The characters of thinking text are kept (`thinking_chars`).
- An unpriced model (an Ollama Cloud model) is *unpriced*, never 0.
- Wall time is the container's, from `docker run` to its end (about a second of container start
  included), the same for every harness; the CLI's own duration is kept where it reports one.
- A run whose transcript says the provider failed (a 429, a 5xx, a lost connection, a quota) is not
  graded, is counted in *Errors* and is run again by `--resume`; so is a CLI that failed to start.
  A run stopped by its turn limit or wall limit is graded as it is (the agent's side).

## The report

`reports/evals/harness-bench.json`, `.md` next to it, and the checkpoint `.rows.jsonl`. One cell
per harness, model, arm (and configuration) and kind of job, over the runs without a provider's or
CLI's failure, each rate and mean with its 95% interval ([statistics](statistics.md)):

- the pass rate (tasks) or accuracy (questions);
- the share of runs that called the documentation server at least once, and docs calls per run;
- tool calls per run;
- wall time (mean, p50, p95), input tokens, output tokens with the thinking, thinking tokens
  (with where they come from), USD;
- built-in web calls and the hosts the gate refused.

Comparisons, on the same jobs:

- **against the same harness's `none` arm**: the pass rate by McNemar's test (mid-p), wall time and
  output tokens (and input tokens) by a paired permutation test, with the ratios of the means;
- **against the same model and arm without a harness**: the same tests against a coding tasks report
  (`--baseline-tasks`) or an agent benchmark report (`--baseline-questions`), paired by model, arm,
  configuration and job.

## Running it

```bash
just harness-bench list
just harness-bench parse --harness opencode --mcp-server exactdocs transcript.jsonl
OLLAMA_API_KEY=... just harness-bench run --harness opencode,codex \
  --model ollama:gpt-oss:120b --model ollama:glm-5.3 --arm none,exactdocs \
  --tasks zod-error-messages-v4,zod-optional-unknown \
  --baseline-tasks packages/exactdocs/evals/results/coding-tasks.json --concurrency 2
ANTHROPIC_API_KEY=... just harness-bench run --harness claude-code \
  --model anthropic:claude-sonnet-4-5 --thinking high --post-cutoff --limit 3
just harness-bench run ... --resume
```

- It needs Docker, Node.js 22 and npm (the CLIs' first install), and the network for the first
  install of the task environments and the pinned ripgrep.
- Models are `<provider>:<model>`; each provider's key comes from its usual variable
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_API_KEY`), and its base URL from
  `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `GOOGLE_GEMINI_BASE_URL` or `OLLAMA_BASE_URL`. A
  subscription login is never used. A harness runs only the models of providers it supports.
- `--arm`, `--retrieval` and `--grounded-docs` are the agent benchmark's.

### The manual workflow

*Harness benchmark (real providers)* (`.github/workflows/harness-bench.yml`, `workflow_dispatch`
only, environment `eval-providers`, the self-hosted runner) runs the same command and uploads the
report and every run's transcript as the artifact `harness-bench`.

| Input | What it is |
|---|---|
| `harnesses` | comma-separated |
| `models` | comma-separated `<provider>:<model>` |
| `arms` | default `none,exactdocs` |
| `thinking` | |
| `args` | e.g. `--post-cutoff --limit 3`, `--jobs tasks,questions --judge-model openai:gpt-5` |

Keys: the secrets `HARNESS_BENCH_ANTHROPIC_API_KEY`, `HARNESS_BENCH_OPENAI_API_KEY`,
`HARNESS_BENCH_GEMINI_API_KEY`, the agent benchmark's `AGENT_BENCH_OLLAMA_API_KEY` and
`CONTEXT7_API_KEY`, and the variable `AGENT_BENCH_OLLAMA_BASE_URL`. Each CLI's container gets only
its provider's key.

## Tests

`tests/evals/test_harness_bench.py` and `features/harness_bench.feature` run in pull request CI,
with no container, no CLI install and no provider:

- every parser on recorded transcripts (`tests/fixtures/harness_transcripts/`):
    - OpenCode's and Codex's were captured from real runs of the pinned CLIs in their containers
      (Ollama Cloud, `gpt-oss:120b`), local paths replaced;
    - Claude Code's and Gemini CLI's are built from the pinned releases' documented stream-JSON
      formats (Claude Code 2.1.330's `init`, `assistant`, `user` and `result` messages; Gemini CLI
      0.70.0's `StreamJsonFormatter`), because no run of either was possible without their
      providers' keys;
    - each with the provider's failure (a 429) and the agent's (the turn limit);
- every harness's configuration: web tools off, only the arm's MCP server, the key by name;
- the gate: tunnels only to allowed hosts, forwards, `NO_PROXY`, an upstream proxy;
- whole runs on the stand-in coding tasks and golden questions with a stand-in CLI (Claude Code's
  adapter, its CLI replaced by `tests/fixtures/harness_stand_in_cli.py`) behind the gate on
  loopback, graded, judged, resumed and reported with the paired comparisons.

The test that runs a real container (a run reaches only what the gate lets through, its root is
read-only) is marked `integration`.

## A first run

One small run is recorded in `packages/exactdocs/evals/results/harness-bench.json` (and `.md`),
made by several commands on one checkpoint and reported with `--report-only`:

| Setting | Value |
|---|---|
| date | 2026-11-25 |
| harnesses | OpenCode 1.19.6 and Codex CLI 0.171.0, each run in its own container behind the gate |
| models | `ollama:gpt-oss:120b` and `ollama:glm-5.3` on Ollama Cloud, each with its default thinking |
| arms | `none` and `exactdocs` (BM25) |
| coding tasks | the six of the [no-harness run](coding-tasks.md#a-first-run), all pinning a version released after gpt-oss's cutoff |
| golden questions | five `how-to` questions (the first of each project), OpenCode with `gpt-oss:120b` only, judged by `glm-5.3` |

Coding tasks passed (of six) and documentation calls per task:

| Harness / model | `none` | `exactdocs` | Docs calls | Output tokens, `exactdocs` / `none` | Wall time, `exactdocs` / `none` |
|---|---|---|---|---|---|
| OpenCode / gpt-oss:120b | 4 | 5 | 2.7 | x0.85 | x1.28 |
| OpenCode / glm-5.3 | 6 | 6 | 5.7 | x0.76 | x0.81 |
| Codex / glm-5.3 | 6 | 6 | 5.5 | x0.60 | x0.67 |
| Codex / gpt-oss:120b | 1 of 1 graded | 0 of 1 graded | 0 | n/a | n/a |

- Every run with a documentation server called it at least once. No CLI made a built-in web call.
- OpenCode with gpt-oss gained `zod-error-messages-v4` with ExactDocs (it used Zod 3's
  `required_error` without it) and failed `starlette-template-response-v1` in both arms: without
  documentation with the name-first `TemplateResponse`; with it, after a `search_docs` call the
  tool refused (the library ID sent with a leading space) and a search for route names only.
  Against `none` on the same tasks: +1 task, p = 0.5 (McNemar, mid-p): six tasks show the plumbing
  on real CLIs, not an effect size.
- glm-5.3 passed every task in both harnesses; with ExactDocs it wrote less (output tokens x0.60 to
  x0.76) and finished sooner, none of it significant on six tasks.
- **Against the same model without a harness** (the pydantic-ai loop's run of the same six tasks):
  OpenCode with gpt-oss passed 4 and 5 where the loop passed 2 and 4, and took 2.2 and 2.5 times
  as long (p = 0.03, paired permutation) with about a quarter more output tokens.
- **Codex with gpt-oss:120b**: 10 of 12 runs ended with server errors from Ollama Cloud's
  Responses API (`stream disconnected before completion: Internal Server Error`, then *high demand*
  on each of Codex's five retries), mid-task, and again for the three run once more with
  `--resume`. The same
  model through the Chat Completions API (OpenCode) and glm-5.3 through the same Responses API
  (Codex) ran without one. They are counted as errors, not graded.
- Golden questions, OpenCode with gpt-oss: 1 of 5 accurate without documentation, 3 of 5 with
  ExactDocs (2 gained, p = 0.25), with 3.4 documentation calls per question and 1.55 times the wall
  time. None of the five is in the agent benchmark's recorded sample, so there is no no-harness
  comparison for them.
- Thinking tokens are *not reported* for every run: both CLIs give 0 reasoning tokens for Ollama
  models, which return their thinking as text. Every run is *unpriced* (Ollama Cloud).
- The gate refused `registry.npmjs.org` (OpenCode) and `api.github.com` and `chatgpt.com` (Codex)
  on every run, and nothing else.

### What was not run

There is no Anthropic, OpenAI or Gemini API key for this run, so Claude Code, Gemini CLI and Codex
with OpenAI's models were not run. Their adapters are tested on transcripts built from their
documented formats ([Tests](#tests)); a run is the manual workflow with the providers' keys.
