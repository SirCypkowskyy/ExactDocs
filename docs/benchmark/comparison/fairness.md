# Fairness and reproducing

!!! abstract "TL;DR"
    - Every tool runs as its documentation sets it up; only what it needs to run on this machine
      was set, and nothing was tuned for the golden set.
    - Context7's coverage and query date are not published: its run is built (#493), and its
      numbers wait for Upstash's written permission.
    - The golden set's own error rate: 23 of 90 sampled cases were wrong in some way, and fixed
      (#490); the other 231 cases were not reviewed.
    - Every run can be repeated with one command; the summary reports are committed, raw
      transcripts and responses only go to the workflow run's artifacts.

## Fairness

### Context7: version coverage and query date

Context7 is hosted, and it serves a library's version only when someone added it. The run
(#493, [Context7](../../evals/context7.md)) asks which of the golden set's pinned versions it
serves, records the date of each answer, and scores the versions it serves apart from those it
answers with another release or its current docs.

No Context7 number, coverage or date is published here: Upstash's Terms of Service forbid
benchmark tests of its services without its express permission, and none has been given
([Terms of service](../../evals/context7.md#terms-of-service)). `just bench-pages` refuses to
publish a run that has a `context7` arm.

### Grounded Docs on its documented defaults

Scraping, its default exclusion patterns, splitting, search and result assembly were left as
they ship. Only telemetry was turned off, the corpus folder given as the one folder it may read,
the embedding request timeout raised for the local CPU endpoint, and the crawl's depth limit
raised where a version's folders are deeper than its default, so that every article was offered
([Its documented defaults](grounded-docs.md)). Its default exclusion patterns skip changelogs,
which costs it on `version-change` questions; that is how it ships, so it stays.

In the agent benchmark it ran with full-text search only, its default when no embedding provider
is configured.

### The same embedding model

Grounded Docs' vector configuration used `BAAI/bge-small-en-v1.5`, the model of ExactDocs' best
local configuration, served from the same ONNX file through a local OpenAI-compatible endpoint
([Same embedding model](grounded-docs.md)). Context7 chooses its own models, which cannot be
set.

### Harnesses and web access

Every CLI the harness benchmark drives can turn its built-in web tools off, so no arm has the web
(Codex CLI and OpenCode in the recorded run, Claude Code and Gemini CLI in their adapters;
[Harnesses](../../evals/harnesses.md)). The gate refuses every host but the model provider and
the arm's MCP server, and the report counts built-in web calls and refused hosts: no CLI made a
web call ([Coding tasks](coding.md#real-coding-agent-clis)).

### The golden set's measured error rate

An independent agent review of a sample of the golden set (#490), not a person:

<!-- bench:golden-review -->
- Sample: 90 cases, 3 per kind and project, seed 490, drawn from golden set `sha256:39f6f9d5e909d128`.
- Reviewed by: independent review agent (adversarial brief; not the agent that wrote the cases), 2026-11-23.
- Verdicts: 67 correct, 23 fixed, 0 removed.
- Wrong cases: 23 of 90, 25.6% (95% Wilson interval 17.7% to 35.4%).

| Problem | Cases |
|---|---|
| `unsupported-fact` | 3 |
| `missing-section` | 17 |
| `wrong-kind` | 6 |

| Kind | Wrong / reviewed |
|---|---|
| `identifier-lookup` | 3 / 15 |
| `how-to` | 3 / 15 |
| `conceptual` | 4 / 15 |
| `version-change` | 8 / 15 |
| `cross-page` | 5 / 15 |
| `unanswerable` | 0 / 15 |

| Project | Wrong / reviewed |
|---|---|
| electron | 3 / 18 |
| pydantic | 3 / 18 |
| starlette | 4 / 18 |
| tanstack-query | 9 / 18 |
| zod | 4 / 18 |
<!-- /bench -->

The wrong cases were fixed before the runs above ([Golden set](../golden-set.md)). Most were
missing sections, which make a tool that finds the right page look worse than it is, for every
tool alike.

### What was not tuned

- ExactDocs runs its defaults (BM25 at `default`, or hybrid search with `bge-small-en-v1.5` where
  named), chosen on the same golden set
  ([How a default is chosen](../method/index.md#how-a-default-is-chosen)). That is an advantage the other tools do not
  get: say so when you quote a lead.
- The agent model, its settings and its request budget are the same in every arm; an arm's
  instructions differ only in the tools they name.

## Reproducing

| Run | Command | Report |
|---|---|---|
| Grounded Docs, retrieval | `just grounded-bench --out packages/exactdocs/evals/results` ([Grounded Docs](../../evals/grounded-docs.md)) | `grounded-docs.json` |
| Context7, retrieval | `CONTEXT7_API_KEY=... just context7-bench` ([Context7](../../evals/context7.md)) | not committed |
| Agents | `just agent-bench run ...` ([Runs](../agent/runs.md)) | `agent.json` |
| Coding tasks, no harness | `just coding-tasks run ...` ([Running it](../../evals/coding-tasks.md#running-it)) | `coding-tasks.json` |
| Coding tasks, CLIs | `just harness-bench run ...` ([Running it](../../evals/harnesses-running.md)) | `harness-bench.json` |
| These pages | `just bench-pages` | `history.json` |

The reports are in
[`packages/exactdocs/evals/results/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/results).
The manual workflows (*Grounded Docs benchmark*, *Agent benchmark (real providers)*, *Harness benchmark (real
providers)* and *Retrieval eval (real providers)*) upload each run's reports as the run's artifact.

### Raw reports

- Committed: each run's summary report (`.json` and `.md`), which holds every result the pages
  show and what a rerun needs.
- Not committed: a run's `reports/evals/` folder, with its checkpoints and transcripts. It is
  the workflow run's artifact, kept 30 days.
- Context7's responses are never committed or published, as its terms ask (#493); they are the
  `context7-responses` artifact of the run.
