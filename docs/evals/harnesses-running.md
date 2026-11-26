# Running the harness benchmark

!!! abstract "TL;DR"
    - `just harness-bench run` needs Docker, Node.js 22 and npm, and each provider's API key in its
      usual variable. A subscription login is never used. The manual *Harness benchmark (real
      providers)* workflow runs the same command.
    - Pull request CI runs every parser on recorded transcripts, with no container, no CLI install
      and no provider.
    - The first run (2026-11-25, OpenCode and Codex CLI on Ollama Cloud): every run with a
      documentation server called it. OpenCode with `gpt-oss:120b` passed 5 of 6 coding tasks with
      ExactDocs against 4 without, and 3 of 5 golden questions against 1. `glm-5.3` passed all six
      in both arms and wrote less with ExactDocs. Six tasks show the plumbing works; they are too
      few to measure an effect.

What the benchmark runs and how is on [Coding-agent CLIs](harnesses.md).

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
- `--report-only` runs nothing: it reports what the checkpoint holds for the jobs, harnesses,
  models and arms asked, for runs made by several commands (a harness on fewer models).
- Every network and container a run creates is labelled `exactdocs.harness-bench=1`; a run killed
  from outside can leave its network behind
  (`docker network prune --filter label=exactdocs.harness-bench=1`).

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
    - Claude Code's and Gemini CLI's model runs are built from the pinned releases' documented
      stream-JSON formats (Claude Code 2.1.330's `init`, `assistant`, `user` and `result`
      messages; Gemini CLI 0.70.0's `StreamJsonFormatter`), because no model run of either was
      possible without their providers' keys;
    - both CLIs were also started for real in their containers with an invalid key, and those
      transcripts are kept: Claude Code's `init` lists the arm's MCP tools (its server connected
      through the gate) and no web tool, and each ends with the API's refusal, which is never the
      agent's failure;
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
