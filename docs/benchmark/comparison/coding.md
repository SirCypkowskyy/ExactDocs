# Coding tasks, per harness, model and arm

!!! abstract "TL;DR"
    - Six version-pinned coding tasks with hidden tests (#496), each pinning a version released
      after the models' training cutoff, done with no docs (`none`) and with the ExactDocs MCP
      tools (`exactdocs`).
    - In real coding-agent CLIs (#497), Codex CLI and OpenCode, with `gpt-oss:120b` and
      `glm-5.3` on Ollama Cloud, and without a harness (the pydantic-ai loop) with `gpt-oss:120b`.
    - No difference between the arms is significant on six tasks: these runs show the plumbing
      works on real CLIs, not an effect size.
    - Not run yet: the `grounded-docs` and `context7` arms, and Claude Code and Gemini CLI, which
      need paid API keys.

Each task is a small project pinned to one version of a library; the agent changes it, and hidden
tests decide whether the code runs against that version
([Coding tasks](../../evals/coding-tasks.md)). The CLIs run headless, each run in its own
container whose only way out is the model provider and the arm's MCP server
([Harnesses](../../evals/harnesses.md)).

## Real coding-agent CLIs

<!-- bench:comparison-harnesses -->
- Started 2026-11-25T17:52:31+00:00; ExactDocs `0.0.0.post149.dev0+866b6daa` at `23bf5e048279`. 58 runs were kept from an earlier run (`--resume`).

11 jobs (6 tasks; 5 golden questions; tasks pydantic-class-model-fields,query-gc-time-v5,starlette-startup-shutdown,starlette-template-response-v1,zod-error-messages-v4,zod-optional-unknown); models ollama:gpt-oss:120b, ollama:glm-5.3; arms none, exactdocs; up to 40 turns and 900 s a run. Isolation: a container per run (read-only root, no capabilities, CPU, memory and process limits) on an internal Docker network of its own; the only way out is the gate: the model provider's host through its proxy and the arm's MCP server through a forward.

| Harness | CLI | Released | Web tools | Turn limit, thinking |
|---|---|---|---|---|
| codex | `@openai/codex@0.171.0` | 2026-11-20 | off: web_search = "disabled" (Codex has no web fetch tool) | no turn limit (the wall limit); thinking: model_reasoning_effort |
| opencode | `opencode-ai@1.19.6` | 2026-11-17 | off: tools webfetch, websearch false; permission webfetch deny | agent build steps; thinking: the model's reasoningEffort (OpenAI-compatible) or --variant |

Thinking: `ollama:gpt-oss:120b` model default; `ollama:glm-5.3` model default.

| Harness / model / arm | Passed | Called the docs | Docs calls | Tool calls | Errors |
|---|---|---|---|---|---|
| codex / ollama:glm-5.3 / none | 100.0 % [100.0, 100.0] (n=6) | n/a | n/a | 8.8 [6.3, 11.7] | 0 |
| codex / ollama:glm-5.3 / exactdocs / bm25 | 100.0 % [100.0, 100.0] (n=6) | 100.0 % [100.0, 100.0] (n=6) | 5.5 [4.8, 6.3] | 11.3 [10.5, 12.2] | 0 |
| codex / ollama:gpt-oss:120b / none | 100.0 % [100.0, 100.0] (n=1) | n/a | n/a | 6.0 [6.0, 6.0] | 5 |
| codex / ollama:gpt-oss:120b / exactdocs / bm25 | 0.0 % [0.0, 0.0] (n=1) | 0.0 % [0.0, 0.0] (n=1) | 0.0 [0.0, 0.0] | 48.0 [48.0, 48.0] | 5 |
| opencode / ollama:glm-5.3 / none | 100.0 % [100.0, 100.0] (n=6) | n/a | n/a | 13.5 [11.5, 15.7] | 0 |
| opencode / ollama:glm-5.3 / exactdocs / bm25 | 100.0 % [100.0, 100.0] (n=6) | 100.0 % [100.0, 100.0] (n=6) | 5.7 [4.7, 6.7] | 13.8 [10.3, 17.0] | 0 |
| opencode / ollama:gpt-oss:120b / none | 66.7 % [33.3, 100.0] (n=6) | n/a | n/a | 9.5 [5.5, 16.7] | 0 |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 83.3 % [50.0, 100.0] (n=6) | 100.0 % [100.0, 100.0] (n=6) | 2.7 [2.3, 3.0] | 10.2 [7.8, 13.5] | 0 |

Against the harness's own `none` arm, on the same jobs:

| Harness / model / arm | Jobs | Passed (pts [CI]; gained/lost; McNemar p) | Wall time (s [CI]; p; ratio) | Output tokens ([CI]; p; ratio) |
|---|---|---|---|---|
| codex / ollama:glm-5.3 / exactdocs / bm25 | 6 | +0.0 pts [+0.0, +0.0]; 0/0; p 1.0 | -9.1 [-22.7, +3.2]; p 0.2458; x0.67 | -1,481.0 [-3,693.0, +345.8]; p 0.2458; x0.6 |
| opencode / ollama:glm-5.3 / exactdocs / bm25 | 6 | +0.0 pts [+0.0, +0.0]; 0/0; p 1.0 | -7.9 [-26.5, +7.7]; p 0.5243; x0.81 | -931.2 [-3,091.5, +692.5]; p 0.5574; x0.76 |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 6 | +16.7 pts [+0.0, +50.0]; 1/0; p 0.5 | +5.8 [-0.7, +16.7]; p 0.3734; x1.28 | -281.7 [-1,268.0, +393.2]; p 0.8463; x0.85 |

Built-in web calls, and the hosts the gate refused:

| Harness | Built-in web calls | Hosts the gate refused |
|---|---|---|
| codex | 0 | `api.github.com:443` (24), `chatgpt.com:443` (24) |
| opencode | 0 | `registry.npmjs.org:443` (34) |
<!-- /bench -->

- Every run with a documentation server called it at least once, and no CLI made a built-in web
  call.
- **Where ExactDocs loses**: Codex with `gpt-oss:120b` failed its one graded task with ExactDocs
  and passed it without; 10 of its 12 runs ended with server errors from Ollama Cloud's
  Responses API and are counted as errors, not graded
  ([A first run](../../evals/harnesses-running.md#a-first-run)). OpenCode with `gpt-oss:120b`
  took longer with ExactDocs (x1.28 wall time, not significant).
- `glm-5.3` passed every task in both harnesses and both arms, so the tasks do not tell the arms
  apart for it.

## Without a harness

The same six tasks, asked through the agent benchmark's pydantic-ai loop in a Docker sandbox with
no network.

<!-- bench:comparison-coding -->
- Started 2026-11-25T10:30:00+00:00; ExactDocs `0.0.0.post139.dev0+124ff7da` at `650a9e818e05`.

6 tasks (tasks starlette-startup-shutdown,starlette-template-response-v1,zod-error-messages-v4,zod-optional-unknown,pydantic-class-model-fields,query-gc-time-v5); arms none, exactdocs; agent models ollama:gpt-oss:120b; up to 20 requests a task; thinking model default; cutoff 2024-06-30. Sandbox: docker, network none: --network none.

| Model / arm | Passed | After the cutoff | Forbidden API used | Files changed | Errors |
|---|---|---|---|---|---|
| ollama:gpt-oss:120b / none | 33.3 % [0.0, 66.7] (n=6) | 33.3 % [0.0, 66.7] (n=6) | 50.0 % [16.7, 83.3] (n=6) | 1.0 [1.0, 1.0]; p50 1.0; p95 1.0 | 0 |
| ollama:gpt-oss:120b / exactdocs / bm25 | 66.7 % [33.3, 100.0] (n=6) | 66.7 % [33.3, 100.0] (n=6) | 16.7 % [0.0, 50.0] (n=6) | 1.0 [1.0, 1.0]; p50 1.0; p95 1.0 | 0 |

Against `none`, on the same tasks (McNemar, mid-p):

| Model / arm | Tasks | Difference [95% CI] | Gained / lost | p | Significant |
|---|---|---|---|---|---|
| ollama:gpt-oss:120b / exactdocs / bm25 | 6 | +33.3 pts [+0.0, +66.7] | 2 / 0 | 0.25 | no |
<!-- /bench -->

## What did not run

- **Grounded Docs and Context7 arms**: the harness benchmark has both arms, but they were not in
  this run. Context7's numbers would not be published anyway
  ([Terms of service](../../evals/context7.md#terms-of-service)).
- **Claude Code and Gemini CLI**: built and parsed in CI from recorded transcripts, but not run:
  they take only their providers' paid API keys (#497).
- **Hosted models**: every model here is open-weight on Ollama Cloud.
