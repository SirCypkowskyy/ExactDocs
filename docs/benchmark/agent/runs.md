# Agent benchmark runs

!!! abstract "TL;DR"
    - Four runs, 24 and 25 November 2026: the first (`none` and `exactdocs`), Grounded Docs added,
      the tools that take loose arguments (#573), and search results grouped by article (#575).
    - Each later run asked only the answers it changed (`--resume`); the recorded run holds the newest
      of each.
    - Every result of every run is also on [Every agent run](history.md).

What each run of the agent benchmark found, in order, then the recorded run: its settings, the commands and how it went. The summary is on
[Agent results](index.md).

## The first run (2026-11-24)


| | |
|---|---|
| Agent models | `gpt-oss:120b` (OpenAI)[^cutoff] and `kimi-k3` (Moonshot AI), from different vendors |
| Judge | `glm-5.3` (Z.ai) |
| Questions | 60 golden questions (2 of each kind in each project, a seeded stratified sample) |
| Answers | 240 |

[^cutoff]: Its model card gives a June 2024 knowledge cutoff, before the newest pinned version of
    every project.

With the ExactDocs tools (both models' answers were asked again on 2026-11-25, see *Tools that
take loose arguments* and *Search results grouped by article* below; the tables on [Every table](results.md) hold
the newest):

- **Accuracy rose for both models, significantly.**

    | Model | `none` | `exactdocs` | Difference | Gained / lost | McNemar p |
    |---|---|---|---|---|---|
    | `gpt-oss:120b` | 13.3% [5.0, 21.7] | 43.3% [31.7, 56.7] | +30.0 points [+18.3, +43.3] | 19 / 1 | 2.1e-05 |
    | `kimi-k3` | 33.3% [21.7, 45.0] | 85.0% [75.0, 93.3] | +51.7 points [+40.0, +65.0] | 31 / 0 | 4.7e-10 |

- **No answer was true of another version only.** Without documentation the judge flagged 15 of
  `gpt-oss:120b`'s 60 answers (25%) and 5 of `kimi-k3`'s (8%) as stating what holds for another
  version; with ExactDocs, none of either model's.
- **More right refusals.** On the 10 `unanswerable` questions, `kimi-k3` said the documentation
  does not cover it 9 times with ExactDocs against 2 without; `gpt-oss:120b` 4 against 2. Neither
  model refused an answerable question with ExactDocs.
- **What it costs depends on the model.**
    - `gpt-oss:120b` took twice as long (2.9 s to 6.0 s a question on average, p95 5.1 s to
      10.3 s; +3.1 s [+2.4, +3.7], p = 0.0001) and wrote 21% more output tokens (745 to 901,
      thinking included; p = 0.002).
    - `kimi-k3` was not slower: its mean fell from 19.1 s to 14.6 s and its output from 1,913 to
      1,318 tokens, neither significant (p = 0.19 and 0.073). Without documentation it thinks at
      length about versions it does not know (p95: 56 s and an estimated 5,400 thinking tokens);
      with it, the median rose (9.8 s to 12.5 s) and the long tail shrank (p95 33 s).
    - Both made about 5.5 tool calls a question. What the tools returned grew the input from
      about 200 tokens to 38,000 (`kimi-k3`) and 50,000 (`gpt-oss:120b`) a question: the bulk of
      the cost on a per-token price.
- **The judge is strict.** `correct` needs every fact the case lists, and the facts often go
  beyond the literal question; a brief, right answer is often `partially_correct` (24 of
  `gpt-oss:120b`'s 60 answers with ExactDocs). That lowers the accuracy of both arms alike.

## Grounded Docs (2026-11-25)

The same 60 questions and the same two agents and judge, added to
the run with `--resume` (120 answers; Grounded Docs 3.4.1 with full-text search, its default with
no model, as ExactDocs ran with BM25). With Grounded Docs' tools:

- **As accurate as ExactDocs on these 60 questions; far above no documentation.**

    | Model | `grounded-docs` | Against `none` | Against `exactdocs` | Gained / lost against `exactdocs` |
    |---|---|---|---|---|
    | `gpt-oss:120b` | 45.0% [31.7, 56.7] | +31.7 points, p = 1.9e-06 | +3.3 points [-8.3, +15.0], p = 0.58[^first-exactdocs] | 7 / 5 |
    | `kimi-k3` | 81.7% [71.7, 91.7] | +48.3 points, p = 1.9e-09 | -3.3 points [-13.3, +5.0], p = 0.51 | 3 / 5 |

    Neither difference between the two tools is significant, and their intervals span several
    points either way: 60 questions cannot tell them apart.

    [^first-exactdocs]: Against the ExactDocs answers asked again in #573's run. Against the
        first run's: +1.7 points [-8.3, +11.7], p = 0.75, 5 / 4.

- **Two answers wrong for the version.** The judge flagged 2 of `gpt-oss:120b`'s 60 answers, against
  none with ExactDocs in the first run (one in #573's); `kimi-k3` had none.
    - One put a deprecation in the wrong Electron release; one cited later Pydantic docs while
      rightly saying v2.5.3 does not cover the question.
    - The agents sometimes searched Grounded Docs with an X-range (`4.36.x`, `5.x`: 22 of its 238
      searches), which can match a newer indexed version of the range than the one asked;
      ExactDocs takes one exact version.
- **Right refusals on `unanswerable` questions:** `kimi-k3` 7 of 10 (9 with ExactDocs),
  `gpt-oss:120b` 5 of 10 (4 with ExactDocs); no answerable question refused.
- **Fewer calls and tokens.**
    - About 3.5 tool calls a question, against 5.5 with ExactDocs (4.7 for `gpt-oss:120b` in
      #573's run).
    - Output tokens 24% lower for `kimi-k3` (-310, p = 0.0001). For `gpt-oss:120b`, 7% lower
      against #573's ExactDocs answers, not significant (-56 [-144, +47], p = 0.25); 13% against
      the first run's (-117 [-198, -31], p = 0.0097).
    - Input tokens: 16,065 a question for `kimi-k3` against 37,754 (p = 0.0001); 41,413 for
      `gpt-oss:120b` against 43,023 (not significant; its p95, 177,000, is a few questions it
      searched 10 to 16 times, each answer a list of passages, before answering or reaching the
      request limit).
    - Each `search_docs` result carries the matching passage with the context Grounded Docs
      assembles around it, so the agents read fewer pages.
- **Wall time is not compared.** The `grounded-docs` answers ran a day after the first run, on a
  different day of Ollama Cloud: their 4.2 s and 8.4 s a question (6.0 s and 14.6 s with ExactDocs
  then; 5.3 s for `gpt-oss:120b`'s ExactDocs answers of #573's run, five hours after them) mix the
  tool with the provider's load. The time columns below are given, not read.
- *Read the answer* (8% and 10%) counts only whole pages read with `read_page` (22 of the 120
  answers); most answers came from `search_docs` passages, which do not count, as ExactDocs'
  snippets do not. It is not comparable with ExactDocs' 36% and 52%.

## Tools that take loose arguments (#573, 2026-11-25)

In the first run, `gpt-oss:120b` hit a tool
error in 21 of its 60 ExactDocs runs, 20 of them on an argument the tools refused (an empty
`query` of `resolve-library-id` 17 times, `path_prefix` on `search_docs` 4 times, `limit: 1000`,
a library's name instead of its ID). The harness ends a run whose tool fails twice, and both of its
`no_answer` runs ended that way. #573 made the tools take those arguments: an empty optional one
counts as not given, a number out of range is clamped, a name is resolved to its ID, `search_docs`
takes `path_prefix`, and a missing path names the closest ones. Its 60 ExactDocs answers were then
asked again, everything else kept (`--resume` on the other 300):

| `gpt-oss:120b`, `exactdocs` | First run | #573's run |
|---|---|---|
| Accuracy | 43.3% [31.7, 56.7] | 41.7% [30.0, 53.3] |
| Against `none` | +30.0 points [+18.3, +43.3], p = 2.1e-05 | +28.3 points [+16.7, +40.0], p = 4.0e-05 |
| `grounded-docs` against it | +1.7 points [-8.3, +11.7], p = 0.75 | +3.3 points [-8.3, +15.0], p = 0.58 |
| No answer | 2 | 1 |
| Runs with a tool error (calls) | 21 (26) | 1 (2) |
| Tool calls a question | 5.5 [4.8, 6.2] | 4.7 [4.2, 5.3] |
| Input tokens a question | 50,433 [41,271, 60,654] | 43,023 [34,322, 54,096] |
| Output tokens a question | 901 [806, 1,008] | 839 [752, 940] |
| Wrong for the version | 0 | 1 |

- **The errors are gone, the accuracy is not up.** 51 of the 60 runs sent `resolve-library-id` an
  empty `query` and all 60 sent `search_docs` an empty `path_prefix` (it is in the schema now);
  each would have failed before. Against the first run's answers, 5 questions were gained and 6
  lost (McNemar p = 0.77): what changed is the sampling of a model at medium thinking, not the
  tools. Of the 21 questions whose first run hit an error, 8 are right now, against 6.
- **The one error left is a path that does not exist.** On "How do I create a model from an ORM
  object?" (Pydantic v1.10.22) it asked `read_article` for `tmp_examples/models_orm_mode.md`. The
  error named `docs/usage/models.md` first, but it tried `docs/tmp_examples/models_orm_mode.md`
  next, and that second miss ended the run (`no_answer`), as in the first run.
- **One answer wrong for the version.** On "Which HTTP client library does TestClient need now?"
  (Starlette 1.10.0) it answered `httpx` after one search, without reading a section; the version
  uses `httpx2`.
- **`read_article` still gave it no text.** Its structured content holds the article's metadata,
  and pydantic-ai, which runs the agents, hands the model the structured content instead of the
  text (#587, fixed in #588). This run measures #573 alone; the next one will have both.

## Search results grouped by article (#575, 2026-11-25)

`search_docs` now returns its results
grouped by article, the best article first ([Retrieval results](../retrieval/grouping.md)),
and `read_article` hands the model its text (#588). Both models' 60 `exactdocs` answers were asked
again, the other 240 kept (`--resume`):

| | `gpt-oss:120b` before | after | `kimi-k3` before | after |
|---|---|---|---|---|
| Accuracy | 41.7% [30.0, 53.3] | 40.0% [28.3, 51.7] | 85.0% [75.0, 93.3] | 83.3% [73.3, 91.7] |
| After against before | | -1.7 points [-13.3, +8.3], 5 / 6, p = 0.77 | | -1.7 points [-11.7, +8.3], 4 / 5, p = 0.75 |
| Against `none` | +28.3 points, p = 4.0e-05 | +26.7 points [+15.0, +40.0], p = 7.6e-05 | +51.7 points, p = 4.7e-10 | +50.0 points [+38.3, +63.3], p = 9.3e-10 |
| `grounded-docs` against it | +3.3 points, p = 0.58 | +5.0 points [-5.0, +16.7], p = 0.39 | -3.3 points, p = 0.51 | -1.7 points [-11.7, +8.3], p = 0.77 |
| Wrong for the version | 1 | 2 | 0 | 0 |
| Runs with a tool error (calls) | 1 (2) | 1 (2) | 2 (2) | 1 (1) |
| Tool calls a question | 4.7 [4.2, 5.3] | 4.0 [3.5, 4.7] | 5.5 [4.8, 6.4] | 4.5 [4.0, 5.0] |
| Input tokens a question | 43,023 [34,322, 54,096] | 50,381 [34,420, 72,490] | 37,754 [28,714, 49,149] | 33,107 [28,356, 38,938] |
| Output tokens a question | 839 [752, 940] | 824 [726, 945] | 1,318 [1,138, 1,522] | 1,186 [1,049, 1,346] |

*Before* is the recorded run before this one: `gpt-oss:120b`'s answers of #573's run, `kimi-k3`'s of
the first run. Gained / lost and p: McNemar's test on the same 60 questions.

- **Accuracy did not change measurably.** Each model lost one question net (5 gained and 6 lost,
  4 and 5), the sampling of a model at medium thinking, as in #573's re-run; 60 questions cannot
  show a change this small either way. ExactDocs stays far above no documentation and level with
  Grounded Docs.
- **Fewer tool calls, significantly.** `gpt-oss:120b` -0.67 a question [-1.23, -0.12] (p = 0.022),
  `kimi-k3` -1.05 [-1.70, -0.47] (p = 0.0005), by a paired permutation test.
    - `kimi-k3` read 38 fewer chunks with `read_chunk` (72 against 110) and searched 10 fewer
      times (104 against 114).
    - `gpt-oss:120b` opened 17 fewer articles with `view_article` (27 against 44), whose text it
      read when `read_article` gave it none, and called `read_chunk` no more (9 before).
    - Grounded Docs still takes fewer: 3.6 and 3.45 a question.
- **Tokens.** `kimi-k3` wrote 132 fewer output tokens a question [-234, -36] (10%, p = 0.012); its
  input fell by 4,648, not significantly (p = 0.25). `gpt-oss:120b`'s output did not change
  (p = 0.65), and its input rose by 7,358, not significantly (p = 0.37; its p95, 143,000, is a few
  questions it searched or read at length).
- **Two answers wrong for the version, both `gpt-oss:120b`'s.** One put Electron's
  navigation-history deprecation in v38 instead of v32. One answered how to `.encode()` a Zod
  v4.0.17 schema, which that version cannot do (codecs came in 4.1): an `unanswerable` case.
  `kimi-k3` had none.
- **The one tool error left for `gpt-oss:120b` is a version's name.** On a Starlette 1.10.0
  question it called `search_docs` with `ref` `v1.10.0` twice. ExactDocs names that version
  `1.10.0`, and the error ("no index for /encode/starlette@v1.10.0") did not list the versions it
  has, so the second miss ended the run (`no_answer`). `kimi-k3`'s one error was an article path
  that does not exist; the error named the closest paths and it answered right.
- **More than the grouping changed.** #575's grouping and #588's `read_article` text both reached
  these answers, and `kimi-k3`'s answers before were the first run's, so #573's tools are new to
  it as well. This run cannot tell their effects apart.
- **Wall time is not compared**: these answers ran on another evening of Ollama Cloud.

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
