# Agent benchmark runs

!!! abstract "TL;DR"
    - Four runs, 24 and 25 November 2026: the first (`none` and `exactdocs`), Grounded Docs added,
      the tools that take loose arguments (#573), and search results grouped by article (#575).
    - Each later run asked only the answers it changed (`--resume`); the recorded run holds the newest
      of each.
    - Every result of every run is also on [Every agent run](history.md), and what each run found
      is on [What each agent run found](findings.md).

The recorded run: its settings, the commands and how it went. What each run found, in order, is
on [What each agent run found](findings.md), and the summary on [Agent results](index.md).

## The run

<!-- bench:agent-run -->
- Started 2026-11-25T22:04:39+00:00; ExactDocs `0.0.0.post140.dev0+eee1e310` at `345de89ced05`. 347 of the answers were kept from an earlier run of the same command (`--resume`), at its commit and time.
- Agents: `ollama:gpt-oss:120b`, `ollama:kimi-k3`; judge `ollama:glm-5.3`; served by ollama at `https://ollama.com/v1`.
- Arms: `none`, `exactdocs`, `grounded-docs`; configurations of `exactdocs`: `bm25`; of `grounded-docs`: `full-text`.
- `exactdocs (bm25)`: exactdocs serve --stdio.
- `grounded-docs (full-text)`: @arabold/docs-mcp-server 3.4.1 (read-only, HTTP).
- Cases: 60 (2 per kind and project, seed 495); at most 20 model requests per question; thinking: medium; 3 questions at a time; 6 retries of a failed request.
<!-- /bench -->

- The judge ran with its model's default thinking.
- The agents ran with `--thinking medium` (sent as `reasoning_effort`; the models think whatever
  it says).
- ExactDocs ran with BM25, its default with no model.

The run was planned on 90 questions (3 per kind and project, seed 495):

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 3 --concurrency 3 --report reports/evals/agent-bench.json
```

How it went:

| Time (UTC) | What happened |
|---|---|
| 08:16 | the run started |
| 08:40 | after about 155 answers, every request got `429 ... reached your session usage limit`[^429] |
| 11:08 | the limit lifted; `--per-stratum 2 --resume` asked again what had failed |
| 11:29 | the 60-question sample finished with no provider error left[^resumed] |
| later | extending it to 90 with `--per-stratum 3 --resume`<br/>hit the limit again after 17 more answers |

[^429]: Recorded as provider errors, not wrong answers.
[^resumed]: The first two of each stratum's three draws: the same seed.

On the plan used, an Ollama Cloud session held about 155 answers with their judgements. The
90-question sample (about 50 answers short) and all 321 questions (about six more sessions) are
left for a later run, which `--resume` lets span sessions.

Each question's four answers (two models, two arms) were asked together, so both arms of a
question ran in the same session, except for one question whose answers straddle the limit.

The `grounded-docs` arm was added on 2026-11-25 with the first run's 240 answers as the
checkpoint (`reports/evals/agent-bench.rows.jsonl`), so only its 120 answers were asked, from 09:37
to 09:50 UTC, with no provider error (the start time above is this run's):

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs,grounded-docs --retrieval bm25:mode=bm25 --grounded-docs full-text \
  --thinking medium --per-stratum 2 --concurrency 3 --report reports/evals/agent-bench.json --resume
```

`gpt-oss:120b`'s `exactdocs` answers were asked again on 2026-11-25 (#573), from 14:41 to 14:48
UTC with no provider error, with the recorded run's other 300 answers as the checkpoint. The same
command with `--resume`; ExactDocs ran this branch's tools:

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs,grounded-docs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 2 --seed 495 --concurrency 3 --max-retries 6 --report reports/evals/agent-bench.json --resume
```

Both models' `exactdocs` answers were asked again on 2026-11-25 (#575), at `345de89ced05`, with
the recorded run's `none` and `grounded-docs` answers (240) as the checkpoint, by the same command
(`--arm none,exactdocs,grounded-docs --retrieval bm25:mode=bm25 --thinking medium --per-stratum 2
--seed 495 --concurrency 3 --resume`):

| Time (UTC) | What happened |
|---|---|
| 20:16 | the run started; the pinned versions were imported |
| 20:33 | after 107 answers, every request got `429 ... reached your session usage limit`; the 13 left were recorded as provider errors, not wrong answers |
| 22:04 | the limit lifted; `--resume` asked those 13 (all Zod questions), with no provider error |

The golden set's fingerprint changed in #601 (`sha256:a00997851150e3b0` to
`sha256:100484c7ccdb1b89`): one Pydantic case's expected heading lost its `{#config-both}`. The
sample is the same 60 cases with the same questions, references and facts; that case is not one
of them.

- Grounded Docs searched the full-text index `just grounded-bench` had built of the 15 pinned
  versions (the same files the ExactDocs importer takes at the pinned commits), in its read-only
  mode.
- The agents were offered `search_docs`, `read_page`, `list_pages`, `list_libraries` and
  `find_version`; not `fetch_url`, which reads any web page.
- The library names it lists are the project IDs (`tanstack-query`). A search for
  `TanStack Query` (or `@tanstack/react-query`) was answered "not found, did you mean
  tanstack-query?", and every such question went on with the right name.

## Moved sections

These sections moved to another page. The old links still land here and point on.

- <a id="the-first-run-2026-11-24"></a>[The first run (2026-11-24)](findings.md#the-first-run-2026-11-24)
- <a id="grounded-docs-2026-11-25"></a>[Grounded Docs (2026-11-25)](findings.md#grounded-docs-2026-11-25)
- <a id="tools-that-take-loose-arguments-573-2026-11-25"></a>[Tools that take loose arguments (#573, 2026-11-25)](findings.md#tools-that-take-loose-arguments-573-2026-11-25)
- <a id="search-results-grouped-by-article-575-2026-11-25"></a>[Search results grouped by article (#575, 2026-11-25)](findings.md#search-results-grouped-by-article-575-2026-11-25)
