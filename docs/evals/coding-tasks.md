# Version-pinned coding tasks

!!! abstract "TL;DR"
    - The golden set asks questions and a judge grades prose; neither shows whether the code an
      agent writes **runs against the version the project pins**. The coding tasks (#496) do.
    - A task is a small project that pins one library version in a lockfile, a request, and hidden
      tests that run in a sandbox with exactly that version installed. It passes only when its
      hidden tests pass.
    - 54 tasks over Pydantic, Starlette, Zod and TanStack Query, mostly **version pairs**: the same
      request at two versions where the right code differs.
    - CI checks on every pull request, with no model, that every reference solution passes and
      every solution written for the other version fails (`just coding-tasks check`).
    - Agents run the tasks with the workspace tools and a documentation arm of the
      [agent benchmark](agent-bench.md) (`just coding-tasks run`), never in CI.
    - Coding-agent CLIs (Claude Code, Codex, Gemini CLI, OpenCode) run the same tasks, graded the
      same way, in the [harness benchmark](harnesses.md).

It lives in
[`packages/exactdocs/evals/coding_tasks/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/coding_tasks)
(the code) and
[`packages/exactdocs/evals/coding/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/coding)
(the environments and the tasks).

## The tasks

54 tasks over four golden-corpus projects, at the versions the corpus pins:

| Project | Tasks | Version pairs | One-way traps | Pinned versions |
|---|---|---|---|---|
| Pydantic | 15 | 6 | 3 | v1.10.22, v2.5.3, v2.14.3 |
| Starlette | 11 | 2 | 7 | 0.27.0, 0.52.1, 1.10.0 |
| Zod | 16 | 5 | 6 | v3.23.8, v4.0.17, v4.6.7 |
| TanStack Query (`@tanstack/query-core`) | 12 | 5 | 2 | v4.36.1, v5.0.0, v5.90.3 |

- **A version pair** ("version trap") is the same request in two projects that pin different
  versions, where the right code differs: Pydantic 1's `@validator` against 2's
  `@field_validator`; Zod 3's `z.string().ip()` against 4's `z.ipv4()`; TanStack Query 4's
  `cacheTime` against 5's `gcTime`. Each side's reference solution is the other side's
  other-version solution, and fails there.
- **A one-way trap** has one side only, because:
    - the old code still works on the new version but not the reverse (Zod 4.1's codecs on
      4.0.17); or
    - a removal has no counterpart (Starlette 1.0 removed `on_startup` and `@app.route`).
- TanStack Query's tasks use `@tanstack/query-core`, its framework-agnostic core, so that they run
  in Node without a browser.
- Electron is left out: its tasks need a display and a large install.

### Training cutoffs

`just coding-tasks list` prints every task with:

- its pinned version and that version's release date;
- the version its other solution is for;
- the release the trap hinges on (`api_since`);
- whether the version and the change came after a training cutoff (`--cutoff`).

The default cutoff is 2024-06-30: gpt-oss:120b's model card gives June 2024. At that cutoff:

| Tasks | Count |
|---|---|
| pin a version released after the cutoff | 31 |
| of those, also hinge on a change released after it (Starlette 1.0's removals, Zod 4, Pydantic 2.11's deprecations) | 18 |
| hinge on a change released after it, whatever the version | 28 |

Another model is counted against its own cutoff with `--cutoff`.

## The task format

A task is a directory `evals/coding/tasks/<project>/<task>/`, one Pydantic Evals case:

| Part | What it holds |
|---|---|
| `task.yaml` | the project and the corpus version it pins (the documentation arms serve that version); the `environment` that installs it; the `prompt`; the `files` the task expects to change; `other_version` and either `other_from` (the task of the pair whose reference is this task's other-version solution) or an `other/` directory; `other_environment` (a one-way trap's other version, where its other solution must pass the same hidden tests); `api_since`; task-level `forbidden` patterns; `notes` on the trap |
| `workspace/` | the template the agent starts from |
| `hidden/` | the tests that decide the task; the agent never sees them |
| `reference/` | a correct solution for the pinned version, laid over the template |
| `other/` | a solution for `other_version`, unless `other_from` names it |

- Every workspace also gets the ecosystem's scaffold (`evals/coding/scaffold/`) and the
  environment's lockfile:
    - Python: a `pyproject.toml` whose pytest configuration makes every warning an error;
    - TypeScript: a strict `tsconfig.json`.
- The hidden tests run with their own configuration, not the workspace's: warnings are errors; for
  TypeScript, a strict type check of `src/` first, then `node --test`.

### Environments

An environment (`evals/coding/environments/<name>/`) pins one library version:

| Ecosystem | Lockfile | Toolchain |
|---|---|---|
| Python | `requirements.txt` compiled with hashes from `requirements.in` (`uv pip compile --generate-hashes`, `--exclude-newer` the release's month) | Python 3.12 |
| Node | `package.json` with exact versions and its `package-lock.json` | Node 22, TypeScript 5.9.3 |

Its `environment.yaml` names the package, version and release date, and the **APIs that must not
appear** for that version:

- each is a regular expression, the API's name and why: added later, removed, or deprecated (which
  fails here, since warnings are errors);
- a task adds its own;
- they are matched against the changed code with comments removed.

## The sandbox

Each environment is installed once from its lockfile into
`~/.cache/exactdocs/coding-tasks/environments/`, in a directory named after the lockfile's hash:

- Python: `uv venv` and `uv pip sync --require-hashes`;
- Node: `npm ci --ignore-scripts`.

Grading copies the workspace, adds the hidden tests, and runs them in a sandbox with that install.
The sandbox first reads the installed version of the pinned package (`@@installed`), so a report
shows the tests ran against exactly the pinned version.

Two sandboxes enforce the same `Limits`, and every report says how (`isolation`):

| Limit | `--sandbox docker` (agent runs) | `--sandbox process` (CI's check) |
|---|---|---|
| network | `--network none` | a new network namespace (`unshare -n`, or `-rn` without root) with only a down loopback; where the kernel allows none, it says `not isolated` and `run` refuses |
| CPU | `--cpus` (1) and `--ulimit cpu` (180 s) | `RLIMIT_CPU` per process (180 s); cores not limited |
| memory | `--memory` with swap (1.5 GiB, cgroup) | `RLIMIT_DATA` per process (1.5 GiB) |
| time | wall limit (180 s), the container killed | wall limit (180 s), the process group killed |
| processes | `--pids-limit` (256) | not limited (`RLIMIT_NPROC` counts every process of the user) |
| files | read-only root, only the workspace writable, the environment and its runtime mounted read-only, `--cap-drop ALL`, `no-new-privileges` | not hidden; `HOME` and `TMPDIR` inside the workspace |
| environment | only `PATH`, `HOME`, `TMPDIR`, the locale and test settings: no key, no proxy | the same |

- The container is `debian:trixie-slim`, pinned by digest.
- The interpreters (uv's Python, Node) are the host's, mounted read-only where they were
  installed, so both sandboxes run the same install.
- The self-hosted CI runner cannot make a network namespace, so CI's check runs there without
  network isolation, and says so. It runs only the repository's own solutions.

## Evaluators and the report

The task function returns the agent's run and the grade. The run is recorded as the agent
benchmark records it: tool calls, tokens, thinking, wall time, retries.

Three evaluators read the grade:

| Evaluator | What it reports |
|---|---|
| `TestsPass` | the hidden tests passed (and the type check), with exactly the pinned version |
| `ForbiddenApi` | no forbidden API in the changed code; its reason names each API used, the file and line, and why it does not exist in the pinned version |
| `FilesChanged` | files added, changed or deleted, and those the task did not name |

`just coding-tasks run` writes `reports/evals/coding-tasks.json` (and `.md`, and the checkpoint
`.rows.jsonl`). Per agent model and arm it gives, each with its 95% interval
([statistics](statistics.md)):

- the pass rate overall, per project, and over the tasks pinning a version after the cutoff;
- the share of tasks using a forbidden API, and which;
- the files changed;
- wall time, tokens and tool calls (documentation calls apart);
- each arm's pass rate against `none` on the same tasks, by McNemar's test (mid-p);
- every task against every cell.

A run the provider failed is not graded, counted in *Errors*, and asked again by `--resume`.

## The agent

The agent is the agent benchmark's (#495): a pydantic-ai agent with one documentation arm
(`none`, `exactdocs`, `context7` or `grounded-docs`, each with only its own tools, as there) and
the workspace tools:

| Tool | What it does |
|---|---|
| `list_files` | lists the workspace's files |
| `read_file` | reads one file |
| `write_file` | writes a whole file; the lockfile cannot be written, nothing outside the workspace |
| `run_tests` | runs the workspace's own tests in the same sandbox |

- It is told `My project uses <title> at version <version>.` and the request.
- Its instructions differ between arms only in the sentence about the documentation tool.
- Scripted models (`--offline`: `offline:reference`, `offline:other`, `offline:idle`) prove the
  plumbing.

## Running it

```bash
just coding-tasks list                          # the inventory
just coding-tasks check                         # every reference passes, every other solution fails (CI)
just coding-tasks check --sandbox docker --projects zod
just coding-tasks run --offline --arm none      # scripted agents, no provider
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just coding-tasks run \
  --agent-model ollama:gpt-oss:120b --arm none,exactdocs --limit 3 --concurrency 2
just coding-tasks run ... --resume
```

- `check` needs `uv`, `npm`, and the network to install the environments the first time.
- `run` with the `exactdocs` arm also imports the golden corpus, as the agent benchmark does.
- `run` needs Docker for its default sandbox, or `--sandbox process` where a network namespace can
  be made.

### CI and the tests

- **CI** runs `check` on every pull request (job *Coding tasks*), with no model and the
  environments cached by their lockfiles' hash: 54 references pass and 54 other-version solutions
  fail in a minute or two. See [Fast and integration tests](../releasing/tests.md).
- **The quick tests** (`tests/evals/test_coding_tasks.py`, `features/coding_tasks.feature`) run
  in the default suite:
    - on stand-in tasks (a tiny library in two versions, `tests/fixtures/coding_tasks/`), with the
      scripted models and the agent benchmark's stand-in documentation tools;
    - and on the real tasks statically: they load, their lockfiles pin their versions, every
      reference uses no forbidden API and every other-version solution uses one.
- The tests that install real environments or need Docker are marked `integration`.

## A first run

One small run is recorded in `packages/exactdocs/evals/results/coding-tasks.json` (and `.md`):

| Setting | Value |
|---|---|
| date | 2026-11-25 |
| agent | `ollama:gpt-oss:120b` (Ollama Cloud, its default thinking) |
| arms | `none` and `exactdocs` (BM25) |
| sandbox | Docker, 20 requests a task |
| tasks | six, all pinning a version released after the model's cutoff |

| Task | `none` | `exactdocs` |
|---|---|---|
| `pydantic-class-model-fields` | fail (`self.model_fields`) | pass |
| `query-gc-time-v5` | pass | pass |
| `starlette-startup-shutdown` | fail | fail |
| `starlette-template-response-v1` | fail (name-first `TemplateResponse`) | fail (the same; it searched nothing) |
| `zod-error-messages-v4` | fail (`required_error`) | pass |
| `zod-optional-unknown` | pass | pass |

- Without documentation it passed 2 of 6 and used a forbidden API in 3. With ExactDocs it passed
  4 of 6 and used one.
- Both arms failed the Starlette lifespan task the same way: they connected the database lazily in
  the endpoint and never disconnected it at shutdown.
- Against `none`: 2 gained, 0 lost, p = 0.25 (McNemar, mid-p), not significant. Six tasks show
  the plumbing works on a real model, not an effect size.

## Adding a task

1. Write the task directory with a reference that passes on the pinned version and an
   other-version solution that fails there (a pair: two tasks naming each other in `other_from`).
2. Add the forbidden patterns that name what the other solution gets wrong.
3. Run `just coding-tasks check --tasks <id>`. It fails until:
    - the reference passes with exactly the pinned version installed and uses no forbidden API;
    - the other solution fails and uses at least one.
