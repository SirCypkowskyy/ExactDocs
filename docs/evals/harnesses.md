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
      the manual *Harness benchmark (real providers)* workflow, with API keys only
      ([Running the harness benchmark](harnesses-running.md), with the first run's results).

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
  built-in web call (`web_calls`) and every host the gate refused, so a web tool that stayed on
  would show, and the gate would refuse its hosts anyway.
    - Gemini CLI 0.70.0 warns that `tools.exclude` is deprecated, to be replaced by its Policy
      Engine in 1.0; a later pin has to move the exclusion there.
    - Claude Code's `init` message lists the tools it offered: the report keeps them
      (`tools_offered`), and in the CLI's own start in its container `WebSearch` and `WebFetch` were
      not among them.
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
| thinking on its own | `usage.output_tokens_details.thinking_tokens` | `reasoning_output_tokens` where reported | *derived*: `total_tokens - input_tokens - output_tokens` | `tokens.reasoning` where reported |
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

## Moved sections

These sections moved to another page. The old links still land here and point on.

- <a id="running-it"></a>[Running it](harnesses-running.md#running-it)
- <a id="the-manual-workflow"></a>[The manual workflow](harnesses-running.md#the-manual-workflow)
- <a id="tests"></a>[Tests](harnesses-running.md#tests)
- <a id="a-first-run"></a>[A first run](harnesses-running.md#a-first-run)
- <a id="what-was-not-run"></a>[What was not run](harnesses-running.md#what-was-not-run)
