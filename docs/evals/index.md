# Retrieval evals

!!! abstract "TL;DR"
    - Retrieval modes are compared with numbers before one becomes a default.
    - The suite and the benchmarks are development and release tooling: none of it ships in the
      wheel or the image.
    - The release workflow runs only the model-free BM25 gates. The manual *Eval* workflow adds
      the suite end to end, the benchmarks' checks and report-only runs on the default local
      models; run it before a release that touches retrieval or chunking. Pull requests run only
      the quick tests. Runs with hosted models or other tools are started by hand.
    - The results and the defaults they recommend are in the [Benchmark](../benchmark/index.md)
      section. These pages are the reference for running them.

The eval suite runs one dataset of questions through every retrieval mode this build can run,
on the fixture docs repository imported for real. Per mode it reports:

- how often the right section comes back;
- how often anything of another version does;
- what it cost and how long it took.

The decisions behind it are in [AI retrieval decisions](../decisions/ai-retrieval/cost.md#evaluation).

The benchmarks (the golden set, ingestion, retrieval and agent) are published with the defaults
they recommend in the [Benchmark](../benchmark/index.md) section.

## Where it lives

- The code is in
  [`packages/exactdocs/evals/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals),
  outside the package.
- [Pydantic Evals](https://ai.pydantic.dev/evals/) (`pydantic-evals` 2.60.0) is in the `dev`
  dependency group, not in an extra.
- Nothing of it ships in the wheel or the image.

## The evals

| Eval | What it measures | Command | Runs |
|---|---|---|---|
| [Retrieval eval suite](suite.md) | every mode on the fixture docs repository: recall, wrong version, latency, cost | `just eval` | BM25 gates at every release, the rest in *Eval* |
| [Gates and the baseline](gates.md) | what fails the suite, and how the baseline moves | `just eval --write-baseline` | every release |
| [Golden set](golden-set.md) | questions with known answers about real projects' docs | `just golden-validate` | CI checks the rules |
| [Ingestion benchmark](ingestion.md) | what the importer makes of the golden corpus per chunking | `just ingestion-bench` | *Eval* (`--check`) |
| [Retrieval benchmark](retrieval-benchmark.md) | every configuration and chunking on the golden set | `just retrieval-bench` | BM25 in *Eval*, the rest by hand |
| [Recommendation and statistics](statistics.md) | how a default is picked; intervals and paired tests | part of `just retrieval-bench` | with the benchmark |
| [Retrieval benchmark runs](retrieval-runs.md) | the recorded run, local and hosted runs, reproducing a result | `just retrieval-bench --out ...` | by hand |
| [Retrieval grid](retrieval-grid.md) | chunking, context and embedding variants, plain baselines | `just retrieval-grid` | by hand |
| [Scoring text results](text-scoring.md) | scoring a tool's text against the golden sections | `just text-bench` | by hand |
| [Grounded Docs](grounded-docs.md) | a pinned docs-mcp-server on the same corpus | `just grounded-bench` | by hand |
| [Context7](context7.md) | which pinned versions Context7 serves, and its answers | `just context7-bench` | by hand |
| [Agent benchmark](agent-bench.md) | an agent answering the golden set with each documentation arm | `just agent-bench run` | by hand |
| [Running the agent benchmark](agent-bench-running.md) | flags, the manual workflow, judge agreement, tests | `just agent-bench` | by hand |
| [Version-pinned coding tasks](coding-tasks.md) | whether an agent's code runs against the version the project pins, per documentation arm | `just coding-tasks check`, `just coding-tasks run` | `check` on every pull request (no model); `run` by hand |
| [Coding-agent CLIs](harnesses.md) | Claude Code, Codex CLI, Gemini CLI and OpenCode, headless in containers, on the coding tasks and golden questions with each documentation arm | `just harness-bench run` | the parsers on every pull request (recorded transcripts); runs by hand |
